import urllib.parse
import requests
import logging
import json
import threading
import secrets
import os
import bcrypt
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, session, send_file, make_response
from flask_cors import CORS
from github_stock import GitHubStockManager
import time
from contextlib import contextmanager
import hashlib
from dotenv import load_dotenv

app = Flask(__name__, static_folder='.', static_url_path='')
_allowed_origins_env = os.getenv('ALLOWED_ORIGINS') or 'http://localhost:5000,http://127.0.0.1:5000'
_allowed_origins = [o.strip() for o in _allowed_origins_env.split(',') if o.strip()]
if 'null' not in _allowed_origins:
    _allowed_origins.append('null')
CORS(app, supports_credentials=True, origins=_allowed_origins)
app.secret_key = secrets.token_hex(32)

load_dotenv('config/.env')

PRODUCTS_CONFIG = {}
ADMIN_CONFIG = {}
SETTINGS = {}
SUPPORTED_GAMEPASSES = []
PENDING_PURCHASE_EXPIRY_SECONDS = 3600  
PRE_START_GRACE_SECONDS = 300  
CHECK_GAMEPASS_COOLDOWN_SECONDS = 3 
_products_config_mtime = None
_products_config_lock = threading.Lock()
_last_forced_push_time = 0  

_roblox_tx_cache = {}
_roblox_tx_cache_time = {}
_roblox_buyer_name_cache = {}
_user_last_api_call = {}
_tx_fetch_debug = {}

_claimed_transactions = None  
_claimed_transactions_lock = threading.Lock()
_claimed_transactions_file = 'Claimed-Transactions'
_ownership_cycles = {}  

def _claimed_file_name():
    try:
        return SETTINGS.get('roblox', {}).get('claimedFile') or _claimed_transactions_file
    except Exception:
        return _claimed_transactions_file

def _load_claimed_transactions(force: bool = False):
    """Load (or return cached) set of claimed transaction IDs from GitHub storage.
    This file is stored as newline-separated JSON or plain lines of transaction IDs.
    """
    global _claimed_transactions
    if _claimed_transactions is not None and not force:
        return _claimed_transactions
    claimed = set()
    try:
        if github_manager:
            lines = github_manager.get_file_content(_claimed_file_name()) or []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('{') and line.endswith('}'):
                    try:
                        obj = json.loads(line)
                        tid = obj.get('transactionId') or obj.get('id')
                        if tid:
                            claimed.add(tid)
                    except Exception:
                        continue
                else:
                    claimed.add(line)
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed loading claimed transactions: {e}")
    _claimed_transactions = claimed
    return _claimed_transactions

def _persist_claimed_transactions():
    """Persist current claimed transaction id set back to GitHub."""
    if _claimed_transactions is None:
        return
    try:
        if not github_manager:
            return
        lines = sorted(list(_claimed_transactions))
        github_manager.update_file_content(_claimed_file_name(), lines, f"Update claimed transactions ({len(lines)})")
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed persisting claimed transactions: {e}")

