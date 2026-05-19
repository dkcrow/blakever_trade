# -*- coding: utf-8 -*-
"""
Name：策略相关性分析工具
Author: 策略手艺人
Date  : 2026/04/25
说明  ：输入多个聚宽回测ID，分析各策略之间的相关性，帮助构建低相关度策略组合
"""
import heapq
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import seaborn as sns
from scipy.optimize import minimize
import warnings
warnings.filterwarnings('ignore')

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
    
# ============================================================
# ★ 配置区：在这里填入你的回测ID和策略名称 ★
# 回测ID:https://www.joinquant.com/algorithm/backtest/detail?backtestId=******** （backtestId后面那部分）
# ============================================================
STRATEGIES = {
    '策略1':'477bc2d6c5b80f60fa8fe816de09817b',
    '策略2':'44020436e108e91c019b61f6acd50565',
    '策略3':'2f3e4242e73b20d020f5b4b76e86bda1',
    '策略4':'6bca5ba585a9e7d4770574acdf917a4f',
    '策略5':'e32a3e2d7e929bdea567a778afc5de2b'    
}

# ---- 分析参数 ----
PARAMS = {  # ★ 核心参数在上方，进阶/图形参数在下方（一般无需修改）
    'correlation_threshold':  0.7,    # 相关度硬阈值：任意两策略超过此值则视为高度相关
    'top_n_candidates':       5,      # 贪心选择时，从相关度和最小的Top N中再选夏普最高的
    'n_strategies':           5,      # 最终推荐的组合策略数量
    'min_combo_size':         2,      # ★ 穷举时的最少策略组合数量（默认2，可自行设置，如设为3则只看3只以上的组合）
    #'start_date':             '2014-01-01',   # 回测分析起始日期，如 '2020-01-01'。设为 None 则自动取最早
    'start_date':             None,   # 回测分析起始日期，如 '2020-01-01'。设为 None 则自动取最早
    'end_date':               None,   # 回测分析结束日期，如 '2023-12-31'。设为 None 则自动取最晚
    'use_log_returns':        True,   # True=对数收益率；False=算术收益率
    'require_mixed':          True,   # True=强制要求组合内同时包含“进攻”和“防守”策略，且配置比例不过度失衡
    'min_overlap_days':       60,     # 两策略共同交易日最少天数，不足则跳过
    'plot_heatmap':           True,   # 是否画相关度热力图
    'plot_returns':           True,   # 是否画累积收益曲线
    'plot_rolling_corr':      True,   # 是否画滚动相关度（动态视角）
    'rolling_window':         60,     # 滚动窗口（交易日）
    'plot_size':              (14, 9),# 图形大小
    'ref_rate':               0.04,   # 无风险利率（年化），用于夏普计算
    'enable_log':             False,   # 是否打印进度日志
    # 权重优化目标：可选 '控制回撤' | '最大夏普' | '最大卡尔马' | '风险平价' | '等权'
    'optimize_target':        '控制回撤',
    # 控制回撤方案：最大可承受回撤（负数），0.20=回撤不超过20%
    'max_drawdown_limit':     0.20,
    # 单个策略权重区间：防止优化器给出极端角点解
    'min_weight':             0.10,   # 每个策略至少占 10%
    'max_weight':             0.60,   # 每个策略最多占 60%
    'frontier_samples':       3000,   # 有效前沿采样数（越多越平滑）
    # 推荐组合类型：决定在穷举排行榜后展示哪些维度的特色推荐
    # 可选: '高收益' | '低回撤' | '攻守兼备' | '低相关' | '高夏普' | '均衡稳健'
    'recommend_types':        ['高收益', '低回撤', '攻守兼备', '低相关', '高夏普', '均衡稳健'],
    'recommend_top_n':        3,      # 每种类型展示的TOP N个组合
}

# ============================================================
# 一、数据获取层
# ============================================================

def fetch_strategy_returns(strategies, params):
    """
    批量获取回测每日收益率。
    返回 dict: {策略名: pd.Series(日收益率, index=DatetimeIndex)}
    同时返回各策略绩效指标 dict 用于后续分析。
    """
    log = params['enable_log']
    returns_dict = {}
    metrics_dict = {}

    if log:
        print("=" * 60)
        print("策略相关性分析工具 - 开始获取回测数据")
        print("=" * 60)

    for name, bt_id in strategies.items():
        if log:
            print(f"\n正在读取策略: [{name}]  ID: {bt_id[:16]}...")
        try:
            gt = get_backtest(bt_id)
            results = gt.get_results()
            if not results:
                print(f"  [警告] {name} 无回测结果，已跳过")
                continue

            df = pd.DataFrame(results)
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').set_index('time')

            # 计算日收益率
            # 注意：get_results()的 returns 字段是【累计收益率】，
            # 1 + df['returns'] 直接就是 NAV，与聚宽策略回测分析工具保持一致
            nav = 1 + df['returns']   # 等价于回测工具的 df['nav'] = 1 + df['returns']
            if params['use_log_returns']:
                daily_ret = np.log(nav / nav.shift(1).fillna(1.0))
            else:
                daily_ret = nav.pct_change()
                daily_ret.iloc[0] = df['returns'].iloc[0]

            # ── 根据指定日期截断数据 ──
            if params.get('start_date'):
                daily_ret = daily_ret[daily_ret.index >= pd.to_datetime(params['start_date'])]
            if params.get('end_date'):
                daily_ret = daily_ret[daily_ret.index <= pd.to_datetime(params['end_date'])]

            if daily_ret.empty:
                print(f"  [警告] {name} 在指定日期范围内无有效数据，已跳过")
                continue

            returns_dict[name] = daily_ret

            # 基础绩效指标（基于截断后的收益率重新计算）
            if params['use_log_returns']:
                nav_series = np.exp(daily_ret.cumsum())
            else:
                nav_series = (1 + daily_ret).cumprod()

            total_ret  = nav_series.iloc[-1] - 1   # 期末NAV - 1 = 总收益率
            days       = len(nav_series)
            ann_ret    = (1 + total_ret) ** (250 / days) - 1 if days > 0 else 0
            ann_vol    = daily_ret.std(ddof=1) * np.sqrt(250)
            sharpe     = (ann_ret - params['ref_rate']) / ann_vol if ann_vol > 0 else np.nan
            mdd        = ((nav_series - nav_series.cummax()) / nav_series.cummax()).min()

            metrics_dict[name] = {
                '总收益':   total_ret,
                '年化收益': ann_ret,
                '年化波动': ann_vol,
                '夏普比率': sharpe,
                '最大回撤': mdd,
                '回测天数': days,
                '开始日':   daily_ret.index[0].strftime('%Y-%m-%d'),
                '结束日':   daily_ret.index[-1].strftime('%Y-%m-%d'),
            }

            if log:
                print(f"  ✓ 获取成功 | {days}天 | "
                      f"年化{ann_ret*100:.2f}% | 夏普{sharpe:.2f} | "
                      f"最大回撤{mdd*100:.2f}%")

        except Exception as e:
            if '没有访问该数据的权限' in str(e):
                print(f"  [错误] {name} 获取失败: 没有访问该数据的权限!")
            else:
                print(f"  [错误] {name} 获取失败: {e}")
            continue

    if log:
        print(f"\n共成功获取 {len(returns_dict)} / {len(strategies)} 个策略的数据")

    return returns_dict, metrics_dict


