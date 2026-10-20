from typing import List, Literal, cast
from decimal import Decimal
from time import sleep, time
import random
import traceback
import requests
import json

from constants import MIN_BITCOIN_SEND_AMOUNT_MAINNET, MIN_BITCOIN_SEND_AMOUNT_TESTNET, MIN_LITECOIN_SEND_AMOUNT_MAINNET, MIN_LITECOIN_SEND_AMOUNT_TESTNET, MIN_MONERO_SEND_AMOUNT_MAINNET, MIN_MONERO_SEND_AMOUNT_TESTNET
import util
import env
import status

ElectrumCoin = Literal['btc', 'ltc', 'ltc-mweb']

def get_fee_rate(coin: ElectrumCoin) -> int:
    coin_to_source: dict[ElectrumCoin, str] = {
        'btc': env.BITCOIN_FEE_SOURCE,
        'ltc': env.LITECOIN_FEE_SOURCE,
        'ltc-mweb': env.LITECOIN_FEE_SOURCE
    }

    coin_to_rate: dict[ElectrumCoin, str] = {
        'btc': env.BITCOIN_FEE_RATE,
        'ltc': env.LITECOIN_FEE_RATE,
        'ltc-mweb': env.LITECOIN_FEE_RATE
    }

    source = coin_to_source[coin]
    rate = coin_to_rate[coin]

    return requests.get(source, timeout=15).json()[rate]

def set_electrum_fee_rate(coin: ElectrumCoin, rate: int = None, dynamic: bool = None):
    if dynamic:  # Fall back to the Electrum rate if there is an issue
        util.request_electrum_rpc(coin, 'setconfig', ['fee_policy.default', 'eta:3'])
    elif rate:
        util.request_electrum_rpc(coin, 'setconfig', ['fee_policy.default', f'feerate:{rate * 1000}'])
    else:
        raise Exception('Either rate or dynamic=True must be provided')

def get_electrum_balance(coin: ElectrumCoin) -> float:
    return float(util.request_electrum_rpc(coin, 'getbalance')['confirmed'])

def get_electrum_unused_address(coin: ElectrumCoin) -> str:
    return util.request_electrum_rpc(coin, 'getunusedaddress')

def create_psbt(coin: ElectrumCoin, destination_address: str, fee_rate: int = None, unsigned = True, from_coins: str | None = None) -> str:
    params = {
        'destination': destination_address,
        'amount': '!',
        'feerate': fee_rate,
        'unsigned': unsigned # This way we can get the input amounts
    }

    if from_coins:
        params['from_coins'] = from_coins

    return util.request_electrum_rpc(coin, 'payto', params, timeout=env.SEND_TIMEOUT)

def get_psbt_data(coin: ElectrumCoin, psbt: str) -> dict:
    return util.request_electrum_rpc(coin, 'deserialize', [psbt])

def get_tx_output_amount(coin: ElectrumCoin, tx_id: str, output_index: int) -> int:
    try:
        serialized_tx = util.request_electrum_rpc(coin, 'gettransaction', [tx_id])
    except Exception as e:
        if 'No such mempool or blockchain transaction' in e.__str__():
            print(util.get_time(), 'Got "No such mempool or blockchain transaction" error while getting transaction outputs. Looking for the offending transaction in history...')
            find_and_remove_offending_transactions(coin)
            serialized_tx = util.request_electrum_rpc(coin, 'gettransaction', [tx_id])
        else:
            raise e

    tx = util.request_electrum_rpc(coin, 'deserialize', [serialized_tx])

    for i, output in enumerate(tx['outputs']):
        if i == output_index:
            return output['value_sats']

    raise Exception(f'Output {output_index} not found in {coin} transaction {tx_id}')

