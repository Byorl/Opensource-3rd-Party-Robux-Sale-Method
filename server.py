import time
import urllib.parse
import requests
import logging
import json
import threading
import secrets
import os
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

lock = threading.Lock()
rate_limit_cache = {}
request_cache = {}

# Load products configuration
def load_products_config():
    try:
        with open('config/products.json', 'r') as f:
            config = json.load(f)
            return {product['gamepassId']: product for product in config['products']}
    except Exception as e:
        logger.error(f"Failed to load products config: {e}")
        return {}

PRODUCTS_CONFIG = load_products_config()
SUPPORTED_GAMEPASSES = list(PRODUCTS_CONFIG.keys())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_DATA_PATH = os.path.join(BASE_DIR, 'user_data.json')

def init_user_data():
    """Initialize the user data file if it doesn't exist."""
    if not os.path.exists(USER_DATA_PATH):
        logger.info(f"User data file {USER_DATA_PATH} not found. Creating a new one.")
        save_user_data({})
        logger.info("User data file initialized successfully.")

def load_user_data():
    """Load user data from a JSON file."""
    try:
        if os.path.exists(USER_DATA_PATH):
            with open(USER_DATA_PATH, 'r') as f:
                return json.load(f)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error reading user data file: {e}")
        return {}

def save_user_data(data):
    """Save user data to a JSON file."""
    try:
        with open(USER_DATA_PATH, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

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

def fetch_user_id(username):
    """Fetch a Roblox user ID by username with caching and improved rate limiting."""
    cache_key = f"user_id_{username.lower()}"
    
    # Check cache first
    cached_result = get_cached_response(cache_key, 300)  # Cache for 5 minutes
    if cached_result:
        return cached_result
    
    # Check rate limiting
    rate_key = f"user_fetch_{username.lower()}"
    if is_rate_limited(rate_key, 15):  # 15 second rate limit per user
        return None, "RATE_LIMITED"
    
    encoded_username = urllib.parse.quote(username)
    search_url = f'https://users.roblox.com/v1/users/search?keyword={encoded_username}'
    
    try:
        response = requests.get(search_url, timeout=10)
        
        if response.status_code == 429:
            logger.warning(f"Rate limit reached for {username}.")
            return None, "RATE_LIMITED"
            
        response.raise_for_status()
        user_data = response.json()

        if user_data['data']:
            result = user_data['data'][0]['id'], None
            cache_response(cache_key, result)
            return result
        
        logger.warning(f"No user match for: {username}")
        result = None, "USER_NOT_FOUND"
        cache_response(cache_key, result)
        return result

    except requests.RequestException as e:
        logger.error(f"User fetch error: {e}")
        return None, str(e)

def check_gamepass_ownership(user_id, gamepass_id):
    """Check if a user owns a specific GamePass with caching and improved rate limiting."""
    cache_key = f"gamepass_{user_id}_{gamepass_id}"
    
    # Check cache first (shorter cache for gamepass ownership)
    cached_result = get_cached_response(cache_key, 30)  # Cache for 30 seconds
    if cached_result:
        return cached_result
    
    # Check rate limiting
    rate_key = f"gamepass_check_{user_id}_{gamepass_id}"
    if is_rate_limited(rate_key, 10):  # 10 second rate limit per user/gamepass combo
        return None, "RATE_LIMITED"
    
    url = f'https://inventory.roblox.com/v1/users/{user_id}/items/GamePass/{gamepass_id}'
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            logger.warning(f"Rate limit reached for gamepass check.")
            return None, "RATE_LIMITED"
            
        response.raise_for_status()
        data = response.json()
        result = bool(data.get('data')), None
        cache_response(cache_key, result)
        return result

    except requests.RequestException as e:
        logger.error(f"GamePass ownership check failed: {e}")
        return None, str(e)

def generate_key():
    """Generate a gamepass key with 'ByorlHub_' prefix and only letters/numbers."""
    key = secrets.token_urlsafe(16)
    key = key.replace('_', '')
    key = f"ByorlHub_{key}"
    return key

@app.route('/products', methods=['GET'])
def get_products():
    """Serve the products configuration."""
    try:
        with open('config/products.json', 'r') as f:
            return jsonify(json.load(f))
    except Exception as e:
        logger.error(f"Failed to load products: {e}")
        return jsonify({'error': 'Failed to load products'}), 500

@app.route('/admin/clear-user-data', methods=['POST'])
def clear_user_data():
    """Clear all user data (admin function)."""
    try:
        save_user_data({})
        logger.info("User data cleared by admin")
        return jsonify({'success': True, 'message': 'User data cleared successfully'})
    except Exception as e:
        logger.error(f"Failed to clear user data: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/check-gamepass', methods=['POST'])
def check_gamepass():
    if not lock.acquire(blocking=False):
        logger.warning("Concurrent access attempt blocked")
        return jsonify({
            'status': 'Rate Limited',
            'message': 'Server is busy, please wait...',
            'shouldRetry': True
        }), 429

    try:
        data = request.get_json()
        username = data.get('username')
        gamepass_id = data.get('gamepass_id')

        if not username or not gamepass_id:
            return jsonify({'error': 'Username and gamepass_id are required'}), 400

        if gamepass_id not in SUPPORTED_GAMEPASSES:
            return jsonify({'error': 'Unsupported GamePass'}), 400

        user_id, user_error = fetch_user_id(username)
        
        if user_error == "RATE_LIMITED":
            return jsonify({
                'status': 'Rate Limited',
                'message': 'Please wait a moment...',
                'shouldRetry': True,
                'hasGamePass': False,
                'keyIssued': False,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
                
            }), 429
            
        if user_error == "USER_NOT_FOUND":
            return jsonify({
                'error': 'Username not found',
                'hasGamePass': False,
                'keyIssued': False,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
            }), 404

        if user_id is None:
            return jsonify({
                'error': f'Error fetching user data: {user_error}',
                'hasGamePass': False,
                'keyIssued': False,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
            }), 500

        has_gamepass, gamepass_error = check_gamepass_ownership(user_id, gamepass_id)
        
        if gamepass_error == "RATE_LIMITED":
            return jsonify({
                'status': 'Rate Limited',
                'message': 'Please wait a moment...',
                'shouldRetry': True,
                'hasGamePass': False,
                'keyIssued': False,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
            }), 429

        user_data = load_user_data()
        if username not in user_data:
            user_data[username] = {}
            for product_id in PRODUCTS_CONFIG:
                user_data[username][product_id] = False

        # Get product info
        product = PRODUCTS_CONFIG.get(gamepass_id)
        if not product:
            return jsonify({'error': 'Invalid gamepass ID'}), 400

        gamepass_link = product.get('gamepassUrl', f"https://www.roblox.com/game-pass/{gamepass_id}")

        if not has_gamepass:
            # Update user data to reflect they don't own the gamepass
            user_data[username][gamepass_id] = False
            save_user_data(user_data)
            return jsonify({
                'hasGamePass': False,
                'keyIssued': False,
                'redirect': True,
                'gamepassLink': gamepass_link
            })

        if has_gamepass:
            # Check if key already redeemed
            if user_data[username].get(gamepass_id, False):
                return jsonify({
                    'hasGamePass': True,
                    'keyIssued': False,
                    'message': f'Key already redeemed for {product["name"]}.'
                })
            else:
                # Issue new key
                key = generate_key()
                user_data[username][gamepass_id] = True
                save_user_data(user_data)
                
                logger.info(f"Key issued for {username} - {product['name']}")
                return jsonify({
                    'hasGamePass': True,
                    'keyIssued': True,
                    'key': key,
                    'message': 'Key issued successfully!'
                })
        else:
            return jsonify({
                'hasGamePass': False,
                'keyIssued': False,
                'redirect': True,
                'gamepassLink': gamepass_link
            })

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({
            'error': f"Unexpected error: {e}",
            'hasGamePass': False,
            'keyIssued': False,
            'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
        }), 500

    finally:
        lock.release()

if __name__ == '__main__':
    init_user_data()
    app.run(debug=False, host="0.0.0.0", port=5000)
