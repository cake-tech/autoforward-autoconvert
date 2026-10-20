#!/bin/sh
set -e

# The base image's own /entrypoint.sh (simple-monero-wallet-rpc v0.18.5.x)
# adds --non-interactive and the RPC bind flags (0.0.0.0 plus
# --confirm-external-bind only when --rpc-login is set), fixes the volume's
# ownership and drops root via su-exec. It replaced the fixuid wrapper this
# file used to call, which no longer exists in the image. All that is left to
# add here is the network flag.
if [ "$TESTNET" = "1" ]; then
  set -- --testnet "$@"
fi

exec /entrypoint.sh "$@"
