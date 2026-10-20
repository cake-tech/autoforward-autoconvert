import os

# Mainnet minimums are batching thresholds, so they are deployment config:
# each can be overridden from the environment without patching this file.
MIN_BITCOIN_SEND_AMOUNT_MAINNET = float(os.getenv('MIN_BITCOIN_SEND_AMOUNT', '0.0001'))
MIN_LITECOIN_SEND_AMOUNT_MAINNET = float(os.getenv('MIN_LITECOIN_SEND_AMOUNT', '0.05'))
MIN_MONERO_SEND_AMOUNT_MAINNET = float(os.getenv('MIN_MONERO_SEND_AMOUNT', '0.03'))

MIN_BITCOIN_SEND_AMOUNT_TESTNET = 0.00001
MIN_LITECOIN_SEND_AMOUNT_TESTNET = 0.00001
MIN_MONERO_SEND_AMOUNT_TESTNET = 0.00001

MONERO_WALLET_FILENAME = os.getenv('MONERO_WALLET_FILENAME', 'mywallet')
