"""DRY_RUN must never move funds.

Each scenario runs a real forward/sale path against fake Electrum, Monero and
Kraken endpoints (faked at requests.post/get, the HTTP boundary) and inspects
the requests that went out. A fund-moving request is an Electrum `broadcast`,
a Monero `sweep_all` without `do_not_relay`, a Kraken `AddOrder` without
`validate`, or a Kraken `DepositAddresses` asking for a new address.

Every scenario also runs with DRY_RUN=0 and must then produce at least one
fund-moving request: that proves the fakes are rich enough for the path to
reach the point where money would move, so the dry-run assertion cannot pass
merely because the path gave up early.
"""
import base64
import importlib
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

KRAKEN_SECRET = base64.b64encode(b'not-a-real-secret').decode()


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class Backends:
    """Canned answers for exactly the calls the forward/sale paths make."""

    def __init__(self):
        self.sent = []

    def post(self, url, headers=None, data=None, json=None, auth=None, timeout=None):
        if url.startswith('https://api.kraken.com'):
            path = url[len('https://api.kraken.com'):]
            self.sent.append(('kraken', path.split('?')[0], dict(data or {})))
            return FakeResponse({'error': [], 'result': self.kraken(path, data or {})})

        body = json if json is not None else __import__('json').loads(data)
        if 'json_rpc' in url:
            self.sent.append(('monero', body['method'], body['params']))
            return FakeResponse({'result': self.monero(body['method'], body['params'])})

        self.sent.append(('electrum', body['method'], body['params']))
        return FakeResponse({'result': self.electrum(body['method'], body['params'])})

    def get(self, url, timeout=None):
        return FakeResponse({'halfHourFee': 5})

    def electrum(self, method, params):
        return {
            'getbalance': {'confirmed': '1.5'},  # over every coin's default minimum
            'setconfig': True,
            'getunusedaddress': 'bc1qownaddress',
            'payto': 'psbt',
            'deserialize': {'inputs': [{'prevout_hash': 'aa', 'prevout_n': 0}],
                            'outputs': [{'value_sats': 999000}]}
            if params == ['psbt'] else {'outputs': [{'value_sats': 1000000}]},
            'gettransaction': 'rawtx',
            'signtransaction': 'signedtx',
            'broadcast': 'txid',
        }[method]

    def monero(self, method, params):
        return {
            'get_transfers': {'in': []},
            'get_height': {'height': 1},
            'get_balance': {'balance': 2 * 10**12, 'unlocked_balance': 2 * 10**12},
            'get_address': {'address': '4ownaddress'},
            'sweep_all': {'tx_hash_list': ['h'], 'fee_list': [1000]},
            'store': {},
        }[method]

    def kraken(self, path, data):
        if path.startswith('/0/private/DepositAddresses'):
            return [{'address': 'kraken-address', 'new': bool(data.get('new'))}]
        if path.startswith('/0/public/AssetPairs'):
            return {'XMRUSDT': {'ordermin': '0.01', 'pair_decimals': 2}}
        if path.startswith('/0/public/Depth'):
            return {'XMRUSDT': {'bids': [['100', '1', 0]], 'asks': [['101', '1', 0]]}}
        if path.startswith('/0/private/AddOrder'):
            return {'descr': {'order': 'sell'}}
        raise AssertionError(f'unexpected Kraken call {path}')

    def fund_moving(self):
        moved = []
        for backend, method, params in self.sent:
            if backend == 'electrum' and method == 'broadcast':
                moved.append(f'electrum {method}')
            if backend == 'monero' and method in ('sweep_all', 'transfer', 'relay_tx') \
                    and not params.get('do_not_relay'):
                moved.append(f'monero {method}')
            if backend == 'kraken' and method == '/0/private/AddOrder' and not params.get('validate'):
                moved.append('kraken AddOrder')
            if backend == 'kraken' and method == '/0/private/DepositAddresses' and params.get('new'):
                moved.append('kraken new deposit address')
        return moved


def load(module, dry_run, kraken_key):
    environment = {
        'DRY_RUN': '1' if dry_run else '0',
        'TESTNET': '0',
        'KRAKEN_API_KEY': 'key' if kraken_key else '',
        'KRAKEN_API_SECRET': KRAKEN_SECRET,
        'STATUS_DIR': '',
        'MONERO_RPC_URL': 'http://monero-wallet-rpc:18082/json_rpc',
        'BITCOIN_ELECTRUM_RPC_URL': 'http://btc-electrum:7000',
        'LITECOIN_MWEB_ELECTRUM_RPC_URL': 'http://ltc-mweb-electrum:7000',
    }
    with mock.patch.dict(os.environ, environment):
        for name in ('env', 'constants', 'util', 'status', module):
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)
    return sys.modules[module]


def forward(coin):
    def run(module):
        if coin == 'xmr':
            module.attempt_monero()
        else:
            module.attempt_electrum_autoforward(coin)
    return run


def sell(module):
    module.asset_name_to_id = {'XMR': 'XXMR', 'USDT': 'USDT'}
    module.balances = {'XXMR': '2.0'}
    module.attempt_sell('XMR', 'USDT')


SCENARIOS = [
    # (name, module, kraken key configured, action)
    ('btc to own address', 'autoforward', False, forward('btc')),
    ('btc to Kraken', 'autoforward', True, forward('btc')),
    ('ltc-mweb to Kraken', 'autoforward', True, forward('ltc-mweb')),
    ('xmr to own address', 'autoforward', False, forward('xmr')),
    ('xmr to Kraken', 'autoforward', True, forward('xmr')),
    ('sell xmr on Kraken', 'autoconvert', True, sell),
]


class DryRunNeverMovesFunds(unittest.TestCase):
    def run_scenario(self, module_name, kraken_key, action, dry_run):
        backends = Backends()
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get):
            module = load(module_name, dry_run, kraken_key)
            action(module)
        return backends

    def test_scenarios(self):
        for name, module_name, kraken_key, action in SCENARIOS:
            with self.subTest(name, dry_run=True):
                backends = self.run_scenario(module_name, kraken_key, action, dry_run=True)
                self.assertEqual(backends.fund_moving(), [], backends.sent)

            with self.subTest(name, dry_run=False):
                backends = self.run_scenario(module_name, kraken_key, action, dry_run=False)
                self.assertNotEqual(backends.fund_moving(), [], backends.sent)


class DryRunIsTheDefault(unittest.TestCase):
    def test_unset_means_dry_run(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DRY_RUN', None)
            env = importlib.reload(importlib.import_module('env'))
        self.assertTrue(env.DRY_RUN)


if __name__ == '__main__':
    unittest.main()
