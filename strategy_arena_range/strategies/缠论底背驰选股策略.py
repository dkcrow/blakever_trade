#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缠论底背驰选股策略
==================
经典缠论策略: 检测底分型+向下笔的MACD面积背驰信号。
价格创新低但MACD绿柱面积缩小，表明下跌动能衰竭。

聚宽平台原始代码已适配为VectorBT回测框架的generate_signals接口。
策略类型: 均值回归（缠论底背驰本质是超卖反转信号）
"""

import numpy as np
import talib

STRATEGY_NAME = "缠论底背驰选股策略"
STRATEGY_TYPE = "均值回归"
STRATEGY_PARAMS = {
    "fenxing_confirm_period": 3,     # 分型确认周期（前后各1根K线验证）
    "bi_min_bars": 5,                # 一笔最少包含的K线数
    "macd_fast": 12,                 # MACD快线周期
    "macd_slow": 26,                 # MACD慢线周期
    "macd_signal": 9,                # MACD信号线周期
    "ma_period": 5,                  # 5日均线过滤（收盘须在5MA上方）
    "divergence_area_ratio": 0.8,    # 面积背驰阈值（后段面积<前段×此值）
    "min_bars_between_bi": 5,        # 两笔之间最少间隔K线数
}


def generate_signals(close, high, low, open_prices, **kwargs):
    """
    缠论底背驰信号生成。

    核心逻辑:
      1. 识别顶底分型（连续3根K线的高低关系）
      2. 构造笔（相邻异性质分型连接，同性质取极值合并）
      3. 找最后一笔向下笔及其前一笔同向向下笔
      4. 对比两段向下笔对应的MACD绿柱面积
         - 价格新低: 后段低点 < 前段低点
         - MACD面积缩小: 后段面积 < 前段面积 × divergence_area_ratio
         → 底背驰信号
      5. 额外过滤: 收盘价须在5日均线之上

    入场: 底背驰确认 + 收盘站上5MA
    出场: 顶分型出现 且 跌破5MA
    """
    fenxing_confirm = kwargs.get('fenxing_confirm_period', 3)
    bi_min = kwargs.get('bi_min_bars', 5)
    macd_fast = kwargs.get('macd_fast', 12)
    macd_slow = kwargs.get('macd_slow', 26)
    macd_signal = kwargs.get('macd_signal', 9)
    ma_period = kwargs.get('ma_period', 5)
    div_area_ratio = kwargs.get('divergence_area_ratio', 0.8)
    min_bars_between = kwargs.get('min_bars_between_bi', 5)

    c = np.array(close, dtype=float)
    h = np.array(high, dtype=float)
    l = np.array(low, dtype=float)
    n = len(c)

    # 计算MACD
    macd_line, signal_line, hist = talib.MACD(c, fastperiod=macd_fast,
                                               slowperiod=macd_slow,
                                               signalperiod=macd_signal)
    # 计算MA
    ma = talib.SMA(c, timeperiod=ma_period)

    entries = np.full(n, False)
    exits = np.full(n, False)

    # ===== 第1步: 识别分型 =====
    top_fx = np.full(n, False)   # 顶分型标记
    bot_fx = np.full(n, False)   # 底分型标记
    fx_high = np.full(n, np.nan)  # 顶分型高点
    fx_low = np.full(n, np.nan)   # 底分型低点
    fx_idx = np.full(n, -1)       # 分型发生的索引位置

    for i in range(1, n - 1):
        # 顶分型: 中间K线高点最高且低点也最高
        if (h[i] > h[i - 1] and h[i] > h[i + 1] and
                l[i] > l[i - 1] and l[i] > l[i + 1]):
            top_fx[i] = True
            fx_high[i] = h[i]
        # 底分型: 中间K线低点最低且高点也最低
        if (l[i] < l[i - 1] and l[i] < l[i + 1] and
                h[i] < h[i - 1] and h[i] < h[i + 1]):
            bot_fx[i] = True
            fx_low[i] = l[i]

    # ===== 第2步: 构造笔 =====
    # 收集所有分型点，按索引排序
    points = []  # (index, type, value)  type='top'/'bottom'
    for i in range(1, n - 1):
        if top_fx[i] and bot_fx[i]:
            # 同时是顶分型和底分型（十字星等），优先按方向处理
            # 这里取高点作为顶，低点作为底（后续合并处理）
            points.append((i, 'top', h[i]))
            points.append((i, 'bottom', l[i]))
        elif top_fx[i]:
            points.append((i, 'top', h[i]))
        elif bot_fx[i]:
            points.append((i, 'bottom', l[i]))

    # 合并同性质相邻分型（保留极值）
    bi_points = []  # 处理后的笔端点
    i = 0
    while i < len(points):
        if i == len(points) - 1:
            bi_points.append(points[i])
            break
        curr = points[i]
        next_p = points[i + 1]
        if curr[1] != next_p[1]:
            # 不同性质，可以连笔
            # 检查笔的长度（两分型之间至少bi_min根K线）
            if next_p[0] - curr[0] >= bi_min:
                bi_points.append(curr)
            else:
                # 太短，跳过
                i += 1
                continue
        else:
            # 同性质，保留极值
            if curr[1] == 'top':
                keep = curr if curr[2] > next_p[2] else next_p
            else:
                keep = curr if curr[2] < next_p[2] else next_p
            # 用极值替换当前位置，跳过下一个
            points[i] = keep
            # 不递增i，下一轮继续比较
            del points[i + 1]
            continue
        i += 1

    # ===== 第3步: 检测底背驰 =====
    # bi_points现在是交替的顶/底分型端点
    # 找最后一笔向下笔（顶分型→底分型），及其前一笔同向向下笔
    # 向下笔: 从顶分型(高点)到底分型(低点)

    down_bi = []  # 向下笔列表: [(start_idx, start_high, end_idx, end_low), ...]
    for i in range(len(bi_points) - 1):
        p1 = bi_points[i]
        p2 = bi_points[i + 1]
        if p1[1] == 'top' and p2[1] == 'bottom':
            # 向下笔: 从顶到低
            if p2[0] - p1[0] >= bi_min:
                down_bi.append((p1[0], p1[2], p2[0], p2[2]))

    # 对相邻向下笔检测底背驰
    # 条件: 后段价格新低 + MACD绿柱面积缩小
    for i in range(len(down_bi) - 1):
        prev_bi = down_bi[i]      # 前一段向下笔
        curr_bi = down_bi[i + 1]  # 后一段向下笔（更近的）

        # 价格新低: 后段低点 < 前段低点
        if curr_bi[3] >= prev_bi[3]:
            continue  # 未创新低，跳过

        # MACD面积比较
        # 计算前段向下笔期间的MACD绿柱面积（hist < 0的部分绝对值之和）
        prev_start = max(prev_bi[0], macd_slow + macd_signal - 1)  # MACD有效起始
        prev_end = prev_bi[2]
        if prev_end <= prev_start or prev_end >= n or prev_start >= n:
            continue

        prev_hist_segment = hist[prev_start:prev_end + 1]
        prev_green_area = np.sum(np.abs(prev_hist_segment[prev_hist_segment < 0]))

        # 计算后段向下笔期间的MACD绿柱面积
        curr_start = max(curr_bi[0], macd_slow + macd_signal - 1)
        curr_end = curr_bi[2]
        if curr_end <= curr_start or curr_end >= n or curr_start >= n:
            continue

        curr_hist_segment = hist[curr_start:curr_end + 1]
        curr_green_area = np.sum(np.abs(curr_hist_segment[curr_hist_segment < 0]))

        # 面积背驰: 后段面积 < 前段面积 × ratio
        if prev_green_area <= 0:
            continue  # 前段无绿柱，无法比较
        if curr_green_area >= prev_green_area * div_area_ratio:
            continue  # 面积未缩小

        # ===== 底背驰确认！=====
        # 在后段向下笔结束的那个底分型位置标记入场信号
        signal_idx = curr_bi[2]  # 底分型索引
        if signal_idx < n and signal_idx >= 0:
            # 额外过滤: 收盘价在5MA上方
            if not np.isnan(ma[signal_idx]) and c[signal_idx] > ma[signal_idx]:
                entries[signal_idx] = True

    # ===== 第4步: 出场信号 =====
    # 顶分型 + 跌破5MA → 出场
    for i in range(1, n - 1):
        if top_fx[i]:
            # 检查后续是否跌破5MA
            if i + 1 < n and not np.isnan(ma[i + 1]) and c[i + 1] < ma[i + 1]:
                exits[i + 1] = True

    return entries, exits