def get_total_psbt_fee(coin: ElectrumCoin, tx: dict, inputs_sum_sats: int | None = None) -> float:
    outputs_sum_sats = 0

    if inputs_sum_sats is None:
        # One gettransaction per input; a batch passes the sum it already knows.
        inputs_sum_sats = 0
        for _input in tx['inputs']:
            inputs_sum_sats += get_tx_output_amount(coin, _input['prevout_hash'], _input['prevout_n'])
    
    for _output in tx['outputs']:
        outputs_sum_sats += cast(int, _output['value_sats'])

    total_fee_sats = inputs_sum_sats - outputs_sum_sats
    total_fee = total_fee_sats / 100000000
    return total_fee

def sign_psbt(coin: ElectrumCoin, psbt: str) -> str:
    return cast(str, util.request_electrum_rpc(coin, 'signtransaction', [psbt], timeout=env.SEND_TIMEOUT))

def find_and_remove_offending_transactions(coin: ElectrumCoin):
    history = cast(List[dict], util.request_electrum_rpc(coin, 'onchain_history'))

    for tx in history:
        if tx['confirmations'] == -2:
            print(util.get_time(), f'Removing local transaction {tx['txid']} from history...')
            util.request_electrum_rpc(coin, 'removelocaltx', [tx['txid']])

def select_coins(coin: ElectrumCoin) -> tuple[str | None, int, int]:
    """The outputs this pass may forward: (payto from_coins, their total in
    sats, how many spendable outputs are left for later passes).

    Only confirmed outputs, and for LTC only those with LITECOIN_MIN_CONFIRMATIONS:
    MWEB receipts reach the LTC wallet as peg-outs, which consensus will not
    let anyone spend for PEGOUT_MATURITY (6) blocks. At most
    ELECTRUM_MAX_INPUTS, largest first, so a backlog goes out in
    standard-size transactions. from_coins is None when the selection is
    simply everything, so the usual '!' sweep applies.
    """
    utxos = util.request_electrum_rpc(coin, 'listunspent')
    min_confirmations = env.LITECOIN_MIN_CONFIRMATIONS if coin == 'ltc' else 1
    tip = util.request_electrum_rpc(coin, 'getinfo')['blockchain_height'] if min_confirmations > 1 else 0

    def confirmations(utxo: dict) -> int:
        height = utxo.get('height', 0)
        if height <= 0:
            return 0
        return tip - height + 1 if tip else 1

    eligible = [u for u in utxos if confirmations(u) >= min_confirmations]
    eligible.sort(key=lambda u: Decimal(str(u['value'])), reverse=True)
    chosen = eligible[:env.ELECTRUM_MAX_INPUTS]
    total_sats = int(sum(Decimal(str(u['value'])) for u in chosen) * 100000000)

    if len(chosen) == len(utxos):
        return None, total_sats, 0

    from_coins = ','.join(f"{u['prevout_hash']}:{u['prevout_n']}" for u in chosen)
    return from_coins, total_sats, len(eligible) - len(chosen)

def get_pegout_address() -> str:
    # A CHANGE address of the LTC wallet. That wallet is the merchant's LTC
    # chain, but merchants hand out only receiving addresses to invoices, so
    # funds arriving here can never be taken for an invoice payment.
    return util.request_electrum_rpc('ltc', 'listaddresses', {'change': True, 'unused': True})[0]

last_address_report: dict = {}

def report_tracked_addresses(coin: ElectrumCoin) -> None:
    if time() - last_address_report.get(coin, 0) < env.ELECTRUM_ADDRESS_REPORT_INTERVAL:
        return

    addresses = util.request_electrum_rpc(coin, 'listaddresses', {'receiving': True}, timeout=env.SEND_TIMEOUT)
    status.set(coin, receiving_addresses=len(addresses), gap_limit=env.ELECTRUM_GAP_LIMIT)
    last_address_report[coin] = time()

def broadcast_electrum_tx(coin: ElectrumCoin, signed_tx: str):
    util.request_electrum_rpc(coin, 'broadcast', [signed_tx], timeout=env.SEND_TIMEOUT)

def get_monero_balance() -> float:
    params = {'account_index': 0}
    return util.request_monero_rpc('get_balance', params)['unlocked_balance'] / 1000000000000

def get_monero_unused_address() -> str:
    return util.request_monero_rpc('get_address', {'account_index': 0})['address']

