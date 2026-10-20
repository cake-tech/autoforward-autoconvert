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
import contextlib
import importlib
import io
import json
import os
import sys
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

KRAKEN_SECRET = base64.b64encode(b'not-a-real-secret').decode()


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.text = json.dumps(payload)
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class Backends:
    """Canned answers for exactly the calls the forward/sale paths make."""

    def __init__(self, utxos=None, tip=1000, zcash_ready=True, zcash_empty_pools=()):
        self.sent = []
        self.zcash_ready = zcash_ready
        self.zcash_empty_pools = zcash_empty_pools
        # One mature output by default; tests of selection pass their own.
        self.utxos = utxos if utxos is not None else [utxo('aa', 0, '1.5', tip - 100)]
        self.tip = tip
        self.kraken_balances = {}

    def post(self, url, headers=None, data=None, json=None, auth=None, timeout=None):
        if url.startswith('https://api.kraken.com'):
            path = url[len('https://api.kraken.com'):]
            self.sent.append(('kraken', path.split('?')[0], dict(data or {})))
            try:
                return FakeResponse({'error': [], 'result': self.kraken(path, data or {})})
            except KrakenError as e:
                return FakeResponse({'error': [str(e)]})

        body = json if json is not None else __import__('json').loads(data)
        if 'zcash-wallet' in url:
            self.sent.append(('zcash', body['method'], body['params']))
            result = self.zcash(body['method'], body['params'])
            if isinstance(result, dict) and 'error' in result and len(result) == 1:
                return FakeResponse({'result': None, 'error': result['error']}, status_code=500)
            return FakeResponse({'result': result, 'error': None})
        if 'json_rpc' in url:
            self.sent.append(('monero', body['method'], body['params']))
            return FakeResponse({'result': self.monero(body['method'], body['params'])})

        self.sent.append(('electrum', body['method'], body['params']))
        return FakeResponse({'result': self.electrum(body['method'], body['params'])})

    def get(self, url, timeout=None):
        if url.endswith('/readyz'):
            self.sent.append(('zcash-health', 'readyz', {}))
            if self.zcash_ready:
                return FakeResponse({'ready': True})
            return FakeResponse({'ready': False, 'reason': 'syncing'}, status_code=503)
        return FakeResponse({'halfHourFee': 5})

    def zcash(self, method, params):
        if method == 'z_mergetoaddress' and params[0][0] in self.zcash_empty_pools:
            return {'error': {'code': -6, 'message': 'Could not find any funds to merge.'}}
        return {
            'getblockchaininfo': {'blocks': 1},
            'getbalances': {'mine': {'trusted': 1.5, 'untrusted_pending': 0, 'immature': 0}},
            'getnewaddress': 'u1ownaddress',
            'z_validateaddress': {'isvalid': True},
            'z_mergetoaddress': {'opid': 'opid-1', 'mergingShieldedValue': 0.75, 'remainingNotes': 0},
            'z_waitforoperation': {'finished': True, 'status': 'success', 'result': {'txid': 'zectx'}},
        }[method]

    def electrum(self, method, params):
        return {
            'getbalance': {'confirmed': '1.5'},  # over every coin's default minimum
            'listunspent': self.utxos,
            'getinfo': {'blockchain_height': self.tip},
            'listaddresses': ['ltc1qchangeaddress'],
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

    # Kraken's spot markets as the sale paths see them: ZEC has no USDT
    # market, so it goes through USD.
    PAIRS = {
        'XXMRUSDT': {'altname': 'XMRUSDT', 'base': 'XXMR', 'quote': 'USDT', 'mid': 100.0},
        'XZECZUSD': {'altname': 'ZECUSD', 'base': 'XZEC', 'quote': 'ZUSD', 'mid': 50.0},
        'USDTZUSD': {'altname': 'USDTUSD', 'base': 'USDT', 'quote': 'ZUSD', 'mid': 1.0},
    }

    def kraken(self, path, data):
        if path.startswith('/0/private/DepositAddresses'):
            address = 't1krakenaddress' if data.get('asset') == 'zec' else 'kraken-address'
            return [{'address': address, 'new': bool(data.get('new'))}]
        if path.startswith('/0/public/AssetPairs'):
            wanted = data.get('pair')
            if wanted and not any(wanted in (pair_id, p['altname']) for pair_id, p in self.PAIRS.items()):
                raise KrakenError('EQuery:Unknown asset pair')
            return {pair_id: {'altname': p['altname'], 'base': p['base'], 'quote': p['quote'], 'status': 'online',
                              'ordermin': '0.01', 'costmin': '0.5', 'pair_decimals': 4, 'lot_decimals': 8}
                    for pair_id, p in self.PAIRS.items() if not wanted or wanted in (pair_id, p['altname'])}
        if path.startswith('/0/public/Depth'):
            mid = self.PAIRS[data['pair']]['mid']
            return {data['pair']: {'bids': [[str(mid * 0.999), '1', 0]], 'asks': [[str(mid * 1.001), '1', 0]]}}
        if path.startswith('/0/private/Balance'):
            return dict(self.kraken_balances)
        if path.startswith('/0/private/AddOrder'):
            if not data.get('validate'):
                self.fill(data)
            return {'descr': {'order': data['type']}}
        raise AssertionError(f'unexpected Kraken call {path}')

    def fill(self, order):
        """Fill a live IOC order whose limit crosses the book, as Kraken would."""
        pair = next(p for p in self.PAIRS.values() if p['altname'] == order['pair'])
        mid, volume, price = pair['mid'], float(order['volume']), float(order['price'])
        base, quote = pair['base'], pair['quote']
        if order['type'] == 'sell' and price <= mid * 0.999:
            self.credit(base, -volume)
            self.credit(quote, volume * mid * 0.999)
        elif order['type'] == 'buy' and price >= mid * 1.001:
            cost = volume * mid * 1.001 * 1.004  # taker fee charged in the quote
            assert cost <= float(self.kraken_balances.get(quote, 0)), f'insufficient {quote} for {order}'
            self.credit(quote, -cost)
            self.credit(base, volume)

    def credit(self, asset_id, amount):
        self.kraken_balances[asset_id] = str(float(self.kraken_balances.get(asset_id, 0)) + amount)

    def fund_moving(self):
        moved = []
        for backend, method, params in self.sent:
            if backend == 'electrum' and method == 'broadcast':
                moved.append(f'electrum {method}')
            if backend == 'monero' and method in ('sweep_all', 'transfer', 'relay_tx') \
                    and not params.get('do_not_relay'):
                moved.append(f'monero {method}')
            if backend == 'zcash' and method in ('z_mergetoaddress', 'z_sendmany', 'sendtoaddress', 'sendmany'):
                moved.append(f'zcash {method}')
            if backend == 'kraken' and method == '/0/private/AddOrder' and not params.get('validate'):
                moved.append('kraken AddOrder')
            if backend == 'kraken' and method == '/0/private/DepositAddresses' and params.get('new'):
                moved.append('kraken new deposit address')
        return moved


def utxo(txid, n, value, height):
    return {'prevout_hash': txid, 'prevout_n': n, 'value': value, 'height': height}


def load(module, dry_run, kraken_key, **extra_env):
    environment = {
        'DRY_RUN': '1' if dry_run else '0',
        'TESTNET': '0',
        'KRAKEN_API_KEY': 'key' if kraken_key else '',
        'KRAKEN_API_SECRET': KRAKEN_SECRET,
        'STATUS_DIR': '',
        'MONERO_RPC_URL': 'http://monero-wallet-rpc:18082/json_rpc',
        'BITCOIN_ELECTRUM_RPC_URL': 'http://btc-electrum:7000',
        'LITECOIN_MWEB_ELECTRUM_RPC_URL': 'http://ltc-mweb-electrum:7000',
        'ZCASH_RPC_URL': 'http://zcash-wallet:8232/',
        'ZCASH_HEALTH_URL': 'http://zcash-wallet:9233',
        **extra_env,
    }
    with mock.patch.dict(os.environ, environment):
        for name in ('env', 'constants', 'util', 'status', module):
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)
    return sys.modules[module]


