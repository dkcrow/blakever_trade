#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
七星策略大对比：4个策略统一回测
1. 七星高照6+1 (A股ETF)
2. 七星三马美股V7
3. 七星拉普拉斯高斯
4. 七星1.7.2 (如果存在)
"""

import subprocess
import sys
import os

def run_backtest(script_name, description):
    """运行单个回测脚本并提取结果"""
    print("\n" + "="*80)
    print(f"正在回测: {description}")
    print(f"脚本: {script_name}")
    print("="*80)
    
    output_file = f"backtest_{script_name.replace('.py', '')}.txt"
    cmd = f'cd "C:\\Users\\blakehao\\.qclaw\\workspace\\strategy_arena" && python "{script_name}" > {output_file} 2>&1'
    
    try:
        result = subprocess.run(cmd, shell=True, timeout=300, cwd=r"C:\Users\blakehao\.qclaw\workspace\strategy_arena")
        if result.returncode != 0:
            print(f"❌ 执行失败，返回码: {result.returncode}")
            return None
        
        # 读取结果
        with open(os.path.join(r"C:\Users\blakehao\.qclaw\workspace\strategy_arena", output_file), 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 提取关键指标
        results = {}
        for line in content.split('\n'):
            if '年化收益率' in line or '总收益率' in line or '夏普' in line or '胜率' in line or '盈亏比' in line or '最大回撤' in line or '总交易' in line:
                print(f"  {line.strip()}")
        
        return output_file
        
    except subprocess.TimeoutExpired:
        print(f"❌ 超时（5分钟）")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        return None

if __name__ == '__main__':
    print("\n" + "🔥"*40)
    print("七星策略大对比 - 4个策略统一回测")
    print("🔥"*40)
    
    strategies = [
        ('七星高照6+1.py', '七星高照6+1 (A股ETF)'),
        ('qixing_sanma_us_v7.py', '七星三马美股V7'),
        ('七星拉普拉斯高斯_backtrader.py', '七星拉普拉斯高斯'),
    ]
    
    results = {}
    for script, desc in strategies:
        output = run_backtest(script, desc)
        if output:
            results[desc] = output
    
    print("\n" + "="*80)
    print("所有回测完成！")
    print("="*80)
    print("\n结果文件:")
    for desc, output in results.items():
        print(f"  {desc}: {output}")
