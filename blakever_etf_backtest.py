"""
Blakever ETF 轮动回测框架 v1.0
通用 ETF 轮动类策略回测（基于 VectorBT）

功能：
1. 支持任意 ETF 池（A股/港股/美股）
2. 策略解耦：通过 strategy_func 传入不同策略
3. 内置3种策略：七星拉普拉斯 / 七星 / 三马七星
4. 统一输出：年化、最大回撤、胜率、交易次数、盈亏比

作者：BlakePro Team
日期：2026-05-25
"""
import pandas as pd
import numpy as np
import vectorbt as vbt
import talib
from datetime import datetime
import json
import os
import warnings
warnings.filterwarnings('ignore')

# =============================================================
# 配置区
# =============================================================
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'

# ETF 中文名称映射（用于输出）
ETF_NAMES = {
    '518880': '黄金ETF华安', '159980': '有色ETF大成', '159985': '豆粕ETF华夏',
    '501018': '南方原油LOF', '161226': '白银LOF国投瑞银', '159981': '能源化工ETF建信',
    '513100': '纳指ETF国泰', '159509': '纳指科技ETF景顺', '513290': '纳指生物科技ETF汇添富',
    '513500': '标普500ETF博时', '159529': '标普消费ETF景顺', '513400': '道琼斯ETF鹏华',
    '513520': '日经ETF华夏', '513030': '德国ETF华安', '513080': '法国ETF华安',
    '513310': '中韩半导体ETF华泰柏瑞', '513730': '东南亚科技ETF华泰柏瑞',
    '159792': '港股通互联网ETF富国', '513130': '恒生科技ETF华泰柏瑞', '513050': '中概互联网ETF易方达',
    '159920': '恒生ETF华夏', '513690': '港股红利ETF博时', '510300': '沪深300ETF华泰柏瑞',
    '510500': '中证500ETF南方', '510050': '上证50ETF华夏', '510210': '上证指数ETF富国',
    '159915': '创业板ETF易方达', '588080': '科创50ETF易方达', '512100': '中证1000ETF南方',
    '563360': 'A500ETF华泰柏瑞', '563300': '中证2000ETF华泰柏瑞', '512890': '红利低波ETF华泰柏瑞',
    '159967': '创业板成长ETF华夏', '512040': '价值100ETF富国', '159201': '自由现金流ETF华夏',
    '511380': '可转债ETF博时', '511010': '国债ETF国泰', '511220': '城投债ETF海富通',
    # 七星6+1
    '159915': '创业板ETF易方达', '513100': '纳指ETF国泰', '159985': '豆粕ETF华夏',
    '518880': '黄金ETF华安', '501018': '南方原油LOF', '161226': '白银LOF国投瑞银',
    '511220': '城投债ETF海富通',
    # 三马七星美股
    'NVDA': '英伟达', 'AAPL': '苹果', 'TSLA': '特斯拉',
    'AMD': 'AMD', 'MU': '美光', 'AVGO': '博通',
    'GOOG': '谷歌', 'AMZN': '亚马逊', 'KO': '可口可乐',
    'NEM': '纽蒙特', 'XOM': '埃克森美孚', 'AEP': '美国电力',
    'JPM': '摩根大通', 'GS': '高盛', 'BRK-B': '伯克希尔'
}

# =============================================================
# 数据加载
# =============================================================
def load_etf_data(etf_list, subdirs=['etf', 'etf_qixing', 'us']):
    """
    加载 ETF 数据，返回 close DataFrame（列=ETF代码）
    """
    close_dict = {}
    for etf in etf_list:
        for subdir in subdirs:
            csv_path = f"{BASE_DIR}\\{subdir}\\{etf}.csv"
            if os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path, parse_dates=['date'], index_col='date')
                    df = df.sort_index()
                    if len(df) > 50:
                        close_dict[etf] = df['close'].astype(float)
                        break
                except Exception as e:
                    print(f"  [WARNING] {etf} 加载失败: {e}")
                    continue
        else:
            print(f"  [WARNING] {etf} 在所有目录中未找到")
    
    if not close_dict:
        raise ValueError("没有成功加载任何 ETF 数据")
    
    close_df = pd.DataFrame(close_dict)
    close_df = close_df.fillna(method='ffill').dropna()
    print(f"  数据加载完成: {len(close_df)} 天, {len(close_df.columns)} 只 ETF")
    return close_df

