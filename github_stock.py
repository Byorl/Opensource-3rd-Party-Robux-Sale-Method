"""
GitHub Stock Management System
Manages license keys using GitHub private repository instead of Pastebin.
"""

import requests
import json
import base64
import os
from typing import List, Optional, Dict
import logging
from dotenv import load_dotenv
import urllib.parse

load_dotenv('config/.env')

logger = logging.getLogger(__name__)

class GitHubStockManager:
    def __init__(self, token: str, repo_owner: str, repo_name: str):
        """Initialize GitHub stock manager."""
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Stock-Manager"
        }
    
    def get_file_content(self, file_path: str) -> List[str]:
        """Get current stock from GitHub file."""
        try:
            path_encoded = urllib.parse.quote(file_path, safe='/')
            url = f"{self.base_url}/contents/{path_encoded}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 404:
                logger.info(f"File {file_path} not found (404). API URL tried: {url}")
                try:
                    logger.debug(f"GitHub response body: {response.text}")
                except Exception:
                    pass
                return []
            
            response.raise_for_status()
            file_data = response.json()
            
            content = base64.b64decode(file_data['content']).decode('utf-8').strip()
            
            if not content:
                return []
            
            try:
                stock_data = json.loads(content)
                if isinstance(stock_data, list):
                    return stock_data
                else:
                    return []
            except json.JSONDecodeError:
                return [line.strip() for line in content.split('\n') if line.strip()]
                
        except Exception as e:
            try:
                logger.error(f"Failed to fetch stock from GitHub {file_path}. API URL tried: {url} Error: {e}")
            except Exception:
                logger.error(f"Failed to fetch stock from GitHub {file_path}. Error: {e}")
            return []
    
    def update_file_content(self, file_path: str, keys: List[str], commit_message: str = None) -> bool:
        """Update GitHub file with new stock."""
        try:
            path_encoded = urllib.parse.quote(file_path, safe='/')
            url = f"{self.base_url}/contents/{path_encoded}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            sha = None
            existing_format = 'json'  # or 'lines'
            if response.status_code == 200:
                file_data = response.json()
                sha = file_data['sha']
                try:
                    existing_raw = base64.b64decode(file_data.get('content','')).decode('utf-8').lstrip()
                    # Heuristic: if file begins with '[' treat as JSON list, else newline separated.
                    if existing_raw.startswith('['):
                        existing_format = 'json'
                    else:
                        existing_format = 'lines'
                except Exception:
                    existing_format = 'json'
            elif response.status_code != 404:
                response.raise_for_status()
            
            # Normalize list, strip whitespace & duplicates while preserving original order of first occurrence
            normalized = []
            seen = set()
            for k in keys:
                if not k:
                    continue
                k2 = k.strip()
                if not k2 or k2 in seen:
                    continue
                seen.add(k2)
                normalized.append(k2)

            if existing_format == 'lines':
                # newline separated list (no JSON overhead)
                content = '\n'.join(normalized) + ('\n' if normalized else '')
            else:
                content = json.dumps(normalized, indent=2)
            encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            if not commit_message:
                commit_message = f"Update stock: {len(keys)} keys available"
            
            update_data = {
                "message": commit_message,
                "content": encoded_content
            }
            
            if sha:
                update_data["sha"] = sha
            
            response = requests.put(url, headers=self.headers, json=update_data, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Successfully updated {file_path} with {len(keys)} keys")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update GitHub file {file_path}: {e}")
            return False
    
    def add_keys_to_stock(self, file_path: str, new_keys: List[str]) -> bool:
        """Add new keys to existing stock."""
        try:
            current_stock = self.get_file_content(file_path)
            
            updated_stock = list(set(current_stock + new_keys))
            
            commit_message = f"Add {len(new_keys)} new keys (total: {len(updated_stock)})"
            return self.update_file_content(file_path, updated_stock, commit_message)
            
        except Exception as e:
            logger.error(f"Failed to add keys to stock: {e}")
            return False
    
    def remove_key_from_stock(self, file_path: str, key_to_remove: str) -> bool:
        """Remove a key from stock (when sold)."""
        try:
            current_stock = self.get_file_content(file_path)
            
            if key_to_remove not in current_stock:
                logger.warning(f"Key {key_to_remove} not found in stock")
                return False
            
            updated_stock = [key for key in current_stock if key != key_to_remove]
            
            commit_message = f"Sold key: {key_to_remove} (remaining: {len(updated_stock)})"
            return self.update_file_content(file_path, updated_stock, commit_message)
            
        except Exception as e:
            logger.error(f"Failed to remove key from stock: {e}")
            return False
    
    def get_stock_count(self, file_path: str) -> int:
        """Get current stock count."""
        stock = self.get_file_content(file_path)
        return len(stock)
    
    def add_bought_key(self, file_path: str, key: str, buyer_info: str = None) -> bool:
        """Add a key to the bought keys file."""
        try:
            current_bought = self.get_file_content(file_path)
            
            if buyer_info:
                entry = f"{key} - {buyer_info}"
            else:
                entry = key
            
            current_bought.append(entry)
            
            commit_message = f"Key sold: {key}"
            return self.update_file_content(file_path, current_bought, commit_message)
            
        except Exception as e:
            logger.error(f"Failed to add bought key: {e}")
            return False
    
    def get_all_existing_keys(self, stock_files: List[str], bought_files: List[str]) -> set:
        """Get all existing keys from stock and bought files to prevent duplicates."""
        all_keys = set()
        
        for file_path in stock_files:
            try:
                keys = self.get_file_content(file_path)
                all_keys.update(keys)
                logger.info(f"Loaded {len(keys)} keys from stock file: {file_path}")
            except Exception as e:
                logger.warning(f"Could not load stock file {file_path}: {e}")
        
        for file_path in bought_files:
            try:
                bought_entries = self.get_file_content(file_path)
                for entry in bought_entries:
                    key = entry.split(' - ')[0].strip()
                    if key:
                        all_keys.add(key)
                logger.info(f"Loaded {len(bought_entries)} bought keys from: {file_path}")
            except Exception as e:
                logger.warning(f"Could not load bought file {file_path}: {e}")
        
        logger.info(f"Total existing keys found: {len(all_keys)}")
        return all_keys
    
    def is_key_duplicate(self, key: str, existing_keys: set) -> bool:
        """Check if a key already exists."""
        return key in existing_keys