def _fetch_user_transactions(username: str, force_refresh: bool = False, limit: int = None):
    """Fetch recent PURCHASE transactions for a given buyer (user perspective).

    This complements _fetch_sale_transactions (developer/seller perspective). We look up the
    target user's id and call the Purchase transaction endpoint. Returns a list of normalized
    dicts [{transactionId, created, detailsId, details, buyerName}]. Always returns a list.
    Caches results for a short window unless force_refresh is True.
    """
    roblox_cfg = SETTINGS.get('roblox', {})
    cookie = roblox_cfg.get('securityCookie')
    if not cookie:
        logger.warning(f"[TXFETCH][purchase] No securityCookie configured; cannot fetch purchase transactions for {username}")
        _tx_fetch_debug[username.lower()] = {
            'mode': 'purchase', 'reason': 'NO_COOKIE', 'count': 0,
            'force_refresh': force_refresh, 'ts': datetime.now(timezone.utc).isoformat()+'Z'
        }
        return []
    if 'PUT_.ROBLOSECURITY' in cookie:
        logger.warning(f"[TXFETCH][purchase] Placeholder cookie detected; update config to real .ROBLOSECURITY value")
        _tx_fetch_debug[username.lower()] = {
            'mode': 'purchase', 'reason': 'PLACEHOLDER_COOKIE', 'count': 0,
            'force_refresh': force_refresh, 'ts': datetime.now(timezone.utc).isoformat()+'Z'
        }
        return []
    if limit is None:
        limit = roblox_cfg.get('transactionsLimit', 25)
    if limit > 100:
        limit = 100
    cache_key = f"purchase_tx_{username.lower()}"
    now = time.time()
    if (not force_refresh) and cache_key in _roblox_tx_cache and (now - _roblox_tx_cache_time.get(cache_key,0)) < 10:
        _tx_fetch_debug[username.lower()] = {
            'mode':'purchase','reason':'CACHE_HIT','count':len(_roblox_tx_cache[cache_key]),
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat()+'Z'
        }
        return _roblox_tx_cache[cache_key]
    rl_key = f"purchase_{username.lower()}"
    last_call = _user_last_api_call.get(rl_key, 0)
    min_interval = 0.5 if force_refresh else 2
    if now - last_call < min_interval:
        if cache_key in _roblox_tx_cache:
            _tx_fetch_debug[username.lower()] = {
                'mode':'purchase','reason':'RATE_LIMIT_CACHE','count':len(_roblox_tx_cache[cache_key]),
                'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat()+'Z'
            }
            return _roblox_tx_cache[cache_key]
        _tx_fetch_debug[username.lower()] = {
            'mode':'purchase','reason':'RATE_LIMIT_NO_CACHE','count':0,
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat()+'Z'
        }
        return []
    _user_last_api_call[rl_key] = now
    headers = {'Cookie': f'.ROBLOSECURITY={cookie}', 'Accept': 'application/json'}
    try:
        uid, _err = fetch_user_id(username)
        if not uid:
            return []
        url = f'https://economy.roblox.com/v2/users/{uid}/transactions?transactionType=Purchase&limit={limit}&sortOrder=Desc'
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            try:
                body = resp.text[:1000]
            except Exception:
                body = ''
            if resp.status_code == 429:
                _user_last_api_call[rl_key] = now
            _tx_fetch_debug[username.lower()] = {
                'mode':'purchase','reason':f'HTTP_{resp.status_code}','count':0,
                'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                'httpBody': body
            }
            logger.warning(f"Purchase transactions HTTP {resp.status_code} for uid={uid}: {body}")
            return []
        raw = resp.json().get('data', [])
        out = []
        sample = []
        for t in raw:
            if len(sample) < 3:
                sample.append({k: t.get(k) for k in ['id','created','agent','details']})
            tx_id = t.get('id') or t.get('transactionId') or t.get('purchaseToken') or t.get('idHash')
            created = t.get('created')
            details = t.get('details') or {}
            details_id = details.get('id')
            details_name = details.get('name')
            if not tx_id or not created:
                continue
            out.append({
                'transactionId': tx_id,
                'created': created,
                'detailsId': details_id,
                'details': details_name,
                'buyerName': username
            })
        _roblox_tx_cache[cache_key] = out
        _roblox_tx_cache_time[cache_key] = now
        _tx_fetch_debug[username.lower()] = {
            'mode': 'purchase',
            'username': username,
            'force_refresh': force_refresh,
            'count': len(out),
            'sample': sample,
            'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return out
    except Exception as e:
        logger.warning(f"Purchase transaction fetch failure for {username}: {e}")
        _tx_fetch_debug[username.lower()] = {
            'mode':'purchase','reason':f'EXC_{type(e).__name__}','count':0,
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return []

def _fetch_sale_transactions(username: str, force_refresh: bool = False, limit: int = None):
    """Fetch recent SALE transactions (developer sales) and match those where buyer == username.

    This mirrors logic from the separate Greier script but adds caching, rate limiting, and
    normalization. Use this when the account whose cookie we have is the CREATOR receiving the
    Robux from the user's gamepass purchase. The sale record contains the buyer (agent) we match.
    """
    roblox_cfg = SETTINGS.get('roblox', {})
    cookie = roblox_cfg.get('securityCookie')
    if not cookie:
        logger.warning(f"[TXFETCH][sale] No securityCookie configured; cannot fetch sale transactions for buyer={username}")
        _tx_fetch_debug[username.lower()] = {
            'mode':'sale','reason':'NO_COOKIE','count':0,'force_refresh':force_refresh,'ts':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return []
    if 'PUT_.ROBLOSECURITY' in cookie:
        logger.warning(f"[TXFETCH][sale] Placeholder cookie detected; update config")
        _tx_fetch_debug[username.lower()] = {
            'mode':'sale','reason':'PLACEHOLDER_COOKIE','count':0,'force_refresh':force_refresh,'ts':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return []
    if limit is None:
        limit = roblox_cfg.get('saleTransactionsLimit', roblox_cfg.get('transactionsLimit', 100))
    cache_key = f"sale_tx_{username.lower()}"
    now = time.time()
    if (not force_refresh) and cache_key in _roblox_tx_cache and (now - _roblox_tx_cache_time.get(cache_key,0)) < 8:
        _tx_fetch_debug[username.lower()] = {
            'mode':'sale','reason':'CACHE_HIT','count':len(_roblox_tx_cache[cache_key]),
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return _roblox_tx_cache[cache_key]
    rl_key = f"sale_{username.lower()}"
    last_call = _user_last_api_call.get(rl_key, 0)
    min_interval = 0.4 if force_refresh else 2
    if now - last_call < min_interval:
        if cache_key in _roblox_tx_cache:
            _tx_fetch_debug[username.lower()] = {
                'mode':'sale','reason':'RATE_LIMIT_CACHE','count':len(_roblox_tx_cache[cache_key]),
                'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
            }
            return _roblox_tx_cache[cache_key]
        _tx_fetch_debug[username.lower()] = {
            'mode':'sale','reason':'RATE_LIMIT_NO_CACHE','count':0,
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return []
    _user_last_api_call[rl_key] = now
    headers = {'Cookie': f'.ROBLOSECURITY={cookie}', 'Accept': 'application/json'}
    try:
        auth_resp = requests.get('https://users.roblox.com/v1/users/authenticated', headers=headers, timeout=10)
        if auth_resp.status_code != 200:
            _tx_fetch_debug[username.lower()] = {
                'mode':'sale','reason':f'AUTH_{auth_resp.status_code}','count':0,
                'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
            }
            return []
        seller_id = auth_resp.json().get('id')
        if not seller_id:
            return []
        if limit > 100: 
            limit = 100
        url = f'https://economy.roblox.com/v2/users/{seller_id}/transactions?transactionType=sale&limit={limit}&sortOrder=Desc'
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            _tx_fetch_debug[username.lower()] = {
                'mode':'sale','reason':f'SALES_HTTP_{resp.status_code}','count':0,
                'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
            }
            return []
        data = resp.json().get('data', [])
        matched = []
        samples = []
        for tx in data:
            if len(samples) < 3:
                samples.append({k: tx.get(k) for k in ['id','created','agent','details','currency']})
            agent = tx.get('agent') or {}
            buyer_id = agent.get('id')
            if not buyer_id:
                continue
            buyer_name = _roblox_buyer_name_cache.get(buyer_id)
            if not buyer_name:
                try:
                    u_resp = requests.get(f'https://users.roblox.com/v1/users/{buyer_id}', headers=headers, timeout=5)
                    if u_resp.status_code == 200:
                        buyer_name = u_resp.json().get('name')
                        if buyer_name:
                            _roblox_buyer_name_cache[buyer_id] = buyer_name
                except Exception:
                    buyer_name = None
            if not buyer_name:
                continue
            if buyer_name.lower() != username.lower():
                continue
            tx_id = tx.get('id') or tx.get('transactionId') or tx.get('purchaseToken') or tx.get('idHash')
            created = tx.get('created')
            details = tx.get('details', {})
            matched.append({
                'transactionId': tx_id,
                'created': created,
                'details': details.get('name'),
                'detailsId': details.get('id'),
                'amount': (tx.get('currency') or {}).get('amount'),
                'buyerName': buyer_name
            })
        _roblox_tx_cache[cache_key] = matched
        _roblox_tx_cache_time[cache_key] = now
        _tx_fetch_debug[username.lower()] = {
            'mode': 'sale',
            'count': len(matched),
            'sample': samples,
            'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return matched
    except Exception as e:
        logger.warning(f"Sale transaction fetch failure: {e}")
        _tx_fetch_debug[username.lower()] = {
            'mode':'sale','reason':f'EXC_{type(e).__name__}','count':0,
            'force_refresh': force_refresh,'ts': datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        }
        return []

def _refetch_transactions_fallback(username: str, force_refresh: bool = False):
    """Fallback lightweight implementation if primary merged logic changes.
    Performs a simple fetch of recent sale transactions and caches them. This is
    less feature-rich than the diagnostic-heavy version but preserves functionality.
    """
    roblox_cfg = SETTINGS.get('roblox', {})
    cookie = roblox_cfg.get('securityCookie')
    limit = roblox_cfg.get('transactionsLimit', 10)
    if not cookie or 'PUT_.ROBLOSECURITY' in cookie:
        return []
    now = time.time()
    cache_key = f"tx_{username.lower()}"
    if (not force_refresh) and cache_key in _roblox_tx_cache and (now - _roblox_tx_cache_time.get(cache_key,0)) < 15:
        return _roblox_tx_cache[cache_key]
    headers = {'Cookie': f'.ROBLOSECURITY={cookie}', 'Accept': 'application/json'}
    try:
        uid, _ = fetch_user_id(username)
        if not uid:
            return []
        sales_url = f'https://economy.roblox.com/v2/users/{uid}/transactions?transactionType=sale&limit={limit}&sortOrder=Desc'
        resp = requests.get(sales_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json().get('data', [])
        out = []
        for tx in data:
            buyer_id = tx.get('agent', {}).get('id')
            if not buyer_id:
                continue
            tx_id = tx.get('id') or tx.get('transactionId') or tx.get('purchaseToken')
            created = tx.get('created')
            if not tx_id or not created:
                continue
            out.append({
                'transactionId': tx_id,
                'created': created,
                'amount': tx.get('currency', {}).get('amount'),
                'details': tx.get('details', {}).get('name'),
                'buyerName': username
            })
        _roblox_tx_cache[cache_key] = out
        _roblox_tx_cache_time[cache_key] = now
        return out
    except Exception:
        return []

def _load_products_config(force: bool = False):
    """Load products configuration from config/products.json.
    Reload only if file mtime changed unless force=True.
    """
    global PRODUCTS_CONFIG, SUPPORTED_GAMEPASSES, _products_config_mtime, github_manager, ADMIN_CONFIG, SETTINGS
    path = 'config/products.json'
    try:
        if not os.path.exists(path):
            return
        current_mtime = os.path.getmtime(path)
        if force or _products_config_mtime is None or current_mtime != _products_config_mtime:
            with _products_config_lock:
                if force or _products_config_mtime is None or current_mtime != _products_config_mtime:
                    with open(path, 'r') as f:
                        cfg = json.load(f)
                    products_list = cfg.get('products', [])
                    new_map = {}
                    for p in products_list:
                        try:
                            new_map[p['id']] = {
                                'name': p['name'],
                                'price': p['price'],
                                'gamepass_id': p['gamepassId'],
                                'gamepass_url': p.get('gamepassUrl', f"https://www.roblox.com/game-pass/{p['gamepassId']}") ,
                                'duration': p['duration'],
                                'stock_file': (lambda sf, pid: (sf if sf and '/' in sf else (f"Stock/{sf}" if sf else f"Stock/{pid.upper()}-Stock")))(p.get('stockGithubFile'), p['id']),
                                'bought_file': os.getenv('GITHUB_BOUGHT_FILE', cfg.get('github', {}).get('bought_file', 'Keys-Bought')),
                                'duration_days': 7 if '7' in p['duration'] else 30 if '30' in p['duration'] else 7,
                                'parentProduct': p.get('parentProduct')
                            }
                        except Exception as inner_e:
                            logging.getLogger(__name__).error(f"Failed parsing product {p}: {inner_e}")
                    PRODUCTS_CONFIG = new_map
                    ADMIN_CONFIG = {
                        'username': os.getenv('ADMIN_USERNAME', cfg.get('admin', {}).get('username', '')),
                        'password': os.getenv('ADMIN_PASSWORD', cfg.get('admin', {}).get('password', ''))
                    }
                    SETTINGS = cfg.get('settings', {}) or {}
                    SETTINGS['roblox'] = SETTINGS.get('roblox', {})
                    SETTINGS['roblox']['securityCookie'] = os.getenv('ROBLOX_SECURITY_COOKIE', SETTINGS['roblox'].get('securityCookie', ''))
                    SUPPORTED_GAMEPASSES = list(PRODUCTS_CONFIG.keys())
                    _products_config_mtime = current_mtime
                    logging.getLogger(__name__).info(f"Reloaded products config ({len(PRODUCTS_CONFIG)} products)")
    except Exception as e:
        logging.getLogger(__name__).error(f"Error loading products config: {e}")

def ensure_products_config_loaded():
    _load_products_config()

_load_products_config(force=True)


_latest_stock_snapshot = None
_latest_stock_snapshot_time = 0
_products_cache_lock = threading.Lock()
_products_cache_data = None
_products_cache_etag = None
_products_cache_time = 0
_PRODUCTS_TTL = 5  

def _compute_etag(obj):
    try:
        payload = json.dumps(obj, sort_keys=True, separators=(',',':'))
    except Exception:
        payload = repr(obj)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def _build_products_payload():
    import json as _json
    with open('config/products.json', 'r') as f:
        config = _json.load(f)
    products = []
    for product_id, product_config in PRODUCTS_CONFIG.items():
        try:
            if github_manager:
                stock_file = product_config.get('stock_file', f'Stock/{product_id.upper()}-Stock')
                if '/' not in stock_file:
                    stock_file = f'Stock/{stock_file}'
                current_stock = github_manager.get_file_content(stock_file)
                stock_count = len(current_stock) if current_stock else 0
            else:
                stock_count = 'not_configured'
            products.append({
                'id': product_id,
                'name': product_config.get('name', product_id.title()),
                'price': product_config.get('price', 1),
                'gamepass_id': product_config.get('gamepass_id') or product_config.get('gamepassId'),
                'gamepassUrl': product_config.get('gamepass_url') or product_config.get('gamepassUrl'),
                'duration': product_config.get('duration', '7 Days'),
                'stock': stock_count,
                'parentProduct': product_config.get('parentProduct')
            })
        except Exception as e:
            logger.error(f"Error getting stock for {product_id}: {e}")
            products.append({
                'id': product_id,
                'name': product_config.get('name', product_id.title()),
                'price': product_config.get('price', 1),
                'gamepass_id': product_config.get('gamepass_id') or product_config.get('gamepassId'),
                'gamepassUrl': product_config.get('gamepass_url') or product_config.get('gamepassUrl'),
                'duration': product_config.get('duration', '7 Days'),
                'stock': 'unavailable',
                'parentProduct': product_config.get('parentProduct')
            })
    main_products = []
    if 'mainProducts' in config:
        for main_product in config['mainProducts']:
            variants = [p for p in products if p.get('parentProduct') == main_product['id']]
            total_stock = sum(p['stock'] for p in variants if isinstance(p['stock'], int))
            min_price = min((p['price'] for p in variants), default=0)
            main_products.append({
                **main_product,
                'totalStock': total_stock,
                'minPrice': min_price,
                'variantProducts': variants
            })
    payload = {
        'products': products,
        'mainProducts': main_products,
        'generatedAt': datetime.now(timezone.utc).isoformat() + 'Z'
    }
    return payload

@app.route('/products')
def get_products():
    global _products_cache_data, _products_cache_time, _products_cache_etag
    try:
        now = time.time()
        with _products_cache_lock:
            if (not _products_cache_data) or (now - _products_cache_time > _PRODUCTS_TTL):
                _products_cache_data = _build_products_payload()
                _products_cache_etag = _compute_etag(_products_cache_data)
                _products_cache_time = now
        inm = request.headers.get('If-None-Match')
        if inm and inm == _products_cache_etag:
            resp = make_response('', 304)
        else:
            resp = make_response(jsonify(_products_cache_data))
        resp.headers['Cache-Control'] = 'public, max-age=5'
        resp.headers['ETag'] = _products_cache_etag
        return resp
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        return jsonify({'error': 'Failed to get products'}), 500
    cookie = roblox_cfg.get('securityCookie')
    limit = roblox_cfg.get('transactionsLimit', 10)
    try:
        target_user_id, _target_err = fetch_user_id(username)
    except Exception:
        target_user_id, _target_err = None, 'LOOKUP_FAIL'
    diag = {
        'username': username,
        'force_refresh': force_refresh,
        'used_cache': False,
        'cookie_present': bool(cookie),
        'cookie_placeholder': bool(cookie and 'PUT_.ROBLOSECURITY' in cookie),
        'auth_status': None,
        'sales_status': None,
        'total_sales_records': 0,
        'matched_buyer_records': 0,
        'limit': limit,
        'error': None,
    'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
        'target_user_id': target_user_id,
        'target_lookup_error': _target_err,
        'match_mode': 'id' if target_user_id else 'name',
        'per_tx_name_lookups': 0,
        'per_tx_lookup_fail': 0
    }
    cache_key = f"tx_{username.lower()}"
    now = time.time()
    if (not force_refresh) and cache_key in _roblox_tx_cache and (now - _roblox_tx_cache_time.get(cache_key,0)) < 15:
        diag['used_cache'] = True
        diag['matched_buyer_records'] = len(_roblox_tx_cache[cache_key])
        _tx_fetch_debug[username.lower()] = diag
        return _roblox_tx_cache[cache_key]
    rate_limit_seconds = 0.5 if force_refresh else 2
    user_key = username.lower()
    last_call = _user_last_api_call.get(user_key, 0)
    if now - last_call < rate_limit_seconds:
        logger.info(f"Rate limiting Roblox API for {username}, last call {now - last_call:.1f}s ago (limit: {rate_limit_seconds}s)")
        if cache_key in _roblox_tx_cache:
            diag['used_cache'] = True
            diag['matched_buyer_records'] = len(_roblox_tx_cache[cache_key])
            _tx_fetch_debug[username.lower()] = diag
            logger.info(f"Using expired cache for {username} due to rate limit")
            return _roblox_tx_cache[cache_key]
        else:
            diag['error'] = 'RATE_LIMIT_NO_CACHE'
            _tx_fetch_debug[username.lower()] = diag
            logger.info(f"Rate limited and no cache for {username}")
            return []
    _user_last_api_call[user_key] = now
    def _return_stale(reason):
        diag['error'] = reason
        if cache_key in _roblox_tx_cache:
            diag['used_cache'] = True
            diag['matched_buyer_records'] = len(_roblox_tx_cache[cache_key])
            _tx_fetch_debug[username.lower()] = diag
            logger.info(f"Transaction fetch diag (stale {reason}): {diag}")
            return _roblox_tx_cache[cache_key]
        _tx_fetch_debug[username.lower()] = diag
        logger.info(f"Transaction fetch diag (no stale {reason}): {diag}")
        return []

    if not cookie:
        return _return_stale('NO_COOKIE')
    if 'PUT_.ROBLOSECURITY' in cookie:
        return _return_stale('PLACEHOLDER_COOKIE')
    headers = {'Cookie': f'.ROBLOSECURITY={cookie}', 'Accept': 'application/json'}
    try:
        auth_resp = requests.get('https://users.roblox.com/v1/users/authenticated', headers=headers, timeout=10)
        diag['auth_status'] = auth_resp.status_code
        if auth_resp.status_code != 200:
            if auth_resp.status_code == 429:
                _user_last_api_call[user_key] = now + 60  
            return _return_stale(f'AUTH_{auth_resp.status_code}')
        authed_id = auth_resp.json().get('id')
        sales_url = f'https://economy.roblox.com/v2/users/{authed_id}/transactions?transactionType=sale&limit={limit}&sortOrder=Desc'
        sales_resp = requests.get(sales_url, headers=headers, timeout=10)
        diag['sales_status'] = sales_resp.status_code
        if sales_resp.status_code != 200:
            if sales_resp.status_code == 429:
                _user_last_api_call[user_key] = now + 60 
            return _return_stale(f'SALES_{sales_resp.status_code}')
        raw_json = sales_resp.json()
        data = raw_json.get('data', [])
        diag['total_sales_records'] = len(data)
        sample_records = []
        field_name_set = set()
        agent_id_mismatch = 0
        collected = 0
        for tx in data:
            for k in tx.keys():
                field_name_set.add(k)
            if collected < 3:
                sanitized = {
                    'id': tx.get('id') or tx.get('transactionId'),
                    'created': tx.get('created'),
                    'agent_keys': list(tx.get('agent', {}).keys()) if isinstance(tx.get('agent'), dict) else type(tx.get('agent')).__name__,
                    'agent_id': tx.get('agent', {}).get('id'),
                    'agent_type': tx.get('agent', {}).get('type'),
                    'details_keys': list(tx.get('details', {}).keys()) if isinstance(tx.get('details'), dict) else type(tx.get('details')).__name__,
                    'currency': tx.get('currency', {}).get('amount'),
                    'details_name': tx.get('details', {}).get('name'),
                }
                sample_records.append(sanitized)
                collected += 1
        out = []
        skip_missing_id = 0
        skip_missing_created = 0
        fallback_id_used = 0
        for tx in data:
            buyer_id = tx.get('agent', {}).get('id')
            if not buyer_id:
                continue
            tx_id = tx.get('id') or tx.get('transactionId')
            if not tx_id:
                tx_id = tx.get('purchaseToken') or tx.get('idHash')
                if not tx_id:
                    tx_id = f"{buyer_id}:{tx.get('created')}:{tx.get('details',{}).get('id')}"
                fallback_id_used += 1
            tx_created = tx.get('created')
            if not tx_created:
                skip_missing_created += 1
                continue
            if not tx_id:
                skip_missing_id += 1
                continue
            matched = False
            buyer_name = None
            if target_user_id and buyer_id == target_user_id:
                matched = True
            else:
                bname = _roblox_buyer_name_cache.get(buyer_id)
                if not bname:
                    try:
                        diag['per_tx_name_lookups'] += 1
                        u_resp = requests.get(f'https://users.roblox.com/v1/users/{buyer_id}', headers=headers, timeout=5)
                        if u_resp.status_code == 200:
                            bname = u_resp.json().get('name','')
                            if bname:
                                _roblox_buyer_name_cache[buyer_id] = bname
                        else:
                            diag['per_tx_lookup_fail'] += 1
                    except Exception:
                        diag['per_tx_lookup_fail'] += 1
                        bname = None
                buyer_name = bname
                if bname and bname.lower() == username.lower():
                    matched = True
            if matched:
                out.append({
                    'transactionId': tx_id,
                    'created': tx_created,
                    'amount': tx.get('currency',{}).get('amount'),
                    'details': tx.get('details',{}).get('name'),
                    'buyerName': buyer_name if buyer_name else username
                })
            else:
                if target_user_id and buyer_id and buyer_id != target_user_id:
                    agent_id_mismatch += 1
        diag['matched_buyer_records'] = len(out)
        if diag['matched_buyer_records'] == 0:
            diag['sample_records'] = sample_records
            diag['sample_field_names'] = sorted(list(field_name_set))
            diag['agent_id_mismatch_count'] = agent_id_mismatch
            diag['raw_nextPageCursor_present'] = bool(raw_json.get('nextPageCursor'))
            diag['skip_missing_id'] = skip_missing_id
            diag['skip_missing_created'] = skip_missing_created
            diag['fallback_id_used'] = fallback_id_used
        _roblox_tx_cache[cache_key] = out
        _roblox_tx_cache_time[cache_key] = now
        _tx_fetch_debug[username.lower()] = diag
        logger.info(f"Transaction fetch diag: {diag}")
        return out
    except Exception as e:
        return _return_stale(f'EXC_{type(e).__name__}')

def _eligible_unclaimed_transactions(username, gamepass_id=None, force_refresh=False):
    """Return recent, unclaimed purchase transactions optionally filtered by gamepass id.

    Filtering logic: if gamepass_id provided, require detailsId match OR details name contains the id.
    (Roblox sometimes exposes numeric id in details.id for gamepasses, else embed in name.)
    """
    prefer_sales = SETTINGS.get('roblox', {}).get('preferSalesAPI', True)
    extreme_debug = SETTINGS.get('roblox', {}).get('extremeDebug', False)
    extreme_trace_limit = int(SETTINGS.get('roblox', {}).get('extremeTraceLimit', 120))
    txs = []
    if prefer_sales:
        txs = _fetch_sale_transactions(username, force_refresh=force_refresh)
        if not txs: 
            txs = _fetch_user_transactions(username, force_refresh=force_refresh)
    else:
        txs = _fetch_user_transactions(username, force_refresh=force_refresh)
    if extreme_debug:
        logger.info(f"[EXTDBG] Initial transactions fetched for {username}: {len(txs)} (prefer_sales={prefer_sales})")
    claimed = _load_claimed_transactions()
    window_hours = SETTINGS.get('roblox',{}).get('claimWindowHours',12)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    eligible = []
    gid_str = str(gamepass_id) if gamepass_id else None
    sale_loose = SETTINGS.get('roblox', {}).get('allowLooseSaleMatch', True)
    multi_products = len(PRODUCTS_CONFIG) > 1

    def _normalize(s):
        if not s: return ''
        return ''.join(ch.lower() if ch.isalnum() else ' ' for ch in s).split()

    product_tokens = {}
    for pid, pcfg in PRODUCTS_CONFIG.items():
        tokens = set()
        for source in [pcfg.get('name'), pcfg.get('gamepass_url'), pcfg.get('gamepass_url') and pcfg.get('gamepass_url').rsplit('/',1)[-1]]:
            if source:
                for t in _normalize(source):
                    tokens.add(t)
        product_tokens[pid] = tokens

    loose_mode_reason_counts = { 'strict':0, 'loose_single':0, 'loose_any':0 }
    trace = [] if extreme_debug else None
    for tx in txs:
        tid = tx.get('transactionId')
        if not tid:
            if extreme_debug and trace is not None:
                trace.append({'tx': None, 'reason': 'missing_transactionId'})
            continue
        if tid in claimed:
            if extreme_debug and trace is not None:
                trace.append({'tx': tid, 'reason': 'already_claimed'})
            continue
        created_raw = tx.get('created')
        try:
            created_dt = datetime.fromisoformat(created_raw.replace('Z','')) if created_raw else None
        except Exception:
            created_dt = None
        if created_dt and created_dt < cutoff:
            if extreme_debug and trace is not None:
                trace.append({'tx': tid, 'reason': 'outside_claim_window', 'created': created_raw})
            continue
        if gid_str:
            details_id = str(tx.get('detailsId')) if tx.get('detailsId') is not None else None
            details_name = (tx.get('details') or '')
            if details_id == gid_str or gid_str in details_name:
                eligible.append(tx)
                loose_mode_reason_counts['strict'] += 1
                if extreme_debug and trace is not None:
                    trace.append({'tx': tid, 'reason': 'strict_match', 'detailsId': details_id, 'details': details_name})
            else:
                accepted = False
                if sale_loose:
                    dtoks = set(_normalize(details_name))
                    if dtoks:
                        matches = []
                        for pid, toks in product_tokens.items():
                            if toks and dtoks & toks: 
                                matches.append(pid)
                        if len(matches) == 1 and PRODUCTS_CONFIG[matches[0]].get('gamepass_id') and str(PRODUCTS_CONFIG[matches[0]]['gamepass_id']) == gid_str:
                            eligible.append(tx)
                            loose_mode_reason_counts['loose_single'] += 1
                            accepted = True
                            if extreme_debug and trace is not None:
                                trace.append({'tx': tid, 'reason': 'loose_single_match', 'details': details_name, 'tokens': list(dtoks), 'matchedProduct': matches[0]})
                    if (not accepted) and (not multi_products):
                        eligible.append(tx)
                        loose_mode_reason_counts['loose_any'] += 1
                        accepted = True
                        if extreme_debug and trace is not None:
                            trace.append({'tx': tid, 'reason': 'loose_any_match', 'details': details_name})
                if not accepted:
                    if extreme_debug and trace is not None:
                        trace.append({'tx': tid, 'reason': 'filtered_no_match', 'details': details_name})
                    continue
        else:
            eligible.append(tx)
            if extreme_debug and trace is not None:
                trace.append({'tx': tid, 'reason': 'no_gid_filter'})
    if extreme_debug:
        diag = _tx_fetch_debug.get(username.lower(), {})
        diag.setdefault('eligibility', {})
        diag['eligibility'].update({
            'inputCount': len(txs),
            'selectedCount': len(eligible),
            'gamepassFilter': bool(gid_str),
            'looseMode': sale_loose,
            'multiProducts': multi_products,
            'looseReasonCounts': loose_mode_reason_counts,
            'windowHours': window_hours,
            'cutoff': cutoff.isoformat()+'Z',
            'claimedCount': len(claimed),
            'traceSampleCount': len(trace) if trace is not None else 0,
            'trace': (trace[:extreme_trace_limit] if trace else [])
        })
        _tx_fetch_debug[username.lower()] = diag
    return eligible

def _check_gamepass_ownership(roblox_user_id: int, gamepass_id: str, cookie: str):
    """Fast ownership probe. Returns (owned: bool, detail: str). Tries multiple endpoints.
    Endpoints:
      - https://inventory.roblox.com/v1/users/{uid}/items/GamePass/{gamepass_id} (presence in data array)
      - https://games.roblox.com/v1/games/game-passes/{gamepass_id}/servers (not reliable for ownership; skipped)
      - https://api.roblox.com/ownership/hasasset?userId={uid}&assetId={gamepass_id} (legacy, still works for some passes)
    """
    headers = {'Accept': 'application/json'}
    if cookie and 'PUT_.ROBLOSECURITY' not in cookie:
        headers['Cookie'] = f'.ROBLOSECURITY={cookie}'
    try:
        inv_url = f"https://inventory.roblox.com/v1/users/{roblox_user_id}/items/GamePass/{gamepass_id}?limit=10"
        r = requests.get(inv_url, headers=headers, timeout=6)
        if r.status_code == 200:
            j = r.json()
            data = j.get('data', []) if isinstance(j, dict) else []
            if any(str(item.get('id')) == str(gamepass_id) for item in data):
                return True, 'inventory'
        elif r.status_code == 429:
            return False, 'inventory_rate'
    except Exception:
        pass
    try:
        legacy_url = f"https://api.roblox.com/ownership/hasasset?userId={roblox_user_id}&assetId={gamepass_id}"
        r2 = requests.get(legacy_url, headers=headers, timeout=6)
        if r2.status_code == 200:
            txt = r2.text.strip().lower()
            if txt == 'true':
                return True, 'legacy'
        elif r2.status_code == 429:
            return False, 'legacy_rate'
    except Exception:
        pass
    return False, 'none'

def _gather_stock_snapshot():
    """Build a snapshot of current stock and aggregated main product stock."""
    global _latest_stock_snapshot, _latest_stock_snapshot_time
    ensure_products_config_loaded()
    snapshot = {'products': {}, 'generatedAt': datetime.now(timezone.utc).isoformat() + 'Z'}
    try:
        for pid, pconf in PRODUCTS_CONFIG.items():
            stock_count = None
            if github_manager:
                try:
                    raw = github_manager.get_file_content(pconf.get('stock_file', f'{pid.upper()}-Stock'))
                    stock_count = len(raw) if raw else 0
                except Exception:
                    stock_count = None
            snapshot['products'][pid] = {
                'stock': stock_count,
                'price': pconf.get('price'),
                'parentProduct': pconf.get('parentProduct')
            }
        try:
            with open('config/products.json','r') as f:
                cfg = json.load(f)
            main_products_cfg = cfg.get('mainProducts', [])
            main_products = []
            for mp in main_products_cfg:
                variants = [pid for pid, pc in PRODUCTS_CONFIG.items() if pc.get('parentProduct') == mp['id']]
                total_stock = 0
                min_price = None
                for vid in variants:
                    vs = snapshot['products'].get(vid, {})
                    s = vs.get('stock')
                    if isinstance(s, int):
                        total_stock += s
                    price = vs.get('price')
                    if price is not None:
                        if min_price is None or price < min_price:
                            min_price = price
                main_products.append({
                    'id': mp['id'],
                    'name': mp.get('name'),
                    'totalStock': total_stock,
                    'minPrice': min_price,
                    'variantIds': variants
                })
            snapshot['mainProducts'] = main_products
        except Exception:
            snapshot['mainProducts'] = []
    finally:
        _latest_stock_snapshot = snapshot
        _latest_stock_snapshot_time = time.time()
    return snapshot

def _get_stock_snapshot(max_age=5):
    if not _latest_stock_snapshot or (time.time() - _latest_stock_snapshot_time) > max_age:
        return _gather_stock_snapshot()
    return _latest_stock_snapshot

@app.route('/stock-stream')
def stock_stream():
    """Server-Sent Events endpoint streaming stock updates."""
    def event_stream():
        retry_ms = 5000
        yield f'retry: {retry_ms}\n'  
        last_payload = None
        while True:
            try:
                snapshot = _get_stock_snapshot()
                payload = json.dumps(snapshot)
                if payload != last_payload:
                    yield f'data: {payload}\n\n'
                    last_payload = payload
                default_sleep = SETTINGS.get('sse', {}).get('sleepDefault', 10)
                burst_sleep = SETTINGS.get('sse', {}).get('sleepBurst', 2)
                sleep_time = default_sleep
                if time.time() - _last_forced_push_time < 5:
                    sleep_time = burst_sleep
                time.sleep(sleep_time)
            except GeneratorExit:
                break
            except Exception as e:
                logger.error(f"SSE stream error: {e}")
                time.sleep(5)
    return app.response_class(event_stream(), mimetype='text/event-stream')

app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=None,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def utc_now_iso():
    """Return timezone-aware current UTC time in RFC3339-like format with trailing Z.
    Uses datetime.now(timezone.utc) to avoid deprecation warnings from datetime.utcnow().
    """
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def parse_ts(ts: str):
    """Parse a stored ISO8601 timestamp (possibly with +00:00Z bug) into a naive UTC datetime.

    Normalizes:
      - '2025-08-28T17:23:41.362992+00:00Z' -> naive 2025-08-28T17:23:41.362992
      - '2025-08-28T17:23:41.362992Z' -> naive
      - '2025-08-28T17:23:41.362992' -> naive
    Returns None if unparsable.
    """
    if not ts or not isinstance(ts, str):
        return None
    t = ts.strip()
    if t.endswith('Z'):
        t = t[:-1]
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo:
        try:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            dt = dt.replace(tzinfo=None)
    return dt

def ensure_naive_utc(dt: datetime):
    """Return a naive UTC datetime for comparison safety.
    Accepts aware (UTC or offset) or naive (assumed UTC) and returns naive UTC.
    """
    if not dt:
        return None
    if dt.tzinfo:
        try:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            return dt.replace(tzinfo=None)
    return dt

user_locks = {}
lock_manager_lock = threading.Lock()
rate_limit_cache = {}
request_cache = {}

persistent_user_cache = {}

@app.after_request
def add_cache_headers(response):
    """Add modest caching for static assets to speed up repeat visits.
    HTML kept short cache; JS/CSS/images longer.
    """
    try:
        path = request.path.lower()
        if path.endswith(('.js', '.css')):
            response.headers.setdefault('Cache-Control', 'public, max-age=3600, immutable')
        elif path.endswith(('.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp')):
            response.headers.setdefault('Cache-Control', 'public, max-age=86400, immutable')
        elif path.endswith(('.json')) and 'products' not in path:
            response.headers.setdefault('Cache-Control', 'public, max-age=60')
        elif path == '/' or path.endswith('.html'):
            response.headers.setdefault('Cache-Control', 'public, max-age=15')
    except Exception:
        pass
    return response

@app.route('/clear-cache', methods=['POST'])
def clear_cache_endpoint():
    """Clear cache endpoint for testing."""
    global request_cache, persistent_user_cache, rate_limit_cache
    request_cache.clear()
    persistent_user_cache.clear()
    rate_limit_cache.clear()
    logger.info("All caches cleared")
    return jsonify({'message': 'All caches cleared successfully'})

def get_user_lock(username, product_id=None):
    """Get or create a lock for a specific user + product combination.
    Using a composite key reduces unnecessary contention when the same Roblox
    username is involved in unrelated product purchases. Falls back to username-only
    if product_id not provided.
    """
    key = f"{username.lower()}::{product_id}" if product_id else username.lower()
    with lock_manager_lock:
        if key not in user_locks:
            user_locks[key] = threading.Lock()
        return user_locks[key]

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
                'last_login': None,
                'pending_purchases': {}
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
                user_data.pop('password_hash', None)
                user_data['user_id'] = user_id
                return user_data
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
        return None
    
    def add_purchase_to_history(self, user_id, purchase_data):
        """Add purchase to legacy embedded account list AND external purchase log."""
        try:
            accounts = self.load_accounts()
            if user_id not in accounts:
                return False
            purchase_entry = {
                'purchase_id': secrets.token_hex(8),
                'user_id': user_id,
                'username': accounts[user_id].get('username'),
                'product_name': purchase_data['product_name'],
                'product_id': purchase_data['product_id'],
                'key': purchase_data['key'],
                'roblox_username': purchase_data['roblox_username'],
                'purchase_date': datetime.now(timezone.utc).isoformat() + 'Z',
                'price': purchase_data['price'],
                'gamepass_id': purchase_data['gamepass_id'],
                'transaction_id': purchase_data.get('transaction_id'),
                'transaction_created': purchase_data.get('transaction_created')
            }
            accounts[user_id].setdefault('purchase_history', []).append(purchase_entry)
            accounts[user_id]['total_purchases'] = len(accounts[user_id]['purchase_history'])
            self.save_accounts(accounts)
            try:
                purchase_history_manager.add_purchase(purchase_entry)
            except Exception as e:
                logger.error(f"Failed to append to external purchase history: {e}")
            return True
        except Exception as e:
            logger.error(f"Error adding purchase to history: {e}")
            return False

    def set_pending_purchase(self, user_id, roblox_username, product_id):
        try:
            accounts = self.load_accounts()
            if user_id not in accounts:
                return False, 'Account not found'
            acct = accounts[user_id]
            if 'pending_purchases' not in acct or not isinstance(acct['pending_purchases'], dict):
                acct['pending_purchases'] = {}
            key = f"{product_id}::{roblox_username.lower()}"
            if key in acct['pending_purchases'] and isinstance(acct['pending_purchases'][key], dict):
                existing_started = acct['pending_purchases'][key].get('started_at')
                logger.info(f"Reuse existing pending purchase user={user_id} product={product_id} username={roblox_username} started_at={existing_started}")
            else:
                started_at = utc_now_iso()
                acct['pending_purchases'][key] = {'started_at': started_at}
                logger.info(f"Set pending purchase user={user_id} product={product_id} username={roblox_username} started_at={started_at}")
            saved = self.save_accounts(accounts)
            return (True, None) if saved else (False, 'Save failed')
        except Exception as e:
            logger.error(f"Error setting pending purchase: {e}")
            return False, 'Internal error'

    def pop_pending_purchase(self, user_id, roblox_username, product_id):
        try:
            accounts = self.load_accounts()
            if user_id not in accounts:
                return None
            key = f"{product_id}::{roblox_username.lower()}"
            acct = accounts[user_id]
            entry = None
            if 'pending_purchases' in acct and isinstance(acct['pending_purchases'], dict):
                entry = acct['pending_purchases'].pop(key, None)
                self.save_accounts(accounts)
            return entry
        except Exception as e:
            logger.error(f"Error popping pending purchase: {e}")
            return None

    def get_pending_purchase(self, user_id, roblox_username, product_id):
        try:
            accounts = self.load_accounts()
            if user_id not in accounts:
                return None
            acct = accounts[user_id]
            key = f"{product_id}::{roblox_username.lower()}"
            return acct.get('pending_purchases', {}).get(key)
        except Exception as e:
            logger.error(f"Error getting pending purchase: {e}")
            return None

    def delete_account(self, user_id):
        """Delete a user account by id"""
        try:
            accounts = self.load_accounts()
            if user_id not in accounts:
                return False, 'User not found'
            del accounts[user_id]
            if self.save_accounts(accounts):
                return True, 'Deleted'
            return False, 'Save failed'
        except Exception as e:
            logger.error(f"Delete account error: {e}")
            return False, 'Error'

@app.route('/start-purchase', methods=['POST'])
def start_purchase():
    try:
        user = get_authenticated_user()
        data = request.get_json() or {}
        roblox_username = data.get('roblox_username') or data.get('username')
        product_id = data.get('product_id') or data.get('product')
        if not roblox_username or not product_id:
            return jsonify({'error': 'roblox_username and product_id required'}), 400
        if product_id not in PRODUCTS_CONFIG:
            return jsonify({'error': 'Unknown product'}), 400
        if not user:
            guest_key = 'guest_' + hashlib.sha256(f"{request.remote_addr}:{roblox_username}".encode()).hexdigest()[:24]
            accounts = account_manager.load_accounts()
            if guest_key not in accounts:
                accounts[guest_key] = {
                    'user_id': guest_key,
                    'username': guest_key,
                    'created_at': utc_now_iso(),
                    'last_login': utc_now_iso(),
                    'guest': True,
                    'pending_purchases': {}
                }
                account_manager.save_accounts(accounts)
            user = accounts[guest_key]
            session['user_id'] = guest_key  
            logger.info(f"/start-purchase guest session created guest_id={guest_key} roblox_username={roblox_username} product_id={product_id}")
        else:
            logger.info(f"/start-purchase attempt user_id={user['user_id']} accountName={user.get('username')} roblox_username={roblox_username} product_id={product_id}")
        ok, err = account_manager.set_pending_purchase(user['user_id'], roblox_username, product_id)
        if not ok:
            return jsonify({'error': err or 'Failed to start purchase'}), 500
        pending_info = account_manager.get_pending_purchase(user['user_id'], roblox_username, product_id) or {}
        logger.info(f"/start-purchase stored pending key={product_id}::{roblox_username.lower()} info={pending_info}")
        return jsonify({'started': True, 'started_at': pending_info.get('started_at'), 'guest': user.get('guest', False)})
    except Exception as e:
        logger.error(f"Error in start_purchase: {e}")
        return jsonify({'error': 'Internal error'}), 500

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
        token = os.getenv('GITHUB_TOKEN')
        repo_owner = os.getenv('GITHUB_REPO_OWNER')
        repo_name = os.getenv('GITHUB_REPO_NAME')
        
        if token and repo_owner and repo_name:
            return GitHubStockManager(
                token=token,
                repo_owner=repo_owner,
                repo_name=repo_name
            )
    except Exception as e:
        logger.error(f"Failed to load GitHub manager: {e}")
    return None

github_manager = load_github_manager()
account_manager = AccountManager(github_manager)
github_user_data_manager = GitHubUserDataManager(github_manager)
key_manager = KeyManager()

_github_atomic_lock = threading.Lock()

def github_atomic_update(file_name: str, mutator, commit_message: str, max_retries: int = 5, backoff: float = 0.4):
    """Perform an atomic read-modify-write on a GitHub text file.
    mutator(lines:list[str]) -> list[str] (new content) or None (no change).
    """
    if not github_manager:
        raise RuntimeError('GitHub manager not configured')
    for attempt in range(1, max_retries+1):
        with _github_atomic_lock:
            current = github_manager.get_file_content(file_name) or []
            try:
                new_lines = mutator(list(current))
            except Exception as e:
                logger.error(f"Mutator error for {file_name}: {e}")
                raise
            if new_lines is None:
                return True
            try:
                if github_manager.update_file_content(file_name, new_lines, commit_message):
                    return True
            except Exception as e:
                logger.warning(f"Attempt {attempt} update failed for {file_name}: {e}")
        time.sleep(backoff * attempt)
    return False

class PurchaseHistoryManager:
    def __init__(self, github_manager, file_name='Purchases'):
        self.github_manager = github_manager
        self.file_name = file_name
        self._cache = []
        self._cache_time = 0
        self._ttl = 10

    def _parse(self, lines):
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def list_purchases(self, force=False):
        now = time.time()
        if (not force) and self._cache and (now - self._cache_time) < self._ttl:
            return list(self._cache)
        if not self.github_manager:
            return []
        lines = self.github_manager.get_file_content(self.file_name) or []
        parsed = self._parse(lines)
        self._cache = parsed
        self._cache_time = now
        return list(parsed)

    def list_purchases_for_user(self, user_id=None, username=None):
        purchases = self.list_purchases()
        res = []
        for p in purchases:
            if user_id and p.get('user_id') == user_id:
                res.append(p)
            elif (not user_id) and username and p.get('username','').lower() == username.lower():
                res.append(p)
        return res

    def add_purchase(self, record: dict):
        rec = dict(record)
        rec.setdefault('ts', datetime.now(timezone.utc).isoformat() + 'Z')
        if not rec.get('purchase_id'):
            rec['purchase_id'] = secrets.token_hex(8)
        line = json.dumps(rec, separators=(',',':'))
        def mut(lines):
            lines.append(line)
            return lines
        ok = github_atomic_update(self.file_name, mut, f"Append purchase {rec['purchase_id']}")
        if ok:
            self._cache.append(rec)
        return ok, rec['purchase_id']

purchase_history_manager = PurchaseHistoryManager(github_manager)

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
    if is_rate_limited(global_rate_key, 2):  
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
                sf = product.get('stockGithubFile')
                if sf and '/' not in sf:
                    sf = f"Stock/{sf}"
                elif not sf:
                    sf = f"Stock/{product['id'].upper()}-Stock"
                PRODUCTS_CONFIG[product['id']] = {
                    'name': product['name'],
                    'price': product['price'],
                    'gamepass_id': product['gamepassId'],
                    'gamepass_url': product.get('gamepassUrl', f"https://www.roblox.com/game-pass/{product['gamepassId']}"),
                    'duration': product['duration'],
                    'stock_file': sf,
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

@app.route('/config.json')
def public_config():
    base_url = os.getenv('PUBLIC_BASE_URL')
    if not base_url:
        scheme = request.headers.get('X-Forwarded-Proto') or request.scheme
        host = request.headers.get('Host')
        base_url = f"{scheme}://{host}" if host else ''
    return jsonify({'baseUrl': base_url.rstrip('/'), 'productsEndpoint': '/products', 'version': 1})

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
        
        if 'user_id' in session:
            existing = account_manager.get_user_by_id(session['user_id'])
            if existing and existing['username'].lower() == username.lower():
                return jsonify({'success': True, 'message': 'Already logged in', 'user': existing})

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
        external = purchase_history_manager.list_purchases_for_user(user_id=user['user_id'])
        embedded = account_manager.get_user_by_id(user['user_id']) or {}
        legacy = embedded.get('purchase_history', [])
        combined = {p.get('purchase_id'): p for p in legacy if p.get('purchase_id')}
        for p in external:
            combined[p.get('purchase_id')] = p
        purchase_history = list(combined.values())
        purchase_history.sort(key=lambda x: x.get('purchase_date') or x.get('ts') or '', reverse=True)
        logger.info(f"Combined purchase history: external={len(external)} legacy={len(legacy)} total={len(purchase_history)}")
        return jsonify({
            'purchases': purchase_history,
            'total_purchases': len(purchase_history)
        })
        
    except Exception as e:
        logger.error(f"Error getting purchase history: {e}")
        return jsonify({'error': 'Failed to load purchase history'}), 500

@app.route('/check-gamepass', methods=['POST'])
def check_gamepass():
    """Transaction-based key issuance. Username + product id; issue one key per unclaimed recent transaction."""
    data = request.get_json() or {}
    logger.info(f"Received gamepass check request: {data}")
    username = data.get('username')
    gamepass_id = data.get('gamepass_id')
    if not username or not gamepass_id:
        return jsonify({'error': 'Username and gamepass_id are required'}), 400
    authenticated_user = get_authenticated_user()
    user_lock = get_user_lock(username)
    if not user_lock.acquire(blocking=False):
        return jsonify({'status':'Rate Limited','message':'Please wait, processing your previous request...','shouldRetry':True}), 429
    try:
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
        _cool_key = (username.lower(), product_id)
        _now_ts = time.time()
        if not hasattr(check_gamepass, '_recent_checks'):
            check_gamepass._recent_checks = {}
        last_ts = check_gamepass._recent_checks.get(_cool_key)
        if last_ts and (_now_ts - last_ts) < CHECK_GAMEPASS_COOLDOWN_SECONDS:
            retry_after = max(0, CHECK_GAMEPASS_COOLDOWN_SECONDS - (_now_ts - last_ts))
            return jsonify({'status':'Rate Limited','message':f'Please wait {retry_after:.1f}s before checking again.','shouldRetry':True,'retryAfter':round(retry_after,1)}), 429
        check_gamepass._recent_checks[_cool_key] = _now_ts
        product = PRODUCTS_CONFIG[product_id]
        user_id, user_error = fetch_user_id(username)
        if user_id is None or user_error:
            return jsonify({'error':'Failed to verify user','detail':user_error}), 400
        if authenticated_user:
            pending_info = account_manager.get_pending_purchase(authenticated_user['user_id'], username, product_id)
            logger.info(f"/check-gamepass pending lookup user={authenticated_user['user_id']} product={product_id} username={username} found={bool(pending_info)} info={pending_info}")
        else:
            pending_info = {'started_at': utc_now_iso(), 'guest': True}
        pending_started_dt = None
        if not pending_info:
            if authenticated_user:
                return jsonify({'hasGamepass': False, 'needStart': True, 'message': 'Start a purchase first.'})
            else:
                pending_info = {'started_at': utc_now_iso(), 'guest': True}
        pending_started_dt = ensure_naive_utc(parse_ts(pending_info.get('started_at')))
        now_naive = ensure_naive_utc(datetime.now(timezone.utc))
        if authenticated_user and pending_started_dt and (now_naive - pending_started_dt).total_seconds() > PENDING_PURCHASE_EXPIRY_SECONDS:
            try:
                account_manager.pop_pending_purchase(authenticated_user['user_id'], username, product_id)
            except Exception:
                pass
            return jsonify({'hasGamepass': False, 'needStart': True, 'purchaseExpired': True, 'message': 'Purchase session expired. Start a new one.'})
        user_data = load_user_data()
        prior_key_count = 0
        if username in user_data:
            prod_record = user_data[username].get(product_id)
            if isinstance(prod_record, dict):
                if 'keys' in prod_record and isinstance(prod_record['keys'], list):
                    prior_key_count = len(prod_record['keys'])
                elif prod_record.get('key_issued'):
                    prior_key_count = 1

        force_refresh = bool(data.get('force_refresh')) or bool(pending_info)

        use_fast_path = SETTINGS.get('roblox', {}).get('useOwnershipFastPath', False)
        ownership_fast_path_used = False
        eligible_txs = []
        if use_fast_path:
            cycle_key = (username.lower(), product_id)
            state = _ownership_cycles.get(cycle_key, {'cycle': 1, 'lastOwned': False})
            roblox_cookie = SETTINGS.get('roblox', {}).get('securityCookie')
            owned_now, owned_mode = _check_gamepass_ownership(user_id, product['gamepass_id'], roblox_cookie)
            if state['lastOwned'] and not owned_now:
                state['cycle'] += 1
                logger.info(f"Ownership drop detected for {username} {product_id}; advancing to cycle {state['cycle']}")
            if owned_now:
                synthetic_tx_id = f"OWNC{state['cycle']}-{user_id}-{product_id}"
                claimed_set_prefetch = _load_claimed_transactions()
                already_claimed_cycle = synthetic_tx_id in claimed_set_prefetch
                if not already_claimed_cycle:
                    existing_product_record_tmp = None
                    if username in user_data:
                        existing_product_record_tmp = user_data[username].get(product_id)
                    duplicate = False
                    if existing_product_record_tmp and isinstance(existing_product_record_tmp, dict):
                        for krec in existing_product_record_tmp.get('keys', []):
                            if krec.get('transaction_id') == synthetic_tx_id:
                                duplicate = True
                                break
                    if not duplicate:
                        ownership_fast_path_used = True
                        eligible_txs = [{
                            'transactionId': synthetic_tx_id,
                            'created': (pending_started_dt or datetime.now(timezone.utc).replace(tzinfo=None)).isoformat() + 'Z',
                            'amount': product.get('price'),
                            'details': f"Gamepass {product['gamepass_id']} ownership cycle {state['cycle']} ({owned_mode})",
                            'buyerName': username
                        }]
                        logger.info(f"Ownership fast-path cycle {state['cycle']} success for {username} via {owned_mode}; synthetic {synthetic_tx_id}")
            state['lastOwned'] = owned_now
            _ownership_cycles[cycle_key] = state
            if not ownership_fast_path_used:
                eligible_txs = _eligible_unclaimed_transactions(username, gamepass_id=product['gamepass_id'], force_refresh=force_refresh)
        else:
            eligible_txs = _eligible_unclaimed_transactions(username, gamepass_id=product['gamepass_id'], force_refresh=force_refresh)
        debug_diag = _tx_fetch_debug.get(username.lower())
        rate_limited = False
        if debug_diag and isinstance(debug_diag, dict) and str(debug_diag.get('reason','')).startswith('HTTP_429'):
            rate_limited = True
        logger.info(f"Eligible tx count for {username} force_refresh={force_refresh}: {len(eligible_txs)} diag={debug_diag} rate_limited={rate_limited}")
        if not eligible_txs:
            if use_fast_path and not ownership_fast_path_used:
                roblox_cfg = SETTINGS.get('roblox', {}).get('securityCookie')
                owned, mode = _check_gamepass_ownership(user_id, product['gamepass_id'], roblox_cfg)
                if owned:
                    cycle_key = (username.lower(), product_id)
                    state = _ownership_cycles.get(cycle_key, {'cycle': 1, 'lastOwned': owned})
                    synthetic_tx_id = f"OWNC{state['cycle']}-{user_id}-{product_id}"
                    claimed_set_prefetch = _load_claimed_transactions()
                    if synthetic_tx_id not in claimed_set_prefetch:
                        eligible_txs = [{
                            'transactionId': synthetic_tx_id,
                            'created': (pending_started_dt or datetime.now(timezone.utc).replace(tzinfo=None)).isoformat() + 'Z',
                            'amount': product.get('price'),
                            'details': f"Gamepass {product['gamepass_id']} ownership fallback cycle {state['cycle']}",
                            'buyerName': username
                        }]
                        debug_diag = debug_diag or {}
                        debug_diag['ownershipFallback'] = mode
                        debug_diag['syntheticTxId'] = synthetic_tx_id
            if not eligible_txs:
                poll_cfg = SETTINGS.get('roblox', {})
                poll_attempts = int(poll_cfg.get('quickPollAttempts', 6))
                poll_interval_ms = int(poll_cfg.get('quickPollIntervalMs', 450))
                for _poll in range(poll_attempts):
                    time.sleep(poll_interval_ms / 1000.0)
                    eligible_txs = _eligible_unclaimed_transactions(username, gamepass_id=product['gamepass_id'], force_refresh=True)
                    if eligible_txs:
                        logger.info(f"Found transactions after quick re-poll {_poll+1}/{poll_attempts} interval={poll_interval_ms}ms")
                        break
            if not eligible_txs:
                resp = {'hasGamepass': False,
                        'message':'No recent purchase transactions detected for this user within claim window.' if not rate_limited else 'Rate limited by Roblox API. Please wait a moment then press the button again.',
                        'priorKeyCount': prior_key_count,
                        'hadPreviousKeys': prior_key_count > 0,
                        'debug': debug_diag,
                        'rate_limited': rate_limited,
                        'shouldRetry': rate_limited}
                if rate_limited:
                    return jsonify(resp), 429
                return jsonify(resp)
        if username not in user_data:
            user_data[username] = {}
        existing_product_record = user_data[username].get(product_id)
        if not existing_product_record or isinstance(existing_product_record, dict) and existing_product_record.get('key_issued'):
            if isinstance(existing_product_record, dict) and existing_product_record.get('key_issued'):
                existing_product_record = {
                    'keys': [
                        {
                            'key': existing_product_record.get('key'),
                            'issued_at': existing_product_record.get('issued_at'),
                            'expiry_date': existing_product_record.get('expiry_date'),
                            'transaction_id': existing_product_record.get('transaction_id')
                        }
                    ]
                }
            else:
                existing_product_record = {'keys': []}
            user_data[username][product_id] = existing_product_record

        claimed_set = _load_claimed_transactions()
        last_issued_dt = None
        try:
            for k in existing_product_record.get('keys', [])[-5:]: 
                t_created = k.get('transaction_created') or k.get('issued_at') or k.get('expiry_date')
                if not t_created: continue
                try:
                    dt = parse_ts(t_created)
                    if (last_issued_dt is None) or dt > last_issued_dt:
                        last_issued_dt = dt
                except Exception:
                    continue
        except Exception as _e:
            logger.warning(f"Failed computing last_issued_dt: {_e}")

        new_tx = None
        fallback_old_tx = None  
        for tx in eligible_txs:
            tx_id = tx.get('transactionId')
            tx_created_raw = tx.get('created')
            logger.info(f"Candidate tx id={tx_id} created={tx_created_raw} lastIssued={last_issued_dt}")
            if not tx_id or not tx_created_raw:
                logger.info("Skipping tx (missing id or created)")
                continue
            enforce_pending = SETTINGS.get('roblox', {}).get('enforcePendingStart', False)
            if enforce_pending and pending_started_dt:
                try:
                    _tx_dt_pending = ensure_naive_utc(datetime.fromisoformat(tx_created_raw.replace('Z','')))
                    if pending_started_dt and _tx_dt_pending <= pending_started_dt - timedelta(seconds=300):
                        logger.info(f"Skip tx {tx_id} due to enforcePendingStart gating")
                        continue
                except Exception:
                    logger.info(f"Skip tx {tx_id}: invalid date vs pending start (enforcePendingStart)")
                    continue
            if tx_id in claimed_set:
                logger.info(f"Skip tx {tx_id} already in claimed set")
                continue
            if any(k.get('transaction_id') == tx_id for k in existing_product_record['keys']):
                logger.info(f"Skip tx {tx_id} already has key issued")
                continue
            tx_created_dt = parse_ts(tx_created_raw)
            if not tx_created_dt:
                logger.info(f"Skip tx {tx_id} invalid created format")
                continue
            if pending_started_dt and tx_created_dt < pending_started_dt:
                delta_sec = (pending_started_dt - tx_created_dt).total_seconds()
                if delta_sec <= PRE_START_GRACE_SECONDS:
                    logger.info(f"Accept tx {tx_id} within pre-start grace ({delta_sec:.1f}s before pending start)")
                else:
                    logger.info(f"Skip tx {tx_id}: {delta_sec:.1f}s before pending start (exceeds grace {PRE_START_GRACE_SECONDS}s)")
                    continue
            if last_issued_dt and tx_created_dt <= last_issued_dt:
                allow_same_ts = False
                if pending_started_dt and tx_created_dt >= last_issued_dt and tx_id not in claimed_set:
                    allow_same_ts = True
                if not allow_same_ts:
                    logger.info(f"Skip tx {tx_id}: not newer than last issued {last_issued_dt} (same timestamp not allowed)")
                    continue
            new_tx = tx
            logger.info(f"Selected new transaction {tx_id} for key issuance")
            break

        if not new_tx and not existing_product_record['keys'] and fallback_old_tx:
            allow_grace = SETTINGS.get('roblox', {}).get('allowGracePriorTx', False)
            grace_tx_id = fallback_old_tx.get('transactionId')
            already_issued = any(k.get('transaction_id') == grace_tx_id for k in existing_product_record['keys'])
            if allow_grace and grace_tx_id and grace_tx_id not in claimed_set and not already_issued:
                new_tx = fallback_old_tx
                logger.info(f"Grace selection of prior transaction {new_tx.get('transactionId')} (created {new_tx.get('created')}) because user has no keys and no newer tx post pending start (grace enabled).")
            else:
                logger.info("Grace fallback suppressed (either disabled, missing id, or already claimed).")

        if not new_tx:
            debug_diag = _tx_fetch_debug.get(username.lower())
            return jsonify({'hasGamepass': False,
                            'message': 'No new unclaimed purchase transaction detected.',
                            'priorKeyCount': prior_key_count,
                            'hadPreviousKeys': prior_key_count > 0,
                            'waitingNewTx': True,
                            'debug': debug_diag})

        key, expiry = key_manager.generate_key_with_expiry(product_id, product.get('duration_days', 7))
        key_entry = {
            'key': key,
            'issued_at': utc_now_iso(), 
            'expiry_date': expiry.isoformat().replace('+00:00', 'Z'),
            'transaction_id': new_tx['transactionId'],
            'transaction_created': new_tx.get('created'),
            'pending_started_at': pending_info.get('started_at') if pending_info else None,
            'claim_method': 'grace' if (fallback_old_tx and new_tx is fallback_old_tx) else 'standard'
        }
        existing_product_record['keys'].append(key_entry)
        with _claimed_transactions_lock:
            claimed = _load_claimed_transactions()
            claimed.add(new_tx['transactionId'])
            _persist_claimed_transactions()

        def update_github_async():
            try:
                stock_file = product.get('stock_file', f'Stock/{gamepass_id.upper()}-Stock')
                if '/' not in stock_file:
                    stock_file = f'Stock/{stock_file}'
                bought_file = product.get('bought_file', 'Keys-Bought')
                def mutate_stock(lines):
                    return lines[1:] if lines else lines
                github_atomic_update(stock_file, mutate_stock, f"Dispense key for {product['name']}")
                def mutate_bought(lines):
                    lines.append(key)
                    return lines
                github_atomic_update(bought_file, mutate_bought, f"Record key for {product['name']}")
                save_user_data(user_data)
            except Exception as e:
                logger.error(f"Async atomic GitHub update error: {e}")
            finally:
                global _last_forced_push_time
                _last_forced_push_time = time.time()

        if authenticated_user:
            try:
                purchase_data = {'product_name': product['name'], 'product_id': product_id, 'key': key, 'roblox_username': username, 'price': product.get('price', 1), 'gamepass_id': product['gamepass_id'], 'transaction_id': new_tx['transactionId'], 'transaction_created': new_tx.get('created')}
                account_manager.add_purchase_to_history(authenticated_user['user_id'], purchase_data)
            except Exception as log_err:
                logger.error(f"Purchase history logging error: {log_err}")
        if authenticated_user:
            try:
                account_manager.pop_pending_purchase(authenticated_user['user_id'], username, product_id)
            except Exception:
                pass
        threading.Thread(target=update_github_async).start()
        return jsonify({
            'hasGamepass': True,
            'keyIssued': True,
            'key': key,
            'expiryDate': expiry.isoformat(),
            'isNewKey': True,
            'transactionId': new_tx['transactionId'],
            'priorKeyCount': prior_key_count,
            'hadPreviousKeys': prior_key_count > 0
        })
    except Exception as e:
        logger.error(f"Error in gamepass check: {e}")
        return jsonify({'error':'Internal server error'}), 500
    finally:
        user_lock.release()

def _build_initial_products_json():
    """Generate lightweight products JSON without per-request GitHub fetch when possible.
    Uses latest cached /products payload if fresh (<=5s) else regenerates by calling logic.
    """
    cached = get_cached_response('products_endpoint', max_age_seconds=5)
    if cached:
        return cached
    try:
        import json as _json
        with open('config/products.json','r') as f:
            cfg = _json.load(f)
        products = []
        for pid, product_config in PRODUCTS_CONFIG.items():
            stock_count = None
            if github_manager:
                try:
                    stock_file = product_config.get('stock_file', f'{pid.upper()}-Stock')
                    current_stock = github_manager.get_file_content(stock_file)
                    stock_count = len(current_stock) if current_stock else 0
                except Exception:
                    stock_count = None
            products.append({
                'id': pid,
                'name': product_config.get('name', pid.title()),
                'price': product_config.get('price', 1),
                'gamepass_id': product_config.get('gamepass_id') or product_config.get('gamepassId'),
                'gamepassUrl': product_config.get('gamepass_url') or product_config.get('gamepassUrl'),
                'duration': product_config.get('duration', '7 Days'),
                'stock': stock_count,
                'parentProduct': product_config.get('parentProduct')
            })
        main_products = []
        if 'mainProducts' in cfg:
            for main_product in cfg['mainProducts']:
                variants = [p for p in products if p.get('parentProduct') == main_product['id']]
                total_stock = sum(p['stock'] for p in variants if isinstance(p['stock'], int))
                min_price = min((p['price'] for p in variants), default=0)
                main_products.append({
                    **main_product,
                    'totalStock': total_stock,
                    'minPrice': min_price,
                    'variantProducts': variants
                })
        payload = {
            'products': products,
            'mainProducts': main_products,
            'generatedAt': datetime.now(timezone.utc).isoformat() + 'Z'
        }
        cache_response('products_endpoint', payload)
        return payload
    except Exception:
        return {'products': [], 'mainProducts': [], 'generatedAt': datetime.now(timezone.utc).isoformat() + 'Z'}

@app.route('/')
def serve_index():
    try:
        initial = _build_initial_products_json()
        with open('index.html','r', encoding='utf-8') as f:
            html = f.read()
        injection = f"<script>window.__INITIAL_PRODUCTS__ = {json.dumps(initial)};</script>"
        if '</head>' in html:
            html = html.replace('</head>', injection + '</head>')
        else:
            html = injection + html
        resp = make_response(html)
        resp.headers['Content-Type'] = 'text/html; charset=utf-8'
        return resp
    except Exception:
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

@app.route('/debug/tx')
def debug_transactions():
    """Return recent sale and purchase transaction views plus diagnostics for a username.
    Query params: username= (required)
    """
    username = request.args.get('username')
    if not username:
        return jsonify({'error': 'username param required'}), 400
    force = request.args.get('force') == '1'
    sales = _fetch_sale_transactions(username, force_refresh=force)
    purchases = _fetch_user_transactions(username, force_refresh=force)
    diag = _tx_fetch_debug.get(username.lower())
    return jsonify({
        'username': username,
        'salesCount': len(sales),
        'purchaseCount': len(purchases),
        'sales': sales[:10],
        'purchases': purchases[:10],
        'diagnostic': diag,
        'preferSalesAPI': SETTINGS.get('roblox', {}).get('preferSalesAPI', True)
    })

@app.route('/debug/eligibility')
def debug_eligibility():
    """Run full eligibility evaluation with extreme debug trace (temporarily enabling if needed).
    Query params: username=, gamepassId= (id or product id), force=1 to force refresh of tx feed.
    """
    username = request.args.get('username')
    if not username:
        return jsonify({'error': 'username param required'}), 400
    gid = request.args.get('gamepassId')
    force = request.args.get('force') == '1'
    resolved_gamepass_id = None
    if gid:
        if gid in PRODUCTS_CONFIG:
            resolved_gamepass_id = PRODUCTS_CONFIG[gid].get('gamepass_id')
        else:
            resolved_gamepass_id = gid
    roblox_settings = SETTINGS.setdefault('roblox', {})
    revert_flag = False
    if not roblox_settings.get('extremeDebug'):
        roblox_settings['extremeDebug'] = True
        revert_flag = True
    try:
        eligible = _eligible_unclaimed_transactions(username, gamepass_id=resolved_gamepass_id, force_refresh=force)
    finally:
        if revert_flag:
            roblox_settings['extremeDebug'] = False
    diag = _tx_fetch_debug.get(username.lower())
    return jsonify({
        'username': username,
        'requestedGamepass': gid,
        'resolvedGamepassId': resolved_gamepass_id,
        'eligibleCount': len(eligible),
        'eligibleSample': eligible[:10],
        'diagnostic': diag.get('eligibility') if diag else None,
        'rawDiagnostic': diag
    })

@app.route('/debug/settings')
def debug_settings():
    """Expose masked runtime SETTINGS and selected diagnostics to confirm configuration."""
    roblox_cfg = SETTINGS.get('roblox', {})
    masked = dict(roblox_cfg)
    cookie = masked.get('securityCookie')
    if cookie:
        masked['securityCookieMasked'] = cookie[:6] + '...' + cookie[-4:] if len(cookie) > 12 else '***mask***'
        masked.pop('securityCookie', None)
    return jsonify({
        'robloxSettings': masked,
        'supportedProducts': list(PRODUCTS_CONFIG.keys()),
        'hasExtremeDebug': roblox_cfg.get('extremeDebug'),
        'preferSalesAPI': roblox_cfg.get('preferSalesAPI'),
        'allowLooseSaleMatch': roblox_cfg.get('allowLooseSaleMatch'),
        'txDebugKeys': list(_tx_fetch_debug.keys())[:20]
    })


@app.route('/debug/whoami')
def debug_whoami():
    """Show which Roblox account the server cookie authenticates as (masked).
    Returns id + name (masked) or an error indicator.
    """
    roblox_cfg = SETTINGS.get('roblox', {})
    cookie = roblox_cfg.get('securityCookie')
    if not cookie or 'PUT_.ROBLOSECURITY' in cookie:
        return jsonify({'error':'NO_COOKIE_OR_PLACEHOLDER'})
    headers = {'Cookie': f'.ROBLOSECURITY={cookie}', 'Accept': 'application/json'}
    try:
        r = requests.get('https://users.roblox.com/v1/users/authenticated', headers=headers, timeout=6)
        if r.status_code != 200:
            return jsonify({'error': f'AUTH_{r.status_code}', 'status': r.status_code, 'body': r.text[:800]})
        j = r.json()
        uid = j.get('id')
        name = j.get('name')
        masked_name = (name[:2] + '...' + name[-2:]) if name and len(name) > 4 else name
        return jsonify({'id': uid, 'nameMasked': masked_name})
    except Exception as e:
        return jsonify({'error': f'EXC_{type(e).__name__}'})


def is_admin_authenticated():
    return session.get('is_admin') is True

def require_admin():
    if not is_admin_authenticated():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    return None

@app.route('/admin/login', methods=['POST'])
def admin_login():
    try:
        data = request.get_json() or {}
        username = data.get('username','')
        password = data.get('password','')
        cfg_user = ADMIN_CONFIG.get('username')
        cfg_pass = ADMIN_CONFIG.get('password')
        if not cfg_user or not cfg_pass:
            return jsonify({'success': False, 'error': 'Admin not configured'}), 500
        if username == cfg_user and password == cfg_pass:
            session['is_admin'] = True
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
    except Exception as e:
        logger.error(f"Admin login error: {e}")
        return jsonify({'success': False, 'error': 'Login failed'}), 500

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return jsonify({'success': True})

@app.route('/admin/accounts', methods=['GET'])
def admin_list_accounts():
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    accounts = account_manager.load_accounts()
    simplified = [
        {
            'user_id': uid,
            'username': acc.get('username'),
            'roblox_username': acc.get('roblox_username'),
            'total_purchases': acc.get('total_purchases',0),
            'created_at': acc.get('created_at'),
            'last_login': acc.get('last_login')
        } for uid, acc in accounts.items()
    ]
    return jsonify({'success': True, 'accounts': simplified})

@app.route('/admin/accounts/<user_id>', methods=['GET'])
def admin_get_account(user_id):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    user = account_manager.get_user_by_id(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify({'success': True, 'account': user})

@app.route('/admin/accounts/<user_id>', methods=['DELETE'])
def admin_delete_account(user_id):
    unauthorized = require_admin()
    if unauthorized:
        return unauthorized
    success, msg = account_manager.delete_account(user_id)
    code = 200 if success else 400
    return jsonify({'success': success, 'message': msg}), code

_admin_panel_route = None
def _get_admin_panel_route():
    global _admin_panel_route
    if _admin_panel_route:
        return _admin_panel_route
    ensure_products_config_loaded()
    r = SETTINGS.get('adminPanelRoute') or 'UdDWCvNNrGAL7FPTOJgvcLxUJhOE4JVt'
    _admin_panel_route = r
    return r

@app.route('/<path:maybe_admin>')
def dynamic_admin_panel(maybe_admin):
    if maybe_admin == _get_admin_panel_route()+'' and os.path.exists(f'{maybe_admin}.html'):
        return send_file(f'{maybe_admin}.html')
    if os.path.exists(maybe_admin):
        return send_file(maybe_admin)
    return jsonify({'error':'Not found'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
