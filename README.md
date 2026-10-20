# autoforward-autoconvert

Programs to auto-forward BTC, LTC, LTC-MWEB, and XMR wallets to Kraken, and then auto-convert to your preferred settlement currency (e.g. USD, USDT, BTC).

## Requirements

- Docker
- Docker Compose

## Configuration

Create a `.env` file as a copy of `.env.example` and set the values for the empty variables.

### Environment variables

| Variable name | Required | Default | Description |
| - | - | - | - |
| `BITCOIN_WALLET_SEED` | Yes | - | Your BIP39 Bitcoin mnemonic seed. Used for all Bitcoin-like assets. |
| `LITECOIN_WALLET_SEED` | Yes | - | Your BIP39 Litecoin mnemonic seed. |
| `LITECOIN_MWEB_WALLET_SEED` | Yes | - | Your Electrum-format Litecoin MWEB mnemonic seed. |
| `MONERO_WALLET_SEED` | Yes | - | Your 25 word Monero mnemonic seed. |
| `MONERO_WALLET_HEIGHT` | Yes | - | The restore height of your Monero wallet. |
| `ELECTRUM_RPC_PASSWORD` | Yes | - | A new strong password for your Electrum RPCs. |
| `MONERO_RPC_PASSWORD` | Yes | - | A new strong password for your Monero RPC. |
| `MONERO_WALLET_PASSWORD` | Yes | - | A new strong password for your Monero Wallet. |
| `KRAKEN_API_KEY` | Yes | - | Your API key from Kraken. |
| `KRAKEN_API_SECRET` | Yes | - | Your API secret from Kraken. |
| `MONERO_DAEMON_ADDRESS` | Yes | - | The address of a Monero daemon you own or trust. |
| `BITCOIN_ELECTRUM_SERVER_ADDRESS` | **No** | - | The address of a Bitcoin Electrum server you own or trust. E.g.: `localhost:50001:t` (no SSL) or `my.electrum.server:50001:s` (SSL). By leaving this blank you're letting Electrum select a random server for you, which may be a privacy concern. |
| `LITECOIN_ELECTRUM_SERVER_ADDRESS` | **No** | - | The address of a Litecoin Electrum server you own or trust. E.g.: `localhost:50001:t` (no SSL) or `my.electrum.server:50001:s` (SSL). By leaving this blank you're letting Electrum select a random server for you, which may be a privacy concern. |
| `MAX_NETWORK_FEE_PERCENT` | **No** | `5` | The maximum accepted miner fee percent when auto-forwarding. Not applied to XMR. |
| `MAX_SLIPPAGE_PERCENT` | **No** | `0.5` | The maximum accepted slippage percent when auto-converting. |
| `SETTLEMENT_CURRENCY` | **No** | `USD` | The currency you wish to convert to. If there isn't a direct trading pair, it attempts to trade through USD first, e.g. XMR->USD->DAI. |
| `BITCOIN_FEE_SOURCE` | **No** | `https://mempool.space/api/v1/fees/recommended` | The fee API source to use for Bitcoin transactions. |
| `BITCOIN_FEE_RATE` | **No** | `halfHourFee` | The fee rate to use in the Bitcoin fee source API response. |
| `LITECOIN_FEE_SOURCE` | **No** | `https://litecoinspace.org/api/v1/fees/recommended` | The fee API source to use for Litecoin transactions. |
| `LITECOIN_FEE_RATE` | **No** | `halfHourFee` | The fee rate to use in the Litecoin fee source API response. |
| `DRY_RUN` | **No** | `1` | **Defaults to on.** Everything a live pass does except moving funds: transactions are built and signed but not broadcast (Monero: `do_not_relay`), Kraken orders are sent with `validate=true`, and no new Kraken deposit address is created. Without a Kraken key, a dry run forwards to the wallet's own address. Set to `0` to forward and sell. Every status file reports `dry_run`. |
| `AUTOFORWARD_COINS` | **No** | `btc,ltc,ltc-mweb,xmr` | Comma-separated wallets to autoforward. A coin left out is not waited for at startup, not imported by the seed importer and never swept. |
| `AUTOCONVERT_ASSETS` | **No** | `XBT,LTC,XMR` | Comma-separated Kraken asset altnames that autoconvert sells (e.g. add `ZEC`). |
| `MIN_BITCOIN_SEND_AMOUNT` | **No** | `0.0001` | Minimum confirmed BTC balance before forwarding (batching threshold). |
| `MIN_LITECOIN_SEND_AMOUNT` | **No** | `0.05` | Minimum confirmed LTC balance before forwarding; applies to LTC and LTC-MWEB. |
| `MIN_MONERO_SEND_AMOUNT` | **No** | `0.03` | Minimum unlocked XMR balance before sweeping. |
| `MONERO_WALLET_FILENAME` | **No** | `mywallet` | Wallet file name inside the monero-wallet-rpc volume. |
| `MONERO_SUBADDRESS_LOOKAHEAD` | **No** | `50:20000` (compose) | `major:minor` subaddress lookahead, applied once right after the seed is restored. Must exceed the longest run of unused subaddresses the merchant can create (one per unpaid invoice), or later payments are never seen. To change it on an existing wallet, call `set_subaddress_lookahead` and then `rescan_blockchain`. |
| `MONERO_WALLET_RPC_VERSION` | **No** | `v0.18.5.1` | Tag of `ghcr.io/sethforprivacy/simple-monero-wallet-rpc` to build from. |
| `ELECTRUM_GAP_LIMIT` | **No** | `1000` | Electrum gap limit, applied at import **and every startup**. A merchant issuing one address per invoice needs it above its longest run of unpaid invoices, or later payments are never seen. |
| `ELECTRUM_MAX_INPUTS` | **No** | `400` | Maximum inputs per forward (largest outputs first); the rest go in later passes, so a backlog never builds a non-standard (>100 kvB) transaction. |
| `LITECOIN_MIN_CONFIRMATIONS` | **No** | `6` | LTC outputs are forwarded only with this many confirmations. MWEB receipts are **pegged out to an LTC change address** (never sent to the exchange directly, since Kraken fails MWEB peg-out deposits), and peg-outs are unspendable for 6 blocks (`PEGOUT_MATURITY`). `ltc-mweb` therefore requires `ltc`. |
| `ELECTRUM_ADDRESS_REPORT_INTERVAL` | **No** | `3600` | Seconds between reporting each wallet's tracked receiving-address count in the status file. |
| `HTTP_TIMEOUT` | **No** | `60` | Seconds before any RPC/HTTP request is abandoned. |
| `SEND_TIMEOUT` | **No** | `600` | Timeout for building, signing and broadcasting a sweep. |
| `MONERO_STORE_INTERVAL` | **No** | `3600` | Seconds between `store` calls, so a restart does not re-sync from the last close. The wallet is also stored after every sweep. |


