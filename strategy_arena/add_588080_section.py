"""
在 generate_html 的表格后面添加"特别关注：588080"区块
"""
file_path = r'C:\Users\blakehao\.qclaw\workspace\strategy_arena\拉普拉斯_盘中监控_最终版.py'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 在 "</table>" 后面添加特别关注区块
old = """    html += """  </table>
    <div class="section">
      <h2>📋 交易记录（最近20次）</h2>"""

# 新代码：添加特别关注区块
new = """    html += """  </table>
    
    <!-- 特别关注：588080 科创50ETF -->
    <div class="section">
      <h2>🎯 特别关注：588080 科创50ETF易方达</h2>
      <table>
        <tr><th>ETF</th><th>实时价</th><th>昨收价</th><th>涨跌幅</th><th>排名</th></tr>"""
    
    # 找到 588080 的信息
    r_588080 = next((r for r in results if r['code'] == '588080'), None)
    if r_588080:
        price = r_588080['realtime_price']
        yc = r_588080['yesterday_close']
        pct = ((price - yc) / yc) * 100
        pct_color = 'green' if pct >= 0 else 'red'
        pct_sign = '+' if pct >= 0 else ''
        rank = r_588080['rank']
        html += f'''
        <tr>
          <td><span style="color:#1d4ed8;font-weight:600;">588080</span> 科创50ETF易方达</td>
          <td style="font-weight:700;font-size:15px">{price:.3f}</td>
          <td>{yc:.3f}</td>
          <td style="color:{pct_color};font-weight:700">{pct_sign}{pct:.2f}%</td>
          <td>第{rank}名</td>
        </tr>'''
    
    html += """
      </table>
    </div>
    
    <div class="section">
      <h2>📋 交易记录（最近20次）</h2>"""

if old in content:
    content = content.replace(old, new)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Added 588080 special section to HTML!")
    print("  Now shows 588080's realtime price, yc, and pct_change")
else:
    print("ERROR: Could not find the target line")
