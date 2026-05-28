"""
傻瓜交易员执行引擎
职责：严格按指令执行，维护持仓与账户状态，无主观判断。

核心功能（通过 paper-trader skill 实现）：
1. 订单撮合引擎（市价执行 + 滑点模拟）
2. 模拟账户管理（初始资金、现金、持仓市值、浮动盈亏）
3. 持仓追踪（建仓价、现价、数量、方向、P&L、历史最大盈利）
4. 止损止盈（ATR止损、固定百分比止损、目标价止盈）
5. 交易记录持久化（trade_history.json / positions.json）
6. 做空支持（融券做空与平仓）

降级策略：
当 paper-trader skill 不可用时，回退到内存模拟模式（旧逻辑保留作为 fallback）。
"""

import os
import json
import subprocess
import logging
import fcntl
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── paper-trader skill 路径 ──
_SKILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          '..', '..', '.agent', 'skills', 'paper-trader')
PAPER_TRADER_SCRIPT = os.path.join(_SKILL_DIR, 'scripts', 'index.js')
PAPER_TRADER_DATA_DIR = os.path.join(_SKILL_DIR, 'data')

# ── 旧版持久化文件路径（fallback 用）──
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(_BASE_DIR, "trade_history.md")
CUR_HOLDINGS_FILE = os.path.join(_BASE_DIR, "cur_holdings.md")
FINISH_HOLDINGS_FILE = os.path.join(_BASE_DIR, "finish_holdings.md")

# ── 持仓建仓regime标记文件（2026-04-22新增）──
POSITION_REGIME_FILE = os.path.join(_BASE_DIR, "position_regime.json")

# 单票最大金额上限（多头/空头名义本金）
MAX_SINGLE_POSITION = 1_000_000  # 100万美元/港币


# ════════════════════════════════════════════════════════════
# 0.5 持仓建仓regime标记管理（2026-04-22新增）
# ════════════════════════════════════════════════════════════

