# Hardening guide

Here are some basic suggestions to keep in mind when running this program.

1. Issue the Kraken API key without withdrawal permission, and restrict it to this server's IP.
2. Give this box one job. No other services, no other users. `.env` mode `0600`, owned by a non-root deploy user.
3. SSH: keys only, no root login, no password authentication.
4. Default-deny inbound firewall, and never publish the wallet RPC ports. Nothing in this stack needs an inbound connection except SSH.
5. Enable automatic server updates and automatic reboots for kernel updates.

A longer guide may come later.