# ============================================================
# 二、相关度计算层
# ============================================================

def calc_pairwise_correlation(returns_dict, params):
    """
    计算所有策略两两之间的皮尔逊相关系数。
    返回 correlation_matrix: pd.DataFrame，行列均为策略名
    """
    names  = list(returns_dict.keys())
    n      = len(names)
    matrix = pd.DataFrame(np.nan, index=names, columns=names)
    log    = params['enable_log']
    min_ov = params['min_overlap_days']

    if log:
        print("\n" + "=" * 60)
        print("计算策略两两相关系数...")
        print("=" * 60)

    for i in range(n):
        matrix.iloc[i, i] = 1.0
        for j in range(i + 1, n):
            s1, s2 = names[i], names[j]
            r1 = returns_dict[s1]
            r2 = returns_dict[s2]
            common = r1.index.intersection(r2.index)

            if len(common) < min_ov:
                if log:
                    print(f"  [跳过] {s1} vs {s2}: 共同日期仅{len(common)}天 < {min_ov}天")
                continue

            corr = np.corrcoef(r1[common].values, r2[common].values)[0, 1]
            matrix.loc[s1, s2] = corr
            matrix.loc[s2, s1] = corr

            if log:
                level = "✓" if corr < params['correlation_threshold'] else "⚠"
                print(f"  {level} {s1} vs {s2}: r={corr:.4f}  (共{len(common)}天)")

    return matrix


# ============================================================
# 三、贪心策略组合选择（参考 ETF 相关性逻辑）
# ============================================================

def greedy_select_strategies(returns_dict, metrics_dict, correlation_matrix, params):
    """
    贪心算法选出低相关度策略组合：
      第1轮：选夏普最高的策略作为「锚」
      后续轮：
        - 排除与已选任意策略相关度 > threshold 的候选
        - 计算候选与所有已选策略的相关度之和
        - 取相关度和最小的 Top N，再从中选夏普最高的
    """
    log = params['enable_log']
    threshold = params['correlation_threshold']
    top_n = params['top_n_candidates']
    n = params['n_strategies']

    names = [k for k in returns_dict.keys() if k in metrics_dict]
    if not names:
        return []

    if log:
        print("\n" + "=" * 60)
        print(f"贪心算法选出低相关度策略组合（目标{n}只）")
        print(f"相关度阈值: {threshold}  Top-N候选: {top_n}")
        print("=" * 60)

    # 夏普排序，选第一个（夏普最高）
    first = max(names, key=lambda k: metrics_dict[k].get('夏普比率', -np.inf)
                if not np.isnan(metrics_dict[k].get('夏普比率', np.nan)) else -np.inf)
    selected   = [first]
    remaining  = [k for k in names if k != first]

    if log:
        m = metrics_dict[first]
        print(f"第1轮选择: 【{first}】 夏普={m['夏普比率']:.2f} 年化={m['年化收益']*100:.1f}%")

    for rnd in range(2, n + 1):
        if not remaining:
            break

        candidate_scores  = {}
        candidate_details = {}

        for cand in remaining:
            corrs = []
            skip  = False
            for sel in selected:
                c = correlation_matrix.loc[cand, sel]
                if pd.isna(c):
                    skip = True
                    break
                if c > threshold:
                    skip = True
                    break
                corrs.append(c)
            if skip:
                continue
            candidate_scores[cand]  = sum(corrs)
            candidate_details[cand] = corrs

        if not candidate_scores:
            if log:
                print(f"第{rnd}轮：无满足条件的候选策略（相关度均超阈值），停止")
            break

        # Top N 相关度和最小 → 再选夏普最高
        actual_top_n = min(top_n, len(candidate_scores))
        low_corr_candidates = heapq.nsmallest(actual_top_n, candidate_scores, key=candidate_scores.get)
        next_s = max(low_corr_candidates,
                     key=lambda k: metrics_dict[k].get('夏普比率', -np.inf)
                     if not np.isnan(metrics_dict[k].get('夏普比率', np.nan)) else -np.inf)

        selected.append(next_s)
        remaining.remove(next_s)

        if log:
            m = metrics_dict[next_s]
            details = candidate_details[next_s]
            print(f"\n第{rnd}轮选择: 【{next_s}】 夏普={m['夏普比率']:.2f} "
                  f"年化={m['年化收益']*100:.1f}% 相关度和={candidate_scores[next_s]:.4f}")
            for i, sel in enumerate(selected[:-1]):
                print(f"    与【{sel}】的相关度: {details[i]:.4f}")

    return selected


# ============================================================
# 三b、穷举最优组合（策略数≤20时使用，保证全局最优）
# ============================================================

def _calc_combo_weights(combo, returns_dict, params, opt_target='最大夏普'):
    """
    对指定策略组合按给定优化目标计算最优权重。
    opt_target: '最大夏普' | '控制回撤' | '最大卡尔马' | '风险平价' | '等权'
    返回 dict {策略名: 权重} 或 None（数据不足时）
    """
    valid = [s for s in combo if s in returns_dict]
    if len(valid) < 2:
        return {s: 1.0 / len(combo) for s in combo}  # 等权兜底

    # 对齐共同交易日
    ret_df = pd.concat([returns_dict[s] for s in valid], axis=1, keys=valid).dropna()
    if len(ret_df) < 30:
        return {s: 1.0 / len(valid) for s in valid}  # 数据不足→等权

    n = len(valid)
    rf = params.get('ref_rate', 0.04)
    raw_min = params.get('min_weight', 0.05)
    raw_max = params.get('max_weight', 0.60)
    min_w = min(raw_min, 1.0 / n)
    max_w = max(raw_max, 1.0 / n)
    bounds = [(min_w, max_w)] * n
    cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1}]
    w0 = np.ones(n) / n

    def _stats(w):
        port = (ret_df * w).sum(axis=1)
        nav = (1 + port).cumprod()
        days = len(port)
        total = nav.iloc[-1] - 1
        ann_ret = (1 + total) ** (250 / days) - 1 if days > 0 else 0
        ann_vol = port.std(ddof=1) * np.sqrt(250)
        sharpe = (ann_ret - rf) / ann_vol if ann_vol > 1e-9 else 0
        mdd = ((nav - nav.cummax()) / nav.cummax()).min()
        calmar = ann_ret / abs(mdd) if abs(mdd) > 1e-9 else 0
        return ann_ret, ann_vol, sharpe, mdd, calmar

    try:
        if opt_target == '等权':
            w = w0
        elif opt_target == '最大夏普':
            res = minimize(lambda w: -_stats(w)[2], w0, method='SLSQP',
                           bounds=bounds, constraints=cons,
                           options={'maxiter': 500, 'ftol': 1e-8})
            w = res.x
        elif opt_target == '最大卡尔马':
            res = minimize(lambda w: -_stats(w)[4], w0, method='SLSQP',
                           bounds=bounds, constraints=cons,
                           options={'maxiter': 500, 'ftol': 1e-8})
            w = res.x
        elif opt_target == '控制回撤':
            mdd_limit = params.get('max_drawdown_limit', 0.20)
            def obj(w):
                ar, _, _, mdd, _ = _stats(w)
                excess = max(0.0, abs(mdd) - mdd_limit)
                return -ar + 1000.0 * excess ** 2
            res = minimize(obj, w0, method='SLSQP',
                           bounds=bounds, constraints=cons,
                           options={'maxiter': 500, 'ftol': 1e-8})
            w = res.x
        elif opt_target == '风险平价':
            def rp_loss(w):
                port_std = (ret_df * w).sum(axis=1).std(ddof=1) * np.sqrt(250)
                cov = ret_df.cov().values * 250
                mrc = cov @ w / (port_std + 1e-10)
                rc = w * mrc
                target_rc = np.full(n, rc.sum() / n)
                return np.sum((rc - target_rc) ** 2)
            res = minimize(rp_loss, w0, method='SLSQP',
                           bounds=bounds, constraints=cons,
                           options={'maxiter': 500, 'ftol': 1e-8})
            w = res.x
        else:
            w = w0
    except Exception:
        w = w0

    w = np.clip(w, 0, 1)
    w = w / w.sum()
    return {s: float(wt) for s, wt in zip(valid, w)}