def forward(coin):
    def run(module, _backends):
        if coin == 'xmr':
            module.attempt_monero()
        elif coin == 'zec':
            module.attempt_zcash_autoforward()
        else:
            module.attempt_electrum_autoforward(coin)
    return run


ASSET_IDS = {'XMR': 'XXMR', 'ZEC': 'XZEC', 'USD': 'ZUSD', 'USDT': 'USDT'}


def sell(asset, amount='2.0'):
    def run(module, backends):
        module.asset_name_to_id = dict(ASSET_IDS)
        backends.kraken_balances[ASSET_IDS[asset]] = amount
        module.load_balances()
        module.load_pairs()
        module.attempt_sell(asset, 'USDT')
    return run


SCENARIOS = [
    # (name, module, kraken key configured, action)
    ('btc to own address', 'autoforward', False, forward('btc')),
    ('btc to Kraken', 'autoforward', True, forward('btc')),
    ('ltc-mweb peg-out', 'autoforward', True, forward('ltc-mweb')),
    ('ltc to Kraken', 'autoforward', True, forward('ltc')),
    ('xmr to own address', 'autoforward', False, forward('xmr')),
    ('xmr to Kraken', 'autoforward', True, forward('xmr')),
    ('zec to own address', 'autoforward', False, forward('zec')),
    ('zec to Kraken', 'autoforward', True, forward('zec')),
    ('sell xmr on Kraken', 'autoconvert', True, sell('XMR')),
    ('sell zec on Kraken via USD', 'autoconvert', True, sell('ZEC')),
    # USD in AUTOCONVERT_ASSETS sweeps the residue those sales leave: a
    # direct route on which the settlement currency is bought, not sold.
    ('sweep usd residue to USDT', 'autoconvert', True, sell('USD', '10.5')),
]


