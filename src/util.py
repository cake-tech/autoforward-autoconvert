import ast
from typing import Literal, cast
from requests.auth import HTTPDigestAuth
from datetime import datetime
import urllib.parse
import threading
import requests
import hashlib
import base64
import hmac
import json
import time
import env
from constants import BTCPAY_API_TIMEOUT, ELECTRUM_RPC_TIMEOUT, KRAKEN_API_TIMEOUT, MONERO_RPC_TIMEOUT, MONERO_WALLET_FILENAME, STALLED_WAIT_ATTEMPTS

def get_time() -> str:
    return f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}]'

def request_electrum_rpc(coin: Literal['btc', 'ltc', 'ltc-mweb'], method: str, params: list | dict = []):
    headers = {'content-type': 'application/json'}

    coin_to_auth = {
        'btc': (env.ELECTRUM_RPC_USERNAME, env.ELECTRUM_RPC_PASSWORD),
        'ltc': (env.ELECTRUM_RPC_USERNAME, env.ELECTRUM_RPC_PASSWORD),
        'ltc-mweb': (env.ELECTRUM_RPC_USERNAME, env.ELECTRUM_RPC_PASSWORD)
    }

    coin_to_url = {
        'btc': env.BITCOIN_ELECTRUM_RPC_URL,
        'ltc': env.LITECOIN_ELECTRUM_RPC_URL,
        'ltc-mweb': env.LITECOIN_MWEB_ELECTRUM_RPC_URL
    }

    data = {
        'jsonrpc': '2.0',
        'id': 'curltext',
        'method': method,
        'params': params,
    }

    response =  requests.post(
         coin_to_url[coin],
        headers=headers,
        data=json.dumps(data),
        auth=coin_to_auth[coin],
        timeout=ELECTRUM_RPC_TIMEOUT
    )

    response_json = response.json()

    if 'error' in response_json:
        raise Exception(response_json)

    response.raise_for_status()

    return response_json['result']

def request_monero_rpc(method: str, params: dict = {}):
    headers = {'content-type': 'application/json'}

    data = {
        'jsonrpc': '2.0',
        'id': '0',
        'method': method,
        'params': params
    }

    response = requests.post(
        env.MONERO_RPC_URL,
        headers=headers,
        json=data,
        auth=HTTPDigestAuth(env.MONERO_RPC_USERNAME, env.MONERO_RPC_PASSWORD),
        timeout=MONERO_RPC_TIMEOUT
    )

    response_json = response.json()

    if 'error' in response_json:
        raise Exception(response_json)

    response.raise_for_status()

    return response_json['result']

def open_monero_wallet() -> None:
    params = {'filename': MONERO_WALLET_FILENAME, 'password': env.MONERO_WALLET_PASSWORD}
    request_monero_rpc('open_wallet', params)

def warn_if_container_missing(asset: str, attempts: int):
    if attempts == STALLED_WAIT_ATTEMPTS:
        print(f'Still waiting for {asset} after {STALLED_WAIT_ATTEMPTS * 10}s. Is "{asset}" missing from COMPOSE_PROFILES?')

def wait_for_rpc():
    for coin in env.ENABLED_ELECTRUM_COINS:
        print(f'Waiting for {coin} Electrum RPC...')
        attempts = 0

        while 1:
            try:
                request_electrum_rpc(coin, 'getinfo')
                break
            except:
                attempts += 1
                warn_if_container_missing(coin, attempts)
                time.sleep(10)

    if not env.MONERO_ENABLED:
        return

    print('Waiting for Monero RPC...')
    attempts = 0

    while 1:
        try:
            request_monero_rpc('get_height')
            break
        except Exception as e:
            if 'No wallet file' in e.__str__():
                break
            attempts += 1
            warn_if_container_missing('xmr', attempts)
            time.sleep(10)

def wait_for_wallets():
    for coin in env.ENABLED_ELECTRUM_COINS:
        print(f'Waiting for {coin} wallet...')
        attempts = 0

        while 1:
            try:
                request_electrum_rpc(coin, 'load_wallet')
                break
            except:
                attempts += 1
                warn_if_container_missing(coin, attempts)
                time.sleep(10)

    if not env.MONERO_ENABLED:
        return

    print('Waiting for Monero wallet...')
    attempts = 0

    while 1:
        try:
            request_monero_rpc('get_balance', {'account_index': 0})
            break
        except Exception as e:
            print('Failed to check Monero balance:', e)
            print('Attempting to open Monero wallet...')

        try:
            open_monero_wallet()
            break
        except Exception as e:
            print('Failed to open Monero wallet:', e)

        attempts += 1
        warn_if_container_missing('xmr', attempts)
        time.sleep(10)

def get_kraken_signature(url: str, payload: dict):
    postdata = urllib.parse.urlencode(payload)
    encoded = (str(payload['nonce']) + postdata).encode()
    message = url.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(env.KRAKEN_API_SECRET), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

_nonce_lock = threading.Lock()
_last_nonce = 0

def get_kraken_nonce() -> str:
    # Kraken rejects a nonce that isn't larger than the last one it saw.
    # This makes it less likely to reject without being overly complicated.
    global _last_nonce

    with _nonce_lock:
        _last_nonce = max(_last_nonce + 1, int(1000000*time.time()))
        return str(_last_nonce)

def kraken_request(path: str, payload = {}) -> dict:
    payload['nonce'] = get_kraken_nonce()
    headers = {}
    headers['API-Key'] = env.KRAKEN_API_KEY
    headers['API-Sign'] = get_kraken_signature(path, payload)

    response = requests.post(
        'https://api.kraken.com' + path,
        headers=headers,
        data=payload,
        timeout=KRAKEN_API_TIMEOUT
    )

    response_json = response.json()

    if response_json['error']:
        print(f'request to kraken at {path} failed:')
        print(response_json)
        raise Exception(response_json)

    return response_json['result']

def post_btcpay_greenfield(path: str, payload: dict) -> None:
    headers = {'Authorization': f'token {env.BTCPAY_API_KEY}'}

    response = requests.post(
        env.BTCPAY_URL.rstrip('/') + path,
        headers=headers,
        json=payload,
        timeout=BTCPAY_API_TIMEOUT
    )

    response.raise_for_status()
