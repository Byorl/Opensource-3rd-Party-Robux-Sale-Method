import time
import urllib.parse
import requests
import logging
import json
import threading
import secrets
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

lock = threading.Lock()

SUPPORTED_GAMEPASSES = ['7day-gamepass-id', '30day-gamepass-id']

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

def fetch_user_id(username):
    """Fetch a Roblox user ID by username, handling rate-limiting differently."""
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
            return user_data['data'][0]['id'], None
        
        logger.warning(f"No user match for: {username}")
        return None, "USER_NOT_FOUND"

    except requests.RequestException as e:
        logger.error(f"User fetch error: {e}")
        return None, str(e)

def check_gamepass_ownership(user_id, gamepass_id):
    """Check if a user owns a specific GamePass, handling rate-limiting differently."""
    url = f'https://inventory.roblox.com/v1/users/{user_id}/items/GamePass/{gamepass_id}'
    
    try:
        response = requests.get(url, timeout=10)
        
        if response.status_code == 429:
            logger.warning(f"Rate limit reached for gamepass check.")
            return None, "RATE_LIMITED"
            
        response.raise_for_status()
        data = response.json()
        return bool(data.get('data')), None

    except requests.RequestException as e:
        logger.error(f"GamePass ownership check failed: {e}")
        return None, str(e)

def generate_key():
    """Generate a gamepass key with 'ByorlHub_' prefix and only letters/numbers."""
    key = secrets.token_urlsafe(16)
    key = key.replace('_', '')
    key = f"ByorlHub_{key}"
    return key

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
            user_data[username] = {'7day': False, '30day': False}

        if gamepass_id == '7day-gamepass-id' and not has_gamepass and username in user_data:
            user_data[username]['7day'] = False
            save_user_data(user_data)
            return jsonify({
                'hasGamePass': False,
                'keyIssued': False,
                'redirect': True,
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
            })

        if has_gamepass:
            if gamepass_id == '7day-gamepass-id' and user_data[username]['7day']:
                return jsonify({
                    'hasGamePass': True,
                    'keyIssued': False,
                    'message': 'Key already redeemed.'
                })
            elif gamepass_id == '30day-gamepass-id' and user_data[username]['30day']:
                return jsonify({
                    'hasGamePass': True,
                    'keyIssued': False,
                    'message': 'Key already redeemed.'
                })
            else:
                key = generate_key()
                if gamepass_id == '7day-gamepass-id':
                    user_data[username]['7day'] = True
                else:
                    user_data[username]['30day'] = True

                save_user_data(user_data)
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
                'gamepassLink': f"https://www.roblox.com/game-pass/{gamepass_id}"
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