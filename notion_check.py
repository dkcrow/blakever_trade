import requests

token = 'ntn_u98332462584JnOEUjEWHWwgrVL7bR3UvMCOnCnH6N8bQ6'
headers = {
    'Authorization': f'Bearer {token}',
    'Notion-Version': '2025-09-03'
}

# 获取页面子内容
page_id = 'ff1ccc85-48ad-4e45-a90e-3fba57ccd50d'
resp = requests.get(f'https://api.notion.com/v1/blocks/{page_id}/children', headers=headers)
data = resp.json()

for block in data.get('results', []):
    btype = block.get('type')
    bid = block.get('id')
    if btype == 'child_database':
        print(f'child_database ID: {bid}')
    elif btype == 'child_page':
        print(f'child_page ID: {bid}')
