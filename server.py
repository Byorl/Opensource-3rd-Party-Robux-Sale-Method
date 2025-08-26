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
                data = json.load(f)
                return cleanup_old_entries(data)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error reading user data file: {e}")
        return {}

def save_user_data(data):
    """Save user data to a JSON file."""
    try:
        cleaned_data = cleanup_old_entries(data)
        with open(USER_DATA_PATH, 'w') as f:
            json.dump(cleaned_data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

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
    
    cached_result = get_cached_response(cache_key, 300) 
    if cached_result:
        return cached_result
    
    rate_key = f"user_fetch_{username.lower()}"
    if is_rate_limited(rate_key, 15):  
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

def check_gamepass_ownership(user_id, gamepass_id, force_refresh=False):
    """Check if a user owns a specific GamePass with caching and improved rate limiting."""
    cache_key = f"gamepass_{user_id}_{gamepass_id}"
    

    if not force_refresh:
        cached_result = get_cached_response(cache_key, 10) 
        if cached_result:
            return cached_result
    
    rate_key = f"gamepass_check_{user_id}_{gamepass_id}"
    rate_limit_seconds = 5 if force_refresh else 10
    if is_rate_limited(rate_key, rate_limit_seconds):
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

@app.route('/admin/reset-user-key', methods=['POST'])
def reset_user_key():
    """Reset a specific user's key for a gamepass (admin function)."""
    try:
        data = request.get_json()
        username = data.get('username')
        gamepass_id = data.get('gamepass_id')
        
        if not username or not gamepass_id:
            return jsonify({'success': False, 'error': 'Username and gamepass_id required'}), 400
        
        user_data = load_user_data()
        if username in user_data and gamepass_id in user_data[username]:
            del user_data[username][gamepass_id]
            if not user_data[username]: 
                del user_data[username]
            save_user_data(user_data)
            logger.info(f"Reset key for {username} - {gamepass_id}")
            return jsonify({'success': True, 'message': f'Key reset for {username}'})
        else:
            return jsonify({'success': False, 'error': 'User or gamepass not found'})
    except Exception as e:
        logger.error(f"Failed to reset user key: {e}")
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
        force_refresh = data.get('force_refresh', False)

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

        has_gamepass, gamepass_error = check_gamepass_ownership(user_id, gamepass_id, force_refresh)
        
        if gamepass_error == "RATE_LIMITED":
            return jsonify({
                'status': 'Rate Limited',
                'message': 'Please wait a moment...',
                'shouldRetry': True,
                'hasGamePass': False,
                'keyIssued': False,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
            }), 429

        product = PRODUCTS_CONFIG.get(gamepass_id)
        if not product:
            return jsonify({'error': 'Invalid gamepass ID'}), 400

        gamepass_link = product.get('gamepassUrl', f"https://www.roblox.com/game-pass/{gamepass_id}")

        if not has_gamepass:
            user_data = load_user_data()
            if username in user_data and gamepass_id in user_data[username]:
                user_data[username][gamepass_id]['ownership_lost'] = datetime.now().isoformat()
                save_user_data(user_data)
                logger.info(f"Marked ownership lost for {username} - {product['name']}")
            
            return jsonify({
                'hasGamePass': False,
                'keyIssued': False,
                'redirect': True,
                'gamepassLink': gamepass_link
            })

        user_data = load_user_data()
        
        if username not in user_data:
            user_data[username] = {}

        user_gamepass_data = user_data[username].get(gamepass_id, {})
        
        if isinstance(user_gamepass_data, dict) and user_gamepass_data.get('key_issued'):
            issued_time = datetime.fromisoformat(user_gamepass_data['issued_at'])
            current_time = datetime.now()
            
            if 'ownership_lost' in user_gamepass_data:
                logger.info(f"Detected remove/repurchase cycle for {username} - {product['name']}, issuing new key")
                key = generate_key()
                user_data[username][gamepass_id] = {
                    'key_issued': True,
                    'issued_at': current_time.isoformat(),
                    'key': key,
                    'previous_key': user_gamepass_data.get('key', 'unknown')
                }
                save_user_data(user_data)
                
                return jsonify({
                    'hasGamePass': True,
                    'keyIssued': True,
                    'key': key,
                    'message': 'New key issued after repurchase!'
                })
            
            if force_refresh:
                if current_time - issued_time > timedelta(minutes=5):
                    logger.info(f"Force refresh: Key was issued over 5 minutes ago for {username} - {product['name']}, issuing new key")
                    key = generate_key()
                    user_data[username][gamepass_id] = {
                        'key_issued': True,
                        'issued_at': current_time.isoformat(),
                        'key': key,
                        'previous_key': user_gamepass_data.get('key', 'unknown')
                    }
                    save_user_data(user_data)
                    
                    return jsonify({
                        'hasGamePass': True,
                        'keyIssued': True,
                        'key': key,
                        'message': 'New key issued after repurchase!'
                    })
                else:
                    return jsonify({
                        'hasGamePass': True,
                        'keyIssued': True,
                        'key': user_gamepass_data['key'],
                        'message': 'Key retrieved successfully!'
                    })
            else:
                if current_time - issued_time > timedelta(minutes=30):
                    logger.info(f"Regular check: Key was issued over 30 minutes ago for {username} - {product['name']}, allowing new key")
                    key = generate_key()
                    user_data[username][gamepass_id] = {
                        'key_issued': True,
                        'issued_at': current_time.isoformat(),
                        'key': key,
                        'previous_key': user_gamepass_data.get('key', 'unknown')
                    }
                    save_user_data(user_data)
                    
                    return jsonify({
                        'hasGamePass': True,
                        'keyIssued': True,
                        'key': key,
                        'message': 'New key issued successfully!'
                    })
                else:
                    return jsonify({
                        'hasGamePass': True,
                        'keyIssued': True,
                        'key': user_gamepass_data['key'],
                        'message': 'Key retrieved successfully!'
                    })
        else:
            key = generate_key()
            user_data[username][gamepass_id] = {
                'key_issued': True,
                'issued_at': datetime.now().isoformat(),
                'key': key
            }
            save_user_data(user_data)
            
            logger.info(f"New key issued for {username} - {product['name']}")
            return jsonify({
                'hasGamePass': True,
                'keyIssued': True,
                'key': key,
                'message': 'Key issued successfully!'
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