def sweep_all_monero(address: str) -> dict:
    params = {
        'account_index': 0,
        'address': address,
        'subaddr_indices_all': True,  # Without this, it sends from each subaddress separately
        # Built and signed, never relayed or recorded as spent.
        'do_not_relay': env.DRY_RUN
    }

    return util.request_monero_rpc('sweep_all', params, timeout=env.SEND_TIMEOUT)

monero_receipts = {'height': 0, 'max_subaddress': -1, 'last_received_at': 0}

def update_monero_receipts() -> None:
    # The highest subaddress index that has ever received funds, tracked
    # incrementally. A monitor compares it with the merchant wallet's (e.g.
    # BTCPay's view-only wallet): a payment there to an index this wallet
    # never reaches means it fell outside the subaddress lookahead and is
    # invisible here.
    params: dict = {'in': True, 'account_index': 0}

    if monero_receipts['height']:
        # min_height is exclusive; re-reading the last block is harmless.
        params.update(filter_by_height=True, min_height=monero_receipts['height'] - 1)

    # Only the first, full read of the history is slow; later ones are incremental.
    timeout = env.HTTP_TIMEOUT if monero_receipts['height'] else env.SEND_TIMEOUT
    transfers = util.request_monero_rpc('get_transfers', params, timeout=timeout).get('in', [])

    for transfer in transfers:
        monero_receipts['max_subaddress'] = max(monero_receipts['max_subaddress'], transfer['subaddr_index']['minor'])
        monero_receipts['height'] = max(monero_receipts['height'], transfer['height'])
        monero_receipts['last_received_at'] = max(monero_receipts['last_received_at'], transfer['timestamp'])

    status.set('xmr',
               wallet_height=util.request_monero_rpc('get_height')['height'],
               max_received_subaddress=monero_receipts['max_subaddress'],
               last_received_at=monero_receipts['last_received_at'])

last_monero_store = time()

def store_monero_wallet(force: bool = False) -> None:
    global last_monero_store

    if force or time() - last_monero_store >= env.MONERO_STORE_INTERVAL:
        util.request_monero_rpc('store', timeout=env.SEND_TIMEOUT)
        last_monero_store = time()

def get_destination_address(coin: ElectrumCoin | Literal['xmr']) -> str:
    # Testnet, or a dry run with no Kraken key: the wallet's own address,
    # since nothing is sent anyway.
    if env.TESTNET == '1' or (env.DRY_RUN and not env.KRAKEN_API_KEY):
        if coin == 'xmr':
            return get_monero_unused_address()
        return get_electrum_unused_address(coin)

    return get_new_kraken_address(coin)

def get_new_kraken_address(asset: Literal['btc', 'ltc', 'xmr']) -> str:
    sym_to_name = {
        "btc": "Bitcoin",
        "ltc": "Litecoin",
        "xmr": "Monero"
    }

    payload: dict[str, str | bool] = {
        'asset': asset,
        'method': sym_to_name[asset]
    }

    result = util.kraken_request('/0/private/DepositAddresses', payload)

    first_new_address = next((addr for addr in result if addr.get('new', False)), None)
    if first_new_address:
        return first_new_address['address']
    elif env.DRY_RUN and result:
        # Creating addresses is a write on the Kraken account; a dry run
        # reuses an existing one.
        return result[0]['address']
    else:
        payload['new'] = True
        result = util.kraken_request('/0/private/DepositAddresses', payload)
        first_new_address = next((addr for addr in result if addr.get('new', False)), None)
        if first_new_address:
            return first_new_address['address']

    raise Exception(f'Kraken did not return a new address: {json.dumps(result, indent=2)}')