def _show_recommend_types(results, params, returns_dict=None):
    """
    根据穷举排行榜结果，按多个维度分别输出特色推荐组合（附带最优权重）。
    支持的类型（可在PARAMS['recommend_types']中配置）：
      高收益    - 按预估年化收益从高到低，权重目标：控制回撤
      低回撤    - 按预估最大回撤（绝对值）从低到高，权重目标：控制回撤
      攻守兼备  - 同时包含进攻和防守标签的组合中，综合得分最高，权重目标：最大夏普
      低相关    - 按平均相关度从低到高，权重目标：风险平价
      高夏普    - 按 (预估年化/预估回撤绝对值) 近似夏普排序，权重目标：最大夏普
      均衡稳健  - 年化收益与回撤综合评分最优（卡尔马近似），权重目标：最大卡尔马
    """
    from IPython.display import display, HTML as _HTML_cls

    recommend_types = params.get('recommend_types', ['高收益', '低回撤', '攻守兼备', '低相关', '高夏普', '均衡稳健'])
    top_n = params.get('recommend_top_n', 3)

    if not results or not recommend_types:
        return

    # 类型配置：(显示名, emoji, 主题色, 排序key函数, 是否反转, 筛选条件, 权重优化目标)
    type_configs = {
        '高收益':   ('高收益组合',   '🚀', '#D32F2F',
                    lambda r: r['est_ann'],     True,  None,
                    '控制回撤'),
        '低回撤':   ('低回撤组合',   '🛡️', '#1565C0',
                    lambda r: abs(r['est_mdd']), False, None,
                    '控制回撤'),
        '攻守兼备': ('攻守兼备组合', '⚔️', '#6A1B9A',
                    lambda r: r['est_ann'] / (abs(r['est_mdd']) + 0.01),
                    True,
                    lambda r: (any('进攻' in s for s in r['combo'])
                               and any('防守' in s for s in r['combo'])),
                    '最大夏普'),
        '低相关':   ('低相关组合',   '🔀', '#00695C',
                    lambda r: r['avg_r'],        False, None,
                    '风险平价'),
        '高夏普':   ('高夏普组合',   '📈', '#E65100',
                    lambda r: (r['est_ann'] - 0.04) / (abs(r['est_mdd']) + 0.01),
                    True,  None,
                    '最大夏普'),
        '均衡稳健': ('均衡稳健组合', '⚖️', '#2E7D32',
                    lambda r: r['est_ann'] / (abs(r['est_mdd']) + 0.01) * (1 - r['avg_r']),
                    True,  None,
                    '最大卡尔马'),
    }

    th = "padding:7px 12px;border:1px solid #CCC;text-align:center;font-weight:bold;"

    html = "<h3 style='color:#444;margin-top:24px;'>🎯 推荐组合类型 — 多维度特色推荐</h3>"
    html += ("<p style='color:#666;font-size:12px;margin:2px 0 12px;'>"
             "以下按不同投资目标，分别从穷举结果中筛选最佳组合，供参考。"
             "</p>")

    for rtype in recommend_types:
        if rtype not in type_configs:
            continue
        display_name, emoji, color, sort_key, reverse, filter_fn, wt_target = type_configs[rtype]

        # 筛选
        pool = results
        if filter_fn is not None:
            pool = [r for r in results if filter_fn(r)]
        if not pool:
            continue

        # 排序
        ranked = sorted(pool, key=sort_key, reverse=reverse)
        top_items = ranked[:top_n]

        # 是否有实际收益率数据可做权重优化
        can_optimize = (returns_dict is not None and len(returns_dict) >= 2)
        wt_col_header = (f"推荐权重<br><span style='font-weight:normal;font-size:11px;'"
                         f">[{wt_target}]</span>") if can_optimize else "推荐权重<br>(等权)"

        # 构建卡片
        html += (f"<div style='margin-bottom:18px;border:2px solid {color};"
                 f"border-radius:8px;overflow:hidden;'>"
                 f"<div style='background:{color};color:#fff;padding:8px 14px;"
                 f"font-weight:bold;font-size:14px;'>"
                 f"{emoji} {display_name} TOP {top_n}</div>"
                 f"<table style='border-collapse:collapse;font-size:13px;"
                 f"font-family:Arial,sans-serif;width:100%;'>"
                 f"<thead><tr style='background:#F5F5F5;'>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:52px;'>名次</th>"
                 f"<th style='{th}'>组合策略</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:52px;'>规模</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:92px;'>预估年化</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:104px;'>预估最大回撤</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:92px;'>平均相关度</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:center;font-weight:bold;width:96px;'>卡尔马(近似)</th>"
                 f"<th style='padding:7px 8px;border:1px solid #CCC;text-align:left;font-weight:bold;min-width:280px;'>{wt_col_header}</th>"
                 f"</tr></thead><tbody>")

        medals = ['🥇', '🥈', '🥉'] + [''] * 10
        for rank, r in enumerate(top_items, 1):
            combo_str = '<br>'.join(r['combo'])
            calmar_approx = r['est_ann'] / (abs(r['est_mdd']) + 0.01)
            ann_c = '#D32F2F' if r['est_ann'] >= 0 else '#388E3C'
            bg = '#FFFDE7' if rank == 1 else '#FFFFFF'

            # ── 计算推荐权重 ──
            if can_optimize:
                wt_dict = _calc_combo_weights(r['combo'], returns_dict, params, opt_target=wt_target)
            else:
                n_s = len(r['combo'])
                wt_dict = {s: 1.0 / n_s for s in r['combo']}

            # 将权重取整到最近的5%倍数，并确保总和=100%
            _keys = list(wt_dict.keys())
            _pcts = [round(wt_dict[k] * 100 / 5) * 5 for k in _keys]
            _diff = 100 - sum(_pcts)
            if _diff != 0:
                _errs = [wt_dict[_keys[i]] * 100 - _pcts[i] for i in range(len(_keys))]
                _steps = int(_diff / 5)
                _idxs = sorted(range(len(_keys)), key=lambda i: _errs[i], reverse=(_steps > 0))
                for _i in range(abs(_steps)):
                    _pcts[_idxs[_i % len(_idxs)]] += 5 * (1 if _steps > 0 else -1)
            wt_dict = {_keys[i]: _pcts[i] / 100.0 for i in range(len(_keys))}

            # 权重展示：每个策略两行（名称行 + 条形图+百分比行）
            wt_lines = []
            for s in r['combo']:
                wt = wt_dict.get(s, 1.0 / len(r['combo']))
                bar_w = int(wt * 160)   # 最大160px
                wt_lines.append(
                    f"<div style='margin:3px 0;text-align:left;'>"
                    f"<div style='font-size:11px;color:#333;margin-bottom:2px;'>{s}</div>"
                    f"<div style='display:flex;align-items:center;justify-content:flex-start;'>"
                    f"<div style='width:{bar_w}px;height:10px;background:{color};"
                    f"border-radius:3px;margin-right:6px;opacity:0.75;flex-shrink:0;'></div>"
                    f"<span style='font-size:12px;font-weight:bold;color:{color};'>{wt*100:.0f}%</span>"
                    f"</div>"
                    f"</div>"
                )
            wt_cell = "".join(wt_lines)

            html += (f"<tr style='background:{bg};'>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;"
                     f"text-align:center;font-weight:bold;font-size:16px;'>{medals[rank-1]}{rank}</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;"
                     f"white-space:normal;word-break:break-word;line-height:1.8;'>{combo_str}</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;'>{r['size']}只</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                     f"color:{ann_c};font-weight:bold;'>{r['est_ann']*100:+.2f}%</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                     f"color:#388E3C;font-weight:bold;'>{r['est_mdd']*100:.2f}%</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                     f"color:#1565C0;font-weight:bold;'>{r['avg_r']:.4f}</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                     f"font-weight:bold;'>{calmar_approx:.2f}</td>"
                     f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:left;'>{wt_cell}</td>"
                     f"</tr>")

        html += "</tbody></table></div>"

    try:
        display(_HTML_cls(html))
    except Exception:
        print(html)


