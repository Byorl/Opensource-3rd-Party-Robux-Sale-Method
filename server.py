import urllib.parse
import requests
import logging
import json
import threading
import secrets
import os
import bcrypt
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, send_file
from flask_cors import CORS
from github_stock import GitHubStockManager

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app, supports_credentials=True, origins=['http://localhost:5000', 'http://127.0.0.1:5000', 'null'])
app.secret_key = secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=None,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

user_locks = {}
lock_manager_lock = threading.Lock()
rate_limit_cache = {}
request_cache = {}

persistent_user_cache = {}

@app.route('/clear-cache', methods=['POST'])
def clear_cache_endpoint():
    """Clear cache endpoint for testing."""
    global request_cache, persistent_user_cache, rate_limit_cache
    request_cache.clear()
    persistent_user_cache.clear()
    rate_limit_cache.clear()
    logger.info("All caches cleared")
    return jsonify({'message': 'All caches cleared successfully'})

def get_user_lock(username):
    """Get or create a lock for a specific user"""
    with lock_manager_lock:
        if username not in user_locks:
            user_locks[username] = threading.Lock()
        return user_locks[username]

def is_rate_limited(key, limit_seconds=30):
    """Check if a request is rate limited."""
    now = datetime.now()
    if key in rate_limit_cache:
        last_request = rate_limit_cache[key]
        if now - last_request < timedelta(seconds=limit_seconds):
            return True
    rate_limit_cache[key] = now
    return False

def get_cached_response(cache_key, max_age_seconds=60):
    """Get cached response if available and not expired."""
    if cache_key in request_cache:
        cached_data, timestamp = request_cache[cache_key]
        if datetime.now() - timestamp < timedelta(seconds=max_age_seconds):
            return cached_data
    return None

def cache_response(cache_key, data):
    """Cache a response."""
    request_cache[cache_key] = (data, datetime.now())

class KeyManager:
    def __init__(self):
        self.key_expiry = {}
    
    def generate_key_with_expiry(self, product_type, days=30):
        """Generate key with expiration date"""
        key = self.generate_base_key(product_type)
        expiry_date = datetime.now() + timedelta(days=days)
        self.key_expiry[key] = expiry_date
        return key, expiry_date
    
    def generate_base_key(self, product_type):
        """Generate base key format"""
        timestamp = datetime.now().strftime("%Y%m")
        
        if product_type == "7day" or product_type == "7d":
            prefix = f"BH7D_{timestamp}"
        elif product_type == "30day" or product_type == "30d":
            prefix = f"BH30D_{timestamp}"
        elif product_type == "lifetime":
            prefix = f"BHLT_{timestamp}"
        else:
            prefix = f"BH_{timestamp}"
        
        random_part = secrets.token_urlsafe(8)
        return f"{prefix}_{random_part}"

