import os


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


TESTNET = os.getenv('TESTNET', '0')

# Everything a live pass does - balances, fee checks, building and signing
# the transaction, Kraken lookups and order validation - except the parts
# that move funds: nothing is broadcast, Monero sweeps are built with
# do_not_relay, Kraken orders are sent with validate=true, and no new Kraken
# deposit address is created. Off only when explicitly "0".
DRY_RUN = os.getenv('DRY_RUN', '1') != '0'
# Broadcast MWEB peg-outs even in a dry run. A peg-out only moves coins
# between the operator's own wallets (MWEB -> an LTC change address), so a
# test bed can exercise the real peg-out, its maturity and the LTC pass that
# follows while every forward to the exchange stays a dry run.
PEGOUT_LIVE = os.getenv('PEGOUT_LIVE', '0') == '1'

# Which wallets autoforward sweeps, and which Kraken assets autoconvert sells.
# A coin left out is neither waited for at startup nor touched in the loop.
AUTOFORWARD_COINS = _csv('AUTOFORWARD_COINS', 'btc,ltc,ltc-mweb,xmr')
AUTOCONVERT_ASSETS = _csv('AUTOCONVERT_ASSETS', 'XBT,LTC,XMR')

# Seconds before an RPC or HTTP request is abandoned. Without one, a single
# hung connection stalls every coin in the loop indefinitely.
HTTP_TIMEOUT = float(os.getenv('HTTP_TIMEOUT', '60'))
# A cheap first call that decides whether a backend answers at all, so a
# hung one costs this much per pass rather than every call's full timeout.
PROBE_TIMEOUT = float(os.getenv('PROBE_TIMEOUT', '15'))
# Building and signing a sweep of many inputs is slow; give it longer.
SEND_TIMEOUT = float(os.getenv('SEND_TIMEOUT', '600'))

# Electrum only generates (and so only sees payments to) addresses up to
# this many past the last one it has seen used. A merchant that issues one
# address per invoice needs it larger than the longest run of unpaid
# invoices: Cake Pay's LTC chain once had a run of 1093, past the old 1000,
# and every later payment went unseen. Applied at every startup, so raising
# it reaches existing wallets too (Electrum then scans the new addresses).
ELECTRUM_GAP_LIMIT = int(os.getenv('ELECTRUM_GAP_LIMIT', '1000'))
# At most this many inputs per forward: a sweep of thousands of outputs would
# exceed the 100 kvB standard transaction size and never relay. The rest
# goes in later passes, largest outputs first.
ELECTRUM_MAX_INPUTS = int(os.getenv('ELECTRUM_MAX_INPUTS', '400'))
# LTC outputs are forwarded only with this many confirmations: MWEB receipts
# arrive as peg-outs, which consensus makes unspendable for 6 blocks
# (PEGOUT_MATURITY, bad-txns-premature-spend-of-pegout).
LITECOIN_MIN_CONFIRMATIONS = int(os.getenv('LITECOIN_MIN_CONFIRMATIONS', '6'))
# How often to report how many receiving addresses each wallet tracks (for
# the monitor that compares it with the merchant's address index). Listing
# them is not free on a wallet with 100k+ addresses.
ELECTRUM_ADDRESS_REPORT_INTERVAL = int(os.getenv('ELECTRUM_ADDRESS_REPORT_INTERVAL', '3600'))

# monero-wallet-rpc only writes its cache on close, so without a periodic
# `store` a restart re-syncs everything since the wallet was last closed.
MONERO_STORE_INTERVAL = int(os.getenv('MONERO_STORE_INTERVAL', '3600'))
# "major:minor". Applied once, right after a seed is restored. A merchant
# that issues one subaddress per invoice needs a minor lookahead larger than
# the longest run of unpaid invoices, or later payments are never seen.
MONERO_SUBADDRESS_LOOKAHEAD = os.getenv('MONERO_SUBADDRESS_LOOKAHEAD', '')

# Directory for <program>.json status files (for monitoring). Unset: none.
STATUS_DIR = os.getenv('STATUS_DIR', '')

BITCOIN_ELECTRUM_RPC_URL = os.getenv('BITCOIN_ELECTRUM_RPC_URL', '')
LITECOIN_ELECTRUM_RPC_URL = os.getenv('LITECOIN_ELECTRUM_RPC_URL', '')
LITECOIN_MWEB_ELECTRUM_RPC_URL = os.getenv('LITECOIN_MWEB_ELECTRUM_RPC_URL', '')
ELECTRUM_RPC_USERNAME = os.getenv('ELECTRUM_RPC_USERNAME', '')
ELECTRUM_RPC_PASSWORD = os.getenv('ELECTRUM_RPC_PASSWORD', '')
BITCOIN_ELECTRUM_SERVER_ADDRESS = os.getenv('BITCOIN_ELECTRUM_SERVER_ADDRESS', '')
LITECOIN_ELECTRUM_SERVER_ADDRESS = os.getenv('LITECOIN_ELECTRUM_SERVER_ADDRESS', '')
BITCOIN_WALLET_SEED = os.getenv('BITCOIN_WALLET_SEED', '')
LITECOIN_WALLET_SEED = os.getenv('LITECOIN_WALLET_SEED', '')
LITECOIN_MWEB_WALLET_SEED = os.getenv('LITECOIN_MWEB_WALLET_SEED', '')

MONERO_RPC_URL = os.getenv('MONERO_RPC_URL', '')
MONERO_RPC_USERNAME = os.getenv('MONERO_RPC_USERNAME', '')
MONERO_RPC_PASSWORD = os.getenv('MONERO_RPC_PASSWORD', '')
MONERO_WALLET_SEED = os.getenv('MONERO_WALLET_SEED', '')
MONERO_WALLET_PASSWORD = os.getenv('MONERO_WALLET_PASSWORD', '')
MONERO_WALLET_HEIGHT = os.getenv('MONERO_WALLET_HEIGHT', '')
MONERO_DAEMON_ADDRESS = os.getenv('MONERO_DAEMON_ADDRESS', '')

KRAKEN_API_KEY = os.getenv('KRAKEN_API_KEY', '')
KRAKEN_API_SECRET = os.getenv('KRAKEN_API_SECRET', '')

MAX_NETWORK_FEE_PERCENT = float(os.getenv('MAX_NETWORK_FEE_PERCENT', '5'))
MAX_SLIPPAGE_PERCENT = float(os.getenv('MAX_SLIPPAGE_PERCENT', '0.5'))
SETTLEMENT_CURRENCY = os.getenv('SETTLEMENT_CURRENCY', 'USD')

BITCOIN_FEE_SOURCE = os.getenv('BITCOIN_FEE_SOURCE', 'https://mempool.space/api/v1/fees/recommended')
BITCOIN_FEE_RATE = os.getenv('BITCOIN_FEE_RATE', 'halfHourFee')
LITECOIN_FEE_SOURCE = os.getenv('LITECOIN_FEE_SOURCE', 'https://litecoinspace.org/api/v1/fees/recommended')
LITECOIN_FEE_RATE = os.getenv('LITECOIN_FEE_RATE', 'halfHourFee')