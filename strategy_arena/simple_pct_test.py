"""
最简单的测试：只发送 588080 和 159967 的涨跌幅
"""
import smtplib
from email.mime.text import MIMEText
import urllib.request

def get_pct(code):
    """获取涨跌幅"""
    prefix = 'sh' if code.startswith('5') or code.startswith('1') else 'sz'
    url = f'http://qt.gtimg.cn/q={prefix}{code}'
    with urllib.request.urlopen(url, timeout=3) as r:
        data = r.read().decode('gbk')
        parts = data.split('~')
        price = float(parts[3])
        yc = float(parts[5])
        pct = ((price - yc) / yc) * 100
        return price, yc, pct, parts[1]  # parts[1] = 名称

# 测试 2 只 ETF
etfs = ['588080', '159967']
rows = ""
for code in etfs:
    try:
        price, yc, pct, name = get_pct(code)
        color = 'green' if pct >= 0 else 'red'
        sign = '+' if pct >= 0 else ''
        rows += f"""
        <tr>
            <td>{code} {name}</td>
            <td>{price:.3f}</td>
            <td>{yc:.3f}</td>
            <td style="color:{color};font-weight:700">{sign}{pct:.2f}%</td>
        </tr>"""
    except Exception as e:
        rows += f'<tr><td colspan="4">Error: {e}</td></tr>'

html = f"""
<html>
<body>
    <h1>ETF 涨跌幅测试（2只）</h1>
    <table border="1" cellpadding="5">
        <tr><th>ETF</th><th>实时价</th><th>昨收价</th><th>涨跌幅</th></tr>
        {rows}
    </table>
    <p>计算方式：(实时价 - 昨收价) / 昨收价 * 100</p>
    <p>测试时间：2026-05-26 13:30</p>
</body>
</html>
"""

msg = MIMEText(html, 'html', 'utf-8')
msg['Subject'] = '[OpenClaw] ETF涨跌幅测试-2只'
msg['From'] = '848786642@qq.com'
msg['To'] = '848786642@qq.com'

try:
    with smtplib.SMTP('smtp.qq.com', 587) as server:
        server.starttls()
        server.login('848786642@qq.com', 'ljbtvacrctjobfed')
        server.send_message(msg)
    print("OK: 测试邮件已发送")
    print(f"  588080: price={price:.3f}, yc={yc:.3f}, pct={pct:.2f}%")
except Exception as e:
    print(f"ERROR: {e}")
