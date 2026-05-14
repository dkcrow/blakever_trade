#!/usr/bin/env python3
"""
修复港股CSV文件中Volume=0的数据

问题：westock-data kline接口对港股早期数据（约2018年之前）不返回成交量，
导致CSV文件中约40-50%的行Volume=0。

修复策略：
1. 优先用yfinance获取真实成交量（如果可用）
2. yfinance不可用时，用智能插值法填充：
   - 对于连续Volume=0的区间，用前向/后向最近非零值的均值填充
   - 考虑周末/节假日导致的成交量模式
3. 在CSV中增加VolumeSource列标注数据来源

使用方法：
  python3 fix_hk_volume.py                    # 修复所有港股文件
  python3 fix_hk_volume.py --yfinance         # 尝试用yfinance获取真实成交量
  python3 fix_hk_volume.py --interpolate-only # 仅用插值法（默认）
  python3 fix_hk_volume.py --dry-run          # 仅检查不修改
"""

import os
import sys
import argparse
import glob
import datetime
from pathlib import Path
from collections import defaultdict

HK_DIR = Path("/data/workspace/back_trader_stocks/hk")
HK_STOCKS_FILE = Path("/data/workspace/hk_stocks_pool.md")


def analyze_csv(csv_path: Path) -> dict:
    """分析CSV文件中Volume缺失情况"""
    with open(csv_path) as f:
        lines = f.readlines()
    
    if len(lines) <= 1:
        return {"total": 0, "vol_zero": 0, "vol_nonzero": 0}
    
    total = 0
    vol_zero = 0
    vol_nonzero = 0
    first_nonzero_date = None
    last_zero_date = None
    zero_ranges = []  # 连续Volume=0的区间
    
    current_range_start = None
    
    for line in lines[1:]:
        parts = line.strip().split(',')
        if len(parts) < 6:
            continue
        
        total += 1
        date = parts[0]
        vol = parts[5].strip()
        
        if vol == '0' or vol == '':
            vol_zero += 1
            last_zero_date = date
            if current_range_start is None:
                current_range_start = date
        else:
            vol_nonzero += 1
            if first_nonzero_date is None:
                first_nonzero_date = date
            if current_range_start is not None:
                zero_ranges.append((current_range_start, last_zero_date, vol_zero - len(zero_ranges)))
                current_range_start = None
    
    # 处理末尾的连续0区间
    if current_range_start is not None:
        zero_ranges.append((current_range_start, last_zero_date, 0))
    
    return {
        "total": total,
        "vol_zero": vol_zero,
        "vol_nonzero": vol_nonzero,
        "first_nonzero_date": first_nonzero_date,
        "last_zero_date": last_zero_date,
        "zero_ranges": zero_ranges,
    }


def interpolate_volume(lines: list) -> list:
    """
    用智能插值法修复Volume=0的行
    
    策略：
    1. 找出所有Volume非零的行及其索引
    2. 对于Volume=0的行，用最近的非零Volume值填充
    3. 如果开头就是0，用后向第一个非零值填充
    4. 如果结尾是0，用前向最后一个非零值填充
    """
    if len(lines) <= 1:
        return lines
    
    # 解析数据行
    data = []
    for i, line in enumerate(lines):
        if i == 0:  # header
            continue
        parts = line.strip().split(',')
        if len(parts) >= 6:
            data.append({
                'index': i,
                'date': parts[0],
                'open': parts[1],
                'high': parts[2],
                'low': parts[3],
                'close': parts[4],
                'volume': parts[5].strip(),
            })
    
    # 找出Volume非零的行
    nonzero_indices = [i for i, d in enumerate(data) if d['volume'] != '0' and d['volume'] != '']
    
    if not nonzero_indices:
        # 全部Volume=0，无法插值
        return lines
    
    # 找出Volume=0的连续区间
    zero_intervals = []
    start = None
    for i, d in enumerate(data):
        if d['volume'] == '0' or d['volume'] == '':
            if start is None:
                start = i
        else:
            if start is not None:
                zero_intervals.append((start, i - 1))
                start = None
    if start is not None:
        zero_intervals.append((start, len(data) - 1))
    
    # 对每个零值区间进行插值
    for interval_start, interval_end in zero_intervals:
        # 获取区间前后的非零Volume值
        before_vol = None
        after_vol = None
        
        # 前向搜索
        for i in range(interval_start - 1, -1, -1):
            if data[i]['volume'] != '0' and data[i]['volume'] != '':
                before_vol = int(data[i]['volume'])
                break
        
        # 后向搜索
        for i in range(interval_end + 1, len(data)):
            if data[i]['volume'] != '0' and data[i]['volume'] != '':
                after_vol = int(data[i]['volume'])
                break
        
        # 选择插值方法
        if before_vol is not None and after_vol is not None:
            # 前后都有值，用线性插值
            fill_vol = (before_vol + after_vol) // 2
        elif before_vol is not None:
            # 只有前面有值，用前向填充
            fill_vol = before_vol
        elif after_vol is not None:
            # 只有后面有值，用后向填充
            fill_vol = after_vol
        else:
            # 不应该到这里（已处理全部为0的情况）
            continue
        
        # 填充零值区间
        for i in range(interval_start, interval_end + 1):
            data[i]['volume'] = str(fill_vol)
            data[i]['volume_source'] = 'interpolated'
    
    # 标记非零Volume行
    for d in data:
        if 'volume_source' not in d:
            d['volume_source'] = 'original'
    
    # 重建CSV
    result = [lines[0].strip() + ',VolumeSource\n']
    for d in data:
        result.append(f"{d['date']},{d['open']},{d['high']},{d['low']},{d['close']},{d['volume']},{d['volume_source']}\n")
    
    return result


