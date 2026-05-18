#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星高照ETF轮动策略 — 港美股衍生版
=====================================
核心思路：将A股排行榜TOP1策略(七星高照ETF轮动V1.7.2)的核心逻辑
衍生到港美股市场，使用各市场可对标的ETF大池。

七星高照核心逻辑：
  1. 加权线性回归动量得分 = 年化 × R²（短期25日 + 长期250日双周期）
  2. 三重过滤：盈利保护 + 短期动量 + 近3日跌幅过滤
  3. 持仓1只最强ETF + 防御ETF(货币基金/短债)
  4. 周频调仓(约98次/年)

港美股ETF大池对标：
  🇺🇸 美股大池(22只): SPY/QQQ/VEA/VWO + 行业ETF(XLK/XLF/XLE等9只) + 
     避险(GLD/TLT/AGG/SHY/IEF) + 房地产(VNQ)
  🇭🇰 港股大池(22只): 盈富/恒生科技/高股息 + A股ETF + 黄金ETF + 蓝筹
  🇨🇳 A股大池(38只): 原版(对比验证)

评分体系：V4 对数+安全区奖励(永不截断)
"""

import os
import sys
import json
import math
import time
import smtplib
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

warnings.filterwarnings('ignore')
sys.path.insert(0, '/data/workspace/strategy_arena')
from strategy_ranker import compute_total_score, get_grade

# ================================================================
# 配置
# ================================================================
LOCAL_DATA_DIR = '/data/workspace/back_trader_stocks'
ETF_DIR = os.path.join(LOCAL_DATA_DIR, 'etf')
HK_ETF_DIR = os.path.join(LOCAL_DATA_DIR, 'hk_etf')
HK_DIR = os.path.join(LOCAL_DATA_DIR, 'hk')
CN_DIR = os.path.join(LOCAL_DATA_DIR, 'a')

INIT_CASH = 1_000_000
FEES_RATE = 0.001          # 单边手续费
SLIPPAGE = 0.001           # 滑点
RISK_FREE_RATE = 0.045     # 无风险利率

# 回测区间
MAIN_START = '2019-01-01'
MAIN_END = '2026-04-25'
STRESS_START = '2015-06-01'
STRESS_END = '2018-12-31'

# ================================================================
# ETF大池定义 — 三市场对标
# ================================================================
# A股38只大池（原版七星高照）
CN_BIG_POOL = {
    '518880_XSHG': '黄金ETF',
    '159985_XSHE': '豆粕ETF',
    '513100_XSHG': '纳指ETF',
    '159915_XSHE': '创业板ETF',
    'sh516080': ('516080_XSHG', '创新药ETF'),
    '511880_XSHG': '银华日利(防御)',
    '510300_XSHG': '沪深300ETF',
    '510500_XSHG': '中证500ETF',
    '512880_XSHG': '证券ETF',
    '512660_XSHG': '军工ETF',
    '513500_XSHG': '标普500ETF',
    '513130_XSHG': '恒生科技ETF',
    '512100_XSHG': '中证1000ETF',
    '512040_XSHG': '价值100ETF',
    '159919_XSHE': '沪深300ETF联接',
    '159920_XSHE': '恒生ETF',
    '513050_XSHG': '中日ETF',
    '511010_XSHG': '国债ETF',
    '511260_XSHG': '十年国债ETF',
    '510050_XSHG': '上证50ETF',
    '510210_XSHG': '上证指数ETF',
    '512890_XSHG': '红利低波ETF',
    '513080_XSHG': '德国DAXETF',
    '513290_XSHG': '纳斯达克生物ETF',
    '513310_XSHG': '东南亚科技ETF',
    '513400_XSHG': '道琼斯ETF',
    '513520_XSHG': '日经225ETF',
    '513690_XSHG': '法国CAC40ETF',
    '513730_XSHG': '东南亚科技ETF',
    '501018_XSHG': '南方原油LOF',
    '159201_XSHE': '自由现金流ETF',
    '159509_XSHE': '中证500ETF联接',
    '159529_XSHE': '科创50ETF',
    '159792_XSHE': '科技创新ETF',
    '159967_XSHE': '创成长ETF',
    '159980_XSHE': '有色ETF',
    '159981_XSHE': '能源化工ETF',
    '511220_XSHG': '城投ETF',
}

# 美股22只大池（对标A股38只的资产类别覆盖）
US_BIG_POOL = {
    # 宽基指数
    'SPY': '标普500ETF',
    'QQQ': '纳斯达克100ETF',
    'VEA': '发达市场ETF',
    'VWO': '新兴市场ETF',
    # 行业ETF(对标A股的行业ETF)
    'XLK': '科技行业ETF',
    'XLF': '金融行业ETF',
    'XLE': '能源行业ETF',
    'XLI': '工业行业ETF',
    'XLP': '消费必需ETF',
    'XLV': '医疗行业ETF',
    'XLU': '公用事业ETF',
    'XLY': '可选消费ETF',
    'XLB': '材料行业ETF',
    'XLC': '通信行业ETF',
    # 避险/固收(对标A股防御ETF)
    'GLD': '黄金ETF',
    'TLT': '20年国债ETF',
    'AGG': '总债券ETF(防御)',
    'SHY': '1-3年国债ETF(防御)',
    'IEF': '7-10年国债ETF',
    # 另类
    'VNQ': '房地产ETF',
    'SH': '做空标普500ETF',
}

# 港股22只大池（ETF+蓝筹混合，对标A股38只覆盖度）
HK_BIG_POOL = {
    # 恒生系列ETF
    'hk02800': '盈富基金(恒指ETF)',
    'hk02819': 'iShares恒指ETF',
    'hk02878': '南方恒生科技ETF',
    'hk03067': 'iShares恒生科技ETF',
    'hk03110': '恒生高股息ETF(防御)',
    # A股/中国ETF
    'hk02845': 'iShares明晟中国ETF',
    'hk02846': 'iShares中国大型股ETF',
    'hk02828': '恒生中国企业ETF(H股)',
    'hk02837': '南方A50ETF',
    'hk02827': '嘉实明晟中国A股ETF',
    'hk03040': '华夏沪深三百ETF',
    'hk03096': '华夏上证五十ETF',
    'hk03032': '易方达中证一百ETF',
    # 另类/行业
    'hk02840': 'SPDR黄金ETF',
    'hk02833': 'iShares富时A50ETF',
    'hk02836': '华夏沪深三百ETF',
    'hk02849': '易方达恒生高股息ETF',
    'hk03005': '南方东英沪深三百ETF',
    'hk03033': '南方沪深三百ETF',
    'hk03039': '华夏恒生ESG指数ETF',
    'hk03042': '招商沪深三百ETF',
    'hk03088': '南方沪深三百增强ETF',
}

# ================================================================
# 数据加载
# ================================================================
def load_csv_data(filepath: str) -> pd.DataFrame:
    """加载CSV价格数据"""
    try:
        df = pd.read_csv(filepath, parse_dates=['Date'], index_col='Date')
        df = df.sort_index()
        # 标准化列名
        col_map = {}
        for c in df.columns:
            cl = c.strip().lower()
            if cl == 'close' or cl == '收盘':
                col_map[c] = 'Close'
            elif cl == 'open' or cl == '开盘':
                col_map[c] = 'Open'
            elif cl == 'high' or cl == '最高':
                col_map[c] = 'High'
            elif cl == 'low' or cl == '最低':
                col_map[c] = 'Low'
            elif cl == 'volume' or cl == '成交量':
                col_map[c] = 'Volume'
        df = df.rename(columns=col_map)
        if 'Close' not in df.columns:
            return pd.DataFrame()
        if 'Volume' not in df.columns:
            df['Volume'] = 0
        return df[['Close', 'Volume']].dropna(subset=['Close'])
    except Exception as e:
        return pd.DataFrame()


def load_market_pool(pool: dict, data_dir: str) -> dict:
    """加载一个大池的所有数据"""
    data = {}
    loaded = 0
    missing = []
    for sym, name in pool.items():
        # 尝试多种文件名格式
        candidates = [
            os.path.join(data_dir, f'{sym}.csv'),
        ]
        if data_dir == CN_DIR:
            # A股格式
            candidates.append(os.path.join(data_dir, f'{sym}.csv'))
        elif data_dir == HK_ETF_DIR or data_dir == HK_DIR:
            candidates.append(os.path.join(data_dir, f'{sym}.csv'))

        found = False
        for fp in candidates:
            if os.path.exists(fp):
                df = load_csv_data(fp)
                if len(df) >= 200:
                    data[sym] = df
                    loaded += 1
                    found = True
                    break
        if not found:
            missing.append(f'{sym}({name})')

    return data, loaded, missing


# ================================================================
# 七星高照核心策略逻辑
# ================================================================
def qixing_rotation_backtest(
    price_data: dict,
    lookback_days: int = 25,
    long_lookback: int = 250,
    holdings_num: int = 1,
    profit_protection_lookback: int = 1,
    profit_protection_threshold: float = 0.05,
    short_momentum_days: int = 10,
    short_momentum_threshold: float = 0.0,
    drop_filter_days: int = 3,
    drop_filter_threshold: float = -0.05,
    safe_asset: str = None,
    start_date: str = MAIN_START,
    end_date: str = MAIN_END,
    fees_rate: float = FEES_RATE,
    market_label: str = '',
) -> dict:
    """
    七星高照ETF轮动策略回测
    
    核心逻辑：
    1. 加权线性回归动量得分 = 年化 × R²（短+长双周期）
    2. 三重过滤：
       - 盈利保护：当前价低于N日前价格×(1-threshold)则淘汰
       - 短期动量：过去M日收益<0则淘汰
       - 急跌过滤：近K日最大跌幅超过阈值则淘汰
    3. 持仓最强1只，不满足条件时持有防御ETF
    4. 周频调仓
    """
    if not price_data:
        return None

    # 构建多资产收盘价矩阵
    close_dict = {}
    vol_dict = {}
    for sym, df in price_data.items():
        if 'Close' in df.columns and len(df) > 0:
            close_dict[sym] = df['Close']
            vol_dict[sym] = df['Volume'] if 'Volume' in df.columns else pd.Series(0, index=df.index)

    if not close_dict:
        return None

    close_prices = pd.DataFrame(close_dict).sort_index()
    volumes = pd.DataFrame(vol_dict).reindex(close_prices.index).fillna(0)

    # 截取日期范围
    mask = (close_prices.index >= start_date) & (close_prices.index <= end_date)
    close_prices = close_prices[mask]
    volumes = volumes[mask]

    if len(close_prices) < long_lookback + 50:
        return None

    # 确定防御ETF
    available = list(close_prices.columns)
    if safe_asset is None or safe_asset not in available:
        # 默认用第一个可用资产作为防御
        safe_asset = available[-1] if available else None
    if safe_asset is None:
        return None

    assets = available

    # 周频调仓日（每周一）
    weekly_dates = close_prices.index.to_series().groupby(
        close_prices.index.to_series().dt.isocalendar().week
    ).first().values
    # 简化：每5个交易日调仓
    all_dates = close_prices.index
    rebalance_indices = list(range(long_lookback, len(all_dates), 5))

    # 回测
    portfolio_value = INIT_CASH
    current_holding = safe_asset
    trade_count = 0
    equity_curve = []
    holding_record = []

    for i in range(len(all_dates)):
        date = all_dates[i]
        daily_prices = close_prices.iloc[i]

        # 计算当日收益率
        if i > 0:
            prev_prices = close_prices.iloc[i - 1]
            if current_holding in daily_prices.index and current_holding in prev_prices.index:
                curr_p = daily_prices[current_holding]
                prev_p = prev_prices[current_holding]
                if pd.notna(curr_p) and pd.notna(prev_p) and prev_p > 0:
                    daily_return = (curr_p / prev_p) - 1
                    # 扣除费用（仅调仓日扣）
                    portfolio_value *= (1 + daily_return)

        equity_curve.append({
            'date': date,
            'value': portfolio_value,
            'holding': current_holding,
        })

        # 调仓逻辑
        if i in rebalance_indices:
            best_etf = safe_asset
            best_score = -999

            for asset in assets:
                if asset not in daily_prices.index or pd.isna(daily_prices[asset]):
                    continue

                # 需要足够的历史数据
                if i < long_lookback:
                    continue

                # 获取历史价格
                hist = close_prices.iloc[i - long_lookback:i + 1][asset].dropna()
                if len(hist) < lookback_days + 5:
                    continue

                # ====== 短期加权线性回归动量 ======
                short_prices = hist.iloc[-lookback_days:]
                y_short = np.log(short_prices.values)
                x_short = np.arange(len(y_short))
                w_short = np.exp(np.linspace(-1, 0, len(y_short)))  # 近期权重大
                w_short /= w_short.sum()

                try:
                    coeffs_s = np.polyfit(x_short, y_short, 1, w=w_short)
                    slope_s = coeffs_s[0]
                except:
                    continue

                ann_s = math.exp(slope_s * 252) - 1
                y_pred_s = slope_s * x_short + coeffs_s[1]
                ss_res_s = np.sum(w_short * (y_short - y_pred_s) ** 2)
                ss_tot_s = np.sum(w_short * (y_short - np.average(y_short, weights=w_short)) ** 2)
                r2_s = 1 - ss_res_s / ss_tot_s if ss_tot_s > 0 else 0

                short_score = ann_s * r2_s
                # 限制范围
                if not (short_score > 0 and short_score < 6):
                    short_score = 0

                # ====== 长期加权线性回归动量 ======
                long_prices = hist
                y_long = np.log(long_prices.values)
                x_long = np.arange(len(y_long))
                w_long = np.exp(np.linspace(-1, 0, len(y_long)))
                w_long /= w_long.sum()

                try:
                    coeffs_l = np.polyfit(x_long, y_long, 1, w=w_long)
                    slope_l = coeffs_l[0]
                except:
                    continue

                ann_l = math.exp(slope_l * 252) - 1
                y_pred_l = slope_l * x_long + coeffs_l[1]
                ss_res_l = np.sum(w_long * (y_long - y_pred_l) ** 2)
                ss_tot_l = np.sum(w_long * (y_long - np.average(y_long, weights=w_long)) ** 2)
                r2_l = 1 - ss_res_l / ss_tot_l if ss_tot_l > 0 else 0

                long_score = ann_l * r2_l
                if not (long_score > 0 and long_score < 0.5):
                    long_score = 0

                combined = short_score + long_score

                # ====== 三重过滤 ======
                # 过滤1：盈利保护（当前价 vs N日前）
                if profit_protection_lookback > 0 and i >= profit_protection_lookback:
                    past_price = close_prices.iloc[i - profit_protection_lookback].get(asset, np.nan)
                    if pd.notna(past_price) and past_price > 0:
                        if daily_prices[asset] < past_price * (1 - profit_protection_threshold):
                            combined = 0  # 回撤超限，淘汰

                # 过滤2：短期动量过滤
                if short_momentum_days > 0 and i >= short_momentum_days:
                    sm_start = close_prices.iloc[i - short_momentum_days].get(asset, np.nan)
                    if pd.notna(sm_start) and sm_start > 0:
                        sm_return = (daily_prices[asset] / sm_start) - 1
                        if sm_return < short_momentum_threshold:
                            combined = 0  # 短期动量不足，淘汰

                # 过滤3：急跌过滤（近K日最大跌幅）
                if drop_filter_days > 0 and i >= drop_filter_days:
                    recent = hist.iloc[-drop_filter_days:]
                    if len(recent) >= drop_filter_days:
                        max_drop = (recent.min() / recent.iloc[0]) - 1
                        if max_drop < drop_filter_threshold:
                            combined = 0  # 急跌，淘汰

                if combined > best_score:
                    best_score = combined
                    best_etf = asset

            # 执行调仓
            if best_etf != current_holding:
                # 扣除交易成本
                portfolio_value *= (1 - fees_rate * 2 - SLIPPAGE * 2)
                current_holding = best_etf
                trade_count += 1

    # ====== 计算绩效指标 ======
    if not equity_curve:
        return None

    eq_df = pd.DataFrame(equity_curve).set_index('date')
    eq_df['return'] = eq_df['value'].pct_change()

    # 总年化收益率
    total_days = (eq_df.index[-1] - eq_df.index[0]).days
    if total_days <= 0:
        return None
    annual_return = (eq_df['value'].iloc[-1] / INIT_CASH) ** (365.0 / total_days) - 1

    # 夏普比率
    daily_returns = eq_df['return'].dropna()
    if len(daily_returns) > 0 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() * 252 - RISK_FREE_RATE) / (daily_returns.std() * math.sqrt(252))
    else:
        sharpe = 0

    # 最大回撤
    cummax = eq_df['value'].cummax()
    drawdown = (eq_df['value'] - cummax) / cummax
    max_drawdown = abs(drawdown.min())

    # 胜率
    win_days = (daily_returns > 0).sum()
    total_trade_days = len(daily_returns)
    win_rate = win_days / total_trade_days * 100 if total_trade_days > 0 else 0

    # 盈亏比
    gains = daily_returns[daily_returns > 0]
    losses = daily_returns[daily_returns < 0]
    avg_gain = gains.mean() if len(gains) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
    profit_factor = (avg_gain * len(gains)) / (avg_loss * len(losses)) if len(losses) > 0 and avg_loss > 0 else 999

    # 年交易次数
    years = total_days / 365.0
    avg_trades_per_year = trade_count / years if years > 0 else 0

    # 持仓分布
    holding_counts = eq_df['holding'].value_counts()
    total_days_held = len(eq_df)
    holding_distribution = {}
    for sym, cnt in holding_counts.items():
        pct = cnt / total_days_held * 100
        pool_name = CN_BIG_POOL.get(sym, US_BIG_POOL.get(sym, HK_BIG_POOL.get(sym, sym)))
        holding_distribution[f'{sym}({pool_name})'] = round(pct, 1)

    # 月度正收益率
    monthly_returns = eq_df['value'].resample('ME').last().pct_change().dropna()
    monthly_positive_rate = (monthly_returns > 0).mean() if len(monthly_returns) > 0 else 0

    # V4评分
    score_result = compute_total_score(
        annual_return=annual_return * 100,
        sharpe=sharpe,
        max_drawdown=max_drawdown * 100,
        profit_factor=profit_factor,
        win_rate=win_rate,
        cross_period_robust=False,  # 港美股暂无跨周期验证
        survivorship_bias=True,
        monthly_positive_rate=monthly_positive_rate,
    )

    return {
        'annual_return': round(annual_return * 100, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'calmar': round(annual_return / max_drawdown, 2) if max_drawdown > 0 else 0,
        'win_rate': round(win_rate, 2),
        'profit_factor': round(profit_factor, 2),
        'avg_trades_per_year': round(avg_trades_per_year, 1),
        'holding_distribution': holding_distribution,
        'total_score': score_result['total_score'],
        'grade': score_result['grade'],
        'score_detail': score_result,
        'monthly_positive_rate': round(monthly_positive_rate, 3),
        'final_value': round(eq_df['value'].iloc[-1], 2),
        'trade_count': trade_count,
        'equity_curve': eq_df,
    }


def run_stress_test(price_data: dict, safe_asset: str = None, market_label: str = '') -> dict:
    """压力测试(2015-2018)"""
    result = qixing_rotation_backtest(
        price_data=price_data,
        safe_asset=safe_asset,
        start_date=STRESS_START,
        end_date=STRESS_END,
        market_label=market_label,
    )
    if result is None:
        return {'annual_return': 0, 'max_drawdown': 0}
    return {
        'annual_return': result['annual_return'],
        'max_drawdown': result['max_drawdown'],
    }


# ================================================================
# 主程序
# ================================================================
def main():
    print("=" * 90)
    print("  🌟 七星高照ETF轮动策略 — 港美股衍生回测")
    print("  核心逻辑：加权线性回归动量(年化×R²) + 三重过滤 + 防御ETF + 周频调仓")
    print("=" * 90)

    all_results = {}

    # ── 1. A股大池(对比验证) ──
    print("\n📦 [1/3] 加载A股大池数据(38只)...")
    cn_data, cn_loaded, cn_missing = load_market_pool(CN_BIG_POOL, CN_DIR)
    print(f"  ✅ 加载{cn_loaded}只，缺失{len(cn_missing)}只")
    if cn_missing:
        print(f"  ⚠️ 缺失: {cn_missing[:5]}...")

    if cn_data:
        print("  🔄 回测A股七星高照(38只大池)...")
        # 确定防御ETF
        cn_safe = '511880_XSHG' if '511880_XSHG' in cn_data else None
        cn_result = qixing_rotation_backtest(cn_data, safe_asset=cn_safe, market_label='A股')
        if cn_result:
            cn_stress = run_stress_test(cn_data, safe_asset=cn_safe, market_label='A股')
            cn_result['stress_test'] = cn_stress
            all_results['CN'] = cn_result
            print(f"  ✅ A股: 年化{cn_result['annual_return']}% 夏普{cn_result['sharpe']} 回撤{cn_result['max_drawdown']}% "
                  f"评分{cn_result['total_score']}({cn_result['grade']})")
        else:
            print("  ❌ A股回测失败")

    # ── 2. 美股大池 ──
    print("\n📦 [2/3] 加载美股大池数据(22只)...")
    us_data, us_loaded, us_missing = load_market_pool(US_BIG_POOL, ETF_DIR)
    print(f"  ✅ 加载{us_loaded}只，缺失{len(us_missing)}只")
    if us_missing:
        print(f"  ⚠️ 缺失: {us_missing[:5]}...")

    if us_data:
        print("  🔄 回测美股七星高照(22只大池)...")
        # 确定防御ETF
        us_safe = 'SHY' if 'SHY' in us_data else ('AGG' if 'AGG' in us_data else None)
        us_result = qixing_rotation_backtest(us_data, safe_asset=us_safe, market_label='美股')
        if us_result:
            us_stress = run_stress_test(us_data, safe_asset=us_safe, market_label='美股')
            us_result['stress_test'] = us_stress
            all_results['US'] = us_result
            print(f"  ✅ 美股: 年化{us_result['annual_return']}% 夏普{us_result['sharpe']} 回撤{us_result['max_drawdown']}% "
                  f"评分{us_result['total_score']}({us_result['grade']})")
        else:
            print("  ❌ 美股回测失败(数据不足)")

    # ── 3. 港股大池 ──
    print("\n📦 [3/3] 加载港股大池数据(22只)...")
    # 港股ETF数据
    hk_data, hk_loaded, hk_missing = load_market_pool(HK_BIG_POOL, HK_ETF_DIR)
    print(f"  ✅ 港股ETF: 加载{hk_loaded}只，缺失{len(hk_missing)}只")
    if hk_missing:
        print(f"  ⚠️ 缺失: {hk_missing[:5]}...")

    if hk_data:
        print("  🔄 回测港股七星高照(22只大池)...")
        # 确定防御ETF — 用高股息ETF
        hk_safe = 'hk03110' if 'hk03110' in hk_data else ('hk02800' if 'hk02800' in hk_data else None)
        hk_result = qixing_rotation_backtest(hk_data, safe_asset=hk_safe, market_label='港股')
        if hk_result:
            hk_stress = run_stress_test(hk_data, safe_asset=hk_safe, market_label='港股')
            hk_result['stress_test'] = hk_stress
            all_results['HK'] = hk_result
            print(f"  ✅ 港股: 年化{hk_result['annual_return']}% 夏普{hk_result['sharpe']} 回撤{hk_result['max_drawdown']}% "
                  f"评分{hk_result['total_score']}({hk_result['grade']})")
        else:
            print("  ❌ 港股回测失败(数据不足)")

    # ── 4. 多参数变体回测 ──
    print("\n\n" + "=" * 90)
    print("  🔬 参数变体回测（调整回看期/过滤条件）")
    print("=" * 90)

    variant_params = [
        {'lookback_days': 20, 'short_momentum_days': 5, 'name': '短周期V1(20日/5日)'},
        {'lookback_days': 30, 'short_momentum_days': 15, 'name': '长周期V2(30日/15日)'},
        {'lookback_days': 25, 'drop_filter_threshold': -0.08, 'name': '宽松急跌V3(-8%阈值)'},
        {'lookback_days': 25, 'profit_protection_threshold': 0.08, 'name': '宽松盈利V4(8%回撤)'},
        {'lookback_days': 15, 'short_momentum_days': 5, 'name': '超短周期V5(15日/5日)'},
    ]

    variant_results = {}
    for market, m_data, m_safe, m_label in [
        ('CN', cn_data, '511880_XSHG' if '511880_XSHG' in cn_data else None, 'A股'),
        ('US', us_data, 'SHY' if 'SHY' in us_data else ('AGG' if 'AGG' in us_data else None), '美股'),
        ('HK', hk_data, 'hk03110' if 'hk03110' in hk_data else ('hk02800' if 'hk02800' in hk_data else None), '港股'),
    ]:
        if not m_data or not m_safe:
            continue
        variant_results[market] = []
        print(f"\n  {m_label}参数变体:")
        for vp in variant_params:
            name = vp.pop('name')
            result = qixing_rotation_backtest(m_data, safe_asset=m_safe, **vp)
            if result:
                result['variant_name'] = name
                result['params'] = vp
                variant_results[market].append(result)
                print(f"    {name}: 年化{result['annual_return']}% 夏普{result['sharpe']} "
                      f"回撤{result['max_drawdown']}% 评分{result['total_score']}({result['grade']})")
            vp['name'] = name  # restore

    # ── 5. 生成报告 ──
    print("\n\n" + "=" * 90)
    print("  📊 生成HTML报告...")
    print("=" * 90)

    html = build_report_html(all_results, variant_results)
    report_path = f'/data/workspace/strategy_arena/qixing_cross_market_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✅ 报告已保存: {report_path}")

    # ── 6. 发送邮件 ──
    print("\n📧 发送邮件...")
    send_email(html)
    print("\n✅ 全部完成！")


# ================================================================
# 报告生成
# ================================================================
def build_report_html(all_results: dict, variant_results: dict) -> str:
    """生成HTML报告"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    GRADE_COLORS = {
        'S+': '#ff4500', 'S': '#f97316', 'A': '#22c55e',
        'B': '#3b82f6', 'C': '#a855f7', 'D': '#6b7280', 'F': '#374151',
    }

    # 核心结果卡片
    cards_html = ''
    for market, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        r = all_results.get(market)
        if not r:
            cards_html += f'''
            <div style="background:#0c0c14;border-radius:10px;padding:16px;margin-bottom:10px;border:1px solid rgba(249,115,22,0.1)">
              <div style="font-size:14px;font-weight:700;color:#6b7280">{mflag} {mlabel}：数据不足，无法回测</div>
            </div>'''
            continue

        grade = r['grade']
        gc = GRADE_COLORS.get(grade, '#6b7280')
        grade_badge = f'<span style="display:inline-block;background:{gc};color:white;font-size:12px;font-weight:800;padding:2px 8px;border-radius:4px;letter-spacing:0.5px">{grade}</span>'

        # 持仓分布Top5
        hd = r.get('holding_distribution', {})
        hd_sorted = sorted(hd.items(), key=lambda x: x[1], reverse=True)[:5]
        hd_html = ''
        for sym_name, pct in hd_sorted:
            bar_w = min(pct, 100)
            hd_html += f'''
              <div style="display:flex;align-items:center;gap:6px;margin:2px 0">
                <span style="font-size:10px;color:#9ca3af;min-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{sym_name}</span>
                <div style="flex:1;background:rgba(249,115,22,0.1);border-radius:2px;height:12px">
                  <div style="width:{bar_w}%;background:linear-gradient(90deg,#f97316,#fb923c);height:100%;border-radius:2px"></div>
                </div>
                <span style="font-size:10px;color:#f97316;font-weight:600">{pct}%</span>
              </div>'''

        stress = r.get('stress_test', {})
        stress_str = f"年化{stress.get('annual_return', 0):.1f}%/回撤{stress.get('max_drawdown', 0):.1f}%" if stress else "N/A"

        cards_html += f'''
        <div style="background:#0c0c14;border-radius:12px;padding:18px;margin-bottom:10px;border-left:3px solid {gc};border-top:1px solid rgba(249,115,22,0.1);border-bottom:1px solid rgba(249,115,22,0.1);border-right:1px solid rgba(249,115,22,0.1)">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span style="font-size:18px">{mflag}</span>
            <span style="font-size:16px;font-weight:800;color:#f97316">{mlabel}七星高照ETF轮动</span>
          </div>
          <div style="display:flex;align-items:baseline;gap:6px;margin-bottom:10px">
            <span style="font-size:28px;font-weight:800;color:{'#f97316' if r['total_score'] >= 50 else '#fb923c' if r['total_score'] >= 28 else '#6b7280'}">{r['total_score']:.1f}</span>
            <span style="font-size:12px;color:#9ca3af">分</span>
            {grade_badge}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 16px;margin-bottom:10px">
            <div><span style="font-size:10px;color:#9ca3af">年化收益</span><br><span style="font-size:15px;font-weight:700;color:#22c55e">{r['annual_return']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">夏普比率</span><br><span style="font-size:15px;font-weight:700;color:#3b82f6">{r['sharpe']:.2f}</span></div>
            <div><span style="font-size:10px;color:#9ca3af">最大回撤</span><br><span style="font-size:15px;font-weight:700;color:#ef4444">{r['max_drawdown']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">胜率</span><br><span style="font-size:15px;font-weight:700;color:#a855f7">{r['win_rate']:.1f}%</span></div>
            <div><span style="font-size:10px;color:#9ca3af">盈亏比</span><br><span style="font-size:15px;font-weight:700;color:#f59e0b">{r['profit_factor']:.2f}</span></div>
            <div><span style="font-size:10px;color:#9ca3af">年交易</span><br><span style="font-size:15px;font-weight:700;color:#6b7280">{r['avg_trades_per_year']:.1f}次</span></div>
          </div>
          <div style="font-size:10px;color:#6b7280;margin-bottom:6px">
            🔥 压力测试(2015-2018): {stress_str} | 📊 月度正收益: {r.get('monthly_positive_rate', 0)*100:.0f}%
          </div>
          <div style="margin-top:6px">
            <div style="font-size:10px;font-weight:600;color:#9ca3af;margin-bottom:4px">持仓分布 Top5</div>
            {hd_html}
          </div>
        </div>'''

    # 参数变体表格
    variant_html = ''
    for market, mlabel, mflag in [('CN', 'A股', '🇨🇳'), ('US', '美股', '🇺🇸'), ('HK', '港股', '🇭🇰')]:
        vlist = variant_results.get(market, [])
        if not vlist:
            continue
        variant_html += f'''
        <div style="margin-top:12px">
          <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:6px">{mflag} {mlabel}参数变体</div>
          <table style="width:100%;border-collapse:collapse;font-size:11px">
            <tr style="border-bottom:1px solid rgba(249,115,22,0.2)">
              <th style="padding:4px 6px;text-align:left;color:#f97316">变体</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">评分</th>
              <th style="padding:4px 6px;text-align:center;color:#f97316">等级</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">年化%</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">夏普</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">回撤%</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">盈亏比</th>
              <th style="padding:4px 6px;text-align:right;color:#f97316">胜率%</th>
            </tr>'''
        for v in vlist:
            vg = v['grade']
            vgc = GRADE_COLORS.get(vg, '#6b7280')
            variant_html += f'''
            <tr style="border-bottom:1px solid rgba(255,255,255,0.05)">
              <td style="padding:4px 6px;color:#e5e7eb">{v['variant_name']}</td>
              <td style="padding:4px 6px;text-align:right;font-weight:700;color:{vgc}">{v['total_score']:.1f}</td>
              <td style="padding:4px 6px;text-align:center"><span style="color:{vgc};font-weight:700">{vg}</span></td>
              <td style="padding:4px 6px;text-align:right;color:#22c55e">{v['annual_return']:.1f}</td>
              <td style="padding:4px 6px;text-align:right;color:#3b82f6">{v['sharpe']:.2f}</td>
              <td style="padding:4px 6px;text-align:right;color:#ef4444">{v['max_drawdown']:.1f}</td>
              <td style="padding:4px 6px;text-align:right;color:#f59e0b">{v['profit_factor']:.2f}</td>
              <td style="padding:4px 6px;text-align:right;color:#a855f7">{v['win_rate']:.1f}</td>
            </tr>'''
        variant_html += '</table></div>'

    # A股 vs 港美股对比分析
    analysis_html = ''
    cn_r = all_results.get('CN')
    us_r = all_results.get('US')
    hk_r = all_results.get('HK')

    if cn_r:
        analysis_html += '''
        <div style="margin-top:12px">
          <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:8px">📋 策略可移植性分析</div>'''

        if us_r:
            us_vs_cn = us_r['annual_return'] / cn_r['annual_return'] * 100 if cn_r['annual_return'] != 0 else 0
            analysis_html += f'''
          <div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(249,115,22,0.1)">
            <div style="font-size:12px;font-weight:600;color:#3b82f6;margin-bottom:4px">🇺🇸 美股 vs 🇨🇳 A股</div>
            <div style="font-size:11px;color:#9ca3af;line-height:1.6">
              年化收益: <span style="color:#22c55e">{us_r['annual_return']:.1f}%</span> vs <span style="color:#22c55e">{cn_r['annual_return']:.1f}%</span> (美股=A股的{us_vs_cn:.0f}%)<br>
              夏普: <span style="color:#3b82f6">{us_r['sharpe']:.2f}</span> vs <span style="color:#3b82f6">{cn_r['sharpe']:.2f}</span><br>
              回撤控制: <span style="color:#ef4444">{us_r['max_drawdown']:.1f}%</span> vs <span style="color:#ef4444">{cn_r['max_drawdown']:.1f}%</span><br>
              评分: <span style="color:#f97316">{us_r['total_score']:.1f}({us_r['grade']})</span> vs <span style="color:#f97316">{cn_r['total_score']:.1f}({cn_r['grade']})</span>
            </div>
          </div>'''

        if hk_r:
            hk_vs_cn = hk_r['annual_return'] / cn_r['annual_return'] * 100 if cn_r['annual_return'] != 0 else 0
            analysis_html += f'''
          <div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;margin-bottom:8px;border:1px solid rgba(249,115,22,0.1)">
            <div style="font-size:12px;font-weight:600;color:#a855f7;margin-bottom:4px">🇭🇰 港股 vs 🇨🇳 A股</div>
            <div style="font-size:11px;color:#9ca3af;line-height:1.6">
              年化收益: <span style="color:#22c55e">{hk_r['annual_return']:.1f}%</span> vs <span style="color:#22c55e">{cn_r['annual_return']:.1f}%</span> (港股=A股的{hk_vs_cn:.0f}%)<br>
              夏普: <span style="color:#3b82f6">{hk_r['sharpe']:.2f}</span> vs <span style="color:#3b82f6">{cn_r['sharpe']:.2f}</span><br>
              回撤控制: <span style="color:#ef4444">{hk_r['max_drawdown']:.1f}%</span> vs <span style="color:#ef4444">{cn_r['max_drawdown']:.1f}%</span><br>
              评分: <span style="color:#f97316">{hk_r['total_score']:.1f}({hk_r['grade']})</span> vs <span style="color:#f97316">{cn_r['total_score']:.1f}({cn_r['grade']})</span>
            </div>
          </div>'''

        analysis_html += '''
          <div style="background:rgba(249,115,22,0.05);border-radius:8px;padding:10px;border:1px solid rgba(249,115,22,0.1)">
            <div style="font-size:12px;font-weight:600;color:#f59e0b;margin-bottom:4px">🔑 可移植性关键因素</div>
            <div style="font-size:11px;color:#9ca3af;line-height:1.7">
              <b style="color:#22c55e">✅ 可移植</b>: 加权线性回归动量得分(年化×R²)是数学方法，市场无关<br>
              <b style="color:#22c55e">✅ 可移植</b>: 三重过滤(盈利保护+短期动量+急跌)是通用风控，市场无关<br>
              <b style="color:#f59e0b">⚠️ 需适配</b>: ETF池结构差异 — A股有商品(黄金/豆粕)+跨境(纳指/恒生科技)，
              美股有9大行业ETF，港股以指数ETF为主<br>
              <b style="color:#f59e0b">⚠️ 需适配</b>: 防御ETF — A股用货币基金(511880)，美股用短债(SHY)，
              港股用高股息(03110)，收益特征不同<br>
              <b style="color:#ef4444">❌ 难移植</b>: A股T+1限制 → 日内无法止损，港股/美股T+0可更灵活<br>
              <b style="color:#ef4444">❌ 难移植</b>: A股涨跌停限制 → 趋势延续性强，美股无涨跌停(仅熔断)
            </div>
          </div>
        </div>'''

    # 策略核心逻辑说明
    logic_html = '''
    <div style="background:#0c0c14;border-radius:10px;padding:14px;margin-top:12px;border:1px solid rgba(249,115,22,0.08)">
      <div style="font-size:12px;font-weight:600;color:#f97316;margin-bottom:8px">📐 七星高照核心逻辑</div>
      <div style="font-size:11px;color:#9ca3af;line-height:1.8">
        <b style="color:#f97316">动量得分</b>: 加权线性回归斜率 → 年化收益率，权重近期大远期小<br>
        &nbsp;&nbsp;得分 = 年化收益率 × R²（R²过滤假趋势）<br>
        &nbsp;&nbsp;短期(25日)+长期(250日)双周期得分相加 → 选最高分ETF<br><br>
        <b style="color:#3b82f6">三重过滤</b>:<br>
        &nbsp;&nbsp;1️⃣ 盈利保护: 当前价 < 1日前×(1-5%) → 淘汰(防止高位接盘)<br>
        &nbsp;&nbsp;2️⃣ 短期动量: 过去10日收益 < 0% → 淘汰(动能不足)<br>
        &nbsp;&nbsp;3️⃣ 急跌过滤: 近3日最大跌幅 > 5% → 淘汰(正在崩盘)<br><br>
        <b style="color:#22c55e">防御机制</b>: 所有ETF均不满足 → 持防御ETF(货币基金/短债/高股息)<br>
        <b style="color:#a855f7">调仓频率</b>: 周频(每5个交易日) — 平衡信号灵敏度和交易成本
      </div>
    </div>'''

    # ETF大池映射对照表
    pool_html = '''
    <details style="background:#0c0c14;border-radius:10px;padding:12px;margin-top:12px;border:1px solid rgba(249,115,22,0.08)">
      <summary style="font-size:12px;font-weight:600;color:#f97316;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">📋 ETF大池对照表（点击展开）</summary>
      <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
        <div>
          <div style="font-size:11px;font-weight:700;color:#f97316;margin-bottom:4px">🇨🇳 A股(38只)</div>
          <div style="font-size:10px;color:#9ca3af;line-height:1.6">''' + '<br>'.join(
              [f'{k}: {v}' for k, v in list(CN_BIG_POOL.items())[:12]]
          ) + '<br>...</div></div><div><div style="font-size:11px;font-weight:700;color:#3b82f6;margin-bottom:4px">🇺🇸 美股(22只)</div><div style="font-size:10px;color:#9ca3af;line-height:1.6">' + '<br>'.join(
              [f'{k}: {v}' for k, v in US_BIG_POOL.items()]
          ) + '</div></div><div><div style="font-size:11px;font-weight:700;color:#a855f7;margin-bottom:4px">🇭🇰 港股(22只)</div><div style="font-size:10px;color:#9ca3af;line-height:1.6">' + '<br>'.join(
              [f'{k}: {v}' for k, v in HK_BIG_POOL.items()]
          ) + '</div></div></div></details>'''

    # 完整HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>七星高照ETF轮动 — 港美股衍生回测</title>
  <style>
    details summary::-webkit-details-marker {{ display: none; }}
    details summary {{ list-style: none; }}
    details summary::marker {{ display: none; content: ""; }}
  </style>