def record_position_regime(symbol: str, regime: str, confidence: float = 0):
    """
    记录持仓建仓时的市场状态。
    
    核心用途：当市场状态切换时，已有持仓的止损止盈规则
    应优先遵循建仓时的市场状态，而非当前状态。
    
    Args:
        symbol:     股票代码
        regime:     建仓时的市场状态（Bull/Bear/Range/Panic）
        confidence: 建仓时的regime置信度
    """
    data = {}
    if os.path.exists(POSITION_REGIME_FILE):
        try:
            with open(POSITION_REGIME_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}
    
    data[symbol] = {
        'regime_at_entry': regime,
        'regime_confidence': confidence,
        'entry_date': datetime.now().strftime('%Y-%m-%d')
    }
    
    try:
        with open(POSITION_REGIME_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[FoolTrader] 记录 {symbol} 建仓regime={regime}（置信度{confidence}%）")
    except Exception as e:
        logger.warning(f"[FoolTrader] 保存regime记录失败: {e}")


def get_position_regimes() -> dict:
    """
    获取所有持仓的建仓regime标记。
    
    Returns:
        {symbol: {'regime_at_entry': str, 'regime_confidence': float, 'entry_date': str}}
    """
    if os.path.exists(POSITION_REGIME_FILE):
        try:
            with open(POSITION_REGIME_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def remove_position_regime(symbol: str):
    """移除已平仓持仓的regime标记"""
    data = get_position_regimes()
    if symbol in data:
        del data[symbol]
        try:
            with open(POSITION_REGIME_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[FoolTrader] 移除regime记录失败: {e}")


# ════════════════════════════════════════════════════════════
# 0. paper-trader skill 可用性检测
# ════════════════════════════════════════════════════════════

def is_paper_trader_available() -> bool:
    """检测 paper-trader skill 是否可用"""
    return os.path.isfile(PAPER_TRADER_SCRIPT)


def _run_paper_trader(*args) -> str:
    """
    调用 paper-trader skill 的 Node.js 脚本。
    
    Args:
        *args: 命令参数，如 'execute', '--symbol', 'AAPL', ...
    
    Returns:
        stdout 输出（Markdown 格式）
    
    Raises:
        RuntimeError: 如果执行失败
    """
    cmd = ['node', PAPER_TRADER_SCRIPT] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.path.dirname(PAPER_TRADER_SCRIPT)
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.error(f"[FoolTrader] paper-trader 执行失败: {error_msg}")
            raise RuntimeError(f"paper-trader 执行失败: {error_msg}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error("[FoolTrader] paper-trader 执行超时（30秒）")
        raise RuntimeError("paper-trader 执行超时")
    except FileNotFoundError:
        logger.error(f"[FoolTrader] paper-trader 脚本未找到: {PAPER_TRADER_SCRIPT}")
        raise RuntimeError(f"paper-trader 脚本未找到: {PAPER_TRADER_SCRIPT}")


def _parse_markdown_table(output: str) -> list:
    """
    解析 paper-trader 返回的 Markdown 表格为字典列表。
    
    示例输入:
        | 代码 | 方向 | 建仓价 |
        |------|------|--------|
        | AAPL | long | 170.00 |
    
    输出:
        [{'代码': 'AAPL', '方向': 'long', '建仓价': '170.00'}]
    """
    lines = output.strip().split('\n')
    headers = None
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.split('|')[1:-1]]  # 去首尾空元素
        if not cells:
            continue
        # 跳过分隔行 (如 |------|------|)
        if all(set(c) <= {'-', ':'} for c in cells):
            continue
        if headers is None:
            headers = cells
        else:
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
    return rows


def _parse_summary_table(output: str) -> dict:
    """
    解析 paper-trader summary 返回的键值表格为字典。
    
    示例:
        | 指标 | 值 |
        |------|-----|
        | 账户净值 | 100142120 |
    
    输出:
        {'账户净值': 100142120.0, ...}
    """
    rows = _parse_markdown_table(output)
    result = {}
    for row in rows:
        key = row.get('指标', '')
        val_str = row.get('值', '')
        # 尝试转为数字
        try:
            # 去掉逗号
            val_str_clean = val_str.replace(',', '')
            if '%' in val_str_clean:
                result[key] = val_str  # 保留百分号字符串
            else:
                result[key] = float(val_str_clean)
        except (ValueError, TypeError):
            result[key] = val_str
    return result


# ════════════════════════════════════════════════════════════
# 1. 成本分档模型（保留作为 fallback 和验证用）
# ════════════════════════════════════════════════════════════

def calculate_execution_cost(order_amount: float, avg_daily_volume_value: float,
                              direction: str, sentiment_factor: float = 0.0) -> dict:
    """
    计算订单执行成本（含市场冲击和情绪附加）。
    
    注意：当 paper-trader 可用时，滑点由其内部模型计算。
    此函数保留作为 fallback 和独立验证用。

    Args:
        order_amount:           订单金额（元/美元/港币）
        avg_daily_volume_value: 近20日日均成交额（同币种）
        direction:              'buy' / 'sell' / 'short' / 'cover'
        sentiment_factor:       情绪因子（来自 Agent 2，范围 -1.0 ~ +1.0）

    Returns:
        {
            'impact_ratio': float,       # 订单冲击比
            'cost_multiplier': float,    # 最终成本乘数
            'liquidity_warning': bool,   # 是否触发流动性警告
            'rejected': bool,            # 是否拒绝执行（冲击比>10%）
            'reject_reason': str
        }
    """
    if avg_daily_volume_value <= 0:
        logger.warning("[FoolTrader] 日均成交额为0，无法计算冲击比，默认拒绝")
        return {'impact_ratio': 999, 'cost_multiplier': 1.0,
                'liquidity_warning': True, 'rejected': True,
                'reject_reason': '日均成交额数据缺失，流动性不足'}

    impact_ratio = order_amount / avg_daily_volume_value
    is_buy_side = direction in ('buy', 'cover')
    liquidity_warning = False
    rejected = False
    reject_reason = ''

    # 基础成本乘数
    if impact_ratio < 0.01:
        multiplier = 1.001 if is_buy_side else 0.999
    elif impact_ratio < 0.05:
        multiplier = 1.003 if is_buy_side else 0.997
    elif impact_ratio < 0.10:
        multiplier = 1.005 if is_buy_side else 0.995
        liquidity_warning = True
        logger.warning(f"[FoolTrader] 流动性警告：冲击比={impact_ratio:.1%}")
    else:
        rejected = True
        reject_reason = f'冲击比={impact_ratio:.1%}，超过10%上限，流动性不足，拒绝执行'
        logger.error(f"[FoolTrader] 流动性拒绝: {reject_reason}")
        return {'impact_ratio': round(impact_ratio, 4), 'cost_multiplier': 1.0,
                'liquidity_warning': True, 'rejected': True, 'reject_reason': reject_reason}

    # 情绪因子附加调节
    if sentiment_factor > 0.5 and is_buy_side:
        multiplier += 0.001
    elif sentiment_factor < -0.5 and not is_buy_side:
        multiplier -= 0.001

    return {
        'impact_ratio': round(impact_ratio, 4),
        'cost_multiplier': round(multiplier, 4),
        'liquidity_warning': liquidity_warning,
        'rejected': False,
        'reject_reason': ''
    }


# ════════════════════════════════════════════════════════════
# 2. paper-trader 接口封装
# ════════════════════════════════════════════════════════════

def paper_trader_init(equity: float = 100000000, cash: float = None) -> dict:
    """
    初始化 paper-trader 模拟账户。
    
    Args:
        equity: 初始净值（默认1亿）
        cash:   初始现金（默认等于 equity，即空仓启动）
    
    Returns:
        初始化后的账户信息
    """
    if cash is None:
        cash = equity
    output = _run_paper_trader('init', '--equity', str(int(equity)), '--cash', str(int(cash)))
    return _parse_summary_table(output)


def paper_trader_execute(symbol: str, action: str, amount: float,
                          direction: str = 'long',
                          stop_loss: float = None, stop_type: str = None,
                          take_profit: float = None,
                          reason: str = '',
                          current_prices: dict = None,
                          avg_daily_volumes: dict = None,
                          sentiment_factor: float = 0.0,
                          mode: str = 'new_open',
                          protection_period: int = 0) -> dict:
    """
    通过 paper-trader 执行订单。
    
    Args:
        symbol:             股票代码
        action:             buy/sell/short/cover
        amount:             交易金额
        direction:          long/short
        stop_loss:          止损价（可选）
        stop_type:          atr/fixed/percent（可选）
        take_profit:        止盈价（可选）
        reason:             交易原因（可选）
        current_prices:     当前价格字典 {'AAPL': 175.5, ...}（必须传入，否则DATA_FREEZE）
        avg_daily_volumes:  日均成交额字典 {'AAPL': 5000000, ...}（可选）
        sentiment_factor:   情绪因子（可选）
        mode:               执行模式: 'new_open'(新开仓,默认) | 'manage'(持仓管理加仓)
                            new_open模式下，如果标的已有持仓，paper-trader会拒绝执行
        protection_period:  保护期天数（0=无保护期，≥1表示N天保护期，2026-04-24新增）
    
    Returns:
        执行结果字典
    """
    args = ['execute', '--symbol', symbol, '--action', action,
            '--amount', str(amount), '--direction', direction,
            '--mode', mode]
    
    if stop_loss is not None:
        args.extend(['--stop-loss', str(stop_loss)])
    if stop_type is not None:
        args.extend(['--stop-type', stop_type])
    if take_profit is not None:
        args.extend(['--take-profit', str(take_profit)])
    if reason:
        args.extend(['--reason', reason])
    
    # 传入当前价格（paper-trader 依赖此参数判断DATA_FREEZE和计算成交价）
    if current_prices:
        args.extend(['--prices', json.dumps(current_prices)])
    if avg_daily_volumes:
        args.extend(['--avg-volumes', json.dumps(avg_daily_volumes)])
    if sentiment_factor != 0.0:
        args.extend(['--sentiment-factor', str(sentiment_factor)])
    if protection_period > 0:
        args.extend(['--protection-period', str(protection_period)])
    
    output = _run_paper_trader(*args)
    
    # 解析执行结果（paper-trader 返回 Markdown 键值表）
    result = {'symbol': symbol, 'action': action, 'raw_output': output}
    
    # 解析键值对表格: | 属性 | 值 |（竖向排列，需逐行提取 key→value）
    rows = _parse_markdown_table(output)
    if rows:
        # 检查是否是竖向键值对表（表头为 "属性|值" 或 "指标|值"）
        merged = {}
        is_kv_table = False
        for row in rows:
            key = row.get('属性', row.get('指标', ''))
            val = row.get('值', '')
            if key:
                merged[key] = val
                is_kv_table = True
        
        if is_kv_table:
            result.update({
                'executed_price': _safe_float(merged.get('执行价', 0)),
                'quantity': _safe_float(merged.get('数量', 0)),
                'amount': _safe_float(merged.get('金额', 0)),
                'cost_multiplier': _safe_float(merged.get('成本乘数', 1.0)),
                'liquidity_warning': '是' in str(merged.get('流动性警告', '')),
                'status': merged.get('状态', 'OK'),
                'message': merged.get('消息', ''),
                'mode': merged.get('模式', mode)
            })
        else:
            # 横向表格（positions格式），取第一行
            row = rows[0] if rows else {}
            result.update({
                'executed_price': _safe_float(row.get('执行价', row.get('成交价', row.get('价格', 0)))),
                'quantity': _safe_float(row.get('数量', row.get('数量(股)', 0))),
                'amount': _safe_float(row.get('金额', 0)),
                'status': row.get('状态', 'OK'),
                'message': row.get('消息', '执行成功')
            })
    else:
        if '错误' in output or '失败' in output or '拒绝' in output:
            result.update({'status': 'ERROR', 'message': output})
        else:
            result.update({'status': 'OK', 'message': output})
    
    return result


def paper_trader_positions() -> list:
    """
    查询 paper-trader 当前所有持仓。
    
    Returns:
        持仓字典列表
    """
    output = _run_paper_trader('positions')
    rows = _parse_markdown_table(output)
    positions = []
    for row in rows:
        pos = {
            'symbol': row.get('代码', ''),
            'direction': row.get('方向', 'long'),
            'entry_price': _safe_float(row.get('建仓价', 0)),
            'current_price': _safe_float(row.get('现价', 0)),
            'quantity': _safe_float(row.get('数量(股)', row.get('数量', 0))),
            'position_size': _safe_float(row.get('持仓市值', 0)),
            'pnl': _safe_float(row.get('浮动盈亏', 0)),
            'pnl_pct': _safe_float_pct(row.get('盈亏%', '0')),
            'max_profit_since_entry': _safe_float(row.get('历史最大盈利', 0)),
            'stop_loss': _safe_float(row.get('止损价', 0)) or None,
            'trailing_stop_price': _safe_float(row.get('吊灯止损', 0)) or None,  # 🆕 吊灯止损参考价
            'take_profit': _safe_float(row.get('止盈价', 0)) or None,
            'add_price': _safe_float(row.get('加仓价', 0)) or None,
            'reduce_price': _safe_float(row.get('减仓价', 0)) or None,
            'close_price': _safe_float(row.get('清仓价', 0)) or None,
            'entry_date': row.get('建仓日期', ''),
        }
        positions.append(pos)
    return positions


def paper_trader_summary() -> dict:
    """
    查询 paper-trader 账户摘要。
    
    Returns:
        账户摘要字典
    """
    output = _run_paper_trader('summary')
    summary = _parse_summary_table(output)
    
    # 标准化字段名
    result = {
        'total_equity': summary.get('账户净值', 0),
        'cash': summary.get('现金', 0),
        'total_position_value': summary.get('持仓市值', 0),
        'total_unrealized_pnl': summary.get('浮动盈亏', 0),
        'total_return_since_inception': _safe_float_pct(summary.get('总收益率', '0')),
        'position_count': int(summary.get('持仓数', 0)),
    }
    return result


def paper_trader_settle(prices: dict) -> dict:
    """
    收盘结算：用最新价格更新所有持仓的P&L，执行止损止盈检查。
    
    🆕 v2: 包含数据异常检测（PnL突变、价格偏离、日价格跳变）。
    
    Args:
        prices: {'AAPL': 175.5, 'NVDA': 900.0, ...}
    
    Returns:
        结算结果（含data_anomalies异常列表）
    """
    prices_json = json.dumps(prices)
    output = _run_paper_trader('settle', '--prices', prices_json)
    
    # 🆕 检查数据异常
    anomalies = []
    if '数据异常检测' in output or 'PRICE_ANOMALY' in output or 'PNL_SPIKE' in output:
        logger.warning(f"[FoolTrader] 🚨 paper-trader结算发现数据异常！")
        # 从输出中提取异常信息
        lines = output.split('\n')
        for line in lines:
            if 'PRICE_ANOMALY' in line or 'PNL_SPIKE' in line or 'DAILY_PRICE_JUMP' in line:
                anomalies.append(line.strip())
    
    return {
        'output': output,
        'data_anomalies': anomalies,
        'has_critical_anomaly': any('CRITICAL' in a for a in anomalies)
    }


def paper_trader_risk_check(prices: dict) -> dict:
    """
    风控检查：检查止损/止盈触发，不实际执行。
    
    Args:
        prices: {'AAPL': 175.5, ...}
    
    Returns:
        风控检查结果
    """
    prices_json = json.dumps(prices)
    output = _run_paper_trader('risk-check', '--prices', prices_json)
    return {'output': output}


def paper_trader_history(limit: int = 20) -> list:
    """
    查询交易历史。
    
    Args:
        limit: 返回最近N条记录
    
    Returns:
        交易记录字典列表
    """
    output = _run_paper_trader('history', '--limit', str(limit))
    rows = _parse_markdown_table(output)
    return rows


def paper_trader_update_stops(updates: dict) -> dict:
    """
    动态更新持仓的止损止盈价格。
    
    核心规则：
    - 多头止损只能上移，空头止损只能下移（不回退）
    - 吊灯止损参考价每次都会更新
    - 减仓价/清仓价/加仓价每次都会更新
    
    Args:
        updates: {
            'SYMBOL': {
                'stop_loss': 170,            # 新止损价
                'reduce_price': 178.5,       # 新减仓价
                'close_price': 161.5,        # 新清仓价
                'add_price': 189,            # 新加仓价
                'trailing_stop_price': 172,  # 吊灯止损参考价
                'trailing_stop_rule': '最高价-1.5×ATR20',  # 吊灯止损规则描述
                'take_profit': 200,          # 新止盈价
                'update_reason': '吊灯止损动态更新'  # 更新原因
            },
            ...
        }
    
    Returns:
        更新结果
    """
    updates_json = json.dumps(updates, ensure_ascii=False)
    output = _run_paper_trader('update-stops', '--updates', updates_json)
    return {'output': output}


def calculate_dynamic_stops(positions_data: list, market_type: str = 'HK') -> dict:
    """
    根据持仓的当前价格、ATR、ADX等指标，计算动态止损止盈价格。
    
    保护期规则（2026-04-24新增）：
    - score≥60的策略配3天保护期，保护期内吊灯止损放宽1个ATR（避免建仓初期被正常波动洗出）
    - score<60的策略无保护期，正常止损
    - 保护期从建仓日期开始计算，到期后恢复正常止损
    
    规则（按市场环境策略）：
    
    【牛市策略】
    - 吊灯止损：最高价 - (1.5或2.0)×ATR20（ADX>25用2.0，否则1.5）
    - 减仓价 = 吊灯止损价 × 1.05
    - 清仓价 = 吊灯止损价 × 0.95
    - 加仓价 = 当前价 × 1.05（仅RSI<70时）
    
    【震荡市策略】
    - 吊灯止损：最高价 - 1.5×ATR20（更紧）
    - 减仓价 = 吊灯止损价 × 1.05
    - 清仓价 = 吊灯止损价 × 0.95
    - 无加仓价
    
    【熊市策略】
    - 空头吊灯止损：最低价 + 2.0×ATR20
    - 多头避险吊灯止损：最高价 - 1.5×ATR20
    - 减仓价 = 吊灯止损价 × 1.05（多头）/ × 0.95（空头）
    - 清仓价 = 吊灯止损价 × 0.95（多头）/ × 1.05（空头）
    - 无加仓价
    
    【阶梯止盈】（通用，浮盈>50%时启用）
    - 利润回吐>50% → 减仓50%（由manage检查执行，不在这里更新止损价）
    - 利润回吐>30% → 减仓25%
    
    Args:
        positions_data: 持仓数据列表，每个元素需包含：
            symbol, direction, entry_price, current_price, 
            pnl_pct, max_profit_since_entry,
            atr20 (当前ATR20值), adx14 (当前ADX14值, 可选),
            highest_since_entry (持仓期间最高价, 可选),
            lowest_since_entry (持仓期间最低价, 可选),
            strategy_type ('gem'/'bull'/'range'/'bear'),  # 'gem'为统一GEM策略，其他为旧数据兼容
            rsi14 (当前RSI14值, 可选),
            protection_period (保护期天数, 默认0, 可选),
            entry_date (建仓日期, 格式'YYYY-MM-DD', 可选)
        market_type: 市场类型 'HK'/'US'
    
    Returns:
        updates字典，可直接传给 paper_trader_update_stops()
    """
    updates = {}
    
    for pos in positions_data:
        symbol = pos.get('symbol', '')
        direction = pos.get('direction', 'long')
        entry_price = float(pos.get('entry_price', 0))
        current_price = float(pos.get('current_price', 0))
        pnl_pct = float(pos.get('pnl_pct', 0))
        atr20 = float(pos.get('atr20', 0))
        adx14 = float(pos.get('adx14', 0))
        highest = float(pos.get('highest_since_entry', current_price))
        lowest = float(pos.get('lowest_since_entry', current_price))
        strategy_type = pos.get('strategy_type', 'gem')
        rsi14 = float(pos.get('rsi14', 50))
        protection_period = int(pos.get('protection_period', 0))
        entry_date_str = pos.get('entry_date', '')
        
        # ── 保护期判断 ──
        in_protection = False
        if protection_period > 0 and entry_date_str:
            try:
                from datetime import date
                if isinstance(entry_date_str, str):
                    entry_dt = datetime.strptime(entry_date_str[:10], '%Y-%m-%d').date()
                elif isinstance(entry_date_str, date):
                    entry_dt = entry_date_str
                else:
                    entry_dt = date.today()
                days_since_entry = (date.today() - entry_dt).days
                if days_since_entry < protection_period:
                    in_protection = True
                    reason_parts.append(f'🛡️保护期({days_since_entry}/{protection_period}天)')
            except Exception:
                pass  # 日期解析失败，不启用保护期
        
        # 数据有效性校验
        if not symbol or current_price <= 0 or atr20 <= 0:
            continue
        
        update = {}
        reason_parts = []
        
        if direction == 'long':
            # === 多头持仓 ===
            if strategy_type == 'gem':
                # GEM统一策略吊灯止损：根据ADX动态调整ATR倍数
                multiplier = 2.0 if adx14 > 25 else 1.5
                # 保护期内放宽1个ATR（避免建仓初期被正常波动洗出）
                if in_protection:
                    multiplier += 1.0  # 保护期内ATR倍数+1（如1.5→2.5, 2.0→3.0）
                trailing_price = round(highest - multiplier * atr20, 2)
                update['trailing_stop_price'] = trailing_price
                if in_protection:
                    update['trailing_stop_rule'] = f'最高价({highest})-{multiplier}×ATR20({atr20:.2f}) [🛡️保护期放宽]'
                else:
                    update['trailing_stop_rule'] = f'最高价({highest})-{multiplier}×ATR20({atr20:.2f})'
                reason_parts.append(f'GEM吊灯[{multiplier}×ATR]' + ('🛡️' if in_protection else ''))
                
                # 止损价：取吊灯止损和静态止损的较大值（更保守）
                # 如果吊灯止损>静态止损，更新静态止损
                update['stop_loss'] = trailing_price
                
                # 减仓价 = 吊灯止损价 × 1.05
                update['reduce_price'] = round(trailing_price * 1.05, 2)
                # 清仓价 = 吊灯止损价 × 0.95
                update['close_price'] = round(trailing_price * 0.95, 2)
                # 加仓价（仅RSI<70时）
                if rsi14 < 70:
                    update['add_price'] = round(current_price * 1.05, 2)
                    
            elif strategy_type in ('range', 'bear'):
                # 兼容旧数据：震荡市/熊市避险吊灯止损：最高价 - 1.5×ATR20（更紧）
                trailing_price = round(highest - 1.5 * atr20, 2)
                update['trailing_stop_price'] = trailing_price
                update['trailing_stop_rule'] = f'最高价({highest})-1.5×ATR20({atr20:.2f})'
                reason_parts.append('GEM避险吊灯[1.5×ATR]')
                
                update['stop_loss'] = trailing_price
                update['reduce_price'] = round(trailing_price * 1.05, 2)
                update['close_price'] = round(trailing_price * 0.95, 2)
                # 震荡市不加仓
                
            elif strategy_type == 'bear':
                # 兼容旧数据：熊市避险吊灯止损：最高价 - 1.5×ATR20
                trailing_price = round(highest - 1.5 * atr20, 2)
                update['trailing_stop_price'] = trailing_price
                update['trailing_stop_rule'] = f'最高价({highest})-1.5×ATR20({atr20:.2f})'
                reason_parts.append('GEM避险吊灯[1.5×ATR]')
                
                update['stop_loss'] = trailing_price
                update['reduce_price'] = round(trailing_price * 1.05, 2)
                update['close_price'] = round(trailing_price * 0.95, 2)
                # 熊市不加仓
        
        elif direction == 'short':
            # === 空头持仓 ===
            if strategy_type in ('bear', 'gem'):
                # GEM/熊市做空吊灯止损：最低价 + 2.0×ATR20
                trailing_price = round(lowest + 2.0 * atr20, 2)
                update['trailing_stop_price'] = trailing_price
                update['trailing_stop_rule'] = f'最低价({lowest})+2×ATR20({atr20:.2f})'
                reason_parts.append('熊市做空吊灯[2×ATR]')
                
                update['stop_loss'] = trailing_price
                update['reduce_price'] = round(trailing_price * 0.95, 2)
                update['close_price'] = round(trailing_price * 1.05, 2)
            else:
                # 非熊市的空头（罕见），使用通用规则
                trailing_price = round(lowest + 2.0 * atr20, 2)
                update['trailing_stop_price'] = trailing_price
                update['trailing_stop_rule'] = f'最低价({lowest})+2×ATR20({atr20:.2f})'
                reason_parts.append('通用空头吊灯[2×ATR]')
                
                update['stop_loss'] = trailing_price
                update['reduce_price'] = round(trailing_price * 0.95, 2)
                update['close_price'] = round(trailing_price * 1.05, 2)
        
        # 阶梯止盈标记（仅浮盈>50%时）
        if pnl_pct > 50:
            update['update_reason'] = f'{" + ".join(reason_parts)} + 阶梯止盈中(浮盈{pnl_pct:.1f}%)'
        else:
            update['update_reason'] = ' + '.join(reason_parts) if reason_parts else '常规动态更新'
        
        if update:
            updates[symbol] = update
    
    return updates


# ════════════════════════════════════════════════════════════
# 3. 辅助函数
# ════════════════════════════════════════════════════════════

def _safe_float(val) -> float:
    """安全转换为浮点数"""
    if val is None:
        return 0.0
    try:
        s = str(val).replace(',', '').strip()
        if '%' in s:
            s = s.replace('%', '')
            return float(s)
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _safe_float_pct(val) -> float:
    """安全转换百分比字符串为浮点数（去掉%号）"""
    if val is None:
        return 0.0
    try:
        s = str(val).replace(',', '').replace('%', '').strip()
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ════════════════════════════════════════════════════════════
# 4. 旧版内存模拟逻辑（fallback）
# ════════════════════════════════════════════════════════════

def execute_order(order: dict, current_prices: dict,
                  avg_daily_volumes: dict, sentiment_factor: float = 0.0) -> dict:
    """
    执行单笔订单（内存模拟模式，仅作为 fallback）。
    
    当 paper-trader 不可用时使用此函数。
    推荐使用 paper_trader_execute() 替代。
    """
    symbol = order.get('symbol', '').upper()
    action = order.get('action', 'buy')
    direction = order.get('direction', 'long')

    # 数据缺失防污染
    raw_price = current_prices.get(symbol)
    if raw_price is None or raw_price <= 0:
        logger.warning(f"[FoolTrader] {symbol} 价格缺失，冻结持仓更新")
        return {
            'symbol': symbol, 'action': action, 'executed_price': 0,
            'quantity': 0, 'amount': 0, 'cost_multiplier': 1.0,
            'liquidity_warning': False, 'status': 'DATA_FREEZE',
            'message': f'{symbol} 价格数据缺失，保留昨日快照'
        }

    base_price = float(raw_price)

    quantity = float(order.get('quantity', 0))
    amount = float(order.get('amount', 0))
    if quantity > 0 and amount <= 0:
        amount = quantity * base_price
    elif amount > 0 and quantity <= 0:
        quantity = amount / base_price
    else:
        if amount > 0:
            quantity = amount / base_price

    if amount <= 0:
        return {
            'symbol': symbol, 'action': action, 'executed_price': base_price,
            'quantity': 0, 'amount': 0, 'cost_multiplier': 1.0,
            'liquidity_warning': False, 'status': 'OK',
            'message': '订单金额为0，跳过执行'
        }

    if amount > MAX_SINGLE_POSITION:
        logger.warning(f"[FoolTrader] {symbol} 订单金额 {amount:.0f} 超过单票上限 {MAX_SINGLE_POSITION}，自动缩减")
        qty = int(MAX_SINGLE_POSITION / base_price)
        amount = qty * base_price

    if base_price > 0 and amount < base_price:
        return {
            'symbol': symbol, 'action': action, 'executed_price': base_price,
            'quantity': 0, 'amount': 0, 'cost_multiplier': 1.0,
            'liquidity_warning': False, 'status': 'AMOUNT_INSUFFICIENT',
            'message': f'金额{amount:.0f}不足以买入1股（单价={base_price:.2f}）'
        }

    avg_vol_value = float(avg_daily_volumes.get(symbol, 0))
    cost_result = calculate_execution_cost(amount, avg_vol_value, action, sentiment_factor)

    if cost_result['rejected']:
        return {
            'symbol': symbol, 'action': action, 'executed_price': base_price,
            'quantity': 0, 'amount': 0, 'cost_multiplier': 1.0,
            'liquidity_warning': True, 'status': 'LIQUIDITY_REJECTED',
            'message': cost_result['reject_reason']
        }

    executed_price = base_price * cost_result['cost_multiplier']
    actual_amount = quantity * executed_price

    return {
        'symbol': symbol,
        'action': action,
        'executed_price': round(executed_price, 4),
        'quantity': round(quantity, 2),
        'amount': round(actual_amount, 2),
        'cost_multiplier': cost_result['cost_multiplier'],
        'liquidity_warning': cost_result['liquidity_warning'],
        'status': 'OK',
        'message': '执行成功(fallback)'
    }


def update_position_pnl(position: dict, current_price: float) -> dict:
    """更新单个持仓的 P&L 数据（fallback 用）"""
    pos = dict(position)
    entry = float(pos.get('entry_price', 0))
    size = float(pos.get('position_size', 0))
    direction = pos.get('direction', 'long')

    if entry <= 0 or size <= 0:
        return pos

    if direction == 'long':
        pnl = (current_price - entry) / entry * size
        pnl_pct = (current_price - entry) / entry * 100
    else:
        pnl = (entry - current_price) / entry * size
        pnl_pct = (entry - current_price) / entry * 100

    pos['current_price'] = round(current_price, 4)
    pos['pnl'] = round(pnl, 2)
    pos['pnl_pct'] = round(pnl_pct, 2)

    prev_max = float(pos.get('max_profit_since_entry', pnl))
    pos['max_profit_since_entry'] = round(max(prev_max, pnl), 2)

    return pos


def update_all_positions(positions: list, current_prices: dict) -> tuple:
    """批量更新所有持仓的 P&L（fallback 用）"""
    updated = []
    frozen = []
    for pos in positions:
        symbol = pos.get('symbol', '').upper()
        price = current_prices.get(symbol)
        if price is None or price <= 0:
            frozen.append(symbol)
            updated.append(pos)
        else:
            updated.append(update_position_pnl(pos, float(price)))
    return updated, frozen


def calculate_account_summary(positions: list, cash: float,
                               inception_equity: float) -> dict:
    """计算账户净值摘要（fallback 用）"""
    total_position_value = sum(float(p.get('position_size', 0)) for p in positions)
    total_unrealized_pnl = sum(float(p.get('pnl', 0)) for p in positions)
    total_equity = cash + total_position_value + total_unrealized_pnl
    total_return = (total_equity - inception_equity) / inception_equity * 100 if inception_equity > 0 else 0

    return {
        'total_equity': round(total_equity, 2),
        'total_position_value': round(total_position_value, 2),
        'cash': round(cash, 2),
        'total_unrealized_pnl': round(total_unrealized_pnl, 2),
        'total_return_since_inception': round(total_return, 2)
    }


# ── 旧版持久化（fallback 用）──

def _write_md_table_safe(filepath: str, headers: list, rows: list, mode: str = 'w'):
    """写入 Markdown 表格（带文件锁，防止并发写入数据损坏）"""
    open_mode = 'a' if mode == 'a' else 'w'
    with open(filepath, open_mode, encoding='utf-8') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            if mode == 'w':
                f.write('| ' + ' | '.join(headers) + ' |\n')
            for row in rows:
                f.write('| ' + ' | '.join(str(c) for c in row) + ' |\n')
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def record_trade(symbol: str, direction: str, action: str, price: float,
                 quantity: float, amount: float, reason: str = ""):
    """记录逐笔交易到 trade_history.md（fallback 用，paper-trader 自动记录）"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, symbol, direction, action, f"{price:.2f}",
           f"{quantity:.0f}", f"{amount:.2f}", reason]
    headers = ['时间', '代码', '方向', '动作', '价格', '数量', '金额', '原因']

    if not os.path.exists(HISTORY_FILE):
        _write_md_table_safe(HISTORY_FILE, headers, [row], 'w')
    else:
        _write_md_table_safe(HISTORY_FILE, headers, [row], 'a')


def update_holdings(holdings: list):
    """覆盖写入当前持仓（fallback 用，paper-trader 自动维护）"""
    headers = ['代码', '方向', '建仓价', '现价', '数量', '浮动盈亏', '盈亏%', '历史最大盈利']
    rows = []
    for h in holdings:
        rows.append([
            h['symbol'], h['direction'],
            f"{h['entry_price']:.2f}", f"{h['current_price']:.2f}",
            h.get('quantity', h.get('position_size', 0)),
            f"{h.get('pnl', 0):.2f}", f"{h.get('pnl_pct', 0):.1f}%",
            f"{h.get('max_profit_since_entry', 0):.2f}"
        ])
    _write_md_table_safe(CUR_HOLDINGS_FILE, headers, rows, 'w')


def record_closed_trade(symbol: str, direction: str, entry_price: float,
                        exit_price: float, quantity: float, pnl: float,
                        pnl_pct: float, exit_reason: str = ""):
    """追加已平仓记录（fallback 用，paper-trader 自动记录）"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, symbol, direction, f"{entry_price:.2f}", f"{exit_price:.2f}",
           f"{quantity:.0f}", f"{pnl:.2f}", f"{pnl_pct:.1f}%", exit_reason]
    headers = ['平仓时间', '代码', '方向', '建仓价', '平仓价', '数量', '盈亏', '盈亏%', '平仓原因']

    if not os.path.exists(FINISH_HOLDINGS_FILE):
        _write_md_table_safe(FINISH_HOLDINGS_FILE, headers, [row], 'w')
    else:
        _write_md_table_safe(FINISH_HOLDINGS_FILE, headers, [row], 'a')


# ════════════════════════════════════════════════════════════
# 5. 傻瓜交易员主入口（整合 paper-trader）
# ════════════════════════════════════════════════════════════

def run_execution(execution_orders: list, current_prices: dict,
                  avg_daily_volumes: dict, None_positions: list = None,
                  cash: float = 0, inception_equity: float = 100000000,
                  sentiment_factor: float = 0.0) -> dict:
    """
    傻瓜交易员完整执行流程。
    
    优先使用 paper-trader skill 进行模拟撮合，当不可用时回退到内存模拟。
    
    Args:
        execution_orders:   CRO 批准后的执行指令列表
        current_prices:     最新价格字典 {'AAPL': 175.5, ...}
        avg_daily_volumes:  近20日日均成交额字典（金额，仅fallback用）
        None_positions:     当前持仓列表（仅fallback用，paper-trader自动维护）
        cash:               账户现金余额（仅fallback用）
        inception_equity:   初始净值
        sentiment_factor:   情绪因子
    
    Returns:
        与 Agent 6 Prompt 输出格式对齐的完整执行结果
    """
    # ── 路径1: paper-trader skill 可用 ──
    if is_paper_trader_available():
        logger.info("[FoolTrader] 🎯 使用 paper-trader skill 执行交易")
        return _run_execution_with_paper_trader(
            execution_orders, current_prices, avg_daily_volumes, sentiment_factor
        )
    
    # ── 路径2: fallback 到内存模拟 ──
    logger.warning("[FoolTrader] ⚠️ paper-trader skill 不可用，回退到内存模拟模式")
    return _run_execution_fallback(
        execution_orders, current_prices, avg_daily_volumes,
        None_positions or [], cash, inception_equity, sentiment_factor
    )


def _run_execution_with_paper_trader(execution_orders: list,
                                      current_prices: dict,
                                      avg_daily_volumes: dict,
                                      sentiment_factor: float) -> dict:
    """
    使用 paper-trader skill 执行交易。
    
    paper-trader 自动维护：
    - 持仓状态（positions.json）
    - 交易历史（trade_history.json）
    - 账户余额（account.json）
    - 止损止盈检查
    - 滑点计算
    """
    execution_results = []
    liquidity_rejected = []
    data_frozen = []
    
    # Step 1: 执行每笔订单
    for order in (execution_orders or []):
        symbol = order.get('symbol', '').upper()
        action = order.get('action', 'buy')
        direction = order.get('direction', 'long')
        amount = float(order.get('amount', 0))
        stop_loss = order.get('stop_loss')
        stop_type = order.get('stop_type')
        take_profit = order.get('take_profit')
        reason = order.get('reason', '')
        
        # ── 数据缺失防污染 ──
        raw_price = current_prices.get(symbol)
        if raw_price is None or raw_price <= 0:
            logger.warning(f"[FoolTrader] {symbol} 价格缺失，冻结该标的")
            execution_results.append({
                'symbol': symbol, 'action': action, 'executed_price': 0,
                'quantity': 0, 'amount': 0, 'status': 'DATA_FREEZE',
                'message': f'{symbol} 价格数据缺失，保留昨日快照'
            })
            data_frozen.append(symbol)
            continue
        
        # ── 单票金额上限检查 ──
        if amount > MAX_SINGLE_POSITION:
            logger.warning(f"[FoolTrader] {symbol} 订单金额 {amount:.0f} 超过单票上限，自动缩减")
            amount = MAX_SINGLE_POSITION
        
        if amount <= 0:
            execution_results.append({
                'symbol': symbol, 'action': action, 'executed_price': 0,
                'quantity': 0, 'amount': 0, 'status': 'OK',
                'message': '订单金额为0，跳过执行'
            })
            continue
        
        # ── 调用 paper-trader execute ──
        try:
            # 为当前标的提取价格和成交额子集
            symbol_price = {symbol: current_prices[symbol]} if symbol in current_prices else {}
            symbol_volume = {symbol: avg_daily_volumes.get(symbol, 0)} if avg_daily_volumes else {}
            
            result = paper_trader_execute(
                symbol=symbol,
                action=action,
                amount=amount,
                direction=direction,
                stop_loss=stop_loss,
                stop_type=stop_type,
                take_profit=take_profit,
                reason=reason,
                current_prices=symbol_price,
                avg_daily_volumes=symbol_volume,
                sentiment_factor=sentiment_factor
            )
            result['sentiment_factor'] = sentiment_factor
            execution_results.append(result)
            
            # ── 记录建仓regime标记（2026-04-22新增）──
            entry_regime = order.get('entry_regime', '')
            entry_regime_confidence = order.get('entry_regime_confidence', 0)
            if entry_regime and result.get('status') == 'OK' and action == 'buy':
                record_position_regime(symbol, entry_regime, entry_regime_confidence)
                logger.info(f"[FoolTrader] 📝 记录 {symbol} 建仓regime={entry_regime}（置信度{entry_regime_confidence}%）")
            
            if result.get('status') == 'ERROR' and '流动性' in result.get('message', ''):
                liquidity_rejected.append(symbol)
            elif result.get('status') == 'ERROR':
                liquidity_rejected.append(symbol)
            
            logger.info(f"[FoolTrader] paper-trader 执行 {action} {symbol} "
                       f"金额={amount:.0f} → {result.get('status', 'UNKNOWN')}")
        
        except RuntimeError as e:
            logger.error(f"[FoolTrader] paper-trader 执行异常: {e}")
            execution_results.append({
                'symbol': symbol, 'action': action, 'executed_price': 0,
                'quantity': 0, 'amount': 0, 'status': 'ERROR',
                'message': f'paper-trader 执行异常: {str(e)}'
            })
            liquidity_rejected.append(symbol)
    
    # Step 2: 收盘结算（用最新价格更新P&L，检查止损止盈）
    closed_trades_today = []
    data_anomalies = []  # 🆕 数据异常列表
    try:
        settle_result = paper_trader_settle(current_prices)
        settle_output = settle_result.get('output', '')
        
        # 🆕 检查数据异常
        anomalies = settle_result.get('data_anomalies', [])
        has_critical = settle_result.get('has_critical_anomaly', False)
        if anomalies:
            logger.warning(f"[FoolTrader] 🚨 结算发现{len(anomalies)}个数据异常")
            data_anomalies = anomalies
            # 严重异常时，冻结所有相关标的的后续操作
            if has_critical:
                logger.error(f"[FoolTrader] ❌ 发现严重数据异常，建议人工审查！")
        
        # 检查是否有止损/止盈触发的平仓
        if '止损' in settle_output or '止盈' in settle_output or '平仓' in settle_output:
            logger.info(f"[FoolTrader] paper-trader 结算触发止损/止盈:\n{settle_output}")
            # 从结算输出中提取平仓信息
            closed_trades_today = _extract_closed_trades(settle_output)
            # ── 清理已平仓持仓的regime标记（2026-04-22新增）──
            for ct in closed_trades_today:
                closed_symbol = ct.get('symbol', '')
                if closed_symbol:
                    remove_position_regime(closed_symbol)
                    logger.info(f"[FoolTrader] 🗑️ 清理 {closed_symbol} 的regime标记（已平仓）")
    except RuntimeError as e:
        logger.error(f"[FoolTrader] paper-trader 结算异常: {e}")
    
    # Step 3: 查询更新后的持仓
    updated_positions = []
    try:
        updated_positions = paper_trader_positions()
    except RuntimeError as e:
        logger.error(f"[FoolTrader] paper-trader 查询持仓异常: {e}")
    
    # Step 4: 查询账户摘要
    account_summary = {}
    try:
        account_summary = paper_trader_summary()
    except RuntimeError as e:
        logger.error(f"[FoolTrader] paper-trader 查询账户摘要异常: {e}")
    
    # 确定整体状态
    if liquidity_rejected:
        overall_status = 'LIQUIDITY_REJECTED'
    elif data_frozen:
        overall_status = 'DATA_FREEZE'
    else:
        overall_status = None
    
    return {
        'error': overall_status,
        'execution_mode': 'paper-trader',
        'execution_results': execution_results,
        'updated_positions': updated_positions,
        'closed_trades_today': closed_trades_today,
        'liquidity_rejected_symbols': liquidity_rejected,
        'data_frozen_symbols': data_frozen,
        'account_summary': account_summary,
        'data_anomalies': data_anomalies  # 🆕 数据异常检测结果
    }


def _extract_closed_trades(settle_output: str) -> list:
    """从 paper-trader settle 输出中提取已平仓交易"""
    closed = []
    lines = settle_output.split('\n')
    for line in lines:
        if '止损' in line or '止盈' in line:
            # 尝试提取关键信息
            parts = line.strip().split()
            symbol = ''
            for p in parts:
                if p.isupper() and len(p) <= 6:
                    symbol = p
                    break
            if symbol:
                closed.append({
                    'symbol': symbol,
                    'exit_reason': line.strip(),
                })
    return closed


def _run_execution_fallback(execution_orders: list, current_prices: dict,
                             avg_daily_volumes: dict, current_positions: list,
                             cash: float, inception_equity: float,
                             sentiment_factor: float) -> dict:
    """
    内存模拟模式（旧逻辑，仅当 paper-trader 不可用时使用）。
    
    保留了完整的成本分档模型、流动性检查、防污染等逻辑。
    """
    execution_results = []
    closed_trades_today = []
    liquidity_rejected = []
    data_frozen = []

    # Step 1: 执行订单
    for order in (execution_orders or []):
        result = execute_order(order, current_prices, avg_daily_volumes, sentiment_factor)
        execution_results.append(result)

        if result['status'] == 'LIQUIDITY_REJECTED':
            liquidity_rejected.append(result['symbol'])
        elif result['status'] == 'DATA_FREEZE':
            data_frozen.append(result['symbol'])
        elif result['status'] == 'AMOUNT_INSUFFICIENT':
            logger.info(f"[FoolTrader] {result['symbol']} 金额不足1股，跳过")
        elif result['status'] == 'OK' and result['quantity'] > 0:
            record_trade(
                symbol=result['symbol'],
                direction=order.get('direction', 'long'),
                action=result['action'],
                price=result['executed_price'],
                quantity=result['quantity'],
                amount=result['amount'],
                reason=order.get('reason', '')
            )
            if result['action'] in ('buy', 'short'):
                new_pos = {
                    'symbol': result['symbol'],
                    'direction': order.get('direction', 'long'),
                    'entry_price': result['executed_price'],
                    'current_price': result['executed_price'],
                    'position_size': result['amount'],
                    'quantity': result['quantity'],
                    'pnl': 0,
                    'pnl_pct': 0,
                    'max_profit_since_entry': 0
                }
                current_positions.append(new_pos)
                if result['action'] == 'buy':
                    cash -= result['amount']
            elif result['action'] in ('sell', 'cover'):
                for i, pos in enumerate(current_positions):
                    if pos['symbol'] == result['symbol']:
                        pos_qty = pos.get('quantity', pos.get('position_size', 0) / max(pos.get('entry_price', 1), 0.01))
                        if result['quantity'] >= pos_qty:
                            entry_p = pos.get('entry_price', 0)
                            closed_trades_today.append({
                                'symbol': result['symbol'],
                                'direction': pos.get('direction', 'long'),
                                'entry_price': entry_p,
                                'exit_price': result['executed_price'],
                                'quantity': result['quantity'],
                                'pnl': result['amount'] - pos.get('position_size', 0),
                                'pnl_pct': (result['executed_price'] - entry_p) / max(entry_p, 0.01) * 100,
                                'exit_reason': order.get('reason', 'sell')
                            })
                            record_closed_trade(
                                symbol=result['symbol'],
                                direction=pos.get('direction', 'long'),
                                entry_price=entry_p,
                                exit_price=result['executed_price'],
                                quantity=result['quantity'],
                                pnl=result['amount'] - pos.get('position_size', 0),
                                pnl_pct=(result['executed_price'] - entry_p) / max(entry_p, 0.01) * 100,
                                exit_reason=order.get('reason', 'sell')
                            )
                            current_positions.pop(i)
                        else:
                            reduce_ratio = result['quantity'] / max(pos_qty, 0.01)
                            pos['position_size'] = pos.get('position_size', 0) * (1 - reduce_ratio)
                            if 'quantity' in pos:
                                pos['quantity'] = pos['quantity'] * (1 - reduce_ratio)
                        if result['action'] == 'sell':
                            cash += result['amount']
                        break

    # Step 2: 更新持仓 P&L
    updated_positions, frozen = update_all_positions(current_positions, current_prices)
    data_frozen = list(set(data_frozen + frozen))

    # Step 3: 持久化
    update_holdings(updated_positions)

    # Step 4: 账户净值汇总
    account_summary = calculate_account_summary(updated_positions, cash, inception_equity)

    if liquidity_rejected:
        overall_status = 'LIQUIDITY_REJECTED'
    elif data_frozen:
        overall_status = 'DATA_FREEZE'
    else:
        overall_status = None

    return {
        'error': overall_status,
        'execution_mode': 'fallback',
        'execution_results': execution_results,
        'updated_positions': updated_positions,
        'closed_trades_today': closed_trades_today,
        'liquidity_rejected_symbols': liquidity_rejected,
        'data_frozen_symbols': data_frozen,
        'account_summary': account_summary
    }


# ── 别名函数（供main_dispatcher.py调用）──
def paper_trader_get_positions() -> list:
    """别名：paper_trader_positions()"""
    return paper_trader_positions()
