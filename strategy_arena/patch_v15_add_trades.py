"""
修改 v15，添加交易记录功能
"""
import re

# 读取 v15
with open('拉普拉斯_盘中监控_v15_干净版.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. 在 generate_html 函数开头添加 trades_html 初始化和读取逻辑
old1 = '''def generate_html(rankings, rank_changes):
    """生成HTML邮件"""
    rows_html = ""
    '''
new1 = '''def generate_html(rankings, rank_changes):
    """生成HTML邮件"""
    rows_html = ""
    trades_html = ""
    
    # 读取交易记录
    import json
    trades_file = r'C:\\Users\\blakehao\\.qclaw\\workspace\\laplace_trades.json'
    try:
        with open(trades_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            trades = data
        elif isinstance(data, dict):
            trades = data.get('trades', [])
        else:
            trades = []
        recent = trades[-20:] if len(trades) >= 20 else trades
        for t in recent:
            act = t.get('action', '')
            etf = t.get('etf', t.get('code', ''))
            price = t.get('price', 0)
            reason = t.get('reason', '')
            pnl = t.get('pnl_pct', t.get('pnl', 0))
            if pnl is None:
                pnl = 0
            ac = '#dc2626' if act == 'SELL' else '#059669'
            pc = '#059669' if pnl > 0 else '#dc2626' if pnl < 0 else '#6b7280'
            ps = '+' if pnl > 0 else ''
            trades_html += '<tr><td>' + str(t.get('date', '')) + '</td>'
            trades_html += '<td>' + etf + '</td>'
            trades_html += '<td style="color:' + ac + '">' + act + '</td>'
            trades_html += '<td>' + format(price, '.3f') + '</td>'
            trades_html += '<td>' + reason + '</td>'
            trades_html += '<td style="color:' + pc + '">' + ps + format(pnl, '.2f') + '%</td></tr>'
    except Exception as e:
        print('  [WARN] 交易记录:', e)
    '''
if old1 in content:
    content = content.replace(old1, new1)
    print('OK: 添加了交易记录逻辑')
else:
    print('ERROR: 找不到位置1')

# 2. 在 </table> 后添加交易记录 HTML
old2 = '''</table>

<p class="footer">'''
new2 = '''</table>

<h2 style="font-size:14px;color:#111827;margin:20px 0 10px 0">📋 最近20次交易记录</h2>
<table>
<tr><th>时间</th><th>ETF</th><th>操作</th><th>价格</th><th>原因</th><th>盈亏</th></tr>
{trades_html}
</table>

<p class="footer">'''
if old2 in content:
    content = content.replace(old2, new2)
    print('OK: 添加了交易记录 HTML')
else:
    print('ERROR: 找不到位置2')

# 保存为 v18
with open('拉普拉斯_盘中监控_v18_最终版.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('OK: v18 已保存')