class DryRunNeverMovesFunds(unittest.TestCase):
    def run_scenario(self, module_name, kraken_key, action, dry_run):
        backends = Backends()
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get):
            module = load(module_name, dry_run, kraken_key)
            action(module, backends)
        return backends

    def test_scenarios(self):
        for name, module_name, kraken_key, action in SCENARIOS:
            with self.subTest(name, dry_run=True):
                backends = self.run_scenario(module_name, kraken_key, action, dry_run=True)
                self.assertEqual(backends.fund_moving(), [], backends.sent)

            with self.subTest(name, dry_run=False):
                backends = self.run_scenario(module_name, kraken_key, action, dry_run=False)
                self.assertNotEqual(backends.fund_moving(), [], backends.sent)


class ForwardSelection(unittest.TestCase):
    """Which outputs a live pass spends."""

    def forward(self, coin, backends, **extra_env):
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get):
            load('autoforward', dry_run=False, kraken_key=True, **extra_env).attempt_electrum_autoforward(coin)
        return [params for backend, method, params in backends.sent if method == 'payto']

    def test_ltc_waits_for_peg_out_maturity(self):
        # Consensus rejects spending a peg-out before PEGOUT_MATURITY (6)
        # blocks, and MWEB receipts reach the LTC wallet as peg-outs.
        tip = 1000
        immature = Backends(utxos=[utxo('aa', 0, '1.5', tip - 4)], tip=tip)  # 5 confirmations
        self.assertEqual(self.forward('ltc', immature), [])
        mature = Backends(utxos=[utxo('aa', 0, '1.5', tip - 5)], tip=tip)  # 6 confirmations
        self.assertEqual(len(self.forward('ltc', mature)), 1)

    def test_backlog_goes_out_in_standard_size_batches(self):
        # Thousands of inputs would exceed the 100 kvB standard size and
        # never relay: each pass spends at most ELECTRUM_MAX_INPUTS, largest first.
        utxos = [utxo(f'{i:064x}', 0, f'0.{i + 1:08d}', 10) for i in range(1000)]
        backends = Backends(utxos=utxos)
        payto = self.forward('btc', backends, ELECTRUM_MAX_INPUTS='400')
        self.assertEqual(len(payto), 1)
        chosen = payto[0]['from_coins'].split(',')
        self.assertEqual(len(chosen), 400)
        self.assertEqual(chosen[0], f'{999:064x}:0')  # the largest output first

    def test_mweb_is_pegged_out_to_an_ltc_change_address_not_sent_to_kraken(self):
        backends = Backends()
        payto = self.forward('ltc-mweb', backends)
        self.assertEqual([p['destination'] for p in payto], ['ltc1qchangeaddress'])
        self.assertFalse([1 for b, method, p in backends.sent if method.startswith('/0/private/DepositAddresses')])
        self.assertIn({'change': True, 'unused': True},
                      [p for b, method, p in backends.sent if method == 'listaddresses'])


class BackendFailures(unittest.TestCase):
    def test_electrum_restart_reloads_the_wallet(self):
        # A restarted Electrum daemon answers 'wallet not loaded' until
        # load_wallet; the coin must recover on its next pass by itself.
        backends = Backends()
        unloaded = {'loaded': False}
        electrum = backends.electrum

        def restarted(method, params):
            if method == 'load_wallet':
                unloaded['loaded'] = True
                return True
            if method == 'changegaplimit':
                return True
            if not unloaded['loaded']:
                raise WalletNotLoaded()
            return electrum(method, params)

        def post(url, **kwargs):
            try:
                return backends_post(url, **kwargs)
            except WalletNotLoaded:
                return FakeResponse({'error': {'code': 1, 'message': 'wallet not loaded'}})

        backends_post = backends.post
        backends.electrum = restarted
        with mock.patch('requests.post', post), mock.patch('requests.get', backends.get):
            load('autoforward', dry_run=True, kraken_key=False).attempt_electrum_autoforward('btc')
        self.assertIn('payto', [method for _, method, _ in backends.sent])

    def test_hung_wallet_rpc_fails_the_pass_on_the_probe(self):
        calls = []

        def hung(url, timeout=None, **kwargs):
            calls.append((json_method(kwargs), timeout))
            raise requests.exceptions.ReadTimeout('paused')

        with mock.patch('requests.post', hung):
            module = load('autoforward', dry_run=True, kraken_key=False)
            with self.assertRaises(requests.exceptions.ReadTimeout):
                module.attempt_monero()
        # One short probe, not a chain of 60 s and 600 s calls.
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(calls[0][1], 15)