def exhaustive_optimal_selection(metrics_dict, correlation_matrix, params, returns_dict=None):
    """
    穷举所有可能的策略子集，按平均相关度从低到高排序。
    对每个子集计算: 平均相关度、ENS、DR，输出完整排行榜。
    返回: 平均相关度全局最低的子集（相同时选ENS最高的）

    适用场景: 策略总数 ≤ 20（组合数 ≤ 2^20 ≈ 100万，秒级完成）
    """
    from itertools import combinations

    names = [k for k in metrics_dict.keys() if k in correlation_matrix.index]
    total = len(names)
    min_size = max(2, params.get('min_combo_size', 2))  # 最少组合策略数量，默认2，可在PARAMS['min_combo_size']中设置
    max_size = min(total, params.get('n_strategies', total))  # 最多选n_strategies个
    log = params['enable_log']

    if log:
        total_combos = sum(
            len(list(combinations(names, k)))
            for k in range(min_size, max_size + 1)
        )
        print("\n" + "=" * 70)
        print(f"穷举最优组合（共评估 {total_combos} 种子集，规模2~{max_size}只）")
        print("=" * 70)

    results = []
    
    require_mixed = params.get('require_mixed', True)
    has_offense_pool = any('进攻' in n for n in names)
    has_defense_pool = any('防守' in n for n in names)
    force_mixed = require_mixed and has_offense_pool and has_defense_pool
    
    if log:
        print(f"攻防约束: require_mixed={require_mixed}, 池中包含进攻策略={has_offense_pool}, 包含防守策略={has_defense_pool}")
    if require_mixed and not force_mixed:
        print("\n[警告] require_mixed=True，但有效策略池中未同时找到带有(进攻)和(防守)标签的策略！强制攻防过滤已自动关闭，请检查策略数据是否获取成功或标签是否正确。")

    for size in range(min_size, max_size + 1):
        for combo in combinations(names, size):
            combo = list(combo)
            
            # 强制要求攻防兼备（过滤掉只有进攻或只有防守的组合）
            if force_mixed:
                if not any('进攻' in s for s in combo) or not any('防守' in s for s in combo):
                    continue
                    
            # 提取子矩阵
            sub = correlation_matrix.loc[combo, combo].values.astype(float)
            # 排除对角线
            mask = ~np.eye(size, dtype=bool)
            off_diag = sub[mask]
            # 跳过含NaN的组合（数据不足以计算相关度）
            if np.any(np.isnan(off_diag)):
                continue
            avg_r = np.mean(off_diag)
            mn_r  = np.min(off_diag)
            mx_r  = np.max(off_diag)
            # ENS
            denom = 1 + (size - 1) * avg_r
            ens = size / denom if denom > 1e-9 else float('nan')
            # DR
            dr_d = denom / size
            dr   = 1.0 / np.sqrt(dr_d) if dr_d > 0 else float('nan')
            dr_max = np.sqrt(size)
            # 预估组合收益（等权平均）
            avg_tot_ret = np.mean([metrics_dict[s]['总收益'] for s in combo])
            avg_ann_ret = np.mean([metrics_dict[s]['年化收益'] for s in combo])
            avg_mdd = np.mean([metrics_dict[s]['最大回撤'] for s in combo])
            
            results.append({
                'combo':  combo,
                'size':   size,
                'avg_r':  avg_r,
                'min_r':  mn_r,
                'max_r':  mx_r,
                'ens':    ens,
                'dr':     dr,
                'dr_max': dr_max,
                'est_tot': avg_tot_ret,
                'est_ann': avg_ann_ret,
                'est_mdd': avg_mdd,
            })

    if not results:
        print("[错误] 没有可用的组合（可能相关度数据不足）")
        return []

    # 按平均相关度升序排序，相同则按ENS降序（与原算法完全一致）
    results.sort(key=lambda x: (round(x['avg_r'], 6), -x['ens']))

    # ── HTML 排行榜 ────────────────────────────────────────
    show_top = min(10, len(results))

    th = "padding:7px 12px;border:1px solid #CCC;text-align:center;font-weight:bold;"
    rank_html = ("<h3 style='color:#444;margin-top:16px;'>穷举最优组合排行榜 Top"
                 f"{show_top}（共评估 {len(results)} 种，规模{min_size}~{max_size}只）</h3>"
                 "<table style='border-collapse:collapse;font-size:13px;"
                 "font-family:Arial,sans-serif;width:100%;'>"
                 f"<thead><tr style='background:#1A3A5C;color:white;'>"
                 f"<th style='{th}width:52px;'>排名</th>"
                 f"<th style='{th}min-width:180px;text-align:left;'>组合策略</th>"
                 f"<th style='{th}width:52px;'>规模</th>"
                 f"<th style='{th}width:96px;'>预估总收益</th>"
                 f"<th style='{th}width:88px;'>预估年化</th>"
                 f"<th style='{th}width:104px;'>预估最大回撤</th>"
                 f"<th style='{th}width:88px;'>平均相关度</th>"
                 f"<th style='{th}width:88px;'>最大相关度</th>"
                 f"<th style='{th}width:60px;'>ENS</th>"
                 f"<th style='{th}width:72px;'>DR达标</th></tr></thead><tbody>")

    for rank, r in enumerate(results[:show_top], 1):
        combo_str = '<br>'.join(r['combo'])
        dr_pct = r['dr'] / r['dr_max'] * 100 if not np.isnan(r['dr']) else float('nan')
        if rank == 1:
            bg, medal = '#FFF9C4', '🏆'
        elif rank <= 3:
            bg, medal = '#F1F8E9', '✓'
        else:
            bg, medal = '#FFFFFF', ''
        rank_html += (f"<tr style='background:{bg};'>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                      f"font-weight:bold;'>{medal}{rank}</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;"
                      f"white-space:normal;word-break:break-word;line-height:1.8;'>{combo_str}</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;'>"
                      f"{r['size']}只</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                      f"color:{'#D32F2F' if r['est_tot']>=0 else '#388E3C'};font-weight:bold;'>{r['est_tot']*100:+.2f}%</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                      f"color:{'#D32F2F' if r['est_ann']>=0 else '#388E3C'};font-weight:bold;'>{r['est_ann']*100:+.2f}%</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                      f"color:#388E3C;font-weight:bold;'>{r['est_mdd']*100:.2f}%</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
                      f"color:#1565C0;font-weight:bold;'>{r['avg_r']:.4f}</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;'>"
                      f"{r['max_r']:.4f}</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;'>"
                      f"{r['ens']:.2f}</td>"
                      f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;'>"
                      f"{dr_pct:.1f}%</td></tr>")
    rank_html += "</tbody></table>"
    _show_html(rank_html)

    # ── 多维度推荐组合类型（高收益/低回撤/攻守兼备/低相关/高夏普/均衡稳健）──────
    _show_recommend_types(results, params, returns_dict=returns_dict)

    # ── 最优组合详情 HTML ────────────────────────────────────
    best = results[0]
    

    return best['combo']