</head>
<body style="margin:0;padding:12px 8px;background-color:#060610;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,sans-serif;color:#e5e7eb">
  <div style="max-width:600px;margin:0 auto">

    <!-- 标题 -->
    <div style="background:#0c0c14;border-radius:14px;padding:20px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="font-size:22px">🌟</span>
        <span style="font-size:20px;font-weight:800;color:#f97316;letter-spacing:1px">七星高照ETF轮动</span>
      </div>
      <div style="font-size:13px;font-weight:600;color:#fb923c;margin-bottom:4px">港美股衍生回测报告</div>
      <div style="font-size:11px;color:#6b7280;line-height:1.6">
        {now_str} · A股TOP1策略跨市场移植<br>
        核心逻辑：加权线性回归动量(年化×R²) + 三重过滤 + 防御ETF + 周频调仓<br>
        评分体系：V4对数+安全区奖励(永不截断)
      </div>
    </div>

    <!-- 核心结果 -->
    <div style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.18)">
      <div style="font-size:13px;font-weight:700;color:#f97316;margin-bottom:10px">🏅 三市场回测结果</div>
      {cards_html}
    </div>

    <!-- 参数变体 -->
    <details style="background:#0c0c14;border-radius:12px;padding:14px;margin-bottom:14px;border:1px solid rgba(249,115,22,0.12)">
      <summary style="font-size:13px;font-weight:700;color:#f97316;cursor:pointer;list-style:none;display:flex;align-items:center;gap:6px;outline:none">🔬 参数变体回测（点击展开）</summary>
      {variant_html}
    </details>

    <!-- 可移植性分析 -->
    {analysis_html}

    <!-- 核心逻辑说明 -->
    {logic_html}

    <!-- ETF大池对照 -->
    {pool_html}

  </div>
</body>
</html>'''

    return html


def send_email(html_content: str):
    """发送HTML邮件"""
    smtp_server = 'smtp.qq.com'
    smtp_port = 465
    sender = '848786642@qq.com'
    password = 'ljbtvacrctjobfed'
    receiver = '848786642@qq.com'

    now_str = datetime.now().strftime('%Y%m%d_%H%M')
    subject = f'【七星高照港美股衍生】{now_str} A股TOP1策略跨市场回测'

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print(f"  ✅ 邮件发送成功")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")


if __name__ == '__main__':
    main()
