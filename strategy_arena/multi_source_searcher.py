#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多源策略搜索器 v3 — 经过实测验证的可靠版本
==============================================

基于2026-04-23实测验证的可用渠道:

  ✅ 完全可用:
    1. GitHub 仓库搜索(search/repositories API) + HTML目录爬取 + raw下载
    2. GitHub Topics (quantitative-finance, algorithmic-trading 等)
    3. awesome-quant 资源列表 (wilsonfreitas/awesome-quant)
    4. QuantConnect 标签API (v2/community/tag/read)
    5. QuantInsti RSS + 文章代码提取
    6. Google搜索 → GitHub链接提取

  ⚠️ 需要Playwright(JS渲染):
    7. 聚宽帖子列表 + 代码提取
    8. BigQuant社区搜索
    9. 雪球搜索(需要先登录获取cookies)

  ❌ 当前环境不可用:
    - TradingView (SSL错误，容器环境无法连接)
    - QuantConnect论坛搜索(超时)

关键设计:
  - GitHub是主力搜索源(搜索→爬目录→raw下载，不占core API配额)
  - Playwright处理JS渲染网站(聚宽/BigQuant/雪球)
  - 每个源独立容错，失败不影响其他源
  - 所有结果统一进入初筛→去重→可移植性评分
"""

import json
import os
import re
import time
import hashlib
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ================================================================
# HTTP请求工具
# ================================================================
_SESSION = None

def _get_session():
    global _SESSION
    if _SESSION is None:
        import requests
        _SESSION = requests.Session()
        _SESSION.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
    return _SESSION


def _safe_get(url, timeout=15, headers=None) -> Optional[object]:
    import requests
    session = _get_session()
    try:
        return session.get(url, timeout=timeout, headers=headers)
    except requests.exceptions.SSLError:
        try:
            import urllib3
            urllib3.disable_warnings()
            return session.get(url, timeout=timeout, headers=headers, verify=False)
        except Exception as e:
            logger.debug(f"SSL skip failed: {url} - {e}")
            return None
    except Exception as e:
        logger.debug(f"GET failed: {url} - {e}")
        return None


# ================================================================
# GitHub限流管理
# ================================================================
GITHUB_COOLDOWN_FILE = '/tmp/ms_github_cooldown.json'

def _is_github_cooling() -> bool:
    if not os.path.exists(GITHUB_COOLDOWN_FILE):
        return False
    try:
        with open(GITHUB_COOLDOWN_FILE) as f:
            data = json.load(f)
        return time.time() < data.get('reset_time', 0)
    except:
        return False

def _set_github_cooldown(until: float):
    try:
        with open(GITHUB_COOLDOWN_FILE, 'w') as f:
            json.dump({'reset_time': until}, f)
    except:
        pass


# ================================================================
# 来源1: GitHub仓库搜索 + git clone下载（最可靠方案）
# ================================================================
_GIT_CLONE_DIR = '/tmp/ms_git_repos'

def search_github(queries: List[str], max_per_query: int = 5) -> List[dict]:
    """
    GitHub仓库搜索（主力搜索源）
    流程: search/repositories(10次/分钟) → git clone --depth 1 → 扫描策略文件
    git clone不需要API配额，是最可靠的代码获取方式
    """
    if _is_github_cooling():
        print("    ⏳ GitHub搜索冷却中")
        return []

    all_results = []
    
    for query in queries[:5]:
        try:
            url = f'https://api.github.com/search/repositories?q={quote(query)}&sort=stars&per_page=3'
            r = _safe_get(url, timeout=15, headers={'Accept': 'application/vnd.github.v3+json'})
            
            if not r:
                continue
            if r.status_code in (403, 429):
                reset = int(r.headers.get('X-RateLimit-Reset', time.time() + 60))
                _set_github_cooldown(reset)
                print(f"    ⏳ GitHub限流，冷却至{datetime.fromtimestamp(reset).strftime('%H:%M')}")
                break
            if r.status_code != 200:
                continue

            items = r.json().get('items', [])
            
            for item in items:
                repo = item['full_name']
                stars = item.get('stargazers_count', 0)
                desc = (item.get('description', '') or '')[:100]
                updated = item.get('updated_at', '')[:10]

                # git clone仓库并扫描策略文件
                strategy_files = _clone_and_scan_repo(repo)
                
                for sfile in strategy_files:
                    all_results.append({
                        'name': sfile['name'],
                        'description': desc,
                        'source': 'github',
                        'source_link': f'https://github.com/{repo}/blob/main/{sfile["relpath"]}',
                        'code': sfile['code'],
                        'stars': stars,
                        'update_time': updated,
                        'is_classic': stars > 100,
                    })
                    print(f"      ✅ GitHub: {repo}/{sfile['relpath']} ({len(sfile['code'])}B ★{stars})")

                time.sleep(1)  # 仓库间隔

            time.sleep(2)  # 搜索间隔

        except Exception as e:
            logger.warning(f"GitHub搜索异常: {e}")
            continue

    return all_results


def _clone_and_scan_repo(repo: str, max_strategies: int = 3) -> List[dict]:
    """
    git clone --depth 1 仓库，扫描其中的策略代码文件
    这是最可靠的方案：不需要GitHub API配额，能获取到所有文件（包括子目录）
    """
    import subprocess
    import shutil
    
    tmp_dir = os.path.join(_GIT_CLONE_DIR, repo.replace('/', '_'))
    
    # 清理旧目录
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    
    # git clone --depth 1（浅克隆，只获取最新提交，速度快）
    try:
        result = subprocess.run(
            ['git', 'clone', '--depth', '1', f'https://github.com/{repo}.git', tmp_dir],
            capture_output=True, timeout=60
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"git clone failed: {repo} - {e}")
        return []
    
    # 扫描.py和.ipynb文件
    strategy_files = []
    skip_dirs = {'.git', '__pycache__', 'node_modules', '.tox', 'venv', 'env', 'dist', 'build', '.eggs', 'migrations', 'api', 'docs', 'tests', 'test', 'scripts', 'utils', 'tools', 'config', 'conf'}
    skip_prefixes = ('test_', 'setup.', '__init__', 'conftest', 'manage.', 'tests/')
    
    for root, dirs, files in os.walk(tmp_dir):
        # 跳过无关目录
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for fname in files:
            if fname.endswith('.py'):
                relpath = os.path.relpath(os.path.join(root, fname), tmp_dir)
                
                # 跳过非策略文件
                if any(relpath.startswith(p) for p in skip_prefixes):
                    continue
                if fname.startswith(('test_', 'setup.', '__init__', 'conftest')):
                    continue
                
                fpath = os.path.join(root, fname)
                size = os.path.getsize(fpath)
                
                if size < 50 or size > 500000:  # 跳过太小或太大的文件
                    continue
                
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()
                except:
                    continue
                
                if _is_valid_strategy_code(code):
                    name = fname.replace('.py', '').replace('_', ' ').title()
                    strategy_files.append({
                        'name': name,
                        'relpath': relpath,
                        'code': code,
                    })
                    
                    if len(strategy_files) >= max_strategies:
                        break
            
            elif fname.endswith('.ipynb'):
                relpath = os.path.relpath(os.path.join(root, fname), tmp_dir)
                if 'checkpoint' in relpath.lower():
                    continue
                
                fpath = os.path.join(root, fname)
                size = os.path.getsize(fpath)
                
                if size < 100 or size > 2000000:
                    continue
                
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        nb_data = json.load(f)
                    code_cells = [c for c in nb_data.get('cells', []) if c.get('cell_type') == 'code']
                    if code_cells:
                        all_code = '\n\n'.join([''.join(c.get('source', [])) for c in code_cells])
                        if len(all_code) > 100 and _is_valid_strategy_code(all_code):
                            name = fname.replace('.ipynb', '').replace('_', ' ').title()
                            strategy_files.append({
                                'name': name,
                                'relpath': relpath,
                                'code': all_code,
                            })
                            
                            if len(strategy_files) >= max_strategies:
                                break
                except:
                    continue
        
        if len(strategy_files) >= max_strategies:
            break
    
    # 清理clone的仓库
    shutil.rmtree(tmp_dir, ignore_errors=True)
    
    return strategy_files


# ================================================================
# 来源2: GitHub Topics 探索
# ================================================================
TOPIC_PAGES = [
    'https://github.com/topics/quantitative-finance',
    'https://github.com/topics/algorithmic-trading',
    'https://github.com/topics/trading-bot',
    'https://github.com/topics/backtesting',
]

def search_github_topics(max_repos: int = 10) -> List[dict]:
    """
    从GitHub Topics发现策略仓库
    Topics页面是React渲染的，HTML中没有仓库链接
    改用GitHub搜索API的topic:限定符来发现（不额外消耗配额，复用搜索配额）
    """
    print("    🌐 探索 GitHub Topics（通过搜索API）...")
    all_results = []
    seen_repos = set()
    
    # 用topic:限定符搜索相关仓库
    topic_queries = [
        'topic:backtesting language:python momentum',
        'topic:algorithmic-trading language:python strategy',
        'topic:quantitative-finance language:python backtest',
        'topic:trading-bot language:python backtest',
    ]
    
    for query in topic_queries:
        if len(all_results) >= max_repos:
            break
            
        try:
            url = f'https://api.github.com/search/repositories?q={quote(query)}&sort=stars&per_page=3'
            r = _safe_get(url, timeout=15, headers={'Accept': 'application/vnd.github.v3+json'})
            if not r or r.status_code != 200:
                continue
            
            for item in r.json().get('items', []):
                repo = item['full_name']
                if repo in seen_repos:
                    continue
                seen_repos.add(repo)
                
                stars = item.get('stargazers_count', 0)
                desc = (item.get('description', '') or '')[:100]
                
                # git clone并扫描
                strategy_files = _clone_and_scan_repo(repo, max_strategies=2)
                
                for sfile in strategy_files:
                    all_results.append({
                        'name': sfile['name'],
                        'description': desc,
                        'source': 'github_topic',
                        'source_link': f'https://github.com/{repo}',
                        'code': sfile['code'],
                        'stars': stars,
                        'update_time': datetime.now().strftime('%Y-%m-%d'),
                        'is_classic': stars > 100,
                    })
                    print(f"      ✅ Topic: {repo}/{sfile['relpath']} ({len(sfile['code'])}B ★{stars})")
                
                time.sleep(1)
            
            time.sleep(2)  # 搜索间隔
            
        except Exception as e:
            logger.warning(f"GitHub Topics异常: {e}")
            continue
    
    return all_results[:max_repos]


# ================================================================
# 来源3: awesome-quant 资源列表
# ================================================================
AWESOME_QUANT_URL = 'https://raw.githubusercontent.com/wilsonfreitas/awesome-quant/master/README.md'

def search_awesome_quant(max_repos: int = 10) -> List[dict]:
    """
    从awesome-quant资源列表发现高质量策略仓库
    awesome-quant是量化领域最权威的资源列表，包含几百个高质量仓库
    使用git clone下载代码（不需要API配额）
    """
    print("    🌐 搜索 awesome-quant 资源列表...")
    all_results = []
    
    try:
        r = _safe_get(AWESOME_QUANT_URL, timeout=15)
        if not r or r.status_code != 200:
            return []
        
        readme = r.text
        
        # 提取带描述的GitHub仓库链接（awesome-quant格式: - [name](url) - description）
        # 正则需要匹配完整的owner/repo路径
        link_desc_pairs = re.findall(
            r'-\s*\[([^\]]*)\]\(https://github\.com/([^/\s)]+/[^/\s)]+)(?:/[^\s)]*)?\)\s*[-–—:]\s*(.+?)(?:\n|$)', 
            readme
        )
        
        # 筛选策略相关的仓库
        strategy_keywords = ['momentum', 'backtest', 'strategy', 'trading', 'rotation', 
                           'signal', 'portfolio', 'factor', 'mean.reversion', 'trend',
                           'dual', 'rotation', 'rebalance']
        
        strategy_repos = []
        for title, repo, desc in link_desc_pairs:
            combined = f"{title} {desc}".lower()
            if any(kw in combined for kw in strategy_keywords):
                # 宽松筛选：标题或描述中包含Python，或者不排除（让git clone来判断）
                has_python = 'python' in desc.lower() or 'python' in title.lower() or '`Python`' in desc
                # 如果明确是非Python语言则跳过
                non_python_langs = ['`R`', '`C++`', '`Java`', '`Go`', '`Rust`', '`Julia`', '`MATLAB`']
                is_non_python = any(lang in desc for lang in non_python_langs)
                
                if is_non_python and not has_python:
                    continue
                    
                strategy_repos.append({
                    'repo': repo,
                    'title': title,
                    'desc': desc.strip()[:100],
                    'relevance': sum(1 for kw in strategy_keywords if kw in combined)
                })
        
        # 按相关性排序
        strategy_repos.sort(key=lambda x: x['relevance'], reverse=True)
        
        # git clone并扫描策略代码
        for entry in strategy_repos[:max_repos]:
            repo = entry['repo']
            
            strategy_files = _clone_and_scan_repo(repo, max_strategies=2)
            
            for sfile in strategy_files:
                # 通过git clone获取不需要API配额
                all_results.append({
                    'name': entry['title'] or sfile['name'],
                    'description': entry['desc'],
                    'source': 'awesome_quant',
                    'source_link': f'https://github.com/{repo}',
                    'code': sfile['code'],
                    'stars': 0,  # 不再调用API获取stars
                    'update_time': datetime.now().strftime('%Y-%m-%d'),
                    'is_classic': True,  # awesome-quant列表中的都是高质量仓库
                })
                print(f"      ✅ awesome-quant: {repo}/{sfile['relpath']} ({len(sfile['code'])}B)")
            
            if len(all_results) >= max_repos:
                break
    
    except Exception as e:
        logger.warning(f"awesome-quant搜索异常: {e}")
    
    return all_results


# ================================================================
# 来源4: QuantConnect 社区
# ================================================================
def search_quantconnect(keywords: List[str], max_results: int = 5) -> List[dict]:
    """
    搜索QuantConnect社区策略。
    策略: 用QC标签API发现策略 → 通过Playwright(如果可用)获取策略代码
    备选: 通过QC论坛的已知算法分享链接直接访问
    """
    print("    🌐 搜索 QuantConnect 社区...")
    all_results = []
    
    try:
        # 获取QC标签列表，找策略相关标签
        r = _safe_get('https://www.quantconnect.com/api/v2/community/tag/read/', timeout=15)
        if r and r.status_code == 200:
            tags = r.json().get('tags', [])
            strategy_tags = [t for t in tags if any(kw in t.get('name', '').lower() 
                           for kw in ['momentum', 'strategy', 'backtest', 'equities', 'etf'])]
            print(f"      策略相关标签: {len(strategy_tags)}")
        
        # QC的已知高质量策略分享链接
        # 这些是从QC社区中收集的经典策略
        qc_known_strategies = [
            {
                'name': 'Dual Momentum Strategy (QC)',
                'url': 'https://www.quantconnect.com/terminal/clone?clone=63107e281bf8b92f36c1b01f',
                'description': 'QC社区双动量策略',
            },
            {
                'name': 'Momentum Rotation Strategy (QC)',
                'url': 'https://www.quantconnect.com/terminal/clone?clone=5d8a4d8bf37c4a46f4b1b95e',
                'description': 'QC社区动量轮动策略',
            },
        ]
        
        # 用Playwright尝试获取策略代码
        try:
            import asyncio
            from playwright.async_api import async_playwright
            
            async def _qc_playwright():
                results = []
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True, args=['--ignore-certificate-errors'])
                    page = await browser.new_page()
                    
                    for strat in qc_known_strategies[:2]:
                        try:
                            await page.goto(strat['url'], timeout=30000, wait_until='domcontentloaded')
                            await page.wait_for_timeout(3000)
                            
                            content = await page.content()
                            # 在QC页面中查找Python代码
                            code_blocks = re.findall(r'<code[^>]*>(.*?)</code>', content, re.DOTALL)
                            import html as html_lib
                            for block in code_blocks:
                                clean = html_lib.unescape(re.sub(r'<[^>]+>', '', block))
                                if len(clean) > 100 and ('import' in clean or 'def ' in clean):
                                    results.append({
                                        'name': strat['name'],
                                        'description': strat['description'],
                                        'source': 'quantconnect',
                                        'source_link': strat['url'],
                                        'code': clean,
                                        'update_time': datetime.now().strftime('%Y-%m-%d'),
                                        'is_classic': True,
                                    })
                                    print(f"      ✅ QC: {strat['name']} ({len(clean)}B)")
                                    break
                        except Exception as e:
                            logger.debug(f"QC Playwright error: {e}")
                    
                    await browser.close()
                return results
            
            qc_results = asyncio.run(_qc_playwright())
            all_results.extend(qc_results)
            
        except ImportError:
            print("      ⚠️ Playwright不可用，跳过QC深度搜索")
        except Exception as e:
            logger.debug(f"QC Playwright error: {e}")
        
        # 备选: 从QC论坛已知帖子获取策略描述
        # 如果Playwright获取不到代码，至少记录策略存在
        if not all_results:
            for strat in qc_known_strategies:
                all_results.append({
                    'name': strat['name'],
                    'description': strat['description'],
                    'source': 'quantconnect',
                    'source_link': strat['url'],
                    'code': None,  # 需要人工获取
                    'update_time': datetime.now().strftime('%Y-%m-%d'),
                    'is_classic': True,
                    'needs_manual_review': True,
                })
                print(f"      ⚠️ QC(需人工): {strat['name']}")
    
    except Exception as e:
        logger.warning(f"QuantConnect搜索异常: {e}")
    
    return all_results


# ================================================================
# 来源5: TradingView (当前环境SSL不可用)
# ================================================================
def search_tradingview(keywords: List[str], max_results: int = 3) -> List[dict]:
    """
    搜索TradingView Pine Script策略。
    当前环境SSL连接TradingView失败，使用备用方案:
    通过GitHub上 TradingView 相关仓库间接获取Pine Script策略
    """
    print("    🌐 搜索 TradingView (间接渠道)...")
    all_results = []
    
    # 直接访问TradingView（可能因SSL失败）
    try:
        r = _safe_get('https://www.tradingview.com/scripts/momentum/?sort=most_liked', timeout=10)
        if r and r.status_code == 200:
            # 成功连接，提取脚本链接
            script_links = re.findall(r'href="/script/([^/"]+)/"', r.text)
            print(f"      TradingView直连成功，发现{len(set(script_links))}个脚本")
            # TODO: 实现直连模式的代码提取
    except:
        pass
    
    # 备用方案: 搜索GitHub上TradingView策略转译
    tv_github_queries = [
        'tradingview+pine+script+python+backtest',
        'pine+script+strategy+momentum+python',
    ]
    
    for query in tv_github_queries:
        try:
            url = f'https://api.github.com/search/repositories?q={quote(query)}&sort=stars&per_page=3'
            r = _safe_get(url, timeout=15, headers={'Accept': 'application/vnd.github.v3+json'})
            if not r or r.status_code != 200:
                continue
            
            for item in r.json().get('items', []):
                repo = item['full_name']
                stars = item.get('stargazers_count', 0)
                
                strategy_files = _clone_and_scan_repo(repo, max_strategies=2)
                for sfile in strategy_files:
                    all_results.append({
                        'name': f'TV转译: {sfile["name"]}',
                        'description': f'来自GitHub仓库{repo}的TradingView策略转译',
                        'source': 'tradingview_indirect',
                        'source_link': f'https://github.com/{repo}',
                        'code': sfile['code'],
                        'is_pine_script': False,
                        'stars': stars,
                        'update_time': datetime.now().strftime('%Y-%m-%d'),
                        'is_classic': False,
                    })
                    print(f"      ✅ TV间接: {repo}/{sfile['relpath']} ({len(sfile['code'])}B ★{stars})")
                
                time.sleep(1)
            
            time.sleep(2)
        except Exception as e:
            logger.warning(f"TV间接搜索异常: {e}")
    
    return all_results


# ================================================================
# 来源6: QuantInsti 博客
# ================================================================
def search_quantinsti(keywords: List[str], max_results: int = 3) -> List[dict]:
    """
    搜索QuantInsti博客策略。
    通过RSS获取文章列表 → Playwright提取代码
    """
    print("    🌐 搜索 QuantInsti 博客...")
    all_results = []
    
    try:
        # 从RSS获取策略相关文章
        r = _safe_get('https://blog.quantinsti.com/rss/', timeout=15)
        if not r or r.status_code != 200:
            return []
        
        # 提取文章链接
        articles = re.findall(r'<link>(.*?)</link>', r.text)
        strategy_articles = [a for a in articles if any(kw in a.lower() 
                         for kw in ['momentum', 'strategy', 'trading', 'backtest', 'mean-reversion'])]
        
        # 用Playwright获取文章中的代码
        try:
            import asyncio
            from playwright.async_api import async_playwright
            import html as html_lib
            
            async def _qi_playwright():
                results = []
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True, args=['--ignore-certificate-errors'])
                    page = await browser.new_page()
                    
                    for article_url in strategy_articles[:max_results]:
                        try:
                            await page.goto(article_url, timeout=30000, wait_until='domcontentloaded')
                            await page.wait_for_timeout(3000)
                            
                            content = await page.content()
                            
                            # 提取代码块（多种格式）
                            code_blocks = []
                            # 格式1: <pre><code>
                            pre_code = re.findall(r'<pre[^>]*>\s*<code[^>]*>(.*?)</code>\s*</pre>', content, re.DOTALL)
                            code_blocks.extend(pre_code)
                            # 格式2: <pre> without <code>
                            if not pre_code:
                                pre_only = re.findall(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
                                code_blocks.extend(pre_only)
                            # 格式3: prism.js高亮
                            prism = re.findall(r'<code[^>]*class="[^"]*language-python[^"]*"[^>]*>(.*?)</code>', content, re.DOTALL)
                            code_blocks.extend(prism)
                            
                            for block in code_blocks:
                                clean = html_lib.unescape(re.sub(r'<[^>]+>', '', block))
                                if len(clean) > 100 and _is_valid_strategy_code(clean):
                                    title = article_url.split('/')[-2].replace('-', ' ').title()
                                    results.append({
                                        'name': title,
                                        'description': f'QuantInsti博客策略',
                                        'source': 'quantinsti',
                                        'source_link': article_url,
                                        'code': clean,
                                        'update_time': datetime.now().strftime('%Y-%m-%d'),
                                        'is_classic': False,
                                    })
                                    print(f"      ✅ QuantInsti: {title[:50]} ({len(clean)}B)")
                                    break
                        except:
                            continue
                    
                    await browser.close()
                return results
            
            qi_results = asyncio.run(_qi_playwright())
            all_results.extend(qi_results)
            
        except ImportError:
            print("      ⚠️ Playwright不可用，跳过QuantInsti代码提取")
        except Exception as e:
            logger.debug(f"QuantInsti Playwright error: {e}")
    
    except Exception as e:
        logger.warning(f"QuantInsti搜索异常: {e}")
    
    return all_results


# ================================================================
# 来源7: 聚宽/BigQuant/雪球 (需要Playwright + cookies)
# ================================================================
# ================================================================
# 聚宽（JoinQuant）策略搜索 — 最优先来源
# ================================================================
# 聚宽社区策略的获取方式：
#   1. GitHub上的聚宽策略仓库（最可靠，直接git clone）
#   2. joinquant-skill模板（内置5个经典策略模板）
#   3. 聚宽社区热门帖子（需Playwright，作为补充）

# GitHub上的聚宽策略仓库（按star排序，定期更新）
JOINQUANT_GH_REPOS = [
    'JizhiXiang/Quant-Strategy',          # ★217 - joinquant/rsrs/价值投资/网格交易
    'yeates/StockTimingStrategy',          # ★124 - KDJ/MACD/SVM/海龟/成交量择时
    'stxupengyu/multi-factor-strategy-joinquant',  # ★41 - 多因子策略
    'gaaiyun/joinquant-skill',             # ★6 - 聚宽API知识库+策略模板
]

# joinquant-skill内置的5个经典策略模板（直接嵌入，无需网络）
JOINQUANT_TEMPLATES = {
    'ETF轮动策略': '''# -*- coding: utf-8 -*-
"""
ETF 轮动策略 — 在N个ETF中按近期动量排名，持有最强的TOP_K个
来源: joinquant-skill/templates/03-etf-rotation.py
"""

ETF_POOL = [
    '510300.XSHG',  # 沪深300ETF
    '510500.XSHG',  # 中证500ETF
    '159915.XSHE',  # 创业板ETF
    '518880.XSHG',  # 黄金ETF
    '511010.XSHG',  # 国债ETF
    '513100.XSHG',  # 纳指ETF
]
TOP_K = 2                # 持有最强的几个
LOOKBACK = 20            # 动量回看天数
REBALANCE_WEEKDAY = 1    # 每周几调仓 (1=周一)


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)

    set_order_cost(OrderCost(
        open_tax=0, close_tax=0,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='fund')
    set_slippage(PriceRelatedSlippage(0.00246))

    g.etf_pool = ETF_POOL
    g.top_k = TOP_K
    g.lookback = LOOKBACK

    run_weekly(rebalance, weekday=REBALANCE_WEEKDAY, time='09:31')


def rebalance(context):
    # 计算每个ETF的动量得分
    scores = {}
    for etf in g.etf_pool:
        prices = attribute_history(etf, g.lookback + 1, '1d', ['close'])['close']
        momentum = (prices.iloc[-1] / prices.iloc[0]) - 1
        scores[etf] = momentum

    # 按动量排名
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    targets = [etf for etf, _ in ranked[:g.top_k]]

    # 卖出不在目标中的持仓
    for etf in context.portfolio.positions:
        if etf not in targets and context.portfolio.positions[etf].closeable_amount > 0:
            order_target(etf, 0)

    # 买入目标ETF（等权）
    weight = 1.0 / len(targets)
    for etf in targets:
        order_target_value(etf, context.portfolio.total_value * weight)
''',

    '多因子选股策略': '''# -*- coding: utf-8 -*-
"""
多因子选股策略 — 月度调仓，从指数成分股中按PE/市值/动量多因子打分选股
来源: joinquant-skill/templates/02-multi-factor.py
"""
from jqdata import *
from jqfactor import get_factor_values

INDEX = '000300.XSHG'   # 股票池来源（沪深300）
HOLD_NUM = 10            # 持仓股票数量


def initialize(context):
    set_benchmark(INDEX)
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    run_monthly(rebalance, monthday=1, time='09:31')


def rebalance(context):
    stocks = get_index_stocks(INDEX)
    
    # 因子1: PE（低PE好）
    q_pe = query(valuation.code, valuation.pe_ratio).filter(valuation.code.in_(stocks))
    df_pe = get_fundamentals(q_pe).dropna()
    
    # 因子2: 市值（中市值好）
    q_cap = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(stocks))
    df_cap = get_fundamentals(q_cap).dropna()
    
    # 因子3: 动量（近期涨幅大好）
    q_mom = query(valuation.code).filter(valuation.code.in_(stocks))
    mom_scores = {}
    for code in stocks:
        prices = attribute_history(code, 20, '1d', ['close'])['close']
        mom_scores[code] = (prices.iloc[-1] / prices.iloc[0]) - 1
    
    # 合并打分
    df_pe['pe_rank'] = df_pe['pe_ratio'].rank(ascending=True)
    df_cap['cap_rank'] = df_cap['market_cap'].rank(ascending=False)
    
    combined = df_pe.merge(df_cap, on='code')
    combined['mom'] = combined['code'].map(mom_scores)
    combined['mom_rank'] = combined['mom'].rank(ascending=False)
    combined['total_rank'] = combined['pe_rank'] + combined['cap_rank'] + combined['mom_rank']
    
    # 选排名前N
    selected = combined.nsmallest(HOLD_NUM, 'total_rank')['code'].tolist()
    
    # 调仓
    for stock in context.portfolio.positions:
        if stock not in selected:
            order_target(stock, 0)
    
    weight = 1.0 / HOLD_NUM
    for stock in selected:
        order_target_value(stock, context.portfolio.total_value * weight)
''',

    '截面动量选股策略': '''# -*- coding: utf-8 -*-
"""
截面动量选股策略 — 周度调仓，从全A股中选近期涨幅最大的N只持有
来源: joinquant-skill/templates/04-momentum-stock.py
"""
from jqdata import *

UNIVERSE = '000905.XSHG'  # 股票池来源（中证500）
HOLD_NUM = 20              # 持仓数量
LOOKBACK = 20              # 动量回看天数
MIN_MARKET_CAP = 30        # 最低市值（亿元），过滤壳股


def initialize(context):
    set_benchmark(UNIVERSE)
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    run_weekly(rebalance, weekday=1, time='09:31')


def rebalance(context):
    stocks = get_index_stocks(UNIVERSE)
    
    # 过滤: 剔除ST、停牌、次新
    current_data = get_current_data()
    stocks = [s for s in stocks if not current_data[s].paused and not current_data[s].is_st]
    
    # 过滤市值
    q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(stocks))
    df = get_fundamentals(q).dropna()
    df = df[df['market_cap'] >= MIN_MARKET_CAP]
    stocks = df['code'].tolist()
    
    # 计算动量
    momentum = {}
    for code in stocks:
        prices = attribute_history(code, LOOKBACK + 1, '1d', ['close'])['close']
        momentum[code] = (prices.iloc[-1] / prices.iloc[0]) - 1
    
    # 选动量最强的
    ranked = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
    selected = [s for s, _ in ranked[:HOLD_NUM]]
    
    # 调仓
    for stock in context.portfolio.positions:
        if stock not in selected:
            order_target(stock, 0)
    
    weight = 1.0 / HOLD_NUM
    for stock in selected:
        order_target_value(stock, context.portfolio.total_value * weight)
''',

    '均值回归布林带RSI策略': '''# -*- coding: utf-8 -*-
"""
均值回归策略 — 布林带 + RSI，价格偏离均值时反向操作
来源: joinquant-skill/templates/05-mean-reversion.py
"""
import numpy as np

STOCKS = ['000001.XSHE', '600036.XSHG']   # 交易池
BB_PERIOD = 20        # 布林带周期
BB_WIDTH = 2.0        # 布林带宽度（标准差倍数）
RSI_PERIOD = 14       # RSI 周期
RSI_OVERSOLD = 30     # RSI 超卖阈值（买入信号）
RSI_OVERBOUGHT = 70   # RSI 超买阈值（卖出信号）
MAX_POS_PER_STOCK = 0.4  # 单只股票最大仓位比例


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(
        open_tax=0, close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        close_today_commission=0, min_commission=5,
    ), type='stock')
    set_slippage(PriceRelatedSlippage(0.00246))
    g.stocks = STOCKS
    run_daily(trade, time='09:31')


def compute_rsi(prices, period=14):
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    return 100 - (100 / (1 + rs))


def trade(context):
    for stock in g.stocks:
        prices = attribute_history(stock, BB_PERIOD + 5, '1d', ['close'])['close']
        
        # 布林带
        mid = prices.rolling(BB_PERIOD).mean().iloc[-1]
        std = prices.rolling(BB_PERIOD).std().iloc[-1]
        upper = mid + BB_WIDTH * std
        lower = mid - BB_WIDTH * std
        
        # RSI
        rsi = compute_rsi(prices.values, RSI_PERIOD)
        
        current_price = prices.iloc[-1]
        pos = context.portfolio.positions.get(stock, None)
        has_pos = pos and pos.total_amount > 0
        
        # 买入: 价格触及下轨 + RSI超卖
        if current_price <= lower and rsi <= RSI_OVERSOLD and not has_pos:
            order_value(stock, context.portfolio.available_cash * MAX_POS_PER_STOCK)
        # 卖出: 价格触及上轨 + RSI超买
        elif current_price >= upper and rsi >= RSI_OVERBOUGHT and has_pos:
            order_target(stock, 0)
''',

    'RSRS阻力支撑相对强度策略': '''# -*- coding: utf-8 -*-
"""
RSRS因子策略 — 阻力支撑相对强度，年均18%收益
来源: JizhiXiang/Quant-Strategy/joinquant_rsrs因子_年均18%收益.py
"""
import pandas as pd
import numpy as np
import statsmodels.api as sm

def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    g.security = '000300.XSHG'
    g.buy_beta, g.sell_beta = 0.7, -0.7
    g.is_first, g.beta_list, g.r2_list = True, [], []
    run_daily(market_open, time='open', reference_security='000300.XSHG')

def calculate_rsrs(end_date='', n=18, m=1100):
    if g.is_first:
        df = get_price(g.security, end_date=end_date, count=m+n, frequency='daily', fields=['high','low'])
    else:
        df = get_price(g.security, end_date=end_date, count=n, frequency='daily', fields=['high','low'])
    for i in range(len(df))[(-m if g.is_first else -1):]:
        x = sm.add_constant(df['low'][i-n+1:i+1])
        y = df['high'][i-n+1:i+1]
        model = sm.OLS(y, x).fit()
        beta = model.params[1]
        r2 = model.rsquared
        g.beta_list.append(beta)
        g.r2_list.append(r2)
    section = g.beta_list[-m:]
    mu = np.mean(section)
    sigma = np.std(section)
    z_score = (section[-1] - mu)/sigma
    z_score_right = z_score * beta * r2
    g.is_first = False
    return z_score_right

def market_open(context):
    cash = context.portfolio.available_cash
    z_score_right = calculate_rsrs(context.previous_date)
    if z_score_right > g.buy_beta and cash > 0:
        order_value(g.security, cash)
    elif z_score_right < g.sell_beta and context.portfolio.positions[g.security].closeable_amount > 0:
        order_target(g.security, 0)
''',
}


def search_joinquant(market_type: str = 'cross_regime', max_results: int = 8) -> List[dict]:
    """
    搜索聚宽策略（最高优先级来源）
    
    三层来源:
      1. joinquant-skill内置模板（5个经典策略，无需网络）
      2. GitHub聚宽策略仓库（git clone，最可靠）
      3. 聚宽社区热门帖子（Playwright，作为补充）
    """
    print("    🌐 搜索聚宽（JoinQuant）策略...")
    all_results = []
    
    # ===== 第1层: 内置模板（零延迟，100%可靠） =====
    print("      📋 第1层: joinquant-skill内置模板")
    for name, code in JOINQUANT_TEMPLATES.items():
        if _is_valid_strategy_code(code):
            all_results.append({
                'name': f'聚宽-{name}',
                'description': f'JoinQuant经典策略模板: {name}',
                'source': 'joinquant_template',
                'source_link': 'https://github.com/gaaiyun/joinquant-skill',
                'code': code,
                'stars': 6,  # joinquant-skill仓库星数
                'update_time': datetime.now().strftime('%Y-%m-%d'),
                'is_classic': True,
            })
            print(f"      ✅ 模板: {name} ({len(code)}B)")
    print(f"      📊 内置模板: {len(all_results)} 个")
    
    # ===== 第2层: GitHub聚宽策略仓库（git clone） =====
    print("      📋 第2层: GitHub聚宽策略仓库")
    for repo_spec in JOINQUANT_GH_REPOS:
        try:
            results = _clone_and_scan_repo(repo_spec)
            # 标记来源为joinquant
            for r in results:
                r['source'] = 'joinquant_github'
                r['name'] = f'聚宽-{r.get("name", "未知")}'
                if r.get('description', ''):
                    r['description'] = f'JoinQuant社区策略: {r["description"]}'
                else:
                    r['description'] = 'JoinQuant社区策略（GitHub搬运）'
            all_results.extend(results)
            if results:
                print(f"      ✅ {repo_spec}: {len(results)} 个策略")
        except Exception as e:
            logger.debug(f"聚宽仓库{repo_spec}扫描异常: {e}")
    
    # ===== 第3层: 聚宽社区热门帖子（Playwright） =====
    if len(all_results) < max_results:
        print("      📋 第3层: 聚宽社区帖子（Playwright）")
        try:
            import asyncio
            from playwright.async_api import async_playwright
            import html as html_lib
            
            async def _jq_playwright():
                results = []
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True, args=['--ignore-certificate-errors'])
                    page = await browser.new_page()
                    
                    # 访问聚宽社区帖子列表
                    jq_list_urls = [
                        'https://www.joinquant.com/community/post/list?tag=%E7%AD%96%E7%95%A5&page=1',
                        'https://www.joinquant.com/community/post/list?tag=%E5%9B%9E%E6%B5%8B&page=1',
                    ]
                    
                    visited_posts = set()
                    for list_url in jq_list_urls:
                        try:
                            await page.goto(list_url, timeout=20000, wait_until='domcontentloaded')
                            await page.wait_for_timeout(3000)
                            
                            # 获取帖子链接
                            links = await page.query_selector_all('a[href*="/community/detail/"]')
                            for link in links[:5]:
                                href = await link.get_attribute('href')
                                if href and '/community/detail/' in href:
                                    post_id = re.search(r'detail/(\d+)', href)
                                    if post_id and post_id.group(1) not in visited_posts:
                                        visited_posts.add(post_id.group(1))
                        except Exception as e:
                            logger.debug(f"聚宽列表页异常: {e}")
                    
                    # 逐个访问帖子提取代码
                    for post_id in list(visited_posts)[:max_results]:
                        try:
                            post_url = f'https://www.joinquant.com/community/detail/{post_id}'
                            await page.goto(post_url, timeout=15000, wait_until='domcontentloaded')
                            await page.wait_for_timeout(2000)
                            
                            title = await page.title()
                            title = title.replace(' - JoinQuant', '').strip()
                            
                            content = await page.content()
                            code_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
                            
                            for block in code_blocks:
                                clean = html_lib.unescape(re.sub(r'<[^>]+>', '', block))
                                if len(clean) > 100 and _is_valid_strategy_code(clean):
                                    results.append({
                                        'name': f'聚宽-{title[:40]}',
                                        'description': f'JoinQuant社区帖子: {title[:50]}',
                                        'source': 'joinquant_community',
                                        'source_link': post_url,
                                        'code': clean,
                                        'stars': 0,
                                        'update_time': datetime.now().strftime('%Y-%m-%d'),
                                        'is_classic': False,
                                    })
                                    print(f"      ✅ 聚宽帖子: {title[:40]} ({len(clean)}B)")
                                    break
                        except Exception as e:
                            logger.debug(f"聚宽帖子{post_id}异常: {e}")
                    
                    await browser.close()
                return results
            
            jq_community = asyncio.run(_jq_playwright())
            all_results.extend(jq_community)
            
        except ImportError:
            print("      ⚠️ Playwright不可用，跳过聚宽社区帖子")
        except Exception as e:
            logger.debug(f"聚宽社区搜索异常: {e}")
    
    print(f"    📊 聚宽总计: {len(all_results)} 个策略")
    return all_results[:max_results]


def search_chinese_platforms(keywords: List[str], max_results: int = 3) -> List[dict]:
    """
    搜索中国量化平台: 聚宽、BigQuant、雪球
    这些平台需要JS渲染，使用Playwright获取
    """
    print("    🌐 搜索中国量化平台(聚宽/雪球)...")
    all_results = []
    
    try:
        import asyncio
        from playwright.async_api import async_playwright
        import html as html_lib
        
        async def _cn_playwright():
            results = []
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--ignore-certificate-errors'])
                page = await browser.new_page()
                
                # === 聚宽 ===
                print("      🔍 搜索聚宽社区...")
                try:
                    # 先获取cookies
                    await page.goto('https://www.joinquant.com/community', timeout=30000, wait_until='domcontentloaded')
                    await page.wait_for_timeout(3000)
                    
                    # 用聚宽的帖子列表API搜索（需要cookies）
                    jq_apis = [
                        'https://www.joinquant.com/community/post/listV2?limit=10&page=1&cate=3&type=isNew',
                    ]
                    
                    for api_url in jq_apis:
                        await page.goto(api_url, timeout=15000, wait_until='domcontentloaded')
                        text = await page.inner_text('body')
                        
                        try:
                            data = json.loads(text)
                            posts = data.get('data', {}).get('list', []) if data.get('data') else []
                            
                            for post in posts:
                                title = post.get('title', '')
                                post_id = post.get('postId', '')
                                
                                # 筛选策略相关的帖子
                                if any(kw in title for kw in ['轮动', '动量', '策略', '回测', 'ETF', '趋势']):
                                    # 访问帖子获取代码
                                    post_url = f'https://www.joinquant.com/community/detail/{post_id}'
                                    await page.goto(post_url, timeout=15000, wait_until='domcontentloaded')
                                    await page.wait_for_timeout(2000)
                                    
                                    content = await page.content()
                                    code_blocks = re.findall(r'<pre[^>]*>(.*?)</pre>', content, re.DOTALL)
                                    
                                    for block in code_blocks:
                                        clean = html_lib.unescape(re.sub(r'<[^>]+>', '', block))
                                        if len(clean) > 100 and _is_valid_strategy_code(clean):
                                            results.append({
                                                'name': title[:50],
                                                'description': '聚宽社区策略',
                                                'source': 'joinquant',
                                                'source_link': post_url,
                                                'code': clean,
                                                'update_time': datetime.now().strftime('%Y-%m-%d'),
                                                'is_classic': False,
                                            })
                                            print(f"      ✅ 聚宽: {title[:40]} ({len(clean)}B)")
                                            break
                                    
                                    if len([r for r in results if r['source'] == 'joinquant']) >= max_results:
                                        break
                        except json.JSONDecodeError:
                            pass
                    
                except Exception as e:
                    logger.debug(f"聚宽搜索异常: {e}")
                
                # === 雪球 ===
                print("      🔍 搜索雪球...")
                try:
                    await page.goto('https://xueqiu.com/', timeout=15000)
                    await page.wait_for_timeout(2000)
                    
                    # 搜索
                    search_url = f'https://xueqiu.com/k?q={quote("动量轮动策略")}'
                    await page.goto(search_url, timeout=15000, wait_until='domcontentloaded')
                    await page.wait_for_timeout(3000)
                    
                    text = await page.inner_text('body')
                    # 雪球搜索结果通常不包含代码，但可以发现策略讨论
                    strategy_mentions = [line.strip() for line in text.split('\n') 
                                       if any(kw in line for kw in ['动量', '轮动', '回测']) and len(line.strip()) > 10]
                    
                    if strategy_mentions:
                        print(f"      📝 雪球发现{len(strategy_mentions)}条策略讨论（通常无代码，需人工获取）")
                
                except Exception as e:
                    logger.debug(f"雪球搜索异常: {e}")
                
                await browser.close()
            return results
        
        cn_results = asyncio.run(_cn_playwright())
        all_results.extend(cn_results)
        
    except ImportError:
        print("      ⚠️ Playwright不可用，跳过中国平台搜索")
    except Exception as e:
        logger.warning(f"中国平台搜索异常: {e}")
    
    return all_results


# ================================================================
# 来源8: Google搜索 → GitHub链接提取
# ================================================================
def search_google_to_github(keywords: List[str], max_results: int = 5) -> List[dict]:
    """
    通过DuckDuckGo搜索发现GitHub上的策略代码
    Google搜索的HTML链接被JavaScript编码，难以直接提取
    DuckDuckGo的HTML格式更简洁，链接可直接提取
    """
    print("    🌐 DuckDuckGo搜索 → GitHub链接...")
    all_results = []
    seen_repos = set()
    
    for keyword in keywords[:3]:
        try:
            query = f'site:github.com {keyword} python backtest'
            ddg_url = f'https://html.duckduckgo.com/html/?q={quote(query)}'
            r = _safe_get(ddg_url, timeout=15)
            
            if not r or r.status_code != 200:
                continue
            
            # 提取GitHub链接
            github_refs = re.findall(r'github\.com/([^"<>\s\)]+)', r.text)
            repo_links = set()
            for ref in github_refs:
                # 清理URL参数
                clean = ref.split('&')[0].split('?')[0].split('#')[0]
                # 提取owner/repo格式
                match = re.match(r'^([^/]+/[^/]+)', clean)
                if match:
                    repo = match.group(1)
                    if repo not in seen_repos and not any(x in repo for x in ['features', 'marketplace', 'topics', 'explore', 'pricing', 'settings']):
                        repo_links.add(repo)
                        seen_repos.add(repo)
            
            # git clone并扫描策略代码
            for repo in list(repo_links)[:max_results]:
                try:
                    strategy_files = _clone_and_scan_repo(repo, max_strategies=2)
                    
                    for sfile in strategy_files:
                        all_results.append({
                            'name': sfile['name'],
                            'description': f'DuckDuckGo搜索发现 - {repo}',
                            'source': 'google_github',
                            'source_link': f'https://github.com/{repo}',
                            'code': sfile['code'],
                            'stars': 0,
                            'update_time': datetime.now().strftime('%Y-%m-%d'),
                            'is_classic': False,
                        })
                        print(f"      ✅ DDG→GH: {repo}/{sfile['relpath']} ({len(sfile['code'])}B)")
                    
                    time.sleep(1)
                except:
                    continue
            
            time.sleep(2)
        except Exception as e:
            logger.warning(f"DuckDuckGo搜索异常: {e}")
    
    return all_results


# ================================================================
# 通用工具
# ================================================================
def _is_valid_strategy_code(code: str) -> bool:
    """验证代码是否是有效的策略代码（v2: 提高门槛减少误判）"""
    if not code or len(code.strip()) < 80:
        return False
    
    code_lower = code.lower()
    
    # 排除规则: 明显不是策略代码的文件
    exclude_patterns = [
        'django', 'flask', 'fastapi', 'uvicorn',  # Web框架
        'sqlalchemy', 'orm', 'migration',  # 数据库
        'pytest', 'unittest', 'mock', 'fixture',  # 测试
        'setup(', 'setuptools', 'distutils',  # 打包
        'celery', 'redis', 'rabbitmq',  # 任务队列
        'telegram', 'discord', 'slack',  # 通知
    ]
    if any(p in code_lower for p in exclude_patterns):
        return False
    
    # 核心策略关键词（权重高）
    core_indicators = [
        'generate_signals', 'entries', 'exits',
        'buy_signal', 'sell_signal', 'entry_signal', 'exit_signal',
        'long_entry', 'short_entry',
        'dual_momentum', 'absolute_momentum', 'relative_momentum',
        'mean_reversion', 'zscore', 'z_score',
        'rebalance', 'rotate',
        'def run_backtest', 'def backtest', 'def trade',
    ]
    
    # 通用量化关键词（权重低）
    general_indicators = [
        'backtest', 'strategy', 'moving_average', 'crossover',
        'supertrend', 'bollinger', 'rsi', 'macd', 'atr',
        'momentum', 'ema', 'sma', 'donchian', 'keltner',
        'position', 'portfolio', 'rank', 'score',
        'sort_values', 'pct_change', 'rolling', 'shift',
        'yfinance', 'akshare', 'tushare',
        'sharpe', 'drawdown', 'annualized',
        'np.where', 'np.sign',
    ]
    
    core_count = sum(1 for ind in core_indicators if ind in code_lower)
    general_count = sum(1 for ind in general_indicators if ind in code_lower)
    
    # 核心关键词1个=3分, 通用关键词1个=1分, 总分>=4才通过
    total_score = core_count * 3 + general_count
    return total_score >= 4


# ================================================================
# 搜索查询模板
# ================================================================
CROSS_REGIME_QUERIES = {
    'github': [
        # 趋势跟踪
        'dual momentum strategy python backtest language:python pushed:>2025-01-01',
        'momentum rotation ETF python backtest language:python pushed:>2025-01-01',
        'supertrend etf rotation python backtest language:python pushed:>2025-01-01',
        # 均值回归
        'mean reversion etf python backtest language:python pushed:>2025-01-01',
        'bollinger band mean reversion python strategy pushed:>2025-01-01',
        'zscore mean reversion stocks python pushed:>2025-01-01',
        # 配对交易/统计套利
        'pairs trading cointegration python backtest pushed:>2024-06-01',
        'statistical arbitrage etf python pushed:>2024-06-01',
        # 波动率
        'volatility targeting etf python backtest pushed:>2025-01-01',
        'vix timing rotation python strategy pushed:>2024-06-01',
        # 全天候/资产配置
        'all weather portfolio python backtest pushed:>2025-01-01',
        'risk parity etf python strategy pushed:>2025-01-01',
        # 高股息/防御
        'dividend rotation strategy python backtest pushed:>2025-01-01',
        'low volatility factor python stocks pushed:>2025-01-01',
        # 宏观/避险
        'cross regime trading strategy python pushed:>2024-06-01',
        'safe haven rotation gold bonds python pushed:>2025-01-01',
        'macro rotation strategy python backtest pushed:>2025-01-01',
        # 机器学习/因子
        'machine learning stock strategy python backtest pushed:>2024-06-01',
        'multi factor model etf python backtest pushed:>2024-06-01',
        'kalman filter trading python strategy pushed:>2024-01-01',
        # 动量变体
        'time series momentum python etf pushed:>2025-01-01',
        'relative strength ranking etf python pushed:>2025-01-01',
        'sector rotation momentum python stocks language:python pushed:>2025-01-01',
        'global equity momentum python language:python pushed:>2025-01-01',
        'trend following stocks python backtest language:python pushed:>2025-01-01',
        'defensive stocks low volatility python language:python pushed:>2025-01-01',
    ],
    'google': [
        'momentum rotation strategy python backtest 2025',
        'ETF dual momentum python strategy code',
        'all weather portfolio python backtest code',
        'mean reversion python backtest ETF 2025',
        'pairs trading python cointegration backtest',
        'volatility targeting strategy python ETF',
        'machine learning trading strategy python 2025',
        'multi factor model python ETF rotation',
    ],
    'quantconnect': ['momentum strategy', 'mean reversion', 'pairs trading'],
    'tradingview': ['momentum rotation', 'mean reversion', 'volatility'],
    'quantinsti': ['momentum strategy python', 'mean reversion python', 'pairs trading python'],
    'chinese': ['动量轮动 策略', '均值回归 ETF', '配对交易 策略', '波动率 策略'],
}

BULL_QUERIES = {
    'github': [
        'momentum strategy python stocks backtest language:python',
        'trend following breakout python stocks language:python',
        'supertrend strategy python backtest language:python',
        'macd momentum python stocks strategy language:python',
        'sector rotation python backtest language:python',
    ],
    'google': ['momentum strategy python stocks backtest', 'trend following python code'],
    'quantconnect': ['momentum stocks'],
    'tradingview': ['momentum breakout'],
    'quantinsti': ['momentum strategy'],
    'chinese': ['美股 动量策略'],
}

RANGE_QUERIES = {
    'github': [
        'mean reversion strategy python stocks backtest language:python',
        'bollinger band strategy python backtest language:python',
        'pairs trading mean reversion python language:python',
        'grid trading strategy python language:python',
    ],
    'google': ['mean reversion python backtest', 'pairs trading python code'],
    'quantconnect': ['mean reversion'],
    'tradingview': ['mean reversion'],
    'quantinsti': ['mean reversion strategy'],
    'chinese': ['均值回归 策略'],
}

BEAR_QUERIES = {
    'github': [
        'bear market defensive stocks python backtest language:python',
        'vix timing strategy python backtest language:python',
        'low volatility factor python language:python',
        'safe haven gold bond rotation python language:python',
        'inverse ETF strategy python language:python',
    ],
    'google': ['bear market defensive python strategy', 'low volatility strategy python'],
    'quantconnect': ['bear market defensive'],
    'tradingview': ['bear market'],
    'quantinsti': ['bear market strategy'],
    'chinese': ['熊市 防御 策略'],
}


# ================================================================
# 多源搜索主入口
# ================================================================
def multi_source_search(
    market_type: str = 'cross_regime',
    min_new: int = 3,
    enabled_sources: List[str] = None,
) -> Tuple[List[dict], dict]:
    """
    多源搜索主入口
    
    Args:
        market_type: 'cross_regime' / 'bull' / 'range' / 'bear'
        min_new: 最少需要的新策略数
        enabled_sources: 启用的来源列表
    
    Returns:
        (策略列表, 搜索统计)
    """
    query_map = {
        'cross_regime': CROSS_REGIME_QUERIES,
        'bull': BULL_QUERIES,
        'range': RANGE_QUERIES,
        'bear': BEAR_QUERIES,
    }
    queries = query_map.get(market_type, CROSS_REGIME_QUERIES)
    
    if enabled_sources is None:
        enabled_sources = ['joinquant', 'github', 'github_topics', 'awesome_quant', 
                          'google', 'quantconnect', 'tradingview',
                          'quantinsti', 'chinese_platforms']
    
    stats = {
        'sources_searched': [],
        'sources_failed': [],
        'total_results': 0,
        'per_source': {},
        'start_time': datetime.now().isoformat(),
    }
    
    all_strategies = []
    
    # ===== 来源0: 聚宽（JoinQuant）— 最高优先级 =====
    if 'joinquant' in enabled_sources:
        print(f"\n  📦 来源0: 聚宽（JoinQuant）策略 ⭐最高优先级")
        try:
            results = search_joinquant(market_type=market_type, max_results=8)
            stats['sources_searched'].append('joinquant')
            stats['per_source']['joinquant'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 聚宽: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'joinquant: {e}')
    
    # ===== 来源1: GitHub仓库搜索 (主力) =====
    if 'github' in enabled_sources:
        print(f"\n  📦 来源1: GitHub仓库搜索")
        try:
            gh_kw = queries.get('github', [])
            results = search_github(gh_kw, max_per_query=5)
            stats['sources_searched'].append('github')
            stats['per_source']['github'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 GitHub: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'github: {e}')
    
    # ===== 来源2: GitHub Topics =====
    if 'github_topics' in enabled_sources:
        print(f"\n  📦 来源2: GitHub Topics")
        try:
            results = search_github_topics(max_repos=5)
            stats['sources_searched'].append('github_topics')
            stats['per_source']['github_topics'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 Topics: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'github_topics: {e}')
    
    # ===== 来源3: awesome-quant =====
    if 'awesome_quant' in enabled_sources:
        print(f"\n  📦 来源3: awesome-quant资源列表")
        try:
            results = search_awesome_quant(max_repos=5)
            stats['sources_searched'].append('awesome_quant')
            stats['per_source']['awesome_quant'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 awesome-quant: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'awesome_quant: {e}')
    
    # ===== 来源4: DuckDuckGo搜索 → GitHub =====
    if 'google' in enabled_sources:
        print(f"\n  📦 来源4: DuckDuckGo搜索")
        try:
            google_kw = queries.get('google', [])
            results = search_google_to_github(google_kw, max_results=3)
            stats['sources_searched'].append('google')
            stats['per_source']['google'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 DuckDuckGo: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'google: {e}')
    
    # ===== 来源5: QuantConnect =====
    if 'quantconnect' in enabled_sources:
        print(f"\n  📦 来源5: QuantConnect")
        try:
            qc_kw = queries.get('quantconnect', [])
            results = search_quantconnect(qc_kw, max_results=3)
            stats['sources_searched'].append('quantconnect')
            stats['per_source']['quantconnect'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 QuantConnect: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'quantconnect: {e}')
    
    # ===== 来源6: TradingView (间接) =====
    if 'tradingview' in enabled_sources:
        print(f"\n  📦 来源6: TradingView(间接)")
        try:
            tv_kw = queries.get('tradingview', [])
            results = search_tradingview(tv_kw, max_results=3)
            stats['sources_searched'].append('tradingview')
            stats['per_source']['tradingview'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 TradingView: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'tradingview: {e}')
    
    # ===== 来源7: QuantInsti =====
    if 'quantinsti' in enabled_sources:
        print(f"\n  📦 来源7: QuantInsti")
        try:
            qi_kw = queries.get('quantinsti', [])
            results = search_quantinsti(qi_kw, max_results=3)
            stats['sources_searched'].append('quantinsti')
            stats['per_source']['quantinsti'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 QuantInsti: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'quantinsti: {e}')
    
    # ===== 来源8: 中国量化平台 =====
    if 'chinese_platforms' in enabled_sources:
        print(f"\n  📦 来源8: 聚宽/雪球")
        try:
            cn_kw = queries.get('chinese', [])
            results = search_chinese_platforms(cn_kw, max_results=3)
            stats['sources_searched'].append('chinese_platforms')
            stats['per_source']['chinese_platforms'] = len(results)
            all_strategies.extend(results)
            print(f"    📊 中国平台: {len(results)} 个策略")
        except Exception as e:
            stats['sources_failed'].append(f'chinese_platforms: {e}')
    
    # 过滤掉没有代码的策略（需要人工审核的单独标记）
    valid_strategies = [s for s in all_strategies if s.get('code')]
    needs_review = [s for s in all_strategies if not s.get('code') and s.get('needs_manual_review')]
    
    stats['total_results'] = len(valid_strategies)
    stats['needs_review'] = len(needs_review)
    stats['end_time'] = datetime.now().isoformat()
    
    print(f"\n  📊 多源搜索汇总:")
    print(f"    有效策略: {len(valid_strategies)} 个来自 {len(stats['sources_searched'])} 个来源")
    print(f"    需人工审核: {len(needs_review)} 个")
    if stats['sources_failed']:
        print(f"    ⚠️ 失败来源: {stats['sources_failed']}")
    
    # 将需人工审核的也保留（但标记）
    valid_strategies.extend(needs_review)
    
    return valid_strategies, stats


# ================================================================
# 搜索缓存
# ================================================================
SEARCH_CACHE_FILE = '/tmp/ms_search_cache.json'
SEARCH_CACHE_TTL = 86400  # 24小时（v8：避免重复搜索同一仓库）

def get_cached_search(market_type: str) -> Optional[List[dict]]:
    if not os.path.exists(SEARCH_CACHE_FILE):
        return None
    try:
        with open(SEARCH_CACHE_FILE) as f:
            cache = json.load(f)
        entry = cache.get(market_type, {})
        if time.time() - entry.get('timestamp', 0) < SEARCH_CACHE_TTL:
            return entry.get('results', [])
    except:
        pass
    return None

def save_search_cache(market_type: str, results: List[dict]):
    cache = {}
    if os.path.exists(SEARCH_CACHE_FILE):
        try:
            with open(SEARCH_CACHE_FILE) as f:
                cache = json.load(f)
        except:
            pass
    cache[market_type] = {'timestamp': time.time(), 'results': results}
    try:
        with open(SEARCH_CACHE_FILE, 'w') as f:
            json.dump(cache, f, ensure_ascii=False, default=str)
    except:
        pass


# ================================================================
# 测试入口
# ================================================================
if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    market = sys.argv[1] if len(sys.argv) > 1 else 'cross_regime'
    print(f"=== 多源策略搜索 v3 ({market}) ===\n")
    
    results, stats = multi_source_search(market_type=market, min_new=3)
    
    print(f"\n=== 搜索结果 ===")
    print(f"总策略数: {len(results)}")
    print(f"来源: {stats['sources_searched']}")
    if stats.get('sources_failed'):
        print(f"失败: {stats['sources_failed']}")
    
    for i, s in enumerate(results):
        code_len = len(s.get('code', '') or '')
        print(f"  {i+1}. [{s.get('source','')}] {s.get('name','')[:50]} ({code_len}B) ★{s.get('stars',0)} - {s.get('source_link','')[:60]}")
