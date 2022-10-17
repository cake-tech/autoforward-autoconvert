import requests
from requests.auth import HTTPDigestAuth

address = ''
index = 0                   # Only change if using different account index
username = 'monero'
password = 'rpcPassword'    # Change this!

headers = {}

get_balance = {
    'jsonrpc': '2.0',
    'id': '0',
    'method': 'get_balance',
    'params': {
        'account_index': index,
    },
}

sweep_all = {
    'jsonrpc': '2.0',
    'id': '0',
    'method': 'sweep_all',
    'params': {
        'address': address,
        'account_index': 0,
    },
}

balance_response = requests.post('http://localhost:18081/json_rpc', headers=headers, json=get_balance, auth=HTTPDigestAuth(username, password)).json()['result']['balance']

if balance_response > 0:
    sweep_response = requests.post('http://localhost:18081/json_rpc', headers=headers, json=sweep_all, auth=HTTPDigestAuth(username, password)).json()
    print(sweep_response)
else:
    print('No balance to sweep')