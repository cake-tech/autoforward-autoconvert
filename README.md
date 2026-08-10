# autoforward-autoconvert

Programs to auto-forward BTC, LTC, LTC-MWEB, and XMR wallets to Kraken, and then auto-convert to your preferred settlement currency (e.g. USD, USDT, BTC).

> [!IMPORTANT]
> This program keeps four wallet seeds and a Kraken API key in plaintext on the server that runs it. If you are setting it up on a new machine, follow the **[hardening guide](HARDENING.md)** — it covers the server setup, the Kraken key permissions, and the seed handling that this design assumes.

## Requirements

- Docker
- Docker Compose

## Configuration

Create a `.env` file as a copy of `.env.example` and set the values for the empty variables.

### Environment variables

Every asset is optional. See [Choosing which assets to run](#choosing-which-assets-to-run) — a variable marked "Yes" below is only required for the assets you enable.

| Variable name | Required | Default | Description |
| - | - | - | - |
| `COMPOSE_PROFILES` | Yes | - | Comma-separated list of the assets to run: any of `btc`, `ltc`, `ltc-mweb`, `xmr`. |
| `BITCOIN_WALLET_SEED` | `btc` | - | Your BIP39 Bitcoin mnemonic seed. |
| `LITECOIN_WALLET_SEED` | `ltc` | - | Your BIP39 Litecoin mnemonic seed. |
| `LITECOIN_MWEB_WALLET_SEED` | `ltc-mweb` | - | Your Electrum-format Litecoin MWEB mnemonic seed. |
| `MONERO_WALLET_SEED` | `xmr` | - | Your 25 word Monero mnemonic seed. |
| `MONERO_WALLET_HEIGHT` | `xmr` | - | The restore height of your Monero wallet. |
| `ELECTRUM_RPC_PASSWORD` | Yes | - | A new strong password for your Electrum RPCs. |
| `MONERO_RPC_PASSWORD` | `xmr` | - | A new strong password for your Monero RPC. |
| `MONERO_WALLET_PASSWORD` | `xmr` | - | A new strong password for your Monero Wallet. |
| `KRAKEN_API_KEY` | Yes | - | Your API key from Kraken. Shared by autoforward and autoconvert. |
| `KRAKEN_API_SECRET` | Yes | - | Your API secret from Kraken. |
| `MONERO_DAEMON_ADDRESS` | `xmr` | - | The address of a Monero daemon you own or trust. |
| `BITCOIN_ELECTRUM_SERVER_ADDRESS` | **No** | - | The address of a Bitcoin Electrum server you own or trust. E.g.: `localhost:50001:t` (no SSL) or `my.electrum.server:50001:s` (SSL). By leaving this blank you're letting Electrum select a random server for you, which may be a privacy concern. |
| `LITECOIN_ELECTRUM_SERVER_ADDRESS` | **No** | - | The address of a Litecoin Electrum server you own or trust. E.g.: `localhost:50001:t` (no SSL) or `my.electrum.server:50001:s` (SSL). By leaving this blank you're letting Electrum select a random server for you, which may be a privacy concern. |
| `MAX_NETWORK_FEE_PERCENT` | **No** | `5` | The maximum accepted miner fee percent when auto-forwarding. Not applied to XMR. |
| `MAX_SLIPPAGE_PERCENT` | **No** | `0.5` | The maximum accepted slippage percent when auto-converting. |
| `SETTLEMENT_CURRENCY` | **No** | `USD` | The currency you wish to convert to. If there isn't a direct trading pair, it attempts to trade through USD first, e.g. XMR->USD->DAI. |
| `BITCOIN_FEE_SOURCE` | **No** | `https://mempool.space/api/v1/fees/recommended` | The fee API source to use for Bitcoin transactions. |
| `BITCOIN_FEE_RATE` | **No** | `halfHourFee` | The fee rate to use in the Bitcoin fee source API response. |
| `LITECOIN_FEE_SOURCE` | **No** | `https://litecoinspace.org/api/v1/fees/recommended` | The fee API source to use for Litecoin transactions. |
| `LITECOIN_FEE_RATE` | **No** | `halfHourFee` | The fee rate to use in the Litecoin fee source API response. |
| `BTCPAY_URL` | **No** | - | Base URL of your BTCPay Server, e.g. `https://btcpay.example.com`. Set all three `BTCPAY_*` variables to enable transaction labeling. |
| `BTCPAY_STORE_ID` | **No** | - | The ID of the BTCPay store whose wallet these forwards are **sent from**. |
| `BTCPAY_API_KEY` | **No** | - | A Greenfield API key with the `btcpay.store.canmanagewallettransactions` permission. |


### Labeling forwarded transactions in BTCPay

This is supported for Bitcoin and Litecoin (not MWEB) only.

After performing an autoforward transaction and if configured, it will attempt to ***replace*** any metadata for the outgoing transaction with two labels: `autoforward` and `kraken`. Configurable with `BTCPAY_LABEL` and `BTCPAY_DESTINATION_LABEL`.

To set it up, create an API key under Account -> API Keys with the **"Manage wallet transactions"** permission (`btcpay.store.canmanagewallettransactions`) for that store. This permission covers labeling only. Spending through the Greenfield API is gated separately on `btcpay.store.cancreatetransactions` and `btcpay.store.cansigntransactions`. Requires BTCPay Server 2.4.0 or newer.

### Choosing which assets to run

`COMPOSE_PROFILES` decides which assets this deployment handles. List only the ones you want:

```bash
COMPOSE_PROFILES="btc,xmr"        # Bitcoin and Monero only
COMPOSE_PROFILES="xmr"            # Monero only
COMPOSE_PROFILES="btc,ltc,ltc-mweb,xmr"   # everything
```

You must include at least one asset. Only software for the assets you need will be downloaded; the others will be skipped.

## Running

After setting the required environment variable values, you can run the containers:

```bash
$ docker-compose --env-file .env up -d
```

Confirm the right assets are live — each program prints what it is managing on startup:

```bash
$ docker compose logs autoforward | head -1     # e.g. Autoforwarding: btc, xmr
$ docker compose logs autoconvert | head -1     # e.g. Autoconverting: XBT, XMR
```

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

This trading stategy may not be optimal for your needs. You can configure the `MAX_SLIPPAGE_PERCENT` environment variable. For illiquid trading pairs that regularly have bid-ask spreads exceeding 1%, consider a higher value than 0.5%. You should consider a different trading strategy if you are sensitive to taker fees.

## Known limitations

### Both programs share one Kraken API key

The same Kraken API key is used for both autoforward (to get fresh deposit addresses) and autoconvert (to trade). It's theoretically possible for a nonce to be rejected, but the worst case scenario is that the single operation will fail and it will work on the next scheduled attempt in a few minutes.

## Contributing

Pull requests welcome!
Thanks for supporting MAGIC Grants.

## License

[MIT](LICENSE)