def attempt_electrum_autoforward(coin: ElectrumCoin):
    coin_upper = coin.upper()
    report_tracked_addresses(coin)
    balance = get_electrum_balance(coin)

    coin_to_min_send_mainnet: dict[ElectrumCoin, float] = {
        'btc': MIN_BITCOIN_SEND_AMOUNT_MAINNET,
        'ltc': MIN_LITECOIN_SEND_AMOUNT_MAINNET,
        'ltc-mweb': MIN_LITECOIN_SEND_AMOUNT_MAINNET
    }

    coin_to_min_send_testnet: dict[ElectrumCoin, float] = {
        'btc': MIN_BITCOIN_SEND_AMOUNT_TESTNET,
        'ltc': MIN_LITECOIN_SEND_AMOUNT_TESTNET,
        'ltc-mweb': MIN_LITECOIN_SEND_AMOUNT_TESTNET
    }

    min_send = coin_to_min_send_testnet[coin] if env.TESTNET == '1' else coin_to_min_send_mainnet[coin]
    status.set(coin, balance=balance, min_send=min_send)

    from_coins, inputs_sum_sats = None, None
    if coin != 'ltc-mweb':
        from_coins, inputs_sum_sats, remaining = select_coins(coin)
        balance = inputs_sum_sats / 100000000  # what this pass can actually forward
        status.set(coin, forwardable=balance, outputs_left_for_later=remaining)
        if remaining:
            print(util.get_time(), f'Batching: this pass forwards the {env.ELECTRUM_MAX_INPUTS} largest {coin_upper} outputs ({balance}); {remaining} left for later passes.')

    if balance < min_send:
        print(util.get_time(), f'Not enough {coin_upper} balance to autoforward. (Forwardable: {balance}, Min. send: {min_send})')
        return

    try:
        fee_rate = get_fee_rate(coin)
        set_electrum_fee_rate(coin, fee_rate)
    except:
        set_electrum_fee_rate(coin, dynamic=True)

    if coin == 'ltc-mweb':
        # Kraken fails MWEB peg-out deposits, so MWEB never goes to Kraken
        # directly: it is pegged out to the LTC wallet, whose own pass then
        # forwards it in a standard transaction once it has matured.
        address = get_pegout_address()
        total_fee = None
        # Electrum-ltc doesn't support deserializing mweb transactions, so we can't check total fee
        signed_tx = create_psbt(coin, address, unsigned=False)
    else:
        address = get_destination_address(coin)

        try:
            psbt = create_psbt(coin, address, from_coins=from_coins)
        except requests.exceptions.HTTPError as http_error:
            response_json = cast(dict, http_error.response.json())

            if response_json.get('error', {}).get('data', {}).get('exception', '') == 'NotEnoughFunds()':
                print(util.get_time(), 'Not autoforwarding due to high transaction fee.')
                return

            raise http_error

        tx = get_psbt_data(coin, psbt)
        total_fee = get_total_psbt_fee(coin, tx, inputs_sum_sats if from_coins else None)
        amount = balance

        if total_fee / amount * 100 > env.MAX_NETWORK_FEE_PERCENT:
            print(util.get_time(), f'Not autoforwarding due to high transaction fee ({total_fee} {coin_upper}).')
            return

        signed_tx = sign_psbt(coin, psbt)

    if env.DRY_RUN and not (coin == 'ltc-mweb' and env.PEGOUT_LIVE):
        status.set(coin, last_dry_run_at=int(time()), last_dry_run_amount=balance, last_dry_run_fee=total_fee)
        print(util.get_time(), f'DRY RUN: built and signed a {balance} {coin_upper} forward to {address} (fee {total_fee}); not broadcast.')
        return

    try:
        broadcast_electrum_tx(coin, signed_tx)
    except Exception as e:
        error_msg = e.__str__()

        # https://github.com/MAGICGrants/autoforward-autoconvert/issues/34
        if ('bad-txns-inputs-missingorspent' in error_msg):
            print(util.get_time(), 'Got bad-txns-inputs-missingorspent error while broadcasting transaction. Looking for the offending transaction in history...')
            find_and_remove_offending_transactions(coin)
            broadcast_electrum_tx(coin, signed_tx)
        else:
            raise e

    if coin == 'ltc-mweb':
        status.set(coin, last_pegout_at=int(time()), last_pegout_amount=balance)
        print(util.get_time(), f'Pegged out {balance} LTC from MWEB to {address}; the LTC pass forwards it after {env.LITECOIN_MIN_CONFIRMATIONS} confirmations.')
        return

    status.set(coin, last_forward_at=int(time()), last_forward_amount=balance)
    print(util.get_time(), f'Autoforwarded {balance} {coin_upper} to {address}!')