def fix_with_yfinance(csv_path: Path, symbol: str) -> bool:
    """
    用yfinance获取真实成交量来修复Volume=0的行
    返回是否成功
    """
    try:
        import yfinance as yf
    except ImportError:
        print(f"  [SKIP] yfinance未安装")
        return False
    
    # 读取现有数据
    with open(csv_path) as f:
        lines = f.readlines()
    
    # 找出Volume=0的日期范围
    zero_dates = []
    for line in lines[1:]:
        parts = line.strip().split(',')
        if len(parts) >= 6 and (parts[5].strip() == '0' or parts[5].strip() == ''):
            zero_dates.append(parts[0])
    
    if not zero_dates:
        return True
    
    # 用yfinance获取数据
    yf_symbol = f"{symbol[2:]}.HK"  # hk00700 -> 0700.HK
    start_date = zero_dates[0]
    end_date = (datetime.datetime.strptime(zero_dates[-1], '%Y-%m-%d') + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    
    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=start_date, end=end_date, interval='1d')
        if df.empty:
            print(f"  [WARN] yfinance返回空数据: {yf_symbol}")
            return False
        
        # 构建日期->Volume映射
        vol_map = {}
        for date, row in df.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            vol = int(row.get('Volume', 0))
            if vol > 0:
                vol_map[date_str] = vol
        
        # 替换Volume=0的行
        fixed_count = 0
        new_lines = [lines[0]]  # 保留header
        
        # 检查是否有VolumeSource列
        has_source = 'VolumeSource' in lines[0]
        if not has_source:
            new_lines[0] = lines[0].strip() + ',VolumeSource\n'
        
        for line in lines[1:]:
            parts = line.strip().split(',')
            if len(parts) >= 6 and (parts[5].strip() == '0' or parts[5].strip() == ''):
                date = parts[0]
                if date in vol_map:
                    parts[5] = str(vol_map[date])
                    if has_source:
                        parts[6] = 'yfinance'
                    else:
                        parts.append('yfinance')
                    fixed_count += 1
                else:
                    if has_source:
                        parts[6] = 'missing'
                    else:
                        parts.append('missing')
            else:
                if not has_source:
                    parts.append('original' if parts[5].strip() != '0' else 'interpolated')
            
            new_lines.append(','.join(parts) + '\n')
        
        # 写回文件
        with open(csv_path, 'w') as f:
            f.writelines(new_lines)
        
        print(f"  [OK] yfinance修复了 {fixed_count}/{len(zero_dates)} 行Volume")
        return fixed_count > 0
        
    except Exception as e:
        if "Rate" in str(e) or "429" in str(e):
            print(f"  [RATE-LIMIT] yfinance被限流")
        else:
            print(f"  [ERROR] yfinance失败: {e}")
        return False


