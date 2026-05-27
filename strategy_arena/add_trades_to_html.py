"""
修改 generate_html() 函数，添加最近20次交易记录
"""
import re

with open('拉普拉斯_盘中监控_v15_干净版.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 </table> 和 </body> 之间的位置，插入交易记录
old = '''</table>
<p class="footer">⚠️ 本邮件为自动化监控，不构成投资建议。涨跌幅 = (实时价 - 昨收价) / 昨收价 × 100</p>
</body>'''

new = '''</table>

<h2 style="font-size:14px;color:#111827;margin:20px 0 10px 0">📋 最近20次交易记录</h2>
<table>
<tr><th>时间</th><th>ETF</th><th>操作</th><th>价格</th><th>原因</th><th>盈亏</th></tr>
{trades_html}
</table>

<p class="footer">⚠️ 本邮件为自动化监控，不构成投资建议。涨跌幅 = (实时价 - 昨收价) / 昨收价 × 100</p>
</body>'''

if old in content:
    content = content.replace(old, new)
    
    # 在函数开头添加读取交易记录的逻辑
    func_old = '''def generate_html(rankings, rank_changes):
    """生成HTML邮件"""
    rows_html = ""
    
    # DEBUG: 检查 159509'''
    
    func_new = '''def generate_html(rankings, rank_changes):
    """生成HTML邮件"""
    rows_html = ""
    trades_html = ""
    
    # 读取交易记录
    trades_file = r'C:\Users\blakehao\.qclaw\workspace\laplace_trades.json'
    if os.path.exists(trades_file):
        try:
            with open(trades_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                trades = data.get('trades', []) if isinstance(data, dict) else data
                # 取最近20条
                recent_trades = trades[-20:] if len(trades) >= 20 else trades
                
                for t in recent_trades:
                    action = t.get('action', '')
                    etf = t.get('etf', t.get('code', ''))
                    price = t.get('price', 0)
                    reason = t.get('reason', '')
                    pnl = t.get('pnl_pct', t.get('pnl', 0))
                    
                    # 颜色
                    action_color = '#dc2626' if action == 'SELL' else '#059669'
                    pnl_color = '#059669' if pnl > 0 else '#dc2626' if pnl < 0 else '#6b7280'
                    pnl_sign = '+' if pnl > 0 else ''
                    
                    trades_html += f'''    <tr>
        <td style="padding:4px 6px;color:#6b7280;font-size:11px">{t.get('date', '')}</td>
        <td style="padding:4px 6px;font-weight:600;color:#111827">{etf}</td>
        <td style="padding:4px 6px;color:{action_color}">{action}</td>
        <td style="padding:4px 6px;color:#111827">{price:.3f}</td>
        <td style="padding:4px 6px;color:#6b7280;font-size:11px">{reason}</td>
        <td style="padding:4px 6px;color:{pnl_color}">{pnl_sign}{pnl:.2f}%</td>
    </tr>'''
        except Exception as e:
            print(f'  [WARN] 读取交易记录失败: {e}')
    
    # DEBUG: 检查 159509'''
    
    if func_old in content:
        content = content.replace(func_old, func_new)
        print('OK: 添加了交易记录逻辑')
        
        # 还要在 trades_html 变量处插入
        content = content.replace('{rows_html}\n</table>', '{rows_html}\n{trades_html}\n</table>')
        print('OK: 添加了 trades_html 变量')
        
        with open('拉普拉斯_盘中监控_v15_干净版.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print('OK: 文件已保存')
    else:
        print('ERROR: 找不到函数开头')
else:
    print('ERROR: 找不到插入位置')