# ============================================================
# 四、可视化层
# ============================================================

def plot_correlation_heatmap(correlation_matrix, params, highlight=None):
    """
    以 HTML 彩色表格展示策略相关度矩阵。
    - 对角线：灰底 1.000
    - 正相关：白→红（值越高越红）
    - 负相关：白→蓝（值越负越蓝）
    - 推荐组合交叉单元格：绿色边框高亮
    """
    if not params['plot_heatmap']:
        return

    highlight = highlight or []
    names  = correlation_matrix.columns.tolist()
    mat    = correlation_matrix.values.astype(float)

    def _corr_cell(r_name, c_name, val):
        """生成单个相关度单元格"""
        is_diag = (r_name == c_name)
        is_hl   = (r_name in highlight and c_name in highlight and not is_diag)

        if is_diag:
            return ("<td style='padding:8px 12px;border:1px solid #CCC;"
                    "text-align:center;background:#EEEEEE;color:#888;'>"
                    "1.000</td>")

        v = float(val)
        if np.isnan(v):
            return ("<td style='padding:8px 12px;border:1px solid #CCC;"
                    "text-align:center;color:#BBB;'>-</td>")

        border = '1px solid #CCC'

        # 四段式固定配色：极低=绿，低=浅绿，中=橙，高=红，负=蓝
        if v < 0:
            # 负相关：蓝色系，越负越深
            intensity = min(abs(v), 1.0)
            r = int(255 - (255 - 21)  * intensity)
            g = int(255 - (255 - 101) * intensity)
            b = int(255 - (255 - 192) * intensity)
            bg    = f'rgb({r},{g},{b})'
            txt_c = '#FFFFFF' if intensity > 0.55 else '#0D47A1'
            lvl   = '负相关'
        elif v < 0.3:
            # 极低：深绿背景，强调分散效果好
            t = v / 0.3  # 0→1
            r = int(200 - (200 - 165) * t)
            g = int(230 - (230 - 214) * t)
            b = int(200 - (200 - 167) * t)
            bg    = f'rgb({r},{g},{b})'
            txt_c = '#1B5E20'
            lvl   = '极低'
        elif v < 0.5:
            # 低：浅绿/薄荷色
            t = (v - 0.3) / 0.2  # 0→1
            r = int(232 - (232 - 220) * t)
            g = int(245 - (245 - 237) * t)
            b = int(233 - (233 - 200) * t)
            bg    = f'rgb({r},{g},{b})'
            txt_c = '#2E7D32'
            lvl   = '低'
        elif v < 0.7:
            # 中：橙黄色，警示
            t = (v - 0.5) / 0.2  # 0→1
            r = int(255 - (255 - 251) * (1 - t))
            g = int(236 - (236 - 192) * t)
            b = int(179 - (179 - 75)  * t)
            bg    = f'rgb({r},{g},{b})'
            txt_c = '#E65100'
            lvl   = '中'
        else:
            # 高：红色系，越高越深
            t = min((v - 0.7) / 0.3, 1.0)  # 0→1
            r = int(239 - (239 - 183) * (1 - t))
            g = int(154 - (154 - 28)  * t)
            b = int(154 - (154 - 28)  * t)
            bg    = f'rgb({r},{g},{b})'
            txt_c = '#FFFFFF' if t > 0.4 else '#B71C1C'
            lvl   = '高'

        return (f"<td style='padding:8px 12px;border:{border};"
                f"text-align:center;background:{bg};'>"
                f"<div style='color:{txt_c};font-weight:bold;font-size:13px;'>{v:.3f}</div>"
                f"<div style='color:{txt_c};font-size:10px;opacity:0.9;'>{lvl}</div>"
                f"</td>")

    # ── 构建表格 ────────────────────────────────────────────
    th = "padding:9px 12px;border:1px solid #CCC;text-align:center;font-weight:bold;"
    html = ("<h3 style='color:#444;margin-top:16px;'>策略相关度矩阵</h3>"
            "<p style='color:#666;font-size:12px;margin:2px 0 8px;'>"
            "<span style='background:rgb(165,214,167);color:#1B5E20;padding:1px 6px;border-radius:3px;font-weight:bold;'>极低 &lt;0.3</span>&nbsp;"
            "<span style='background:rgb(220,237,200);color:#2E7D32;padding:1px 6px;border-radius:3px;font-weight:bold;'>低 0.3~0.5</span>&nbsp;"
            "<span style='background:rgb(251,192,75);color:#E65100;padding:1px 6px;border-radius:3px;font-weight:bold;'>中 0.5~0.7</span>&nbsp;"
            "<span style='background:rgb(183,28,28);color:#fff;padding:1px 6px;border-radius:3px;font-weight:bold;'>高 &gt;0.7</span>&nbsp;"
            "<span style='background:rgb(21,101,192);color:#fff;padding:1px 6px;border-radius:3px;font-weight:bold;'>负相关 &lt;0 ★天然对冲</span>"
            "</p>"
            "<table style='border-collapse:collapse;font-size:13px;"
            "font-family:Arial,sans-serif;'>"
            f"<thead><tr style='background:#1A3A5C;color:white;'>"
            f"<th style='{th}'></th>")
    for name in names:
        star = '★ ' if name in highlight else ''
        bg_h = '#F5A623' if name in highlight else '#1A3A5C'
        html += (f"<th style='padding:9px 12px;border:1px solid #CCC;"
                 f"text-align:center;font-weight:bold;background:{bg_h};'>"
                 f"{star}{name}</th>")
    html += "</tr></thead><tbody>"

    for i, r_name in enumerate(names):
        star  = '★ ' if r_name in highlight else ''
        bg_rh = '#FFF9C4' if r_name in highlight else '#FAFAFA'
        html += (f"<tr><td style='padding:9px 12px;border:1px solid #CCC;"
                 f"font-weight:bold;background:{bg_rh};white-space:nowrap;'>"
                 f"{star}{r_name}</td>")
        for j, c_name in enumerate(names):
            html += _corr_cell(r_name, c_name, mat[i][j])
        html += "</tr>"

    html += "</tbody></table>"

    # ── 整体分散化统计 ───────────────────────────────────────
    mat_copy = mat.copy()
    np.fill_diagonal(mat_copy, np.nan)
    avg = float(np.nanmean(mat_copy))
    mn  = float(np.nanmin(mat_copy))
    mx  = float(np.nanmax(mat_copy))
    if avg < 0.3:
        grade, gc = '优秀（整体接近独立）', '#1B5E20'
    elif avg < 0.5:
        grade, gc = '良好（有明显分散效果）', '#2E7D32'
    elif avg < 0.7:
        grade, gc = '一般（建议引入更多差异化策略）', '#E65100'
    else:
        grade, gc = '差（高度相关，分散价值低）', '#B71C1C'

    html += ("<table style='border-collapse:collapse;font-size:13px;"
             "font-family:Arial,sans-serif;margin-top:10px;width:50%;'><tbody>")
    for k, v in [('全策略平均相关度', f"{avg:.4f}"),
                 ('最小相关度', f"{mn:.4f}"),
                 ('最大相关度', f"{mx:.4f}"),
                 ('整体分散化评级',
                  f"<span style='color:{gc};font-weight:bold;'>{grade}</span>")]:
        html += (f"<tr><td style='padding:6px 14px;border:1px solid #DDD;"
                 f"background:#F5F5F5;font-weight:bold;width:40%;'>{k}</td>"
                 f"<td style='padding:6px 14px;border:1px solid #DDD;'>{v}</td></tr>")
    html += "</tbody></table>"
    _show_html(html)