class AccountManager:
    def __init__(self, github_manager):
        self.github_manager = github_manager
        self.accounts_file = 'Accounts'
        self.cache = {}
        self.cache_timestamp = None
        self.cache_duration = 60
    
    def _is_cache_valid(self):
        """Check if cache is still valid"""
        if not self.cache_timestamp:
            return False
        return (datetime.now() - self.cache_timestamp).seconds < self.cache_duration
    
    def load_accounts(self):
        """Load accounts from GitHub"""
        if self._is_cache_valid():
            return self.cache
            
        try:
            if not self.github_manager:
                logger.warning("GitHub manager not available")
                return {}
            
            content_list = self.github_manager.get_file_content(self.accounts_file)
            if content_list and len(content_list) > 0:
                accounts = json.loads(content_list[0])
                self.cache = accounts
                self.cache_timestamp = datetime.now()
                logger.info(f"Loaded accounts, found {len(accounts)} accounts")
                return accounts
            else:
                logger.info("No accounts file found, initializing empty")
                return {}
                
        except Exception as e:
            logger.error(f"Error loading accounts: {e}")
            return {}
    
    def save_accounts(self, accounts):
        """Save accounts to GitHub"""
        try:
            if not self.github_manager:
                logger.warning("GitHub manager not available")
                return False
            
            self.cache = accounts
            self.cache_timestamp = datetime.now()
            
            logger.info("Attempting to save accounts data to GitHub")
            json_data = json.dumps(accounts, indent=2)
            logger.info(f"Converted accounts to JSON, length: {len(json_data)}")
            
            success = self.github_manager.update_file_content(
                self.accounts_file,
                [json_data],
                "Update accounts data"
            )
            logger.info(f"GitHub update result: {success}")
            return success
        except Exception as e:
            logger.error(f"Failed to save accounts: {e}")
            return False
    
    def hash_password(self, password):
        """Hash password using bcrypt"""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def verify_password(self, password, hashed):
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def register_user(self, username, password, roblox_username=None):
        """Register a new user"""
        try:
            accounts = self.load_accounts()
            
            if username.lower() in [acc['username'].lower() for acc in accounts.values()]:
                return False, "Username already exists"
            
            user_id = secrets.token_hex(16)
            while user_id in accounts:
                user_id = secrets.token_hex(16)
            
            accounts[user_id] = {
                'username': username,
                'password_hash': self.hash_password(password),
                'roblox_username': roblox_username or '',
                'created_at': datetime.now().isoformat(),
                'purchase_history': [],
                'total_purchases': 0,
                'last_login': None
            }
            
            if self.save_accounts(accounts):
                return True, user_id
            else:
                return False, "Failed to save account"
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False, str(e)
    
    def login_user(self, username, password):
        """Login user and return user data"""
        try:
            accounts = self.load_accounts()
            
            user_id = None
            for uid, account in accounts.items():
                if account['username'].lower() == username.lower():
                    user_id = uid
                    break
            
            if not user_id:
                return False, "User not found"
            
            user_account = accounts[user_id]
            
            if not self.verify_password(password, user_account['password_hash']):
                return False, "Invalid password"
            
            user_account['last_login'] = datetime.now().isoformat()
            accounts[user_id] = user_account
            self.save_accounts(accounts)
            
            user_data = user_account.copy()
            del user_data['password_hash']
            user_data['user_id'] = user_id
            
            return True, user_data
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, str(e)
    
    def get_user_by_id(self, user_id):
        """Get user data by ID"""
        try:
            accounts = self.load_accounts()
            if user_id in accounts:
                user_data = accounts[user_id].copy()
                del user_data['password_hash']
                user_data['user_id'] = user_id
                return user_data
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
        return None
    
    def add_purchase_to_history(self, user_id, purchase_data):
        """Add a purchase to user's history"""
        try:
            logger.info(f"Attempting to add purchase to history for user_id: {user_id}")
            accounts = self.load_accounts()
            
            if user_id not in accounts:
                logger.error(f"User {user_id} not found in accounts")
                return False
            
            purchase_entry = {
                'purchase_id': secrets.token_hex(8),
                'product_name': purchase_data['product_name'],
                'product_id': purchase_data['product_id'],
                'key': purchase_data['key'],
                'roblox_username': purchase_data['roblox_username'],
                'purchase_date': datetime.now().isoformat(),
                'price': purchase_data['price'],
                'gamepass_id': purchase_data['gamepass_id']
            }
            
            logger.info(f"Created purchase entry: {purchase_entry}")
            
            accounts[user_id]['purchase_history'].append(purchase_entry)
            accounts[user_id]['total_purchases'] += 1
            
            save_result = self.save_accounts(accounts)
            logger.info(f"Save accounts result: {save_result}")
            
            if save_result:
                logger.info(f"Successfully added purchase to account history for user {user_id}")
                return True
            else:
                logger.error(f"Failed to save accounts after adding purchase for user {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error adding purchase to history: {e}")
            return False

