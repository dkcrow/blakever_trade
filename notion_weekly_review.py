# -*- coding: utf-8 -*-
import requests
import sys
import io
from datetime import datetime, timedelta

# 强制UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

token = 'ntn_u98332462584JnOEUjEWHWwgrVL7bR3UvMCOnCnH6N8bQ6'
headers = {
    'Authorization': f'Bearer {token}',
    'Notion-Version': '2025-09-03'
}

print('=== Notion 每周复盘 ===')
print('扫描时间: 2026-05-18 23:02')
print('')

# 获取最近编辑的页面
search_resp = requests.post('https://api.notion.com/v1/search', headers=headers, json={
    'page_size': 100,
    'sort': {'timestamp': 'last_edited_time', 'direction': 'descending'}
})
results = search_resp.json().get('results', [])

# 筛选最近7天的
week_ago = datetime.now() - timedelta(days=7)
recent = []
for item in results:
    edited = item.get('last_edited_time', '')
    if edited:
        try:
            edit_time = datetime.fromisoformat(edited.replace('Z', '+00:00'))
            if edit_time >= week_ago:
                recent.append(item)
        except:
            pass

print(f'本周新增/更新: {len(recent)} 个页面')
print('')

for item in recent[:20]:
    title = ''
    props = item.get('properties', {})
    if 'title' in props and props['title'].get('title'):
        title = props['title']['title'][0].get('plain_text', '')
    elif 'Name' in props and props['Name'].get('title'):
        title = props['Name']['title'][0].get('plain_text', '')
    elif 'Content' in props and props['Content'].get('title'):
        title = props['Content']['title'][0].get('plain_text', '')

    obj_type = item.get('object', 'unknown')
    edit_time = item.get('last_edited_time', '')[:10]

    if title:
        print(f'- [{edit_time}] [{obj_type}] {title}')

print('')
print('=== 知识扩展建议 ===')
print('基于本周笔记内容，建议关注以下方向：')
print('1. 持续跟踪已记录的学习主题')
print('2. 补充相关领域的深度内容')
print('3. 整理碎片化笔记为系统化知识')
