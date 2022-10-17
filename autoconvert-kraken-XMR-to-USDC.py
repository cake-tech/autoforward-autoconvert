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

amount_to_sell_xmr = resp['result']['XMR']      # Change XMR to another asset
amount_to_sell_usd = resp['result']['ZUSD']     # if you want to sell something
                                                # other than XMR; XBT for
                                                # Bitcoin. Add additional
                                                # variables if you want to
                                                # configure multiple assets, eg
                                                # XMR and BTC


# https://docs.kraken.com/rest/#tag/User-Trading/operation/addOrder
# Add additional orders if you want to sell additional assets; change the pair
# string and volume variable.
# If you wish to have 1 asset undergo 2 conversions in the same run, you will
# need to check the balance for the first asset, then convert to the base pair,
# then check the balance of the base pair, then convert to the second asset. If
# you aren't worried about volatility (eg: USD to USDC for the second
# conversion), then you can simply run both together, and the next cron job
# will handle it.
resp = kraken_request('/0/private/AddOrder', {
    "nonce": str(int(1000*time.time())),
    "ordertype": "market",
    "type": "sell",
    "volume": amount_to_sell_xmr,
    "pair": "XMRUSD"
}, api_key, api_sec)

resp = kraken_request('/0/private/AddOrder', {
    "nonce": str(int(1000*time.time())),
    "ordertype": "market",
    "type": "buy",
    "volume": amount_to_sell_usd,
    "pair": "USDCUSD"
}, api_key, api_sec)
