import math
import traceback
import random
import time
import util
import env
import status

balances = {}
asset_name_to_id = {}
pairs = {}

# Tried in order when an asset has no market with the settlement currency.
# Value can sit in the intermediary if its second leg is below the minimum.
INTERMEDIARY_CURRENCIES = ['USD', 'USDT', 'USDC', 'EUR', 'XBT']
PROCEEDS_POLLS = 6
PROCEEDS_POLL_SECONDS = 5

def load_asset_names_and_ids():
    global asset_name_to_id
    result = util.kraken_request('/0/public/Assets')
    asset_name_to_id = {asset_info['altname']: asset_id for asset_id, asset_info in result.items()}


def load_balances():
    global balances
    balances = util.kraken_request('/0/private/Balance')


def get_balance(asset: str) -> float:
    global balances
    
    asset_id = asset_name_to_id[asset]

    if asset_id in balances:
        return float(balances[asset_id])
    else:
        return 0


def load_pairs():
    """Index Kraken's tradable pairs by (base, quote) altname, e.g. ('ZEC', 'USD').

    Routes are chosen from this table, so a pair that does not exist (ZEC has
    no USDT market) is a lookup miss rather than a failed API call that logs
    an error on every pass.
    """
    global pairs
    id_to_name = {asset_id: name for name, asset_id in asset_name_to_id.items()}
    loaded = {}
    for pair_id, details in util.kraken_request('/0/public/AssetPairs').items():
        if details.get('status', 'online') != 'online':
            continue
        base, quote = id_to_name.get(details['base']), id_to_name.get(details['quote'])
        if base and quote:
            loaded[(base, quote)] = dict(details, pair_id=pair_id)
    pairs = loaded


def has_market(a: str, b: str) -> bool:
    return (a, b) in pairs or (b, a) in pairs


def find_route(asset: str, settlement_currency: str) -> list[str] | None:
    if has_market(asset, settlement_currency):
        return [asset, settlement_currency]
    for intermediary in INTERMEDIARY_CURRENCIES:
        if intermediary not in (asset, settlement_currency) \
                and has_market(asset, intermediary) and has_market(intermediary, settlement_currency):
            return [asset, intermediary, settlement_currency]
    return None


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def convert(amount: float, from_asset: str, to_asset: str) -> float | None:
    """Turn `amount` of from_asset into to_asset with one IOC limit order.

    Sells on a from/to market, buys on a to/from one. Returns the amount of
    to_asset the order should yield after fees, or None when `amount` is
    below the market's minimum. Under DRY_RUN Kraken validates the order and
    places nothing.
    """
    selling = (from_asset, to_asset) in pairs
    pair = pairs[(from_asset, to_asset)] if selling else pairs[(to_asset, from_asset)]
    book = util.kraken_request('/0/public/Depth', {'pair': pair['pair_id'], 'count': 1})[pair['pair_id']]
    bid, ask = float(book['bids'][0][0]), float(book['asks'][0][0])
    mid = (bid + ask) / 2
    fee = env.KRAKEN_FEE_MARGIN_PERCENT / 100

    # The limit is the worst price accepted: below mid to sell, above mid
    # to buy. A buy limited below mid never fills as IOC, which would leave
    # the first leg's proceeds sitting in the intermediary.
    if selling:
        price = round(mid * (1 - env.MAX_SLIPPAGE_PERCENT / 100), int(pair['pair_decimals']))
        volume = round_down(amount, int(pair['lot_decimals']))
        receives = volume * price * (1 - fee)
    else:
        price = round(mid * (1 + env.MAX_SLIPPAGE_PERCENT / 100), int(pair['pair_decimals']))
        # Kraken's volume is in the base (bought) asset and a buy's fee is
        # charged in the quote. Sized at the ask, which is where it fills;
        # sizing at the limit would leave the slippage allowance behind in
        # the intermediary. The fee margin over the real fee absorbs a move.
        volume = round_down(amount / (ask * (1 + fee)), int(pair['lot_decimals']))
        receives = volume

    if volume < float(pair['ordermin']) or volume * price < float(pair.get('costmin') or 0):
        print(f'{amount} {from_asset} is below the minimum for {pair["altname"]} (ordermin {pair["ordermin"]} {to_asset if not selling else from_asset}); skipping')
        return None

    payload = {
        'ordertype': 'limit',
        'timeinforce': 'IOC',  # fill what the book allows now, cancel the rest
        'type': 'sell' if selling else 'buy',
        'pair': pair['altname'],
        'volume': volume,
        'price': price,
    }
    action = f'{"selling" if selling else "buying"} {volume} {from_asset if selling else to_asset} on {pair["altname"]} at limit {price}'
    if env.DRY_RUN:
        payload['validate'] = True
        util.kraken_request('/0/private/AddOrder', payload)
        print(util.get_time(), f'DRY RUN: Kraken validated {action}; not placed.')
    else:
        util.kraken_request('/0/private/AddOrder', payload)
        print(util.get_time(), action[0].upper() + action[1:])
    return receives