class GitHubUserDataManager:
    """Manages user data using GitHub as storage backend"""
    
    def __init__(self, github_manager):
        self.github_manager = github_manager
        self.cache = {}
        self.cache_timestamp = None
        self.cache_duration = 60
    
    def _is_cache_valid(self):
        """Check if cache is still valid"""
        if not self.cache_timestamp:
            return False
        return (datetime.now() - self.cache_timestamp).seconds < self.cache_duration
    
    def load_user_data(self):
        """Load user data from GitHub"""
        if self._is_cache_valid():
            return self.cache
            
        try:
            if not self.github_manager:
                logger.warning("GitHub manager not available, falling back to local file")
                return self._load_local_fallback()
            
            content_list = self.github_manager.get_file_content('user_data')
            if content_list and len(content_list) > 0:
                data = json.loads(content_list[0])
                self.cache = data
                self.cache_timestamp = datetime.now()
                logger.info("User data loaded from GitHub")
                return data
            else:
                logger.info("User data file not found on GitHub, initializing empty")
                return {}
                
        except Exception as e:
            logger.error(f"Error loading user data from GitHub: {e}")
            return self._load_local_fallback()
    
    def save_user_data(self, data):
        """Save user data to GitHub"""
        try:
            if not self.github_manager:
                logger.warning("GitHub manager not available, saving locally")
                return self._save_local_fallback(data)
            
            self.cache = data
            self.cache_timestamp = datetime.now()
            
            content_json = json.dumps(data, indent=2)
            success = self.github_manager.update_file_content('user_data', [content_json], 
                                                            f"Update user data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            if success:
                logger.info("User data saved to GitHub successfully")
            else:
                logger.error("Failed to save user data to GitHub")
                self._save_local_fallback(data)
                
        except Exception as e:
            logger.error(f"Error saving user data to GitHub: {e}")
            self._save_local_fallback(data)
    
    def _load_local_fallback(self):
        """Fallback to local file loading"""
        try:
            if os.path.exists('user_data.json'):
                with open('user_data.json', 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading local user data: {e}")
            return {}
    
    def _save_local_fallback(self, data):
        """Fallback to local file saving"""
        try:
            with open('user_data.json', 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving local user data: {e}")

def load_github_manager():
    try:
        with open('config/products.json', 'r') as f:
            config = json.load(f)
            github_config = config.get('github', {})
            
            if github_config.get('token'):
                return GitHubStockManager(
                    token=github_config.get('token'),
                    repo_owner=github_config.get('repo_owner'),
                    repo_name=github_config.get('repo_name')
                )
    except Exception as e:
        logger.error(f"Failed to load GitHub manager: {e}")
    return None

github_manager = load_github_manager()
account_manager = AccountManager(github_manager)
github_user_data_manager = GitHubUserDataManager(github_manager)
key_manager = KeyManager()

def init_user_data():
    """Initialize the user data if it doesn't exist."""
    data = github_user_data_manager.load_user_data()
    if not data:
        logger.info("User data not found. Initializing empty user data.")
        github_user_data_manager.save_user_data({})
        logger.info("User data initialized successfully.")

def load_user_data():
    """Load user data using GitHub manager."""
    return github_user_data_manager.load_user_data()

def save_user_data(data):
    """Save user data using GitHub manager."""
    cleaned_data = cleanup_old_entries(data)
    github_user_data_manager.save_user_data(cleaned_data)

def cleanup_old_entries(data):
    """Remove old entries to prevent file bloat."""
    if not data:
        return {}
    
    current_time = datetime.now()
    cleaned_data = {}
    
    for username, user_info in data.items():
        cleaned_user_info = {}
        
        for gamepass_id, entry in user_info.items():
            if isinstance(entry, dict) and 'issued_at' in entry:
                issued_time = datetime.fromisoformat(entry['issued_at'])
                if current_time - issued_time < timedelta(days=30):
                    cleaned_user_info[gamepass_id] = entry
                else:
                    logger.info(f"Cleaned up old entry for {username} - {gamepass_id}")
            elif isinstance(entry, bool):
                if entry:  
                    cleaned_user_info[gamepass_id] = {
                        'key_issued': True,
                        'issued_at': current_time.isoformat(),
                        'key': f"ByorlHub_legacy_{secrets.token_urlsafe(8)}"
                    }
        if cleaned_user_info:
            cleaned_data[username] = cleaned_user_info
    
    return cleaned_data

def fetch_user_id(username):
    """Fetch a Roblox user ID by username with caching and improved rate limiting."""
    cache_key = f"user_id_{username.lower()}"
    logger.info(f"Fetching user ID for username: {username}")
    
    if username.lower() in persistent_user_cache:
        cached_data = persistent_user_cache[username.lower()]
        if cached_data['timestamp'] + 3600 > datetime.now().timestamp():  
            logger.info(f"Using persistent cache for user ID: {cached_data['result']}")
            return cached_data['result']
    
    cached_result = get_cached_response(cache_key, 600) 
    if cached_result:
        logger.info(f"Using cached user ID result: {cached_result}")
        return cached_result

    global_rate_key = "global_user_fetch"
    if is_rate_limited(global_rate_key, 5):  
        logger.info("Global rate limit hit for user fetching")
        return None, "RATE_LIMITED"
    
    rate_key = f"user_fetch_{username.lower()}"
    if is_rate_limited(rate_key, 60):  
        return None, "RATE_LIMITED"
    
    encoded_username = urllib.parse.quote(username)
    search_url = f'https://users.roblox.com/v1/users/search?keyword={encoded_username}'
    logger.info(f"Making request to Roblox user search API: {search_url}")
    
    try:
        response = requests.get(search_url, timeout=10)  
        logger.info(f"User search API response status: {response.status_code}")
        
        if response.status_code == 429:
            logger.warning("Roblox API rate limit hit")
            return None, "ROBLOX_RATE_LIMITED"
            
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"User search API response data: {data}")
        users = data.get('data', [])
        
        for user in users:
            if user.get('name', '').lower() == username.lower():
                result = user.get('id'), None
                logger.info(f"Found matching user: {result}")
                cache_response(cache_key, result)
                persistent_user_cache[username.lower()] = {
                    'result': result,
                    'timestamp': datetime.now().timestamp()
                }
                return result
        
        result = None, "USER_NOT_FOUND"
        logger.info(f"User not found in search results: {result}")
        cache_response(cache_key, result)
        persistent_user_cache[username.lower()] = {
            'result': result,
            'timestamp': datetime.now().timestamp()
        }
        return result
        
    except requests.exceptions.Timeout:
        return None, "TIMEOUT"
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching user ID for {username}: {e}")
        return None, "REQUEST_ERROR"
    except Exception as e:
        logger.error(f"Unexpected error fetching user ID for {username}: {e}")
        return None, "UNKNOWN_ERROR"

def check_gamepass_ownership(user_id, gamepass_id, force_refresh=False):
    """Check if a user owns a specific gamepass with optimized caching."""
    cache_key = f"gamepass_{user_id}_{gamepass_id}"
    
    if not force_refresh:
        cached_result = get_cached_response(cache_key, 15)  
        if cached_result is not None:
            logger.info(f"Using cached gamepass result: {cached_result}")
            return cached_result
    
    global_gamepass_rate_key = "global_gamepass_check"
    if is_rate_limited(global_gamepass_rate_key, 1): 
        logger.info("Global rate limit hit for gamepass checking")
        return None
    
    rate_key = f"gamepass_check_{user_id}_{gamepass_id}"
    if is_rate_limited(rate_key, 10): 
        return None
    
    url = f'https://inventory.roblox.com/v1/users/{user_id}/items/GamePass/{gamepass_id}'
    
    try:
        response = requests.get(url, timeout=5)  
        
        if response.status_code == 429:
            logger.warning(f"Roblox API rate limit hit for gamepass check")
            return None
            
        response.raise_for_status()
        
        data = response.json()
        has_gamepass = len(data.get('data', [])) > 0
        
        cache_time = 8 if not has_gamepass else 30
        cache_response(cache_key, has_gamepass)
        
        logger.info(f"Gamepass check result: user_id={user_id}, gamepass_id={gamepass_id}, has_gamepass={has_gamepass}")
        return has_gamepass
        
    except requests.exceptions.Timeout:
        logger.warning(f"Timeout checking gamepass {gamepass_id} for user {user_id}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Error checking gamepass ownership: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error checking gamepass: {e}")
        return None

try:
    with open('config/products.json', 'r') as f:
        config_data = json.load(f)
        products_list = config_data.get('products', [])
        
        PRODUCTS_CONFIG = {}
        for product in products_list:
            PRODUCTS_CONFIG[product['id']] = {
                'name': product['name'],
                'price': product['price'],
                'gamepass_id': product['gamepassId'],
                'gamepass_url': product.get('gamepassUrl', f"https://www.roblox.com/game-pass/{product['gamepassId']}"),
                'duration': product['duration'],
                'stock_file': product.get('stockGithubFile', f"{product['id'].upper()}-Stock"),
                'bought_file': config_data.get('github', {}).get('bought_file', 'Keys-Bought'),
                'duration_days': 7 if '7' in product['duration'] else 30 if '30' in product['duration'] else 7,
                'parentProduct': product.get('parentProduct')
            }
            
except Exception as e:
    logger.error(f"Failed to load products config: {e}")
    PRODUCTS_CONFIG = {}

SUPPORTED_GAMEPASSES = list(PRODUCTS_CONFIG.keys())

init_user_data()

def warm_user_cache():
    """Pre-populate cache with known usernames to avoid API calls"""
    try:
        persistent_user_cache['byorlals'] = {
            'result': (9213180540, None),  
            'timestamp': datetime.now().timestamp()
        }
        logger.info("Pre-populated cache with known user: byorlals")
        
        user_data = load_user_data()
        for username in user_data.keys():
            if username.lower() not in persistent_user_cache:
                logger.info(f"Cache warming needed for user: {username}")
    except Exception as e:
        logger.error(f"Error warming cache: {e}")

warm_user_cache()

def get_client_ip():
    """Get the real client IP address"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr

def get_authenticated_user():
    """Get authenticated user from session or token"""
    try:
        if 'user_id' in session:
            logger.info(f"Found user_id in session: {session['user_id']}")
            user_data = account_manager.get_user_by_id(session['user_id'])
            if user_data:
                logger.info(f"Authentication successful via session for user: {user_data['username']}")
                return user_data
        
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            logger.info(f"Auth token check: token={token[:10]}..., found_user_id=None")
        
        logger.info("No authentication found (no session or valid token)")
        return None
        
    except Exception as e:
        logger.error(f"Error in authentication: {e}")
        return None

@app.route('/products')
def get_products():
    """Get available products with current stock levels."""
    try:
        import json
        with open('config/products.json', 'r') as f:
            config = json.load(f)
        
        products = []
        main_products = []
        
        for product_id, product_config in PRODUCTS_CONFIG.items():
            try:
                if github_manager:
                    stock_file = product_config.get('stock_file', f'{product_id.upper()}-Stock')
                    current_stock = github_manager.get_file_content(stock_file)
                    stock_count = len(current_stock) if current_stock else 0
                    print(f"DEBUG: Product {product_id} - Stock file: {stock_file}, Stock count: {stock_count}")
                else:
                    stock_count = 'not_configured'
                    print(f"DEBUG: Product {product_id} - GitHub manager not available")
                
                product = {
                    'id': product_id,
                    'name': product_config.get('name', product_id.title()),
                    'price': product_config.get('price', 1),
                    'gamepass_id': product_config.get('gamepass_id') or product_config.get('gamepassId'),
                    'gamepassUrl': product_config.get('gamepass_url') or product_config.get('gamepassUrl'),
                    'duration': product_config.get('duration', '7 Days'),
                    'stock': stock_count,
                    'parentProduct': product_config.get('parentProduct')
                }
                products.append(product)
                
            except Exception as e:
                logger.error(f"Error getting stock for {product_id}: {e}")
                product = {
                    'id': product_id,
                    'name': product_config.get('name', product_id.title()),
                    'price': product_config.get('price', 1),
                    'gamepass_id': product_config.get('gamepass_id') or product_config.get('gamepassId'),
                    'gamepassUrl': product_config.get('gamepass_url') or product_config.get('gamepassUrl'),
                    'duration': product_config.get('duration', '7 Days'),
                    'stock': 'unavailable',
                    'parentProduct': product_config.get('parentProduct')
                }
                products.append(product)

        if 'mainProducts' in config:
            for main_product in config['mainProducts']:
                variants = [p for p in products if p.get('parentProduct') == main_product['id']]
                total_stock = sum(p['stock'] for p in variants if isinstance(p['stock'], int))
                min_price = min(p['price'] for p in variants) if variants else 0
                
                print(f"DEBUG: Main product {main_product['id']} - Variants: {len(variants)}, Total stock: {total_stock}")
                for variant in variants:
                    print(f"  - Variant {variant['id']}: stock={variant['stock']}")
                
                main_product_data = {
                    **main_product,
                    'totalStock': total_stock,
                    'minPrice': min_price,
                    'variantProducts': variants
                }
                main_products.append(main_product_data)

        return jsonify({
            'products': products,
            'mainProducts': main_products
        })
        
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        return jsonify({'error': 'Failed to get products'}), 500

@app.route('/register', methods=['POST'])
def register():
    """Register a new user account"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        roblox_username = data.get('roblox_username', '').strip()
        
        if not username or len(username) < 3:
            return jsonify({'success': False, 'error': 'Username must be at least 3 characters'}), 400
        
        if not password or len(password) < 6:
            return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400
        
        if not username.replace('_', '').replace('-', '').isalnum():
            return jsonify({'success': False, 'error': 'Username can only contain letters, numbers, _ and -'}), 400
        
        success, result = account_manager.register_user(username, password, roblox_username)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Account created successfully',
                'user_id': result
            })
        else:
            return jsonify({'success': False, 'error': result}), 400
            
    except Exception as e:
        logger.error(f"Registration endpoint error: {e}")
        return jsonify({'success': False, 'error': 'Registration failed'}), 500

