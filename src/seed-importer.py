from typing import Literal
from bip_utils import Bip39SeedGenerator, Bip84, Bip84Coins
import traceback
import util
import env
from constants import MONERO_WALLET_FILENAME

def get_xprv_from_mnemonic(coin: Literal['btc', 'ltc',], mnemonic: str ) -> str:
   if env.TESTNET == '1':
      coin_type = Bip84Coins.BITCOIN_TESTNET if coin == 'btc' else Bip84Coins.LITECOIN_TESTNET
   else:
      coin_type = Bip84Coins.BITCOIN if coin == 'btc' else Bip84Coins.LITECOIN

   seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
   bip84_master_key = Bip84.FromSeed(seed_bytes, coin_type)
   zprv = bip84_master_key.Purpose().Coin().Account(0).PrivateKey().ToExtended()
   return zprv

def import_bitcoin_seed():
   # Only support electrum format for testnet
   if env.TESTNET == '1':
      key = env.BITCOIN_WALLET_SEED
   else:
      key = get_xprv_from_mnemonic('btc', env.BITCOIN_WALLET_SEED)

   util.request_electrum_rpc('btc', 'restore', [key])

def import_litecoin_seed():
   # Only support electrum format for testnet
   if env.TESTNET == '1':
      key = env.LITECOIN_WALLET_SEED
   else:
      key = get_xprv_from_mnemonic('ltc', env.LITECOIN_WALLET_SEED)

   util.request_electrum_rpc('ltc', 'restore', [key])

def import_litecoin_mweb_seed():
   util.request_electrum_rpc('ltc-mweb', 'restore', [env.LITECOIN_MWEB_WALLET_SEED])

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

   # Persisted in the keys file by the RPC, so this is needed only once.
   if env.MONERO_SUBADDRESS_LOOKAHEAD:
      major, minor = (int(n) for n in env.MONERO_SUBADDRESS_LOOKAHEAD.split(':'))
      util.request_monero_rpc('set_subaddress_lookahead', {
         'major_idx': major,
         'minor_idx': minor,
         'password': env.MONERO_WALLET_PASSWORD
      }, timeout=env.SEND_TIMEOUT)
      print(f'Monero subaddress lookahead set to {major}:{minor}')

util.wait_for_rpc()

if 'btc' in env.AUTOFORWARD_COINS:
  try:
     import_bitcoin_seed()
     util.request_electrum_rpc('btc', 'load_wallet')
     util.request_electrum_rpc('btc', 'changegaplimit', [env.ELECTRUM_GAP_LIMIT, True])
     print('Bitcoin seed has successfully been imported!')
  except Exception as e:
     if 'Remove the existing wallet first!' in e.__str__():
        print('Bitcoin wallet already exists. Skipping...')
     else:
        print(util.get_time(), 'Error importing bitcoin seed:')
        print(traceback.format_exc())


if 'ltc' in env.AUTOFORWARD_COINS:
  try:
     import_litecoin_seed()
     util.request_electrum_rpc('ltc', 'load_wallet')
     util.request_electrum_rpc('ltc', 'changegaplimit', [env.ELECTRUM_GAP_LIMIT, True])
     print('Litecoin seed has successfully been imported!')
  except Exception as e:
     if 'Remove the existing wallet first!' in e.__str__():
        print('Litecoin wallet already exists. Skipping...')
     else:
        print(util.get_time(), 'Error importing litecoin seed:')
        print(traceback.format_exc())

if 'ltc-mweb' in env.AUTOFORWARD_COINS:
  try:
     import_litecoin_mweb_seed()
     util.request_electrum_rpc('ltc-mweb', 'load_wallet')
     util.request_electrum_rpc('ltc-mweb', 'changegaplimit', [env.ELECTRUM_GAP_LIMIT, True])
     print('Litecoin mimblewimble seed has successfully been imported!')
  except Exception as e:
     if 'Remove the existing wallet first!' in e.__str__():
        print('Litecoin mimblewimble wallet already exists. Skipping...')
     else:
        print(util.get_time(), 'Error importing litecoin mimblewimble seed:')
        print(traceback.format_exc())

if 'xmr' in env.AUTOFORWARD_COINS:
  try:
     import_monero_seed()
     print('Monero seed has successfully been imported!')
  except Exception as e:
     if 'Remove the existing wallet first!' in e.__str__():
        print('Monero wallet already exists. Skipping...')
     else:
        print(util.get_time(), 'Error importing monero seed:')
        print(traceback.format_exc())