def wait_for_increase(asset: str, before: float) -> float:
    """What a just-filled order added to `asset`, once Kraken's balance shows it."""
    for _ in range(PROCEEDS_POLLS):
        load_balances()
        delta = get_balance(asset) - before
        if delta > 0:
            return delta
        time.sleep(PROCEEDS_POLL_SECONDS)
    return 0.0


def attempt_sell(asset: str, settlement_currency: str):
    balance = get_balance(asset)
    status.set(asset, balance=balance)

    if balance == 0:
        print(f'No balance for {asset}; skipping')
        return

    route = find_route(asset, settlement_currency)
    if route is None:
        raise Exception(f'Kraken has no market from {asset} to {settlement_currency}, directly or via {", ".join(INTERMEDIARY_CURRENCIES)}')

    if len(route) == 2:
        if convert(balance, asset, settlement_currency) is not None and not env.DRY_RUN:
            status.set(asset, last_sell_at=int(time.time()), last_sell_amount=balance)
        return

    # NOTE: conversion fees apply to each leg:
    # https://www.kraken.com/features/fee-schedule#spot-crypto
    intermediary = route[1]
    before = get_balance(intermediary) if intermediary in asset_name_to_id else 0.0
    expected = convert(balance, asset, intermediary)
    if expected is None:
        return

    # Only this sale's proceeds go on to the settlement currency: whatever
    # else the account holds in the intermediary is not ours to convert.
    proceeds = expected if env.DRY_RUN else wait_for_increase(intermediary, before)
    if proceeds <= 0:
        raise Exception(f'sold {asset} for {intermediary} but no {intermediary} proceeds showed up in the balance; '
                        f'convert them to {settlement_currency} by hand')
    convert(proceeds, intermediary, settlement_currency)
    if not env.DRY_RUN:
        status.set(asset, last_sell_at=int(time.time()), last_sell_amount=balance, last_sell_via=intermediary)

if __name__ == '__main__':
    if env.TESTNET == '1':
        print('Testnet mode enabled. Autoconvert will now sleep forever. Zz Zz Zz...')
        time.sleep(999999999)

    if not env.KRAKEN_API_KEY:
        print('No Kraken API key configured. Autoconvert will now sleep forever.')
        status.set('kraken', disabled='no API key')
        status.write('autoconvert')
        time.sleep(999999999)

    print('Autoconverting:', ', '.join(env.AUTOCONVERT_ASSETS), '->', env.SETTLEMENT_CURRENCY)
    if env.DRY_RUN:
        print('DRY RUN: orders are validated by Kraken but never placed. Set DRY_RUN=0 to sell.')

    while 1:
        # First, get the settlement currency formatted correctly
        settlement_currency = env.SETTLEMENT_CURRENCY

        # A Kraken outage (an HTML error page instead of JSON) must cost one
        # pass, not crash the program.
        try:
            if not asset_name_to_id:
                load_asset_names_and_ids()
            if not pairs:
                load_pairs()
            load_balances()
            status.ok('kraken')
        except Exception as e:
            status.error('kraken', e)
            status.write('autoconvert')
            print(util.get_time(), 'Error loading Kraken assets or balances:')
            print(traceback.format_exc())
            time.sleep(random.randint(30, 90))
            continue

        status.set('kraken', settlement_balance=get_balance(settlement_currency) if settlement_currency in asset_name_to_id else None)

        # Then, initiate the selling process for each supported asset unless it's already the settlement currency
        for asset in env.AUTOCONVERT_ASSETS:
            try:
                if settlement_currency != asset:
                    attempt_sell(asset, settlement_currency)
                    status.ok(asset)
                else:
                    print(f'Not converting {asset} since it is already in the settlement currency')
            except Exception as e:
                status.error(asset, e)
                print(util.get_time(), f'Error attempting to sell {asset}:')
                print(traceback.format_exc())

        status.write('autoconvert')

        delay = random.randint(30, 90)
        time.sleep(delay)