# =============================================================
# 策略1：七星拉普拉斯（Laplace）
# =============================================================
def strategy_laplace(close_df, top_n=1, short_window=25, long_window=250, 
                      stop_loss_pct=0.08, profit_protect_pct=0.05, cooldown_days=40):
    """
    七星拉普拉斯策略：
    - 综合得分 = 短期动量×1.0 + 长期动量×0.5
    - 持有 Top N（默认1只）
    - 止损：-8%（用最低价触发，这里用收盘价近似）
    - 盈利保护：回撤超5%触发
    - 冷却期：卖出后N天不买回
    
    返回：entries, exits (DataFrame, 形状同 close_df)
    """
    etfs = close_df.columns.tolist()
    n = len(close_df)
    
    # 初始化
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    # 计算每只 ETF 的动量得分
    for etf in etfs:
        prices = close_df[etf].values
        
        # 短期动量（25日）
        short_scores = np.zeros(n)
        for i in range(short_window, n):
            recent = prices[max(0, i-short_window):i+1]
            if len(recent) >= 2:
                y = np.log(recent)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                try:
                    slope, _ = np.polyfit(x, y, 1, w=weights)
                    short_scores[i] = slope * 250  # 年化对数收益率
                except:
                    short_scores[i] = 0
        
        # 长期动量（250日）
        long_scores = np.zeros(n)
        for i in range(long_window, n):
            long_prices = prices[max(0, i-long_window):i+1]
            if len(long_prices) >= 2:
                y = np.log(long_prices)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                try:
                    slope, _ = np.polyfit(x, y, 1, w=weights)
                    long_scores[i] = slope * 250
                except:
                    long_scores[i] = 0
        
        # 综合得分
        scores[etf] = short_scores * 1.0 + long_scores * 0.5
        scores[etf] = scores[etf].fillna(0)
    
    # 每日排名（得分越高排名越前，rank=1为最高）
    for i in range(n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    # 生成信号
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    
    # 持仓状态跟踪
    holding = {etf: {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': 0} for etf in etfs}
    
    for i in range(long_window + 1, n):
        current_date = close_df.index[i]
        day_prices = close_df.iloc[i]
        day_low = day_prices * 0.999  # 近似最低价（实际应该用low列，这里简化）
        
        # 更新持仓状态
        for etf in etfs:
            if holding[etf]['in_pos']:
                entry = holding[etf]['entry_price']
                current = day_prices[etf]
                high = holding[etf]['high_price']
                
                # 更新最高价
                if current > high:
                    holding[etf]['high_price'] = current
                
                # 止损检查（用最低价）
                stop_price = entry * (1 - stop_loss_pct)
                if day_low[etf] <= stop_price:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
                    continue
                
                # 盈利保护（回撤超5%）
                drawdown = (high - current) / high
                if drawdown >= profit_protect_pct:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
                    continue
                
                # 冷却期递减
                if holding[etf]['cooldown'] > 0:
                    holding[etf]['cooldown'] -= 1
            
            elif holding[etf]['cooldown'] > 0:
                holding[etf]['cooldown'] -= 1
        
        # 排名检查（每5天检查一次，简化版每天检查）
        if i % 5 != 0:
            continue
        
        # 获取当前 Top N
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        top_etfs = day_ranks[day_ranks <= top_n].index.tolist()
        
        # 卖出不在 Top N 的持仓
        for etf in etfs:
            if holding[etf]['in_pos'] and etf not in top_etfs:
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': False, 'entry_price': 0, 'high_price': 0, 'cooldown': cooldown_days}
        
        # 买入新进入 Top N 的 ETF
        for etf in top_etfs:
            if not holding[etf]['in_pos'] and holding[etf]['cooldown'] == 0:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': True, 'entry_price': day_prices[etf], 'high_price': day_prices[etf], 'cooldown': 0}
    
    return entries, exits

# =============================================================
# 策略2：七星（6+1）策略
# =============================================================
def strategy_qixing(close_df, top_n=1, short_window=10, long_window=60):
    """
    七星6+1策略（简化版）：
    - 7只ETF：159915/513100/159985/518880/501018/161226/511220
    - 使用EMA快慢线交叉 + 动量过滤
    - 持有 Top N
    
    返回：entries, exits
    """
    # 简化：直接用排名（EMA短期动量）
    etfs = close_df.columns.tolist()
    n = len(close_df)
    
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    for etf in etfs:
        prices = close_df[etf].values
        
        # EMA 动量（10日 vs 60日）
        ema_short = pd.Series(prices).ewm(span=short_window, adjust=False).mean().values
        ema_long = pd.Series(prices).ewm(span=long_window, adjust=False).mean().values
        
        momentum = np.zeros(n)
        for i in range(long_window, n):
            if ema_long[i] > 0:
                momentum[i] = (ema_short[i] / ema_long[i] - 1) * 100
        
        scores[etf] = momentum
    
    # 排名
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    for i in range(long_window, n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    # 生成信号（简化：每天检查排名）
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    
    holding = {etf: False for etf in etfs}
    
    for i in range(long_window + 1, n):
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        top_etfs = day_ranks[day_ranks <= top_n].index.tolist()
        
        # 卖出不在 Top N 的
        for etf in etfs:
            if holding[etf] and etf not in top_etfs:
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = False
        
        # 买入 Top N
        for etf in top_etfs:
            if not holding[etf]:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = True
    
    return entries, exits

# =============================================================
# 策略3：三马七星美股版（Sanma）
# =============================================================
def strategy_sanma(close_df, top_n=2, short=20, long=60, atr_multiplier=2.0, 
                    hard_stop_pct=0.20, min_score=0.15):
    """
    三马七星美股版策略：
    - Top N 持仓（默认2只）
    - ATR 动态止损（2.0x）
    - 20% 硬止损底线
    - 最低得分过滤（min_score）
    
    返回：entries, exits
    """
    etfs = close_df.columns.tolist()
    n = len(close_df)
    
    # 计算得分（简化：短期动量）
    scores = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    
    for etf in etfs:
        prices = close_df[etf].values
        
        momentum = np.zeros(n)
        for i in range(long + 1, n):
            if i >= short and i >= long:
                # 短期动量
                short_ret = (prices[i] / prices[i-short] - 1) * 100
                # 长期动量
                long_ret = (prices[i] / prices[i-long] - 1) * 100
                momentum[i] = short_ret * 1.0 + long_ret * 0.5
        
        scores[etf] = momentum
    
    # 排名
    ranks = pd.DataFrame(index=close_df.index, columns=etfs, data=np.nan)
    for i in range(long + 1, n):
        day_scores = scores.iloc[i]
        if day_scores.isna().all():
            continue
        ranks.iloc[i] = day_scores.rank(method='first', ascending=False)
    
    # 生成信号
    entries = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    exits = pd.DataFrame(index=close_df.index, columns=etfs, data=False)
    
    holding = {etf: {'in_pos': False, 'entry_price': 0, 'atr': 0} for etf in etfs}
    
    for i in range(long + 2, n):
        current_prices = close_df.iloc[i]
        
        # 更新持仓（止损检查）
        for etf in etfs:
            if holding[etf]['in_pos']:
                entry = holding[etf]['entry_price']
                current = current_prices[etf]
                
                # 硬止损
                if current <= entry * (1 - hard_stop_pct):
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'atr': 0}
                    continue
                
                # ATR 止损（简化：用固定百分比代替）
                atr_stop = entry * (1 - atr_multiplier * 0.02)  # 假设2% ATR
                if current <= atr_stop:
                    exits.iloc[i, close_df.columns.get_loc(etf)] = True
                    holding[etf] = {'in_pos': False, 'entry_price': 0, 'atr': 0}
        
        # 排名检查（每5天）
        if i % 5 != 0:
            continue
        
        day_ranks = ranks.iloc[i]
        if day_ranks.isna().all():
            continue
        
        # 过滤低分
        day_scores = scores.iloc[i]
        valid_etfs = day_ranks.index[day_scores >= min_score].tolist()
        top_etfs = [etf for etf in day_ranks.index if day_ranks[etf] <= top_n and etf in valid_etfs]
        
        # 卖出不在 Top N 或低分
        for etf in etfs:
            if holding[etf]['in_pos'] and (etf not in top_etfs):
                exits.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': False, 'entry_price': 0, 'atr': 0}
        
        # 买入 Top N
        for etf in top_etfs:
            if not holding[etf]['in_pos']:
                entries.iloc[i, close_df.columns.get_loc(etf)] = True
                holding[etf] = {'in_pos': True, 'entry_price': current_prices[etf], 'atr': 0.02}
    
    return entries, exits

# =============================================================
# 回测引擎
# =============================================================
def run_backtest(close_df, entries, exits, init_cash=100000, fees=0.0015):
    """
    使用 VectorBT 回测
    返回：portfolio 对象
    """
    # 确保数据类型正确
    close_values = close_df.values.astype(float)
    entries_values = entries.values
    exits_values = exits.values
    
    # 创建组合
    portfolio = vbt.Portfolio.from_signals(
        close_values,
        entries=entries_values,
        exits=exits_values,
        init_cash=init_cash,
        fees=fees,
        freq='D'
    )
    
    return portfolio

def get_metrics(portfolio, close_df):
    """
    提取绩效指标
    """
    try:
        stats = portfolio.stats()
        
        # 总收益率
        total_return = float(stats['Total Return [%]'])
        
        # 年化收益
        returns = portfolio.returns()
        n_days = len(returns)
        n_years = n_days / 252
        if n_years > 0 and total_return > -100:
            annual = ((1 + total_return/100) ** (1/n_years) - 1) * 100
        else:
            annual = -100
        
        # 最大回撤
        max_dd = float(stats['Max Drawdown [%]'])
        
        # 胜率
        win_rate = float(stats['Win Rate [%]'])
        
        # 交易次数
        trades = int(stats['Total Trades'])
        
        # 盈亏比
        closed_trades = portfolio.trades.records_readable
        if len(closed_trades) > 0:
            wins = closed_trades[closed_trades['PnL'] > 0]['PnL']
            losses = closed_trades[closed_trades['PnL'] < 0]['PnL']
            avg_win = wins.mean() if len(wins) > 0 else 0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 1
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        else:
            profit_factor = 0
        
        return {
            'total_return': total_return,
            'annual': annual,
            'max_dd': max_dd,
            'win_rate': win_rate,
            'trades': trades,
            'profit_factor': profit_factor,
            'n_years': n_years,
            'n_days': n_days
        }
    except Exception as e:
        print(f"    [ERROR] get_metrics 失败: {e}")
        return None

# =============================================================
# 主程序：回测3个策略（近2年）
# =============================================================
if __name__ == '__main__':
    print("=" * 110)
    print("Blakever ETF 轮动回测框架 v1.0")
    print("=" * 110)
    
    # 设置回测时间范围（近2年）
    end_date = datetime.now()
    start_date = end_date.replace(year=end_date.year - 2)
    print(f"\n回测时间范围: {start_date.date()} ~ {end_date.date()} (约2年)")
    
    # ==========================================
    # 1. 七星拉普拉斯（38只ETF池，Top1）
    # ==========================================
    print("\n" + "=" * 110)
    print("策略1：七星拉普拉斯（Laplace）- 38只ETF，Top1持仓")
    print("=" * 110)
    
    LAPLACE_ETF_POOL = [
        '518880', '159980', '159985', '501018', '161226',
        '159981', '513100', '159509', '513290', '513500',
        '159529', '513400', '513520', '513030', '513080',
        '513310', '513730', '159792', '513130', '513050',
        '159920', '513690', '510300', '510500', '510050',
        '510210', '159915', '588080', '512100', '563360',
        '563300', '512890', '159967', '512040', '159201',
        '511380', '511010', '511220'
    ]
    
    print("\n[1/3] 加载数据...")
    close_laplace = load_etf_data(LAPLACE_ETF_POOL)
    close_laplace = close_laplace[start_date: end_date]
    print(f"  数据范围: {close_laplace.index[0].date()} ~ {close_laplace.index[-1].date()}, {len(close_laplace)} 天")
    
    print("\n[2/3] 生成信号（拉普拉斯策略）...")
    entries_laplace, exits_laplace = strategy_laplace(
        close_laplace, top_n=1, short_window=25, long_window=250,
        stop_loss_pct=0.08, profit_protect_pct=0.05, cooldown_days=40
    )
    print(f"  入场信号总数: {entries_laplace.sum().sum()}")
    print(f"  出场信号总数: {exits_laplace.sum().sum()}")
    
    print("\n[3/3] 回测中...")
    pf_laplace = run_backtest(close_laplace, entries_laplace, exits_laplace)
    m_laplace = get_metrics(pf_laplace, close_laplace)
    
    if m_laplace:
        print(f"\n  总收益率: {m_laplace['total_return']:.2f}%")
        print(f"  年化收益: {m_laplace['annual']:.2f}%")
        print(f"  最大回撤: {m_laplace['max_dd']:.2f}%")
        print(f"  胜率: {m_laplace['win_rate']:.2f}%")
        print(f"  交易次数: {m_laplace['trades']}")
        print(f"  盈亏比: {m_laplace['profit_factor']:.2f}")
        print(f"  回测天数: {m_laplace['n_days']} 天 ({m_laplace['n_years']:.2f}年)")
    
    # ==========================================
    # 2. 七星（6+1）策略
    # ==========================================
    print("\n" + "=" * 110)
    print("策略2：七星（6+1）- 7只ETF，Top1持仓")
    print("=" * 110)
    
    QIXING_ETF_POOL = [
        '159915',  # 创业板ETF易方达
        '513100',  # 纳指ETF国泰
        '159985',  # 豆粕ETF华夏
        '518880',  # 黄金ETF华安
        '501018',  # 南方原油LOF
        '161226',  # 白银LOF国投瑞银
        '511220'   # 城投债ETF海富通（安全池）
    ]
    
    print("\n[1/3] 加载数据...")
    close_qixing = load_etf_data(QIXING_ETF_POOL)
    close_qixing = close_qixing[start_date: end_date]
    print(f"  数据范围: {close_qixing.index[0].date()} ~ {close_qixing.index[-1].date()}, {len(close_qixing)} 天")
    
    print("\n[2/3] 生成信号（七星策略）...")
    entries_qixing, exits_qixing = strategy_qixing(
        close_qixing, top_n=1, short_window=10, long_window=60
    )
    print(f"  入场信号总数: {entries_qixing.sum().sum()}")
    print(f"  出场信号总数: {exits_qixing.sum().sum()}")
    
    print("\n[3/3] 回测中...")
    pf_qixing = run_backtest(close_qixing, entries_qixing, exits_qixing)
    m_qixing = get_metrics(pf_qixing, close_qixing)
    
    if m_qixing:
        print(f"\n  总收益率: {m_qixing['total_return']:.2f}%")
        print(f"  年化收益: {m_qixing['annual']:.2f}%")
        print(f"  最大回撤: {m_qixing['max_dd']:.2f}%")
        print(f"  胜率: {m_qixing['win_rate']:.2f}%")
        print(f"  交易次数: {m_qixing['trades']}")
        print(f"  盈亏比: {m_qixing['profit_factor']:.2f}")
        print(f"  回测天数: {m_qixing['n_days']} 天 ({m_qixing['n_years']:.2f}年)")
    
    # ==========================================
    # 3. 三马七星美股版（Sanma）
    # ==========================================
    print("\n" + "=" * 110)
    print("策略3：三马七星美股版（Sanma）- 15只美股，Top2持仓")
    print("=" * 110)
    
    SANMA_ETF_POOL = [
        'NVDA', 'AAPL', 'TSLA', 'AMD', 'MU', 'AVGO',
        'GOOG', 'AMZN', 'KO', 'NEM', 'XOM', 'AEP',
        'JPM', 'GS', 'BRK-B'
    ]
    
    print("\n[1/3] 加载数据...")
    close_sanma = load_etf_data(SANMA_ETF_POOL, subdirs=['us'])
    close_sanma = close_sanma[start_date: end_date]
    print(f"  数据范围: {close_sanma.index[0].date()} ~ {close_sanma.index[-1].date()}, {len(close_sanma)} 天")
    
    print("\n[2/3] 生成信号（三马七星策略）...")
    entries_sanma, exits_sanma = strategy_sanma(
        close_sanma, top_n=2, short=20, long=60,
        atr_multiplier=2.0, hard_stop_pct=0.20, min_score=0.15
    )
    print(f"  入场信号总数: {entries_sanma.sum().sum()}")
    print(f"  出场信号总数: {exits_sanma.sum().sum()}")
    
    print("\n[3/3] 回测中...")
    pf_sanma = run_backtest(close_sanma, entries_sanma, exits_sanma, init_cash=100000, fees=0.0015)
    m_sanma = get_metrics(pf_sanma, close_sanma)
    
    if m_sanma:
        print(f"\n  总收益率: {m_sanma['total_return']:.2f}%")
        print(f"  年化收益: {m_sanma['annual']:.2f}%")
        print(f"  最大回撤: {m_sanma['max_dd']:.2f}%")
        print(f"  胜率: {m_sanma['win_rate']:.2f}%")
        print(f"  交易次数: {m_sanma['trades']}")
        print(f"  盈亏比: {m_sanma['profit_factor']:.2f}")
        print(f"  回测天数: {m_sanma['n_days']} 天 ({m_sanma['n_years']:.2f}年)")
    
    # ==========================================
    # 汇总对比
    # ==========================================
    print("\n" + "=" * 110)
    print("策略对比汇总（近2年）")
    print("=" * 110)
    
    header = "│{:<30}│{:>12}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
        '策略', '总收益率%', '年化收益%', '最大回撤%', '胜率%', '交易数', '盈亏比'
    )
    sep = "├" + "─"*30 + "┼" + "─"*12 + "┼" + "─"*12 + "┼" + "─"*12 + "┼" + "─"*10 + "┼" + "─"*8 + "┼" + "─"*8 + "┤"
    footer = "└" + "─"*30 + "┴" + "─"*12 + "┴" + "─"*12 + "┴" + "─"*12 + "┴" + "─"*10 + "┴" + "─"*8 + "┴" + "─"*8 + "┘"
    
    print("\n" + sep)
    print(header)
    print(sep)
    
    def print_row(name, m):
        if m is None:
            return "│{:<30}│{:>12}│{:>12}│{:>12}│{:>10}│{:>8}│{:>8}│".format(
                name, 'N/A', '-', '-', '-', '-', '-'
            )
        return "│{:<30}│{:>11.2f}%│{:>11.2f}%│{:>11.2f}%│{:>9.2f}%│{:>8}│{:>8.2f}│".format(
            name, m['total_return'], m['annual'], m['max_dd'], m['win_rate'], m['trades'], m['profit_factor']
        )
    
    print(print_row("1. 七星拉普拉斯（Top1）", m_laplace))
    print(print_row("2. 七星6+1（Top1）", m_qixing))
    print(print_row("3. 三马七星（Top2）", m_sanma))
    
    print(footer)
    
    print("\n" + "=" * 110)
    print("Blakever ETF 轮动回测完成（v1.0）")
    print("=" * 110)
