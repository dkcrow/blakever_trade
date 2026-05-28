"""
选股池配置模块
职责：统一管理 Blakever 系统的选股池配置

选股池定义：标普500成分股 + 纳指100成分股 + 恒生科技成分股 + 恒生指数成分股

核心功能：
1. 提供完整的成分股代码列表（内部代码格式）
2. 分层筛选机制：先技术粗筛，再精细评分，避免700+只股票全量获取数据
3. 港股/美股代码映射与转换
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════
# 1. 标普500成分股（按GICS行业分类，内部代码 = yfinance代码）
# ══════════════════════════════════════════════════════════
SP500_SYMBOLS = [
    # 信息技术 Technology
    'AAPL', 'MSFT', 'NVDA', 'AVGO', 'CRM', 'ORCL', 'CSCO', 'ADBE', 'AMD', 'INTC',
    'QCOM', 'TXN', 'IBM', 'NOW', 'INTU', 'AMAT', 'MU', 'LRCX', 'KLAC', 'APH',
    'ADI', 'MRVL', 'PANW', 'SNPS', 'CDNS', 'MCHP', 'FTNT', 'ANET', 'KEYS', 'CTSH',
    'MPWR', 'SWKS', 'ON', 'GLW', 'WDC', 'STX', 'NTAP', 'VRSK', 'IT', 'GDDY',
    # 通信服务 Communication Services
    'GOOGL', 'META', 'DIS', 'NFLX', 'CMCSA', 'T', 'VZ', 'TMUS', 'CHTR', 'EA',
    'TTWO', 'PARA', 'WBD', 'NWSA', 'FOXA', 'LYV', 'OMC', 'IPG',
    # 非必需消费 Consumer Discretionary
    'AMZN', 'TSLA', 'HD', 'MCD', 'NKE', 'LOW', 'SBUX', 'TJX', 'BKNG', 'ABNB',
    'MAR', 'RCL', 'CCL', 'CMG', 'YUM', 'LULU', 'ROST', 'DLTR', 'ORLY', 'AZO',
    'AAP', 'AUTO', 'BBY', 'DHI', 'LEN', 'POOL', 'ULTA', 'ETSY', 'HAS', 'MAT',
    # 必需消费 Consumer Staples
    'PG', 'KO', 'PEP', 'COST', 'WMT', 'PM', 'MO', 'MDLZ', 'CL', 'KMB',
    'GIS', 'K', 'HSY', 'STZ', 'CAG', 'SJM', 'CLX', 'CHD', 'EL', 'KVUE',
    # 医疗健康 Health Care
    'UNH', 'JNJ', 'LLY', 'PFE', 'MRK', 'ABBV', 'TMO', 'ABT', 'MRNA', 'DHR',
    'BMY', 'AMGN', 'GILD', 'CVS', 'MDT', 'SYK', 'VRTX', 'ISRG', 'REGN', 'CI',
    'HUM', 'ELV', 'CNC', 'BIIB', 'ZTS', 'HCA', 'COR', 'MCK', 'EW', 'BSX',
    # 金融 Financials
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'BLK', 'SCHW',
    'C', 'AXP', 'CB', 'PGR', 'USB', 'AIG', 'MET', 'PRU', 'BK', 'STT',
    'COF', 'TFC', 'AON', 'MMC', 'PNC', 'ICE', 'CME', 'NDAQ', 'DFS', 'ALL',
    # 工业 Industrials
    'GE', 'CAT', 'BA', 'UNP', 'HON', 'UPS', 'RTX', 'LMT', 'DE', 'MMM',
    'EMR', 'ETN', 'CMI', 'NSC', 'CSX', 'AEP', 'SLB', 'SHW', 'BDX', 'ITW',
    # 能源 Energy
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PXD', 'OXY', 'VLO', 'WMB',
    # 材料 Materials
    'LIN', 'APD', 'SHW', 'DD', 'ECL', 'FCX', 'NEM', 'NUE', 'DOW', 'CE',
    # 公用事业 Utilities
    'NEE', 'DUK', 'SO', 'D', 'AEP', 'EXC', 'SRE', 'XEL', 'PEG', 'WEC',
    # 房地产 Real Estate
    'PLD', 'AMT', 'CCI', 'EQIX', 'SPG', 'O', 'DLR', 'PSA', 'WELL', 'VICI',
]

# ══════════════════════════════════════════════════════════
# 2. 纳指100成分股（内部代码 = yfinance代码）
# ══════════════════════════════════════════════════════════
NASDAQ100_SYMBOLS = [
    # 科技核心
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'ORCL', 'ADBE',
    'CRM', 'INTC', 'AMD', 'QCOM', 'TXN', 'CSCO', 'IBM', 'NOW', 'INTU', 'AMAT',
    'MU', 'LRCX', 'KLAC', 'ADI', 'MRVL', 'PANW', 'SNPS', 'CDNS', 'MCHP', 'FTNT',
    'ANET', 'KEYS', 'CTSH', 'MPWR', 'SWKS', 'ON', 'WDC', 'STX', 'NTAP', 'MDB',
    'DDOG', 'ZS', 'CRWD', 'PANW', 'NET', 'SNOW', 'PLTR', 'RIVN', 'MRVL',
    # 通信与媒体
    'CMCSA', 'NFLX', 'DIS', 'CHTR', 'TMUS', 'WBD', 'EA', 'TTWO', 'PARA',
    # 消费
    'COST', 'PEP', 'SBUX', 'ABNB', 'MELI', 'BKNG', 'DLTR', 'LULU', 'ORLY', 'AZO',
    'CPRT', 'ROST', 'TSLA', 'MAR', 'CMG', 'YUM',
    # 医疗
    'AMGN', 'GILD', 'MRNA', 'REGN', 'VRTX', 'ISRG', 'BIIB', 'IDXX', 'ILMN',
    # 工业
    'ODFL', 'FAST', 'CTAS', 'PCAR', 'CSX',
    # 金融
    'V', 'MA', 'PYPL', 'FISV', 'ICE', 'CME', 'AXP',
]

# ══════════════════════════════════════════════════════════
# 3. 恒生科技指数成分股（内部代码格式：数字.HK）
# ══════════════════════════════════════════════════════════
HSTECH_SYMBOLS = [
    '0700.HK',   # 腾讯控股
    '9988.HK',   # 阿里巴巴-SW
    '3690.HK',   # 美团-W
    '9618.HK',   # 京东集团-SW
    '9888.HK',   # 百度集团-SW
    '9999.HK',   # 网易-S
    '1810.HK',   # 小米集团-W
    '0241.HK',   # 阿里健康
    '1024.HK',   # 快手-W
    '9881.HK',   # 中通快递-SW
    '6690.HK',   # 海尔智家
    '0285.HK',   # 比亚迪电子
    '0268.HK',   # 金蝶国际
    '0772.HK',   # 阅文集团
    '6060.HK',   # 众安在线
    '2015.HK',   # 理想汽车-W
    '9866.HK',   # 蔚来-SW
    '9868.HK',   # 小鹏汽车-W
    '2518.HK',   # 汽车之家-S
    '0909.HK',   # 明源云集团
    '0267.HK',   # 中信股份
    '1211.HK',   # 比亚迪股份
    '2359.HK',   # 药明康德  (注意：可能已剔除，保留备用)
    '2269.HK',   # 药明生物
    '2020.HK',   # 安踏体育
    '2382.HK',   # 舜宇光学科技
    '1876.HK',   # 百威亚太
    '9626.HK',   # 哔哩哔哩-SW
    '9698.HK',   # 万国数据-SW
    '6618.HK',   # 京东健康
]

# ══════════════════════════════════════════════════════════
# 4. 恒生指数成分股（内部代码格式：数字.HK）
# ══════════════════════════════════════════════════════════
HSI_SYMBOLS = [
    # 金融
    '0005.HK',   # 汇丰控股
    '1299.HK',   # 友邦保险
    '2388.HK',   # 中银香港
    '0388.HK',   # 香港交易所
    '1398.HK',   # 工商银行
    '3988.HK',   # 中国银行
    '2628.HK',   # 中国人寿
    '0941.HK',   # 中国移动
    '1288.HK',   # 农业银行
    '1658.HK',   # 邮储银行
    '3328.HK',   # 交通银行
    '0883.HK',   # 中国海洋石油
    '0016.HK',   # 新鸿基地产
    '0011.HK',   # 恒生银行
    '0002.HK',   # 中电控股
    '0003.HK',   # 香港中华煤气
    '0006.HK',   # 电能实业
    '0012.HK',   # 恒基兆业地产
    '0017.HK',   # 新世界发展
    '0066.HK',   # 港铁公司
    '0101.HK',   # 恒隆地产
    '0175.HK',   # 吉利汽车
    '0241.HK',   # 阿里健康
    '0267.HK',   # 中信股份
    '0288.HK',   # 万洲国际
    '0291.HK',   # 华润啤酒
    '0386.HK',   # 中国石油化工
    '0669.HK',   # 创科实业
    '0688.HK',   # 中国海外发展
    '0762.HK',   # 中国联通
    '0823.HK',   # 领展房产基金
    '0857.HK',   # 中国石油
    '0868.HK',   # 信义玻璃
    '0939.HK',   # 建设银行
    '0960.HK',   # 龙湖集团
    '0968.HK',   # 信义光能
    '1038.HK',   # 长江基建集团
    '1044.HK',   # 恒安国际
    '1093.HK',   # 石药集团
    '1109.HK',   # 华润置地
    '1113.HK',   # 长实集团
    '1177.HK',   # 中国生物制药
    '1211.HK',   # 比亚迪股份
    '1810.HK',   # 小米集团-W
    '1876.HK',   # 百威亚太
    '1928.HK',   # 金沙中国
    '1997.HK',   # 九龙仓置业
    '2007.HK',   # 碧桂园
    '2018.HK',   # 瑞声科技
    '2020.HK',   # 安踏体育
    '2269.HK',   # 药明生物
    '2313.HK',   # 申洲国际
    '2318.HK',   # 中国平安
    '2382.HK',   # 舜宇光学科技
    '2388.HK',   # 中银香港
    '2628.HK',   # 中国人寿
    '2899.HK',   # 紫金矿业
    '3690.HK',   # 美团-W
    '3968.HK',   # 招商银行
    '3988.HK',   # 中国银行
    '6098.HK',   # 碧桂园服务
    '6618.HK',   # 京东健康
    '6862.HK',   # 海底捞
    '9618.HK',   # 京东集团-SW
    '9633.HK',   # 农夫山泉
    '9688.HK',   # 百度集团 (二次上市)
    '9888.HK',   # 百度集团-SW
    '9988.HK',   # 阿里巴巴-SW
    '9999.HK',   # 网易-S
    '0700.HK',   # 腾讯控股
    '1024.HK',   # 快手-W
    '0981.HK',   # 中芯国际
]

# ══════════════════════════════════════════════════════════
# 5. 合并去重后的完整选股池
# ══════════════════════════════════════════════════════════

def _merge_pools() -> list:
    """合并所有选股池并去重，保持顺序（美股在前，港股在后）"""
    seen = set()
    result = []
    for symbol in SP500_SYMBOLS + NASDAQ100_SYMBOLS + HSTECH_SYMBOLS + HSI_SYMBOLS:
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result

FULL_STOCK_POOL = _merge_pools()


def get_us_symbols() -> list:
    """获取所有美股代码"""
    seen = set()
    result = []
    for s in SP500_SYMBOLS + NASDAQ100_SYMBOLS:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def get_hk_symbols() -> list:
    """获取所有港股代码"""
    seen = set()
    result = []
    for s in HSTECH_SYMBOLS + HSI_SYMBOLS:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def is_hk_symbol(symbol: str) -> bool:
    """判断是否为港股代码"""
    return symbol.endswith('.HK')


def is_us_symbol(symbol: str) -> bool:
    """判断是否为美股代码"""
    return not is_hk_symbol(symbol)


# ══════════════════════════════════════════════════════════
# 6. 港股行业映射（降级备选）
# ══════════════════════════════════════════════════════════

HK_INDUSTRY_MAP = {
    '0700.HK': '互联网服务', '9988.HK': '电子商务', '3690.HK': '本地生活',
    '9618.HK': '电子商务', '9888.HK': '搜索引擎', '9999.HK': '在线游戏',
    '1810.HK': '消费电子', '0241.HK': '互联网医疗', '1024.HK': '短视频',
    '9881.HK': '物流', '6690.HK': '家电', '0285.HK': '电子制造',
    '0268.HK': '企业软件', '0772.HK': '数字阅读', '6060.HK': '保险科技',
    '2015.HK': '新能源汽车', '9866.HK': '新能源汽车', '9868.HK': '新能源汽车',
    '2518.HK': '汽车媒体', '0909.HK': '云服务', '0267.HK': '综合集团',
    '1211.HK': '新能源汽车', '2269.HK': '生物制药', '2020.HK': '运动服饰',
    '2382.HK': '光学元件', '1876.HK': '啤酒', '9626.HK': '视频平台',
    '9698.HK': '数据中心', '6618.HK': '互联网医疗',
    # 恒生指数成分股
    '0005.HK': '银行', '1299.HK': '保险', '2388.HK': '银行',
    '0388.HK': '金融交易所', '1398.HK': '银行', '3988.HK': '银行',
    '2628.HK': '保险', '0941.HK': '电信', '1288.HK': '银行',
    '1658.HK': '银行', '3328.HK': '银行', '0883.HK': '石油',
    '0016.HK': '房地产', '0011.HK': '银行', '0002.HK': '电力',
    '0003.HK': '公用事业', '0006.HK': '公用事业', '0012.HK': '房地产',
    '0017.HK': '房地产', '0066.HK': '轨道交通', '0101.HK': '房地产',
    '0175.HK': '汽车', '0288.HK': '食品', '0291.HK': '啤酒',
    '0386.HK': '石油化工', '0669.HK': '工业制造', '0688.HK': '房地产',
    '0762.HK': '电信', '0823.HK': 'REITs', '0857.HK': '石油',
    '0868.HK': '玻璃', '0939.HK': '银行', '0960.HK': '房地产',
    '0968.HK': '光伏', '1038.HK': '基建', '1044.HK': '日用品',
    '1093.HK': '制药', '1109.HK': '房地产', '1113.HK': '房地产',
    '1177.HK': '制药', '1928.HK': '博彩', '1997.HK': '房地产',
    '2007.HK': '房地产', '2018.HK': '电子元件', '2313.HK': '纺织制造',
    '2318.HK': '保险', '2899.HK': '矿业', '3968.HK': '银行',
    '6098.HK': '物业管理', '6862.HK': '餐饮', '9633.HK': '饮料',
    '9688.HK': '搜索引擎', '0981.HK': '半导体',
}

# 港股市值降级映射（十亿美元）
HK_MARKET_CAP_MAP = {
    '0700.HK': 450, '9988.HK': 260, '3690.HK': 110, '9618.HK': 55,
    '9888.HK': 35, '9999.HK': 55, '1810.HK': 80, '1024.HK': 25,
    '1211.HK': 100, '2269.HK': 20, '2020.HK': 55, '2382.HK': 20,
    '0005.HK': 150, '1299.HK': 90, '0388.HK': 45, '1398.HK': 230,
    '3988.HK': 130, '2628.HK': 50, '0941.HK': 130, '1288.HK': 150,
    '2318.HK': 100, '0883.HK': 80, '0016.HK': 40, '0011.HK': 40,
    '0002.HK': 25, '0939.HK': 180, '0857.HK': 140, '3968.HK': 100,
    '0981.HK': 25, '9633.HK': 50, '6862.HK': 15,
}

# 港股Beta降级映射
HK_BETA_MAP = {
    '0700.HK': 0.9, '9988.HK': 1.3, '3690.HK': 1.4, '9618.HK': 1.3,
    '9888.HK': 1.2, '9999.HK': 1.1, '1810.HK': 1.3, '1024.HK': 1.5,
    '1211.HK': 1.5, '2269.HK': 1.2, '2020.HK': 1.0, '2382.HK': 1.1,
    '0005.HK': 0.7, '1299.HK': 1.0, '0388.HK': 0.9, '1398.HK': 0.6,
    '3988.HK': 0.6, '2628.HK': 1.0, '0941.HK': 0.6, '1288.HK': 0.6,
    '2318.HK': 0.9, '0883.HK': 0.9, '0016.HK': 0.7, '0011.HK': 0.5,
    '0002.HK': 0.4, '0939.HK': 0.7, '0857.HK': 0.8, '3968.HK': 0.7,
    '0981.HK': 1.4, '9633.HK': 0.8, '6862.HK': 1.3,
}

# 港股股息率降级映射
HK_DIVIDEND_YIELD_MAP = {
    '0700.HK': 0.008, '9988.HK': 0.005, '3690.HK': 0.0, '9618.HK': 0.015,
    '9888.HK': 0.0, '9999.HK': 0.015, '1810.HK': 0.0, '1024.HK': 0.0,
    '1211.HK': 0.0, '2269.HK': 0.0, '2020.HK': 0.015, '2382.HK': 0.01,
    '0005.HK': 0.05, '1299.HK': 0.02, '0388.HK': 0.025, '1398.HK': 0.06,
    '3988.HK': 0.07, '2628.HK': 0.03, '0941.HK': 0.06, '1288.HK': 0.06,
    '2318.HK': 0.04, '0883.HK': 0.06, '0016.HK': 0.04, '0011.HK': 0.04,
    '0002.HK': 0.04, '0939.HK': 0.06, '0857.HK': 0.07, '3968.HK': 0.05,
    '0981.HK': 0.0, '9633.HK': 0.01, '6862.HK': 0.0,
}

# 港股中文名称映射（用于报告展示）
HK_NAME_MAP = {
    '0700.HK': '腾讯控股', '9988.HK': '阿里巴巴', '3690.HK': '美团',
    '9618.HK': '京东集团', '9888.HK': '百度集团', '9999.HK': '网易',
    '1810.HK': '小米集团', '0241.HK': '阿里健康', '1024.HK': '快手',
    '1211.HK': '比亚迪', '2269.HK': '药明生物', '2020.HK': '安踏体育',
    '2382.HK': '舜宇光学', '0005.HK': '汇丰控股', '1299.HK': '友邦保险',
    '0388.HK': '港交所', '1398.HK': '工商银行', '3988.HK': '中国银行',
    '2628.HK': '中国人寿', '0941.HK': '中国移动', '1288.HK': '农业银行',
    '2318.HK': '中国平安', '0883.HK': '中海油', '0016.HK': '新鸿基',
    '0011.HK': '恒生银行', '0002.HK': '中电控股', '0939.HK': '建设银行',
    '0857.HK': '中国石油', '3968.HK': '招商银行', '0981.HK': '中芯国际',
    '9633.HK': '农夫山泉', '6862.HK': '海底捞', '1876.HK': '百威亚太',
    '6618.HK': '京东健康', '9626.HK': '哔哩哔哩', '9881.HK': '中通快递',
    '2015.HK': '理想汽车', '9866.HK': '蔚来', '9868.HK': '小鹏汽车',
    '0268.HK': '金蝶国际', '0285.HK': '比亚迪电子', '6690.HK': '海尔智家',
}


# ══════════════════════════════════════════════════════════
# 7. 分层筛选机制
# ══════════════════════════════════════════════════════════

def prefilter_by_volume_and_price(stock_data: dict,
                                   min_price: float = 5.0,
                                   min_avg_volume_usd: float = 5_000_000,
                                   min_data_rows: int = 60) -> list:
    """
    第一层筛选：按成交额和价格粗筛，剔除流动性不足和低价股。

    Args:
        stock_data: {symbol: DataFrame} 行情数据
        min_price: 最低价格（美元/港元）
        min_avg_volume_usd: 最低日均成交额（美元/港元）
        min_data_rows: 最少数据行数

    Returns:
        通过筛选的 symbol 列表
    """
    passed = []
    for symbol, df in stock_data.items():
        if df is None or df.empty or len(df) < min_data_rows:
            continue
        try:
            latest = df.iloc[-1]
            close = float(latest['close'])
            if close < min_price:
                continue
            # 计算近20日平均成交额
            vol_ma20 = latest.get('volume_ma20', None)
            if vol_ma20 is not None and not __import__('pandas').isna(vol_ma20):
                avg_turnover = float(vol_ma20) * close
            else:
                # 使用近20日成交量均值
                recent_vol = df['volume'].tail(20)
                recent_close = df['close'].tail(20)
                avg_turnover = float((recent_vol * recent_close).mean())
            if avg_turnover >= min_avg_volume_usd:
                passed.append(symbol)
        except Exception as e:
            logger.debug(f"[StockPool] {symbol} 粗筛跳过: {e}")
            continue
    return passed


def get_pool_for_market(market: str = 'all') -> list:
    """
    按市场类型获取选股池。

    Args:
        market: 'us'(美股), 'hk'(港股), 'all'(全部)

    Returns:
        股票代码列表
    """
    if market == 'us':
        return get_us_symbols()
    elif market == 'hk':
        return get_hk_symbols()
    else:
        return FULL_STOCK_POOL


def get_index_symbol_for_market(market: str = 'us') -> str:
    """
    根据市场类型获取对应的大盘指数代码。

    Args:
        market: 'us' 或 'hk'

    Returns:
        指数代码（美股返回SPY，港股返回HSI）
    """
    if market == 'hk':
        return 'HSI'
    return 'SPY'


def print_pool_summary():
    """打印选股池统计摘要"""
    us_syms = get_us_symbols()
    hk_syms = get_hk_symbols()
    print(f"选股池统计：")
    print(f"  标普500成分股: {len(SP500_SYMBOLS)} 只")
    print(f"  纳指100成分股: {len(NASDAQ100_SYMBOLS)} 只 (含重复)")
    print(f"  恒生科技成分股: {len(HSTECH_SYMBOLS)} 只")
    print(f"  恒生指数成分股: {len(HSI_SYMBOLS)} 只 (含重复)")
    print(f"  美股去重后: {len(us_syms)} 只")
    print(f"  港股去重后: {len(hk_syms)} 只")
    print(f"  总选股池: {len(FULL_STOCK_POOL)} 只")


if __name__ == '__main__':
    print_pool_summary()