def plot_cumulative_returns(returns_dict, params, highlight=None):
    """
    绘制各策略累积收益曲线（归一化，起点=1.0）。
    推荐组合策略用实线+粗线强调，其余用细虚线淡化。
    """
    if not params['plot_returns']:
        return

    # print("\n正在绘制各策略累积净值曲线...")

    fig, ax = plt.subplots(figsize=params['plot_size'])

    # 颜色列表
    palette = plt.cm.tab20(np.linspace(0, 1, len(returns_dict)))
    highlight = highlight or []

    for idx, (name, ret) in enumerate(returns_dict.items()):
        nav = (1 + ret).cumprod()
        nav = nav / nav.iloc[0]  # 归一化起点=1.0

        is_highlighted = (name in highlight)
        lw     = 2.5 if is_highlighted else 1.0
        alpha  = 1.0 if is_highlighted else 0.35
        ls     = '-'  if is_highlighted else '--'
        zorder = 3    if is_highlighted else 1
        label  = f"★ {name}" if is_highlighted else name

        ax.plot(nav.index, nav.values,
                label=label, linewidth=lw, alpha=alpha,
                linestyle=ls, color=palette[idx], zorder=zorder)

    ax.set_title('各策略累积净值曲线（归一化，起点=1.0）\n★ = 推荐低相关组合',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('日期', fontsize=11)
    ax.set_ylabel('累积净值', fontsize=11)
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=9,
              framealpha=0.9, borderpad=0.8)
    ax.grid(True, alpha=0.25, linestyle='--')
    ax.tick_params(axis='x', rotation=30)
    plt.tight_layout()
    plt.show()


def plot_rolling_correlation(returns_dict, params, pairs=None):
    """
    绘制策略对的滚动相关度曲线，动态展示相关度随市场变化的波动。
    pairs: 指定要画的策略对列表 [(name1, name2), ...]，None则取所有两两组合
    """
    if not params['plot_rolling_corr']:
        return

    # print(f"\n正在绘制滚动相关度曲线（窗口={params['rolling_window']}日）...")

    names = list(returns_dict.keys())
    window = params['rolling_window']

    if pairs is None:
        pairs = [(names[i], names[j])
                 for i in range(len(names))
                 for j in range(i + 1, len(names))]

    if not pairs:
        return

    fig, ax = plt.subplots(figsize=params['plot_size'])
    palette = plt.cm.tab20(np.linspace(0, 1, len(pairs)))

    for idx, (n1, n2) in enumerate(pairs):
        r1 = returns_dict[n1]
        r2 = returns_dict[n2]
        common = r1.index.intersection(r2.index)
        if len(common) < window + 5:
            continue
        df_pair = pd.DataFrame({'r1': r1[common], 'r2': r2[common]})
        rolling_corr = df_pair['r1'].rolling(window).corr(df_pair['r2']).dropna()

        ax.plot(rolling_corr.index, rolling_corr.values,
                label=f"{n1} vs {n2}", linewidth=1.5,
                color=palette[idx], alpha=0.85)

    # 阈值线
    ax.axhline(y=params['correlation_threshold'], color='red', linestyle='--',
               linewidth=1.2, alpha=0.7, label=f"阈值={params['correlation_threshold']}")
    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.8, alpha=0.4)

    ax.set_title(f'策略滚动相关度（{window}日窗口）\n红虚线=相关度阈值',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('日期', fontsize=11)
    ax.set_ylabel('皮尔逊相关系数', fontsize=11)
    ax.set_ylim(-1.1, 1.1)
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=9,
              framealpha=0.9)
    ax.grid(True, alpha=0.25, linestyle='--')
    ax.tick_params(axis='x', rotation=30)
    plt.tight_layout()
    plt.show()


# ============================================================
# 六、最优权重优化（Markowitz 均倣-方差模型）
# ============================================================

def _portfolio_stats(weights, ret_matrix, rf=0.04):
    """
    计算组合日收益的年化绩效指标。
    ret_matrix: DataFrame，列为各策略日收益率序列（已对齐）
    """
    port_ret = (ret_matrix * weights).sum(axis=1)       # 组合日收益率
    nav      = (1 + port_ret).cumprod()                  # 组合净値
    days     = len(port_ret)
    total    = nav.iloc[-1] - 1
    ann_ret  = (1 + total) ** (250 / days) - 1 if days > 0 else 0
    ann_vol  = port_ret.std(ddof=1) * np.sqrt(250)
    sharpe   = (ann_ret - rf) / ann_vol if ann_vol > 1e-9 else 0
    mdd      = ((nav - nav.cummax()) / nav.cummax()).min()
    calmar   = ann_ret / abs(mdd) if abs(mdd) > 1e-9 else 0
    return ann_ret, ann_vol, sharpe, mdd, calmar, nav







# ============================================================
# 新增：月度收益 & 月度最大回撤 HTML 对比表格
# （风格参照聚宽策略回测结果分析工具，纯 HTML，无需 matplotlib）
# ============================================================

try:
    from IPython.display import display, HTML as _HTML
    def _show_html(html): display(_HTML(html))
except ImportError:
    def _show_html(html): print(html)


