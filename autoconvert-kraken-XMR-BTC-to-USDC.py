import urllib.parse
import hashlib
import hmac
import base64
import time
import os
import requests

os.environ['API_KEY_KRAKEN'] = ''       # This is your "API Key"
os.environ['API_SEC_KRAKEN'] = ''       # This is your Kraken "Private key" NOT
                                        # YOUR MONERO PRIVATE KEY
api_url = "https://api.kraken.com"
api_key = os.environ['API_KEY_KRAKEN']
api_sec = os.environ['API_SEC_KRAKEN']


def get_kraken_signature(urlpath, data, secret):

    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()

    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()


def kraken_request(uri_path, data, api_key, api_sec):
    headers = {}
    headers['API-Key'] = api_key
    headers['API-Sign'] = get_kraken_signature(uri_path, data, api_sec)             
    req = requests.post((api_url + uri_path), headers=headers, data=data)
    return req


# https://docs.kraken.com/rest/#tag/User-Data/operation/getAccountBalance
resp = kraken_request('/0/private/Balance', {
    "nonce": str(int(1000*time.time()))
}, api_key, api_sec)

data = resp.json()


# https://docs.kraken.com/rest/#tag/User-Trading/operation/addOrder
try:
    amount_to_sell_xmr = data['result']['XXMR']
except KeyError:
    print('There is no XMR balance')
else:
    amount_to_sell_xmr = data['result']['XXMR']
    resp = kraken_request('/0/private/AddOrder', {
        "nonce": str(int(1000*time.time())),
        "ordertype": "market",
        "type": "sell",
        "volume": amount_to_sell_xmr,
        "pair": "XMRUSD"
    }, api_key, api_sec)


try:
    amount_to_sell_btc = data['result']['XBT']
except KeyError:
    print('There is no BTC balance')
else:
    amount_to_sell_btc = data['result']['XBT']
    resp = kraken_request('/0/private/AddOrder', {
        "nonce": str(int(1000*time.time())),
        "ordertype": "market",
        "type": "sell",
        "volume": amount_to_sell_btc,
        "pair": "XBTUSD"
    }, api_key, api_sec)


try:
    amount_to_sell_usd = data['result']['ZUSD']
except KeyError:
    print('There is no USD balance')
else:
    amount_to_sell_usd = data['result']['ZUSD']
    resp = kraken_request('/0/private/AddOrder', {
        "nonce": str(int(1000*time.time())),
        "ordertype": "market",
        "type": "buy",
        "volume": amount_to_sell_usd,
        "pair": "USDCUSD"
    }, api_key, api_sec)
