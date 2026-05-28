"""
市场环境研判模块
输出：Bull / Bear / Range / Panic 及置信度

优化点：
- 增加 ADX 辅助趋势强度确认（不再只依赖均线排列）
- Panic 置信度根据 VIX 绝对值分级（而非固定95）
- Range 置信度计算更合理（结合 ADX 低位确认）
- 增加指标列完整性校验
- 增加异常处理
- 【2026-04-22】增加确认期防抖机制：regime切换需连续N日确认
"""

import logging
import json
import os
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)

# VIX 阈值
VIX_PANIC_THRESHOLD = 35
VIX_HIGH_THRESHOLD = 25
VIX_CHANGE_PANIC_THRESHOLD = 20  # 单日涨幅%

# ── 确认期防抖配置（2026-04-22新增）──
REGIME_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', 'regime_history.json')
CONFIRM_DAYS = 2  # 新regime需连续N日才正式切换
# Panic无需确认期：极端恐慌应立即切换
PANIC_SKIP_CONFIRM = True


def _load_regime_history() -> list:
    """加载历史regime判断记录"""
    if os.path.exists(REGIME_HISTORY_FILE):
        try:
            with open(REGIME_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[MarketAnalyze] 加载regime历史失败: {e}")
    return []


def _save_regime_history(history: list):
    """持久化regime判断记录（保留最近30天）"""
    # 只保留最近30条记录，避免文件无限增长
    if len(history) > 30:
        history = history[-30:]
    try:
        with open(REGIME_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[MarketAnalyze] 保存regime历史失败: {e}")


def _check_confirmation(raw_regime: str, raw_confidence: int, history: list) -> tuple:
    """
    确认期防抖核心逻辑。
    
    规则：
    1. Panic立即生效，无需确认期（极端恐慌必须即时响应）
    2. 新regime与上一个confirmed_regime不同时，需连续CONFIRM_DAYS天判断一致才切换
    3. 确认期间维持旧的confirmed_regime，但置信度逐步降低
    4. 高置信度(>=80)切换只需1天确认
    
    Returns:
        (confirmed_regime, confirmed_confidence, pending_info)
        pending_info: None 或 {'regime': str, 'days': int, 'required': int}
    """
    if not history:
        # 首次运行，直接确认
        return raw_regime, raw_confidence, None

    last_record = history[-1]
    prev_confirmed = last_record.get('confirmed_regime', 'Range')

    # 规则1: Panic立即切换
    if raw_regime == 'Panic' and PANIC_SKIP_CONFIRM:
        return raw_regime, raw_confidence, None

    # 如果当前判断与已确认的一致，无需确认
    if raw_regime == prev_confirmed:
        return raw_regime, raw_confidence, None

    # 规则4: 高置信度只需1天确认
    required_days = 1 if raw_confidence >= 80 else CONFIRM_DAYS

    # 统计最近连续多少天判断为同一新regime
    consecutive_days = 0
    for record in reversed(history):
        if record.get('raw_regime') == raw_regime:
            consecutive_days += 1
        else:
            break
    # 加上今天
    consecutive_days += 1

    pending_info = {
        'regime': raw_regime,
        'days': consecutive_days,
        'required': required_days
    }

    if consecutive_days >= required_days:
        # 确认期满足，正式切换
        logger.info(f"[MarketAnalyze] ✅ Regime切换确认：{prev_confirmed} → {raw_regime}（连续{consecutive_days}日判断一致）")
        return raw_regime, raw_confidence, pending_info
    else:
        # 确认期未满，维持旧regime，置信度打折
        discounted_confidence = max(40, raw_confidence - (required_days - consecutive_days) * 10)
        logger.info(f"[MarketAnalyze] ⏳ Regime切换待确认：{prev_confirmed} → {raw_regime}（{consecutive_days}/{required_days}日），"
                     f"维持{prev_confirmed}，置信度从{raw_confidence}降至{discounted_confidence}")
        return prev_confirmed, discounted_confidence, pending_info


def analyze_market(index_df: pd.DataFrame, vix_df: pd.DataFrame = None) -> dict:
    """
    基于大盘指数 DataFrame 和 VIX 数据研判市场状态。

    Args:
        index_df: 大盘指数 DataFrame，必须包含 close/ma20/ma60/ma120/adx14/volatility20 列
                  （由 market_info.standardize_ohlcv 处理后自动包含）
        vix_df:   VIX 指数 DataFrame，需含 close 列

    Returns:
        {
            'regime': 'Bull' / 'Bear' / 'Range' / 'Panic',
            'confidence': 0-100,
            'vix': float,
            'vix_change_pct': float,
            'summary': str
        }
    """
    # ── 输入校验 ──
    if index_df is None or index_df.empty:
        logger.error("[MarketAnalyze] 大盘指数数据为空")
        return {'regime': 'Range', 'confidence': 0, 'vix': 0,
                'vix_change_pct': 0, 'summary': '数据缺失，无法研判'}

    # 检查必要指标列
    required_cols = ['close', 'ma20', 'ma60', 'ma120']
    missing = [c for c in required_cols if c not in index_df.columns]
    if missing:
        logger.error(f"[MarketAnalyze] 大盘数据缺少必要列: {missing}，请确保数据经过 standardize_ohlcv 处理")
        return {'regime': 'Range', 'confidence': 0, 'vix': 0,
                'vix_change_pct': 0, 'summary': f'数据列缺失: {missing}'}

    latest = index_df.iloc[-1]
    latest_vix = 0.0
    vix_change = 0.0

    # ── 处理 VIX ──
    if vix_df is not None and not vix_df.empty:
        try:
            latest_vix = float(vix_df.iloc[-1]['close'])
            if len(vix_df) > 1:
                prev_vix = float(vix_df.iloc[-2]['close'])
                if prev_vix > 0:
                    vix_change = (latest_vix - prev_vix) / prev_vix * 100
        except Exception as e:
            logger.warning(f"[MarketAnalyze] VIX 数据处理失败: {e}")

    # ── 高波动恐慌优先判断 ──
    if latest_vix > VIX_PANIC_THRESHOLD or vix_change > VIX_CHANGE_PANIC_THRESHOLD:
        # 置信度根据 VIX 绝对值分级（VIX越高越确定是恐慌）
        if latest_vix > 50:
            confidence = 99
            summary = f"VIX={latest_vix:.1f}（极度恐慌），市场处于系统性风险状态"
        elif latest_vix > 40:
            confidence = 95
            summary = f"VIX={latest_vix:.1f}（严重恐慌），建议全面防御"
        elif vix_change > VIX_CHANGE_PANIC_THRESHOLD:
            confidence = 88
            summary = f"VIX单日暴涨{vix_change:.1f}%（={latest_vix:.1f}），恐慌情绪急剧升温"
        else:
            confidence = 85
            summary = f"VIX={latest_vix:.1f}，超过恐慌阈值35，市场高度不确定"
        return {'regime': 'Panic', 'confidence': confidence,
                'vix': round(latest_vix, 2), 'vix_change_pct': round(vix_change, 2),
                'summary': summary}

    # ── 获取均线和辅助指标 ──
    try:
        ma20 = float(latest.get('ma20', 0))
        ma60 = float(latest.get('ma60', 0))
        ma120 = float(latest.get('ma120', 0))
        close = float(latest['close'])
        adx = float(latest.get('adx14', 20))
        volatility = float(latest.get('volatility20', 0.15))
    except Exception as e:
        logger.error(f"[MarketAnalyze] 指标读取失败: {e}")
        return {'regime': 'Range', 'confidence': 40, 'vix': round(latest_vix, 2),
                'vix_change_pct': round(vix_change, 2), 'summary': f'指标读取异常: {e}'}

    if ma20 <= 0 or ma60 <= 0 or ma120 <= 0:
        logger.warning("[MarketAnalyze] 均线值为0，数据可能不足（需至少120行），降低置信度")
        return {'regime': 'Range', 'confidence': 30, 'vix': round(latest_vix, 2),
                'vix_change_pct': round(vix_change, 2),
                'summary': '均线数据不足，无法可靠研判，建议观望'}

    # ── 均线排列判断 ──
    bullish_alignment = (ma20 > ma60 > ma120) and (close > ma20)
    bearish_alignment = (ma20 < ma60 < ma120) and (close < ma20)

    # ADX 辅助确认趋势强度（ADX > 20 表示有趋势，> 30 趋势强）
    trend_confirmed = adx > 20
    trend_strong = adx > 30

    # VIX 高位对置信度的折扣
    vix_discount = 0
    if latest_vix > VIX_HIGH_THRESHOLD:
        vix_discount = int((latest_vix - VIX_HIGH_THRESHOLD) * 0.5)  # 每超1点扣0.5分

    if bullish_alignment:
        # 基础置信度
        if close > ma20 * 1.02:
            base_confidence = 85
        else:
            base_confidence = 70
        # ADX 加成
        if trend_strong:
            base_confidence = min(95, base_confidence + 10)
        elif trend_confirmed:
            base_confidence = min(90, base_confidence + 5)
        confidence = max(50, base_confidence - vix_discount)
        summary = (f"均线多头排列（MA20={ma20:.0f}>MA60={ma60:.0f}>MA120={ma120:.0f}），"
                   f"ADX={adx:.0f}{'（趋势强）' if trend_strong else ''}，"
                   f"VIX={latest_vix:.1f}，判定为趋势牛市，置信度{confidence}%")
        return {'regime': 'Bull', 'confidence': confidence,
                'vix': round(latest_vix, 2), 'vix_change_pct': round(vix_change, 2),
                'summary': summary}

    elif bearish_alignment:
        if close < ma20 * 0.98:
            base_confidence = 85
        else:
            base_confidence = 70
        if trend_strong:
            base_confidence = min(95, base_confidence + 10)
        elif trend_confirmed:
            base_confidence = min(90, base_confidence + 5)
        confidence = max(50, base_confidence - vix_discount)
        summary = (f"均线空头排列（MA20={ma20:.0f}<MA60={ma60:.0f}<MA120={ma120:.0f}），"
                   f"ADX={adx:.0f}{'（趋势强）' if trend_strong else ''}，"
                   f"VIX={latest_vix:.1f}，判定为趋势熊市，置信度{confidence}%")
        return {'regime': 'Bear', 'confidence': confidence,
                'vix': round(latest_vix, 2), 'vix_change_pct': round(vix_change, 2),
                'summary': summary}

    else:
        # 震荡市：ADX 低位 + 波动率适中 → 置信度更高
        base_confidence = 55
        if adx < 20:
            base_confidence += 15  # ADX低位确认震荡
        elif adx < 25:
            base_confidence += 8
        # 波动率适中加分
        if 0.10 <= volatility <= 0.25:
            base_confidence += 10
        confidence = max(40, min(80, base_confidence - vix_discount))
        summary = (f"均线排列混乱（MA20={ma20:.0f}，MA60={ma60:.0f}，MA120={ma120:.0f}），"
                   f"ADX={adx:.0f}（{'无明显趋势' if adx < 25 else '趋势不明'}），"
                   f"VIX={latest_vix:.1f}，判定为震荡市，置信度{confidence}%")
        return {'regime': 'Range', 'confidence': confidence,
                'vix': round(latest_vix, 2), 'vix_change_pct': round(vix_change, 2),
                'summary': summary}


def analyze_market_with_confirmation(index_df: pd.DataFrame,
                                      vix_df: pd.DataFrame = None) -> dict:
    """
    带确认期防抖的市场研判（2026-04-22新增）。
    
    在 analyze_market() 基础上增加确认期机制：
    - 新regime需连续N日判断一致才正式切换
    - Panic无需确认期，立即生效
    - 高置信度(>=80)只需1天确认
    
    Args:
        index_df: 同 analyze_market()
        vix_df:   同 analyze_market()
    
    Returns:
        {
            'regime': str,             # 已确认的regime（用于策略调度）
            'confidence': int,         # 已确认regime的置信度
            'confirmed_regime': str,   # 同regime（兼容字段）
            'raw_regime': str,         # 当日原始判断（未经确认期过滤）
            'raw_confidence': int,     # 当日原始置信度
            'pending_switch': dict|None,  # 待确认切换信息
            'vix': float,
            'vix_change_pct': float,
            'summary': str
        }
    """
    # 1. 先调用原始研判获取当日原始结果
    raw_result = analyze_market(index_df, vix_df)
    raw_regime = raw_result['regime']
    raw_confidence = raw_result['confidence']

    # 2. 加载历史记录
    history = _load_regime_history()

    # 3. 确认期逻辑
    confirmed_regime, confirmed_confidence, pending_info = _check_confirmation(
        raw_regime, raw_confidence, history
    )

    # 4. 记录今日判断到历史
    today_record = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'raw_regime': raw_regime,
        'raw_confidence': raw_confidence,
        'confirmed_regime': confirmed_regime,
        'confirmed_confidence': confirmed_confidence,
    }
    history.append(today_record)
    _save_regime_history(history)

    # 5. 组装返回结果
    # 构建增强版summary
    if pending_info:
        summary_suffix = (f"｜待确认切换→{pending_info['regime']}（{pending_info['days']}/{pending_info['required']}日）"
                          if confirmed_regime != raw_regime else "")
    else:
        summary_suffix = ""

    result = {
        **raw_result,
        'regime': confirmed_regime,
        'confidence': confirmed_confidence,
        'confirmed_regime': confirmed_regime,
        'raw_regime': raw_regime,
        'raw_confidence': raw_confidence,
        'pending_switch': pending_info,
        'summary': raw_result['summary'] + summary_suffix,
    }
    return result