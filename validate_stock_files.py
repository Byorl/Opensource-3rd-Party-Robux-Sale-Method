"""
Validate Stock/ files existence in GitHub repo (non-destructive).
Reads config/products.json and checks each product's stockGithubFile (auto-prefixes Stock/ if needed).

Usage:
  python validate_stock_files.py

It prints a report and returns exit code 0 if all found, 1 if any missing or errors.
"""
import os
import json
import sys
import requests
from dotenv import load_dotenv
from typing import List, Tuple

load_dotenv('config/.env')

GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
REPO_OWNER = os.getenv('GITHUB_REPO_OWNER')
REPO_NAME = os.getenv('GITHUB_REPO_NAME')

API_BASE = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"
HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}' if GITHUB_TOKEN else '',
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': 'Stock-Validator'
}


def resolve_stock_path(entry: str) -> str:
    if not entry:
        return ''
    return entry if '/' in entry else f"Stock/{entry}"


def check_file_exists(path: str) -> Tuple[bool, str]:
    """Return (exists, message)."""
    try:
        from urllib.parse import quote
        path_enc = quote(path, safe='/')
        url = f"{API_BASE}/{path_enc}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            return True, 'OK'
        elif resp.status_code == 404:
            return False, f'Not found (404) - URL tried: {url}'
        else:
            return False, f'HTTP {resp.status_code} - {resp.text[:200]}'
    except Exception as e:
        return False, f'Error: {e}'


def main():
    if not REPO_OWNER or not REPO_NAME:
        print('[X] GITHUB_REPO_OWNER and GITHUB_REPO_NAME must be set in config/.env')
        sys.exit(1)

    try:
        with open('config/products.json','r',encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f'[X] Failed to load config/products.json: {e}')
        sys.exit(1)

    files: List[str] = []
    for prod in cfg.get('products', []):
        sf = prod.get('stockGithubFile')
        if sf:
            files.append(resolve_stock_path(sf))

    bought = cfg.get('github', {}).get('bought_file') or os.getenv('GITHUB_BOUGHT_FILE')
    if bought:
        files.append(bought)

    files = list(dict.fromkeys(files))

    if not files:
        print('[!] No stock files configured in products.json')
        sys.exit(0)

    all_ok = True
    print('Checking stock files in GitHub:')
    for i, fpath in enumerate(files, 1):
        ok, msg = check_file_exists(fpath)
        status = 'OK' if ok else 'MISSING'
        print(f'{i:2d}. {fpath} -> {status} {"-" if ok else ":"} {msg}')
        if not ok:
            all_ok = False

    if all_ok:
        print('\nAll files found.')
        sys.exit(0)
    else:
        print('\nSome files were missing or errored.')
        sys.exit(1)

if __name__ == '__main__':
    main()
