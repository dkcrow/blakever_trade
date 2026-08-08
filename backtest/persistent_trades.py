"""
港美股版持久化交易模块
参照七星QMT的trades.xlsx机制, 实现跨次运行持仓持久化

用法:
  from persistent_trades import get_holdings, append_trade, US_TRADES_XLSX, HK_TRADES_XLSX
"""
from pathlib import Path
import pandas as pd
from datetime import datetime

_PROJECT = Path(__file__).parent.parent
_BACKTEST_DIR = _PROJECT / 'backtest'

US_TRADES_XLSX = _BACKTEST_DIR / 'results_us100' / '七星美股版_实盘交易记录.xlsx'
HK_TRADES_XLSX = _BACKTEST_DIR / 'results_hk' / '七星港股版_实盘交易记录.xlsx'

COLS = ['交易日期', '代码', '名称', '方向', '成交价格', '数量(股)', '动量得分', '交易理由']

def _ensure_xlsx(xlsx_path):
    if not xlsx_path.exists():
        df = pd.DataFrame(columns=COLS)
        xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(xlsx_path, index=False)

def get_holdings(xlsx_path):
    """
    获取当前持仓列表。
    返回 list of dict: [{code, name, price, shares, buy_date, score}, ...]
    每次买入会增加持仓, 卖出会清除对应持仓。
    """
    _ensure_xlsx(xlsx_path)
    df = pd.read_excel(xlsx_path)
    holdings = {}  # code -> holding dict
    for _, row in df.iterrows():
        code = str(row.get('代码', ''))
        direction = str(row.get('方向', ''))
        if direction == '买入':
            holdings[code] = {
                'code': code,
                'name': str(row.get('名称', '')),
                'price': float(row.get('成交价格', 0)),
                'shares': int(row.get('数量(股)', 0)),
                'buy_date': str(row.get('交易日期', '')),
                'score': row.get('动量得分', 'N/A'),
            }
        elif direction == '卖出' and code in holdings:
            del holdings[code]
    return list(holdings.values())

def append_trade(xlsx_path, direction, code, name, price, shares, date, score, reason):
    """追加一条交易记录"""
    _ensure_xlsx(xlsx_path)
    df = pd.read_excel(xlsx_path)
    new_row = pd.DataFrame([{
        '交易日期': str(date),
        '代码': code,
        '名称': name,
        '方向': direction,
        '成交价格': price,
        '数量(股)': shares,
        '动量得分': score,
        '交易理由': reason,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel(xlsx_path, index=False)

def get_today_trades(xlsx_path, date_str):
    """获取今日已执行的交易列表"""
    _ensure_xlsx(xlsx_path)
    df = pd.read_excel(xlsx_path)
    today = df[df['交易日期'].astype(str).str.startswith(str(date_str))]
    return today.to_dict('records')

def has_traded_today(xlsx_path, date_str):
    """检查今日是否已有交易"""
    _ensure_xlsx(xlsx_path)
    df = pd.read_excel(xlsx_path)
    today = df[df['交易日期'].astype(str).str.startswith(str(date_str))]
    return len(today) > 0
