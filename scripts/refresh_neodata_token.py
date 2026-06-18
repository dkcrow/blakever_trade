#!/usr/bin/env python3
"""刷新 neodata token 到标准位置。
用法: python refresh_neodata_token.py <token>
"""
import json, sys, time
from pathlib import Path

TOKEN_FILE = Path.home() / '.workbuddy' / '.neodata_token'

def save_token(token_str: str):
    data = {'token': token_str, 'saved_at': time.time()}
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data))
    # 同步写入 skill 目录（兼容旧路径）
    skill_file = Path.home() / '.workbuddy' / 'plugins' / 'marketplaces' / 'cb_teams_marketplace' / 'plugins' / 'finance-data' / 'skills' / 'neodata-financial-search' / 'scripts' / '.neodata_token'
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(json.dumps(data))
    print(f'[OK] neodata token 已保存到 {TOKEN_FILE}, 有效期至 {time.strftime("%H:%M:%S", time.localtime(time.time() + 43200))}')

if __name__ == '__main__':
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print('用法: python refresh_neodata_token.py <token>', file=sys.stderr)
        sys.exit(1)
    save_token(sys.argv[1].strip())