def attempt_monero_autoforward():
    balance = get_monero_balance()

    min_send = MIN_MONERO_SEND_AMOUNT_TESTNET if env.TESTNET == '1' else MIN_MONERO_SEND_AMOUNT_MAINNET
    status.set('xmr', balance=balance, min_send=min_send)

    if balance < min_send:
        print(util.get_time(), f'Not enough XMR balance to autoforward. (Balance: {balance}, Min Send: {min_send})')
        return

    address = get_destination_address('xmr')
    result = sweep_all_monero(address)

    if env.DRY_RUN:
        fee = sum(result.get('fee_list', [])) / 1000000000000
        status.set('xmr', last_dry_run_at=int(time()), last_dry_run_amount=balance, last_dry_run_fee=fee,
                   last_dry_run_txs=len(result.get('tx_hash_list', [])))
        print(util.get_time(), f'DRY RUN: built a {balance} XMR sweep to {address} in {len(result.get("tx_hash_list", []))} tx(s) (fee {fee}); not relayed.')
        return

    status.set('xmr', last_forward_at=int(time()), last_forward_amount=balance)
    print(util.get_time(), f'Autoforwarded {balance} XMR to {address}!')
    store_monero_wallet(force=True)

def attempt_monero() -> None:
    # A hung wallet-rpc would otherwise hold the whole loop for every call's
    # timeout in turn (11 minutes a pass on btcpay-stg); fail the pass fast.
    util.request_monero_rpc('get_height', timeout=env.PROBE_TIMEOUT)

    # Bookkeeping for monitoring only: never let it block the sweep.
    try:
        update_monero_receipts()
        status.ok('xmr-receipts')
    except Exception as e:
        status.error('xmr-receipts', e)
        print(util.get_time(), 'Error reading Monero receipts:')
        print(traceback.format_exc())

    attempt_monero_autoforward()
    store_monero_wallet()

attempts = {
    'btc': ('Bitcoin', lambda: attempt_electrum_autoforward('btc')),
    'ltc': ('Litecoin', lambda: attempt_electrum_autoforward('ltc')),
    'ltc-mweb': ('Litecoin MWEB', lambda: attempt_electrum_autoforward('ltc-mweb')),
    'xmr': ('Monero', attempt_monero),
}

def main() -> None:
    unknown = [coin for coin in env.AUTOFORWARD_COINS if coin not in attempts]
    if unknown:
        raise SystemExit(f'Unknown AUTOFORWARD_COINS entries: {unknown}')
    if 'ltc-mweb' in env.AUTOFORWARD_COINS and 'ltc' not in env.AUTOFORWARD_COINS:
        raise SystemExit('ltc-mweb pegs out to the LTC wallet, so it needs ltc in AUTOFORWARD_COINS too.')

    print('Autoforwarding:', ', '.join(env.AUTOFORWARD_COINS))
    if env.DRY_RUN:
        print('DRY RUN: transactions are built and signed but never broadcast. Set DRY_RUN=0 to forward.')
        if env.PEGOUT_LIVE:
            print('PEGOUT_LIVE: MWEB peg-outs to the LTC wallet ARE broadcast; forwards stay dry.')

    util.wait_for_rpc()
    util.wait_for_wallets()

    while 1:
        for coin in env.AUTOFORWARD_COINS:
            name, attempt = attempts[coin]

            try:
                attempt()
                status.ok(coin)
            except Exception as e:
                status.error(coin, e)
                print(util.get_time(), f'Error autoforwarding {name}:')
                print(traceback.format_exc())

        status.write('autoforward')

        delay = random.randint(270, 330)
        sleep(delay)

if __name__ == '__main__':
    main()