@app.route('/login', methods=['POST'])
def login():
    """Login user"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password required'}), 400
        
        success, result = account_manager.login_user(username, password)
        
        if success:
            session['user_id'] = result['user_id']
            session.permanent = True
            
            return jsonify({
                'success': True,
                'message': 'Login successful',
                'user': result
            })
        else:
            return jsonify({'success': False, 'error': result}), 401
            
    except Exception as e:
        logger.error(f"Login endpoint error: {e}")
        return jsonify({'success': False, 'error': 'Login failed'}), 500

@app.route('/logout', methods=['POST'])
def logout():
    """Logout user"""
    try:
        session.clear()
        return jsonify({'success': True, 'message': 'Logged out successfully'})
    except Exception as e:
        logger.error(f"Logout error: {e}")
        return jsonify({'success': False, 'error': 'Logout failed'}), 500

@app.route('/me', methods=['GET'])
def get_current_user():
    """Get current authenticated user"""
    try:
        user = get_authenticated_user()
        if user:
            return jsonify({
                'authenticated': True,
                'user': user
            })
        else:
            return jsonify({'authenticated': False})
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return jsonify({'authenticated': False})

@app.route('/purchase-history', methods=['GET'])
def get_purchase_history():
    """Get purchase history for authenticated user"""
    try:
        logger.info(f"Purchase history request - Session: {dict(session)}")
        logger.info(f"Purchase history request - Headers: {dict(request.headers)}")
        
        user = get_authenticated_user()
        if not user:
            logger.info("No authenticated user found for purchase history request")
            return jsonify({'error': 'Authentication required'}), 401
        
        logger.info(f"Getting purchase history for user: {user['user_id']} ({user['username']})")
        
        fresh_user_data = account_manager.get_user_by_id(user['user_id'])
        if not fresh_user_data:
            return jsonify({'error': 'User not found'}), 404
        
        purchase_history = fresh_user_data.get('purchase_history', [])
        logger.info(f"Found {len(purchase_history)} purchases in history")
        logger.info(f"Purchase history data: {purchase_history}")
        
        return jsonify({
            'purchases': purchase_history,
            'total_purchases': len(purchase_history)
        })
        
    except Exception as e:
        logger.error(f"Error getting purchase history: {e}")
        return jsonify({'error': 'Failed to load purchase history'}), 500

@app.route('/check-gamepass', methods=['POST'])
def check_gamepass():
    """Check gamepass ownership and issue keys."""
    try:
        data = request.get_json()
        logger.info(f"Received gamepass check request: {data}")
        username = data.get('username')
        gamepass_id = data.get('gamepass_id')
        force_refresh = data.get('force_refresh', False)
        logger.info(f"Parsed values - username: {username}, gamepass_id: {gamepass_id}")
        logger.info(f"SUPPORTED_GAMEPASSES: {SUPPORTED_GAMEPASSES}")
        logger.info(f"PRODUCTS_CONFIG: {PRODUCTS_CONFIG}")
        
        authenticated_user = get_authenticated_user()
        if authenticated_user:
            logger.info(f"Authenticated user making gamepass check: {authenticated_user['username']}")
        else:
            logger.info("Unauthenticated gamepass check")
        
        user_lock = get_user_lock(username)
        if not user_lock.acquire(blocking=False):
            logger.warning(f"Concurrent access attempt blocked for user: {username}")
            return jsonify({
                'status': 'Rate Limited',
                'message': 'Please wait, processing your previous request...',
                'shouldRetry': True
            }), 429

        try:
            if not username or not gamepass_id:
                return jsonify({'error': 'Username and gamepass_id are required'}), 400
            
            product_id = None
            if gamepass_id in SUPPORTED_GAMEPASSES:
                product_id = gamepass_id
            else:
                for pid, pconfig in PRODUCTS_CONFIG.items():
                    if str(pconfig['gamepass_id']) == str(gamepass_id):
                        product_id = pid
                        break
            
            if not product_id:
                return jsonify({'error': f'Gamepass {gamepass_id} is not supported'}), 400
            
            product = PRODUCTS_CONFIG[product_id]
            
            user_id, user_error = fetch_user_id(username)
            logger.info(f"User ID fetch result: user_id={user_id}, error={user_error}")
            
            if user_id is None or user_error:
                logger.error(f"Failed to get user ID for {username}: {user_error}")
                if user_error == "USER_NOT_FOUND":
                    return jsonify({
                        'error': 'Username not found',
                        'message': f'Roblox user "{username}" does not exist'
                    }), 404
                elif user_error == "RATE_LIMITED" or user_error == "ROBLOX_RATE_LIMITED":
                    return jsonify({
                        'error': 'Rate limited',
                        'message': 'Too many requests. Please wait a moment and try again.',
                        'shouldRetry': True
                    }), 429
                else:
                    return jsonify({
                        'error': 'Failed to verify user',
                        'message': 'Unable to connect to Roblox services. Please try again later.',
                        'shouldRetry': True
                    }), 503
            
            has_gamepass = check_gamepass_ownership(user_id, product['gamepass_id'], force_refresh)
            logger.info(f"Gamepass ownership check: user_id={user_id}, gamepass_id={product['gamepass_id']}, has_gamepass={has_gamepass}")
            
            if has_gamepass is None:
                return jsonify({
                    'error': 'Service temporarily unavailable',
                    'message': 'Unable to verify gamepass ownership. Please try again later.'
                }), 503
            
            user_data = load_user_data()
            logger.info(f"User data for {username}: {user_data.get(username, 'No data found')}")
            
            if not has_gamepass:
                if (username in user_data and product_id in user_data[username] and 
                    user_data[username][product_id].get('key_issued') and 
                    not user_data[username][product_id].get('ownership_lost')):
                    user_data[username][product_id]['ownership_lost'] = datetime.now().isoformat()
                    threading.Thread(target=save_user_data, args=(user_data,)).start()
                    logger.info(f"Marked ownership lost for {username} - {product['name']}")
                
                return jsonify({
                    'hasGamepass': False,
                    'message': f'You need to purchase the {product["name"]} gamepass first.',
                    'gampassId': product['gamepass_id']
                })
            
            if username not in user_data:
                user_data[username] = {}
            
            user_gamepass_data = user_data[username].get(product_id, {})
            
            if (user_gamepass_data.get('ownership_lost') and 
                user_gamepass_data.get('key_issued')):
                
                ownership_lost_time = datetime.fromisoformat(user_gamepass_data['ownership_lost'])
                if datetime.now() - ownership_lost_time < timedelta(minutes=5):
                    logger.info(f"Detected remove/repurchase cycle for {username} - {product['name']}, issuing new key")
                    
                    key, expiry = key_manager.generate_key_with_expiry(product_id, 
                                                                     product.get('duration_days', 7))
                    
                    user_data[username][product_id] = {
                        'key_issued': True,
                        'issued_at': datetime.now().isoformat(),
                        'key': key,
                        'expiry_date': expiry.isoformat(),
                        'previous_key': user_gamepass_data.get('key', 'unknown')
                    }
                    
                    def update_github_async():
                        try:
                            stock_file = product.get('stock_file', f'{gamepass_id.upper()}-Stock')
                            current_stock = github_manager.get_file_content(stock_file)
                            
                            if current_stock and len(current_stock) > 0:
                                updated_stock = current_stock[1:] 
                                github_manager.update_file_content(stock_file, updated_stock, 
                                                                 f"Dispensed key for {product['name']}. Remaining: {len(updated_stock)}")
                                logger.info(f"Dispensed key from stock for {product['name']}. Remaining stock: {len(updated_stock)}")
                                
                                bought_file = product.get('bought_file', 'Keys-Bought')
                                bought_keys = github_manager.get_file_content(bought_file) or []
                                bought_keys.append(key)
                                github_manager.update_file_content(bought_file, bought_keys, 
                                                                 f"Added dispensed key for {product['name']}")
                                logger.info(f"Successfully updated {bought_file.replace('-', ' ')} with {len(bought_keys)} keys")
                            
                            save_user_data(user_data)
                        except Exception as e:
                            logger.error(f"Error in async GitHub update: {e}")
                    
                    if authenticated_user:
                        purchase_data = {
                            'product_name': product['name'],
                            'product_id': product_id,
                            'key': key,
                            'roblox_username': username,
                            'price': product.get('price', 1),
                            'gamepass_id': product['gamepass_id']
                        }
                        
                        success = account_manager.add_purchase_to_history(authenticated_user['user_id'], purchase_data)
                        if success:
                            logger.info(f"Successfully added repurchase to account history for user {authenticated_user['user_id']}")
                        else:
                            logger.error(f"Failed to add repurchase to account history for user {authenticated_user['user_id']}")
                    
                    threading.Thread(target=update_github_async).start()
                    
                    return jsonify({
                        'hasGamepass': True,
                        'keyIssued': True,
                        'key': key,
                        'message': f'New key issued for {product["name"]}!',
                        'expiryDate': expiry.isoformat(),
                        'isNewKey': True
                    })
            
            if user_gamepass_data.get('key_issued'):
                existing_key = user_gamepass_data.get('key', 'Key not found')
                expiry_date = user_gamepass_data.get('expiry_date')
                logger.info(f"User {username} already has key for {product['name']}: {existing_key}")
                
                logger.info(f"Returning existing key for {username}")
                return jsonify({
                    'hasGamepass': True,
                    'keyIssued': True,
                    'key': existing_key,
                    'message': f'You already have a key for {product["name"]}!',
                    'expiryDate': expiry_date,
                    'isNewKey': False
                })
            
            key, expiry = key_manager.generate_key_with_expiry(product_id, 
                                                             product.get('duration_days', 7))
            
            user_data[username][product_id] = {
                'key_issued': True,
                'issued_at': datetime.now().isoformat(),
                'key': key,
                'expiry_date': expiry.isoformat()
            }
            
            def update_github_async():
                try:
                    stock_file = product.get('stock_file', f'{gamepass_id.upper()}-Stock')
                    current_stock = github_manager.get_file_content(stock_file)
                    
                    if current_stock and len(current_stock) > 0:
                        updated_stock = current_stock[1:]  
                        github_manager.update_file_content(stock_file, updated_stock, 
                                                         f"Dispensed key for {product['name']}. Remaining: {len(updated_stock)}")
                        logger.info(f"Dispensed key from stock for {product['name']}. Remaining stock: {len(updated_stock)}")
                        
                        bought_file = product.get('bought_file', 'Keys-Bought')
                        bought_keys = github_manager.get_file_content(bought_file) or []
                        bought_keys.append(key)
                        github_manager.update_file_content(bought_file, bought_keys, 
                                                         f"Added dispensed key for {product['name']}")
                        logger.info(f"Successfully updated {bought_file.replace('-', ' ')} with {len(bought_keys)} keys")
                    
                    save_user_data(user_data)
                except Exception as e:
                    logger.error(f"Error in async GitHub update: {e}")
            
            logger.info(f"New key issued for {username} - {product['name']}")
            
            logger.info("Checking for authenticated user to add purchase to history...")
            if authenticated_user:
                logger.info(f"Found authenticated user: {authenticated_user['username']} ({authenticated_user['user_id']})")
                
                purchase_data = {
                    'product_name': product['name'],
                    'product_id': product_id,
                    'key': key,
                    'roblox_username': username,
                    'price': product.get('price', 1),
                    'gamepass_id': product['gamepass_id']
                }
                
                logger.info(f"Attempting to add purchase to history: {purchase_data}")
                
                success = account_manager.add_purchase_to_history(authenticated_user['user_id'], purchase_data)
                if success:
                    logger.info(f"Successfully added purchase to account history for user {authenticated_user['user_id']}")
                else:
                    logger.error(f"Failed to add purchase to account history for user {authenticated_user['user_id']}")
            else:
                logger.warning("No authenticated user found - purchase will not be added to account history")
            
            threading.Thread(target=update_github_async).start()
            
            return jsonify({
                'hasGamepass': True,
                'keyIssued': True,
                'key': key
            })
            
        finally:
            if 'user_lock' in locals():
                user_lock.release()
            
    except Exception as e:
        logger.error(f"Error in gamepass check: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/')
def serve_index():
    return send_file('index.html')

@app.route('/index.html')
def serve_index_explicit():
    return send_file('index.html')

@app.route('/auth.html')
def serve_auth():
    return send_file('auth.html')

@app.route('/license.html')
def serve_license():
    return send_file('license.html')

@app.route('/history.html')
def serve_history():
    return send_file('history.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