def _build_monthly_combined(returns_dict, params):
    """
    计算所有策略的月度收益率，返回：
      combined_ret : dict {策略名: {year: {month: rate}}}
      all_years    : sorted list of years
      global_end   : 所有策略数据的最大结束日期（Timestamp）
    """
    combined = {}
    all_years = set()
    global_end = None
    use_log = params.get('use_log_returns', False)

    for name, daily_ret in returns_dict.items():
        if len(daily_ret) == 0:
            continue
        s_end = daily_ret.index.max()
        if global_end is None or s_end > global_end:
            global_end = s_end
            
        if use_log:
            nav = np.exp(daily_ret.cumsum())
        else:
            nav = (1 + daily_ret).cumprod()
            
        monthly_nav = nav.resample('M').last()
        monthly_start = monthly_nav.shift(1)
        monthly_start.iloc[0] = 1.0
        monthly_rate = monthly_nav / monthly_start - 1
        
        strat_data = {}
        for ts, rate in monthly_rate.items():
            y, m = ts.year, ts.month
            all_years.add(y)
            if y not in strat_data:
                strat_data[y] = {}
            strat_data[y][m] = rate
        # 年度汇总（复利）
        for y in strat_data:
            yr_ret = 1.0
            for m in range(1, 13):
                if m in strat_data[y]:
                    yr_ret *= (1 + strat_data[y][m])
            strat_data[y][0] = yr_ret - 1   # key=0 代表年度
        combined[name] = strat_data

    return combined, sorted(all_years, reverse=True), global_end


def _rate_cell(rate, is_annual=False):
    """生成单个月度/年度收益率 HTML 单元格（A股惯例：正红负绿）。"""
    if rate is None or (isinstance(rate, float) and (pd.isna(rate) or np.isinf(rate))):
        return "<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;color:#BBB;'>-</td>"

    color      = '#D32F2F' if rate >= 0 else '#388E3C'
    bg         = '#FFF5F5' if rate >= 0 else '#F5FFF5'
    font_w     = 'bold' if is_annual else 'normal'
    if is_annual:
        bg = '#FFF0E0' if rate >= 0 else '#E8FFE8'
    rate_str   = f"{rate*100:+.2f}%"
    return (f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
            f"background:{bg};font-weight:{font_w};'>"
            f"<span style='color:{color};font-size:13px;'>{rate_str}</span></td>")


def _mdd_cell(mdd, is_annual=False):
    """生成单个月度/年度最大回撤 HTML 单元格（0=白，越深红=越大）。"""
    if mdd is None or (isinstance(mdd, float) and (pd.isna(mdd) or np.isinf(mdd))):
        return "<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;color:#BBB;'>-</td>"

    # 回撤为负数，abs 越大颜色越深
    intensity  = min(abs(mdd) / 0.25, 1.0)           # 超过25%算满色
    r_ch = int(255 - (255 - 211) * intensity)         # 255→211
    g_ch = int(255 - (255 - 47)  * intensity)         # 255→47
    b_ch = int(255 - (255 - 47)  * intensity)         # 255→47
    bg         = f'rgb({r_ch},{g_ch},{b_ch})'
    color      = '#FFFFFF' if intensity > 0.5 else '#B71C1C'
    font_w     = 'bold' if is_annual else 'normal'
    mdd_str    = f"{mdd*100:.2f}%"
    return (f"<td style='padding:6px 10px;border:1px solid #DDD;text-align:center;"
            f"background:{bg};font-weight:{font_w};'>"
            f"<span style='color:{color};font-size:13px;'>{mdd_str}</span></td>")



def plot_monthly_returns(returns_dict, params, highlight=None):
    """
    输出「所有策略月度收益合并对比」HTML 表格（一张表）。
    结构：
      - 表头：年份 | 月份 | 策略A | 策略B | 策略C | ...
      - 每年用浅灰行分隔，末行为该年年度汇总
      - 颜色：正红负绿（A股惯例），★ = 推荐组合策略列
      - 不显示超出所有策略回测区间（最大结束日期）的月份
    """
    highlight = highlight or []
    if not returns_dict:
        return

    combined, all_years, global_end = _build_monthly_combined(returns_dict, params)
    names        = list(returns_dict.keys())
    month_keys   = list(range(12, 0, -1)) + [0]
    months_label = ['12月','11月','10月','9月','8月','7月',
                    '6月','5月','4月','3月','2月','1月','年度']

    # 回测区间截止年月
    end_y = global_end.year  if global_end is not None else 9999
    end_m = global_end.month if global_end is not None else 12

    def _within_range(year, month_key):
        """month_key=0 表示年度汇总行，仅当该年 <= end_y 时显示。"""
        if month_key == 0:
            return year <= end_y
        return (year, month_key) <= (end_y, end_m)

    # print("\n正在生成月度收益合并对比表...")

    # ── 构建表头 ────────────────────────────────────────────
    th = "padding:8px 10px;border:1px solid #CCC;text-align:center;font-weight:bold;"
    html = ("<h3 style='color:#444;margin-top:20px;'>月度收益率对比（各策略合并）</h3>"
            "<table style='border-collapse:collapse;font-size:12px;"
            "font-family:Arial,sans-serif;'>"
            "<thead><tr style='background:#1A3A5C;color:white;'>"
            f"<th style='{th}'>年份</th>"
            f"<th style='{th}'>月份</th>")
    for name in names:
        star = "★ " if name in highlight else ""
        bg_h = "#F5A623" if name in highlight else "#1A3A5C"
        html += (f"<th style='padding:8px 10px;border:1px solid #CCC;"
                 f"text-align:center;font-weight:bold;background:{bg_h};'>"
                 f"{star}{name}</th>")
    html += "</tr></thead><tbody>"

    # ── 逐年逐月填入数据 ────────────────────────────────────
    for y in all_years:
        # 预计算本年实际渲染行数（排除无数据月份、超出回测区间的月份，以及独立的年度汇总行），用于正确设置 rowspan
        year_row_count = sum(
            1 for mk in month_keys
            if mk != 0 and _within_range(y, mk)
            and any(mk in combined.get(name, {}).get(y, {}) for name in names)
        )
        if year_row_count == 0:
            continue
        year_printed = False

        for mk, ml in zip(month_keys, months_label):
            is_annual = (mk == 0)
            # 跳过超出回测区间的月份
            if not _within_range(y, mk):
                continue
            has_data  = any(mk in combined.get(name, {}).get(y, {}) for name in names)
            if not has_data:
                continue

            if is_annual:
                td_year  = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;font-weight:bold;background:#FFF3E0;"
                            f"white-space:nowrap;'>{y}</td>")
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;font-weight:bold;background:#FFF3E0;'>"
                            f"{ml}</td>")
            elif not year_printed:
                td_year  = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"border-top:2px solid #555;text-align:center;"
                            f"font-weight:bold;background:#F5F5F5;"
                            f"white-space:nowrap;' rowspan='{year_row_count}'>{y}</td>")
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"border-top:2px solid #555;text-align:center;"
                            f"background:#FAFAFA;'>{ml}</td>")
                year_printed = True
            else:
                td_year  = ""
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;background:#FAFAFA;'>{ml}</td>")

            html += f"<tr>{td_year}{td_month}"
            for name in names:
                rate = combined.get(name, {}).get(y, {}).get(mk, None)
                html += _rate_cell(rate, is_annual=is_annual)
            html += "</tr>"

    html += "</tbody></table>"
    _show_html(html)




