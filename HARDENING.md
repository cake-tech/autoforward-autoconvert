# Hardening guide

Here are some basic suggestions to keep in mind when running this program.

1. Issue the Kraken API key without withdrawal permission, and restrict it to this server's IP.
2. If you use BTCPay labeling, give that API key only `btcpay.store.canmanagewallettransactions`, scoped to the one store.
3. Give this box one job. No other services, no other users. `.env` mode `0600`, owned by a non-root deploy user.
4. SSH: keys only, no root login, no password authentication.
5. Default-deny inbound firewall, and never publish the wallet RPC ports. Nothing in this stack needs an inbound connection except SSH.
6. Enable automatic server updates and automatic reboots for kernel updates.

A longer guide may come later.
