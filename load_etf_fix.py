"""
Blakever ETF 轮动回测框架 v1.0 (纯 pandas/numpy 实现)
通用 ETF 轮动类策略回测（不依赖 VectorBT）

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
from datetime import datetime
import os
import warnings
warnings.filterwarnings('ignore')

# =============================================================
# 配置区
# =============================================================
BASE_DIR = r'C:\Users\blakehao\.qclaw\workspace\back_trader_stocks'

# ETF 中文名称映射
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
    """加载 ETF 数据，返回 close DataFrame（列=ETF代码）"""
    close_dict = {}
    for etf in etf_list:
        for subdir in subdirs:
            csv_path = f"{BASE_DIR}\\{subdir}\\{etf}.csv"
            if os.path.exists(csv_path):
                try:
                    # 尝试不同列名（date/Date）
                    df = None
                    for date_col in ['date', 'Date']:
                        try:
                            df = pd.read_csv(csv_path, parse_dates=[date_col], index_col=date_col)
                            break
                        except:
                            continue
                    if df is None:
                        print(f"  [WARNING] {etf} 无法解析日期列")
                        continue
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