class KrakenError(Exception):
    pass


class WalletNotLoaded(Exception):
    pass


def json_method(kwargs):
    return (kwargs.get('json') or {}).get('method')


class IndirectSale(unittest.TestCase):
    """ZEC has no USDT market on Kraken, so it is sold for USD, then USD for USDT."""

    def sell_zec(self, dry_run, usd_already_held='0'):
        backends = Backends()
        backends.kraken_balances['ZUSD'] = usd_already_held
        output = io.StringIO()
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get), \
                contextlib.redirect_stdout(output):
            sell('ZEC')(load('autoconvert', dry_run=dry_run, kraken_key=True), backends)
        return backends, output.getvalue()

    def test_second_leg_converts_this_sales_proceeds_and_nothing_else(self):
        # The first leg's USD must reach USDT (a buy limited below the book
        # never fills as IOC), and USD the account already held is not ours.
        backends, _ = self.sell_zec(dry_run=False, usd_already_held='1000')
        balances = {k: float(v) for k, v in backends.kraken_balances.items()}
        self.assertAlmostEqual(balances['XZEC'], 0)
        self.assertGreater(balances.get('USDT', 0), 98)  # 2 ZEC at ~50 USD, less fees
        self.assertAlmostEqual(balances['ZUSD'], 1000, delta=1)

    def test_a_missing_market_is_not_logged_as_an_error(self):
        # Zabbix pages on any error/failed line in the autoconvert log
        # (af.convert.errors), so routing around ZECUSDT must stay quiet.
        _, output = self.sell_zec(dry_run=True)
        self.assertIn('USDTUSD', output)
        self.assertNotRegex(output.lower(), r'error|exception|traceback|failed')


class ZcashSweep(unittest.TestCase):
    def run_live(self, backends):
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get):
            load('autoforward', dry_run=False, kraken_key=True).attempt_zcash_autoforward()
        return [params for backend, method, params in backends.sent if method == 'z_mergetoaddress']

    def test_never_sweeps_a_wallet_that_is_not_ready(self):
        # A wallet still scanning reports a partial balance.
        backends = Backends(zcash_ready=False)
        with self.assertRaises(Exception):
            self.run_live(backends)
        self.assertEqual([m for b, m, p in backends.sent if b == 'zcash'], [])

    def test_sweeps_each_pool_to_the_kraken_t_address_and_skips_an_empty_one(self):
        merges = self.run_live(Backends(zcash_empty_pools=('ANY_SAPLING',)))
        self.assertEqual([m[0] for m in merges], [['ANY_ORCHARD'], ['ANY_SAPLING']])
        for m in merges:
            self.assertEqual(m[1], 't1krakenaddress')
            self.assertEqual(m[6], 'AllowRevealedRecipients')


class PegoutLive(unittest.TestCase):
    """PEGOUT_LIVE makes only the own-wallet peg-out real."""

    def run_dry(self, action, **extra_env):
        backends = Backends()
        with mock.patch('requests.post', backends.post), mock.patch('requests.get', backends.get):
            action(load('autoforward', dry_run=True, kraken_key=True, **extra_env), backends)
        return backends

    def test_peg_out_is_broadcast(self):
        backends = self.run_dry(forward('ltc-mweb'), PEGOUT_LIVE='1')
        self.assertIn('electrum broadcast', backends.fund_moving())

    def test_every_forward_to_the_exchange_stays_dry(self):
        for coin in ('btc', 'ltc', 'xmr'):
            with self.subTest(coin):
                self.assertEqual(self.run_dry(forward(coin), PEGOUT_LIVE='1').fund_moving(), [])


class DryRunIsTheDefault(unittest.TestCase):
    def test_unset_means_dry_run(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('DRY_RUN', None)
            env = importlib.reload(importlib.import_module('env'))
        self.assertTrue(env.DRY_RUN)


if __name__ == '__main__':
    unittest.main()
