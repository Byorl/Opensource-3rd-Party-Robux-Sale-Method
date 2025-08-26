"""
GitHub Stock Management System
Manages license keys using GitHub private repository instead of Pastebin.
"""

import requests
import json
import base64
from typing import List, Optional, Dict
import logging

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
            "User-Agent": "ByorlHub-Stock-Manager"
        }
    
    def get_file_content(self, file_path: str) -> List[str]:
        """Get current stock from GitHub file."""
        try:
            url = f"{self.base_url}/contents/{file_path}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 404:
                logger.info(f"File {file_path} not found, returning empty stock")
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
            logger.error(f"Failed to fetch stock from GitHub {file_path}: {e}")
            return []
    
    def update_file_content(self, file_path: str, keys: List[str], commit_message: str = None) -> bool:
        """Update GitHub file with new stock."""
        try:
            url = f"{self.base_url}/contents/{file_path}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            sha = None
            if response.status_code == 200:
                file_data = response.json()
                sha = file_data['sha']
            elif response.status_code != 404:
                response.raise_for_status()
            
            content = json.dumps(keys, indent=2)
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

def test_github_connection():
    """Test GitHub connection and permissions."""
    
    config = {
        "token": "YOUR_GITHUB_TOKEN",
        "repo_owner": "YOUR_GITHUB_USERNAME",
        "repo_name": "YOUR_REPO_NAME"
    }
    
    print("🔍 Testing GitHub Connection...")
    print("=" * 50)
    
    manager = GitHubStockManager(config["token"], config["repo_owner"], config["repo_name"])
    
    try:
        url = f"https://api.github.com/repos/{config['repo_owner']}/{config['repo_name']}"
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
    
    files_to_test = ["7-Day Stock", "Keys Bought"]
    
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
