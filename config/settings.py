"""
全局配置文件 - Global Settings
集中管理所有路径和全局配置参数
"""

from pathlib import Path
import os

# ==================== 项目根目录 ====================
PROJECT_ROOT = Path(__file__).parent.parent

# ==================== 路径配置 ====================
PATHS = {
    # 数据目录
    'data_dir': os.path.join(PROJECT_ROOT, 'data'),
    'stock_data_dir': os.path.join(PROJECT_ROOT, 'data', 'storage', 'stock_data'),
    'market_data_dir': os.path.join(PROJECT_ROOT, 'data', 'storage', 'market_data'),

    # 结果目录
    'results_dir': os.path.join(PROJECT_ROOT, 'backtest', 'results'),
    'report_dir': os.path.join(PROJECT_ROOT, 'reporting', 'results'),
    'log_dir': os.path.join(PROJECT_ROOT, 'logs'),

    # 缓存目录
    'cache_dir': os.path.join(PROJECT_ROOT, 'cache'),

    # 配置目录
    'config_dir': os.path.join(PROJECT_ROOT, 'config'),

    # 文档目录
    'docs_dir': os.path.join(PROJECT_ROOT, 'docs'),
}

# ==================== 数据源配置 ====================
DATA_SOURCES = {
    'jqdata': {
        'enabled': False,  # 需要用户自行配置JQData账号
        'username': '',
        'password': '',
    },
    'westock': {
        'enabled': True,
    },
    'akshare': {
        'enabled': True,
    },
    'tqsdk': {
        'enabled': False,
    },
}

# ==================== 回测配置 ====================
BACKTEST_CONFIG = {
    'initial_cash': 100000,  # 初始资金
    'commission': 0.001,  # 交易佣金
    'slippage': 0.001,  # 滑点
    'min_trade_size': 100,  # 最小交易单位
    'position_size': 0.1,  # 单仓位大小（10%）
    'stop_loss': 0.05,  # 止损比例（5%）
    'take_profit': 0.15,  # 止盈比例（15%）
}

# ==================== 邮件配置 ====================
EMAIL_CONFIG = {
    'smtp_server': 'smtp.qq.com',
    'smtp_port': 587,
    'sender_email': '',
    'sender_password': '',
    'receiver_emails': [],
}

# ==================== 日志配置 ====================
LOG_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file': os.path.join(PROJECT_ROOT, 'logs', 'blakever_trade.log'),
}
