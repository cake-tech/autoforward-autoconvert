from typing import Callable, Literal
from bip_utils import Bip39SeedGenerator, Bip84, Bip84Coins
import traceback
import util
import env
from constants import MONERO_WALLET_FILENAME

def get_xprv_from_mnemonic(coin: Literal['btc', 'ltc',], mnemonic: str, passphrase: str = '') -> str:
   if env.TESTNET == '1':
      coin_type = Bip84Coins.BITCOIN_TESTNET if coin == 'btc' else Bip84Coins.LITECOIN_TESTNET
   else:
      coin_type = Bip84Coins.BITCOIN if coin == 'btc' else Bip84Coins.LITECOIN

   seed_bytes = Bip39SeedGenerator(mnemonic).Generate(passphrase)
   bip84_master_key = Bip84.FromSeed(seed_bytes, coin_type)
   zprv = bip84_master_key.Purpose().Coin().Account(0).PrivateKey().ToExtended()
   return zprv

def restore_electrum_wallet(coin: Literal['btc', 'ltc', 'ltc-mweb'], key: str):
   util.request_electrum_rpc(coin, 'restore', [key])
   util.request_electrum_rpc(coin, 'load_wallet')
   util.request_electrum_rpc(coin, 'changegaplimit', [1000, 'iknowhatimdoing'])

def import_bitcoin_seed():
   # Only support electrum format for testnet
   if env.TESTNET == '1':
      if env.BITCOIN_WALLET_PASSPHRASE:
         print('WARNING: BITCOIN_WALLET_PASSPHRASE is ignored on testnet, where the seed is imported as-is.')

      key = env.BITCOIN_WALLET_SEED
   else:
      key = get_xprv_from_mnemonic('btc', env.BITCOIN_WALLET_SEED, env.BITCOIN_WALLET_PASSPHRASE)

   restore_electrum_wallet('btc', key)

def import_litecoin_seed():
   # Only support electrum format for testnet
   if env.TESTNET == '1':
      key = env.LITECOIN_WALLET_SEED
   else:
      key = get_xprv_from_mnemonic('ltc', env.LITECOIN_WALLET_SEED)

   restore_electrum_wallet('ltc', key)

def import_litecoin_mweb_seed():
   # MWEB is an electrum-format seed on every network, so it's never derived
   restore_electrum_wallet('ltc-mweb', env.LITECOIN_MWEB_WALLET_SEED)

def import_monero_seed():
   params = {
      'filename': MONERO_WALLET_FILENAME,
      'seed': env.MONERO_WALLET_SEED,
      'password': env.MONERO_WALLET_PASSWORD,
      'restore_height': env.MONERO_WALLET_HEIGHT,
      'language': 'english',
      'autosave_current': True
   }

   util.request_monero_rpc('restore_deterministic_wallet', params)

def try_import(label: str, do_import: Callable[[], None]):
   try:
      do_import()
      print(f'{label} seed has successfully been imported!')
   except Exception as e:
      if 'Remove the existing wallet first!' in e.__str__():
         print(f'{label} wallet already exists. Skipping...')
      else:
         print(util.get_time(), f'Error importing {label} seed:')
         print(traceback.format_exc())

ASSET_SEEDS = (
   ('btc', 'BITCOIN_WALLET_SEED', env.BITCOIN_ENABLED, env.BITCOIN_WALLET_SEED),
   ('ltc', 'LITECOIN_WALLET_SEED', env.LITECOIN_ENABLED, env.LITECOIN_WALLET_SEED),
   ('ltc-mweb', 'LITECOIN_MWEB_WALLET_SEED', env.LITECOIN_MWEB_ENABLED, env.LITECOIN_MWEB_WALLET_SEED),
   ('xmr', 'MONERO_WALLET_SEED', env.MONERO_ENABLED, env.MONERO_WALLET_SEED),
)

missing_seeds = [var for _, var, enabled, seed in ASSET_SEEDS if enabled and not seed]
if missing_seeds:
   raise SystemExit(f'Enabled in COMPOSE_PROFILES but no seed given: {", ".join(missing_seeds)}. Set the seed, or drop the asset from COMPOSE_PROFILES.')

ignored_seeds = [f'{var} ({asset})' for asset, var, enabled, seed in ASSET_SEEDS if seed and not enabled]
if ignored_seeds:
   print(f'WARNING: seed set for an asset missing from COMPOSE_PROFILES, so it will not be imported or forwarded: {", ".join(ignored_seeds)}')

print(f'Importing seeds for: {", ".join(env.ENABLED_ASSETS)}')

util.wait_for_rpc()

coin_to_import = {
   'btc': ('Bitcoin', import_bitcoin_seed),
   'ltc': ('Litecoin', import_litecoin_seed),
   'ltc-mweb': ('Litecoin mimblewimble', import_litecoin_mweb_seed)
}

for coin in env.ENABLED_ELECTRUM_COINS:
   label, do_import = coin_to_import[coin]
   try_import(label, do_import)

if env.MONERO_ENABLED:
   try_import('Monero', import_monero_seed)