def test_github_connection():
    """Test GitHub connection and permissions."""
    print("🔍 Testing GitHub Connection...")
    print("=" * 50)

    token = os.getenv('GITHUB_TOKEN')
    repo_owner = os.getenv('GITHUB_REPO_OWNER')
    repo_name = os.getenv('GITHUB_REPO_NAME')

    if not token or not repo_owner or not repo_name:
        print("❌ GitHub configuration missing in environment variables (GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME required)")
        return False

    manager = GitHubStockManager(token, repo_owner, repo_name)
    
    try:
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        response = requests.get(url, headers=manager.headers, timeout=10)
        
        if response.status_code == 200:
            repo_data = response.json()
            print(f"✅ Repository access: OK")
            print(f"📁 Repository: {repo_data['full_name']}")
            print(f"🔒 Private: {repo_data['private']}")
        else:
            print(f"❌ Repository access failed: {response.status_code}")
            print(f"📄 Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False
    
    files_to_test = []
    try:
        with open('config/products.json', 'r', encoding='utf-8') as f:
            products_cfg = json.load(f)
        
        for product in products_cfg.get('products', []):
            stock_file = product.get('stockGithubFile')
            if stock_file:
                if '/' not in stock_file:
                    stock_file = f"Stock/{stock_file}"
                if stock_file not in files_to_test:
                    files_to_test.append(stock_file)
        
        bought_file = os.getenv('GITHUB_BOUGHT_FILE', products_cfg.get('github', {}).get('bought_file', 'Keys Bought'))
        if bought_file and bought_file not in files_to_test:
            files_to_test.append(bought_file)
            
    except Exception as e:
        print(f"⚠️  Could not load products.json for file list: {e}")
        files_to_test = []
        bought_file = os.getenv('GITHUB_BOUGHT_FILE', 'Keys Bought')
        if bought_file:
            files_to_test.append(bought_file)
    
    if not files_to_test:
        files_to_test = ["7-Day Stock", "Keys Bought"]
        print("⚠️ Using default test files as no files were found in products.json")
    
    for file_path in files_to_test:
        print(f"\n📄 Testing file: {file_path}")
        try:
            stock = manager.get_file_content(file_path)
            print(f"✅ File access: OK ({len(stock)} items)")
            
            if stock:
                print(f"📋 Sample content: {stock[0]}")
            
        except Exception as e:
            print(f"❌ File access error: {e}")
    
    print(f"\n✅ GitHub connection test complete!")
    return True

if __name__ == "__main__":
    test_github_connection()
