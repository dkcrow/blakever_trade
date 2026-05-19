import requests, json
from datetime import datetime, timedelta

token = 'ntn_u98332462584JnOEUjEWHWwgrVL7bR3UvMCOnCnH6N8bQ6'
headers = {
    'Authorization': f'Bearer {token}',
    'Notion-Version': '2025-09-03',
    'Content-Type': 'application/json'
}

# 查询日记列表数据库
db_id = 'dc7ce9aa-2d18-447f-bc2d-4495076e0986'
query = {
    'page_size': 100,
    'sorts': [{'timestamp': 'created_time', 'direction': 'descending'}]
}

resp = requests.post(f'https://api.notion.com/v1/databases/{db_id}/query', headers=headers, json=query)
print(f'状态码: {resp.status_code}')
if resp.status_code != 200:
    print(f'错误: {resp.text}')
    exit(1)

data = resp.json()
print(f'记录数: {len(data.get("results", []))}')

for r in data.get('results', [])[:15]:
    props = r.get('properties', {})
    title = ''
    if 'Content' in props and props['Content'].get('title'):
        title = props['Content']['title'][0].get('plain_text', '')
    date = ''
    if 'Date' in props and props['Date'].get('date'):
        date = props['Date']['date'].get('start', '')
    print(f'- [{date}] {title}')