def plot_monthly_drawdowns(returns_dict, params, highlight=None):
    """
    输出「所有策略月度最大回撤合并对比」HTML 表格（一张表）。
    结构与 plot_monthly_returns 相同，颜色：白→深红（回撤越大越红）。
    """
    highlight = highlight or []
    if not returns_dict:
        return

    # print("\n正在生成月度最大回撤合并对比表...")

    # ── 计算月度 & 年度最大回撤 ─────────────────────────────
    use_log = params.get('use_log_returns', False)
    
    def _month_mdd(daily_ret, year, month):
        grp = daily_ret[
            (daily_ret.index.year == year) & (daily_ret.index.month == month)
        ]
        if len(grp) == 0:
            return None
        if use_log:
            nav = np.exp(grp.cumsum())
        else:
            nav = (1 + grp).cumprod()
        return ((nav - nav.cummax()) / nav.cummax()).min()

    def _year_mdd(daily_ret, year):
        grp = daily_ret[daily_ret.index.year == year]
        if len(grp) == 0:
            return None
        if use_log:
            nav = np.exp(grp.cumsum())
        else:
            nav = (1 + grp).cumprod()
        return ((nav - nav.cummax()) / nav.cummax()).min()

    all_mdd    = {}
    all_years  = set()
    global_end = None
    names      = list(returns_dict.keys())

    for name, daily_ret in returns_dict.items():
        if len(daily_ret) == 0:
            continue
        s_end = daily_ret.index.max()
        if global_end is None or s_end > global_end:
            global_end = s_end
            
        monthly_anchor = daily_ret.resample('M').last()
        strat_data = {}
        for ts in monthly_anchor.index:
            y, m = ts.year, ts.month
            all_years.add(y)
            if y not in strat_data:
                strat_data[y] = {}
            strat_data[y][m] = _month_mdd(daily_ret, y, m)
        for y in strat_data:
            strat_data[y][0] = _year_mdd(daily_ret, y)
        all_mdd[name] = strat_data

    all_years    = sorted(all_years, reverse=True)

    # 回测区间截止年月
    end_y = global_end.year  if global_end is not None else 9999
    end_m = global_end.month if global_end is not None else 12

    def _within_range_dd(year, month_key):
        if month_key == 0:
            return year <= end_y
        return (year, month_key) <= (end_y, end_m)
    month_keys   = list(range(12, 0, -1)) + [0]
    months_label = ['12月','11月','10月','9月','8月','7月',
                    '6月','5月','4月','3月','2月','1月','年度最大']

    # ── 构建表头 ────────────────────────────────────────────
    th = "padding:8px 10px;border:1px solid #CCC;text-align:center;font-weight:bold;"
    html = ("<h3 style='color:#444;margin-top:20px;'>月度最大回撤对比（各策略合并）</h3>"
            "<table style='border-collapse:collapse;font-size:12px;"
            "font-family:Arial,sans-serif;'>"
            "<thead><tr style='background:#1A3A5C;color:white;'>"
            f"<th style='{th}'>年份</th>"
            f"<th style='{th}'>月份</th>")
    for name in names:
        star = "★ " if name in highlight else ""
        bg_h = "#F5A623" if name in highlight else "#1A3A5C"
        html += (f"<th style='padding:8px 10px;border:1px solid #CCC;"
                 f"text-align:center;font-weight:bold;background:{bg_h};'>"
                 f"{star}{name}</th>")
    html += "</tr></thead><tbody>"

    # ── 逐年逐月填入数据 ────────────────────────────────────
    for y in all_years:
        year_row_count = sum(
            1 for mk in month_keys
            if mk != 0 and _within_range_dd(y, mk)
            and any(mk in all_mdd.get(name, {}).get(y, {}) for name in names)
        )
        if year_row_count == 0:
            continue
        year_printed = False

        for mk, ml in zip(month_keys, months_label):
            is_annual = (mk == 0)
            # 跳过超出回测区间的月份
            if not _within_range_dd(y, mk):
                continue
            has_data  = any(mk in all_mdd.get(name, {}).get(y, {}) for name in names)
            if not has_data:
                continue

            if is_annual:
                td_year  = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;font-weight:bold;background:#FFF3E0;"
                            f"white-space:nowrap;'>{y}</td>")
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;font-weight:bold;background:#FFF3E0;'>"
                            f"{ml}</td>")
            elif not year_printed:
                td_year  = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"border-top:2px solid #555;text-align:center;"
                            f"font-weight:bold;background:#F5F5F5;"
                            f"white-space:nowrap;' rowspan='{year_row_count}'>{y}</td>")
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"border-top:2px solid #555;text-align:center;"
                            f"background:#FAFAFA;'>{ml}</td>")
                year_printed = True
            else:
                td_year  = ""
                td_month = (f"<td style='padding:6px 10px;border:1px solid #CCC;"
                            f"text-align:center;background:#FAFAFA;'>{ml}</td>")

            html += f"<tr>{td_year}{td_month}"
            for name in names:
                mdd = all_mdd.get(name, {}).get(y, {}).get(mk, None)
                html += _mdd_cell(mdd, is_annual=is_annual)
            html += "</tr>"

    html += "</tbody></table>"
    _show_html(html)


# ============================================================
# 六、主入口
# ============================================================

def run_strategy_correlation_analysis(strategies=None, params=None):
    """
    主函数：一键运行策略相关性分析。
    strategies: dict {策略名: 回测ID}，None则使用顶部配置的 STRATEGIES
    params    : dict 参数，None则使用顶部配置的 PARAMS
    """
    strats = strategies or STRATEGIES
    p      = params    or PARAMS

    if not strats:
        print("⚠ 请在配置区 STRATEGIES 中填入回测ID！")
        print("示例：")
        print("  STRATEGIES = {")
        print("      '策略A': 'your_backtest_id_here',")
        print("      '策略B': 'another_backtest_id',")
        print("  }")
        return

    # 1. 获取数据
    returns_dict, metrics_dict = fetch_strategy_returns(strats, p)

    if len(returns_dict) < 2:
        print("策略数量不足（至少需要2个），分析终止")
        return

    # 2. 计算相关矩阵
    corr_matrix = calc_pairwise_correlation(returns_dict, p)

    # ⑤ 相关度热力图
    plot_correlation_heatmap(corr_matrix, p, highlight=[])

    # ① 穷举/贪心求最优组合（排行榜在此函数内输出）
    EXHAUSTIVE_LIMIT = 10
    if len(returns_dict) <= EXHAUSTIVE_LIMIT:
        selected = exhaustive_optimal_selection(metrics_dict, corr_matrix, p, returns_dict=returns_dict)
    else:
        print(f"\n策略数>{EXHAUSTIVE_LIMIT}，使用贪心算法近似求解...")
        selected = greedy_select_strategies(returns_dict, metrics_dict, corr_matrix, p)


    # ③ 月度收益率对比
    plot_monthly_returns(returns_dict, p, highlight=selected)

    # ④ 月度最大回撤对比
    plot_monthly_drawdowns(returns_dict, p, highlight=selected)

    return {
        'returns':        returns_dict,
        'metrics':        metrics_dict,
        'correlation':    corr_matrix,
        'selected':       selected
    }


# ============================================================
# 入口
# ============================================================
if __name__ == '__main__':
    my_strategies = {}
    my_params = {**PARAMS}

    result = run_strategy_correlation_analysis(
        strategies=my_strategies if my_strategies else None,
        params=my_params
    )