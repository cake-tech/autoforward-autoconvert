import math
import traceback
import random
import time
import util
import env

balances = {}
asset_name_to_id = {}

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


def get_pair_details(quote_curency, base_currency):
    pair_details_result = util.kraken_request('/0/public/AssetPairs', {'pair': f'{quote_curency}{base_currency}'})
    pair_id = next(iter(pair_details_result))
    pair_details = pair_details_result[pair_id]
    order_min = float(pair_details['ordermin'])
    trade_decimals = int(pair_details['pair_decimals'])
    volume_decimals = int(pair_details['lot_decimals'])
    return order_min, trade_decimals, volume_decimals


# amount is held in quote_currency when selling and in base_currency when buying
def prepare_and_make_trade(amount, quote_currency, base_currency, payload):
    # Get trading pair details for a direct conversion
    order_min, trade_decimals, volume_decimals = get_pair_details(quote_currency, base_currency)
    is_sell = payload['type'] == 'sell'

    # If we continue, then we got the pair details without issues
    # We get the current orderbook to calculate the mid market price
    orderbook_result = util.kraken_request('/0/public/Depth?count=1', {'pair': f'{quote_currency}{base_currency}'})
    pair_id = next(iter(orderbook_result))
    orderbook = orderbook_result[pair_id]

    mid_market_price = float(orderbook['bids'][0][0]) + ((float(orderbook['asks'][0][0]) - float(orderbook['bids'][0][0])) / 2) # Example 212.55+((212.72-212.55)/2) = 212.635
    slippage = env.MAX_SLIPPAGE_PERCENT / 100
    limit_price = mid_market_price * (1 - slippage if is_sell else 1 + slippage) # Example 212.635*(1-0.5/100) = 211.571825
    limit_price = round(limit_price, trade_decimals)  # Example 211.571825 -> 211.57

    # Kraken always denominates volume in quote_currency, so a buy converts what it has to spend
    volume = amount if is_sell else amount / limit_price
    volume = math.floor(volume * 10 ** volume_decimals) / 10 ** volume_decimals  # Rounding up would exceed the balance

    # We ensure we have more than the minimum to trade
    if volume < order_min:
        print(f'{quote_currency} volume {volume} is below the minimum of {order_min}; skipping')
        return

    # We make the trade
    payload['price'] = limit_price
    payload['volume'] = volume
    util.kraken_request('/0/private/AddOrder', payload)
    print(util.get_time(), f'{"Selling" if is_sell else "Buying"} up to {volume} {quote_currency} for pair {payload['pair']} for limit price {limit_price}')


def attempt_sell(asset: str, settlement_currency: str):
    balance = get_balance(asset)

    if balance == 0:
        print(f'No balance for {asset}; skipping')
        return

    payload = {
        'ordertype': 'limit',
        'timeinforce': 'IOC' # Immediately fill order to extent possible, then cancel
    }

    try:
        payload['type'] = 'sell'
        payload['pair'] = f'{asset}{settlement_currency}'
        prepare_and_make_trade(balance, asset, settlement_currency, payload)
        return
    except Exception as e:
        print('prepare_and_make_trade error: ', e)
        # If we are here, then there is an issue getting the pair details and executing the trade
        # Either there is a Kraken error, or this trading pair does not exist
        print(f'Attempting to sell indirectly via other assets')

    for intermediary_currency in ['USD', 'USDT', 'USDC', 'EUR', 'XBT']:
        # NOTE: it's possible for the conversion to be "stuck" in the intermediary currency if there is not enough to convert out of
        # Remove any intermediary currencies that you don't want value to get potentially stuck in
        # Conversion fees apply: https://www.kraken.com/features/fee-schedule#spot-crypto
        # Fees are lower for trades between stablecoins/FX, such as USDT/EUR
        try:
            get_pair_details(asset, intermediary_currency)  # Using asset as quote currency and intermediary as base currency
            get_pair_details(settlement_currency, intermediary_currency)  # Using settlement currency as quote currency and intermediary as base currency
        except Exception:
            print(f'No path found through {intermediary_currency}')
            continue

        # If we made it here, then a route through the intermediary currency exists (we would have gotten an error with get_pair_details if it didn't)
        # A trade that fails from here on is raised, not swallowed, so it isn't reported as a missing path
        # Start the first trade, selling the asset for the base intermediary currency
        payload['type'] = 'sell'
        payload['pair'] = f'{asset}{intermediary_currency}'
        prepare_and_make_trade(balance, asset, intermediary_currency, payload)

        # Start the second trade, buying the quote settlement currency with the base intermediary currency balance
        load_balances()
        intermediary_balance = get_balance(intermediary_currency)
        payload['type'] = 'buy'
        payload['pair'] = f'{settlement_currency}{intermediary_currency}'
        prepare_and_make_trade(intermediary_balance, settlement_currency, intermediary_currency, payload)
        break  # The balance is spent, so don't sell it again through the next intermediary

def get_enabled_kraken_assets() -> list[str]:
    assets = []

    if env.BITCOIN_ENABLED:
        assets.append('XBT')

    # Both Litecoin wallets deposit as LTC on Kraken, so either one enables the sell
    if env.LITECOIN_ENABLED or env.LITECOIN_MWEB_ENABLED:
        assets.append('LTC')

    if env.MONERO_ENABLED:
        assets.append('XMR')

    return assets


if __name__ == '__main__':
    if env.TESTNET == '1':
        print('Testnet mode enabled. Autoconvert will now sleep forever. Zz Zz Zz...')
        time.sleep(999999999)

    enabled_assets = get_enabled_kraken_assets()
    print(util.get_time(), f'Autoconverting: {", ".join(enabled_assets) or "nothing"}')

    load_asset_names_and_ids()

    while 1:
        # First, get the settlement currency formatted correctly
        settlement_currency = env.SETTLEMENT_CURRENCY
        load_balances()

        # Then, initiate the selling process for each enabled asset unless it's already the settlement currency
        for asset in enabled_assets:
            try:
                if settlement_currency != asset:
                    attempt_sell(asset, settlement_currency)
                else:
                    print(f'Not converting {asset} since it is already in the settlement currency')
            except Exception as e:
                print(util.get_time(), f'Error attempting to sell {asset}:')
                print(traceback.format_exc())

        delay = random.randint(30, 90)
        time.sleep(delay)