## Running

After setting the required environment variable values, you can run the containers:

```bash
$ docker-compose --env-file .env up -d
```

## Monitoring

`autoforward` and `autoconvert` each rewrite `status/<program>.json` after every pass (bind-mounted at `/status`). `updated` is the heartbeat; each section (a coin, a Kraken asset, `kraken`, `xmr-receipts`) carries `last_ok`, `last_error_at`, `last_error` and `errors_total`, plus balances and the last forward or sale. The `xmr` section also reports `max_received_subaddress`: compare it with the merchant wallet's highest paid subaddress to catch payments that fell outside the lookahead.

## Changing seeds

If you wish to change any of the wallet seeds in the future, first you have to take down all Docker Compose services and delete the volumes:

```bash
$ docker-compose down -v
```

Change the seeds in the `.env` file and start all services again:

```bash
$ docker-compose --env-file .env up -d
```

## Trading Strategy

The trading strategy utilized in this program is as follows:

- Fetch the current balance to sell.
- First try to sell with one trade, e.g. XMR->USD.
- If that fails, try to sell via USD, e.g. XMR->USD->DAI.
- Sell by taking as many maarket trades as possible to not move the price down more than 0.5% from the calculated mid price.
- Wait a random amount of time before trying again between 30-90 seconds.

We strongly recommend running this program with a dedicated Kraken account to ensure that it does not interfere with any of your other activities.

This trading stategy may not be optimal for your needs. You can configure the `MAX_NETWORK_FEE_PERCENT` environment variable. For illiquid trading pairs that regularly have bid-ask spreads exceeding 1%, consider a higher value than 0.5%. You should consider a different trading strategy if you are sensitive to taker fees.

## Contributing

Pull requests welcome!
Thanks for supporting MAGIC Grants.

## License

[MIT](LICENSE)
