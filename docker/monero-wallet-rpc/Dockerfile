# Pinned: `latest` silently changes the wallet software under a hot wallet.
ARG VERSION=v0.18.5.4
FROM ghcr.io/sethforprivacy/simple-monero-wallet-rpc:${VERSION}

COPY docker-entrypoint.sh /usr/local/bin/

ENTRYPOINT ["docker-entrypoint.sh"]