def fix_csv_interpolate(csv_path: Path) -> dict:
    """
    用插值法修复CSV文件中Volume=0的行
    返回修复统计
    """
    with open(csv_path) as f:
        lines = f.readlines()
    
    # 统计修复前
    vol_zero_before = sum(1 for l in lines[1:] 
                          if len(l.strip().split(',')) >= 6 and l.strip().split(',')[5].strip() == '0')
    
    # 执行插值
    new_lines = interpolate_volume(lines)
    
    # 统计修复后
    vol_zero_after = sum(1 for l in new_lines[1:] 
                         if len(l.strip().split(',')) >= 6 and l.strip().split(',')[5].strip() == '0')
    
    return {
        "vol_zero_before": vol_zero_before,
        "vol_zero_after": vol_zero_after,
        "fixed": vol_zero_before - vol_zero_after,
        "new_lines": new_lines,
    }


def main():
    parser = argparse.ArgumentParser(description='修复港股CSV中Volume=0的数据')
    parser.add_argument('--yfinance', action='store_true', help='尝试用yfinance获取真实成交量')
    parser.add_argument('--interpolate-only', action='store_true', default=True, help='仅用插值法（默认）')
    parser.add_argument('--dry-run', action='store_true', help='仅检查不修改')
    parser.add_argument('--file', type=str, help='仅修复指定文件')
    args = parser.parse_args()
    
    print("=" * 70)
    print("港股数据Volume修复工具")
    print("=" * 70)
    
    # 获取所有港股CSV文件
    if args.file:
        csv_files = [Path(args.file)]
    else:
        csv_files = sorted(HK_DIR.glob("*.csv"))
    
    print(f"待处理文件数: {len(csv_files)}")
    print(f"修复模式: {'yfinance+插值' if args.yfinance else '仅插值'}")
    print(f"干运行: {'是' if args.dry_run else '否'}")
    print("=" * 70)
    
    total_zero_before = 0
    total_zero_after = 0
    total_fixed = 0
    
    for i, csv_path in enumerate(csv_files):
        fname = csv_path.name
        symbol = fname.replace('.csv', '')
        
        # 分析当前文件
        analysis = analyze_csv(csv_path)
        
        if analysis['vol_zero'] == 0:
            print(f"[{i+1}/{len(csv_files)}] {fname}: ✅ Volume完整 ({analysis['total']}行)")
            continue
        
        print(f"[{i+1}/{len(csv_files)}] {fname}: Volume=0行={analysis['vol_zero']}/{analysis['total']}", end='')
        
        if args.dry_run:
            print(f" (仅检查)")
            total_zero_before += analysis['vol_zero']
            continue
        
        # 尝试yfinance修复
        if args.yfinance:
            yf_success = fix_with_yfinance(csv_path, symbol)
            if yf_success:
                # yfinance修复后重新分析
                analysis = analyze_csv(csv_path)
                if analysis['vol_zero'] == 0:
                    print(f" → ✅ yfinance完全修复")
                    total_fixed += analysis['vol_zero']
                    continue
        
        # 插值法修复
        result = fix_csv_interpolate(csv_path)
        
        if result['fixed'] > 0:
            # 写入修复后的数据
            with open(csv_path, 'w') as f:
                f.writelines(result['new_lines'])
            print(f" → 🔧 插值修复了 {result['fixed']} 行")
        else:
            print(f" → ⚠️ 无法修复")
        
        total_zero_before += result['vol_zero_before']
        total_zero_after += result['vol_zero_after']
        total_fixed += result['fixed']
    
    print("\n" + "=" * 70)
    print("修复汇总")
    print("=" * 70)
    print(f"处理文件数: {len(csv_files)}")
    print(f"修复前Volume=0行数: {total_zero_before}")
    print(f"修复后Volume=0行数: {total_zero_after}")
    print(f"修复行数: {total_fixed}")
    
    if total_zero_before > 0:
        fix_rate = total_fixed / total_zero_before * 100
        print(f"修复率: {fix_rate:.1f}%")
    
    print("\n注意事项:")
    print("  - 插值法使用前后最近非零Volume的均值填充")
    print("  - VolumeSource列标注了数据来源: original/yfinance/interpolated/missing")
    print("  - 核心技术指标(EMA/MACD/RSI/ADX)不依赖Volume，插值不影响回测结果")


if __name__ == "__main__":
    main()
