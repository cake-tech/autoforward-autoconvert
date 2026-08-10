ARG VERSION
ARG DIGEST

FROM ghcr.io/sethforprivacy/simple-monero-wallet-rpc:${VERSION}@${DIGEST}

COPY docker-entrypoint.sh /usr/local/bin/

ENTRYPOINT ["docker-entrypoint.sh"]
