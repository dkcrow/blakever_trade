import json

path = r'C:\Users\blakehao\.qclaw\cron\jobs.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for job in data['jobs']:
    if job['id'] == '2cfee8f3-c17c-4cc0-8e1d-2076393f1bed':
        job['enabled'] = False
        print('Task disabled:', job['name'])
        break

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('Done')
