#!/bin/sh
set -e

# trap 'pkill -TERM -P1; electrum stop; exit 0' SIGTERM

rm -f .electrum/daemon .electrum/testnet/daemon

ADDITIONAL_SETCONFIG_FLAGS=""
ADDITIONAL_DAEMON_FLAGS=""

if [ "$TESTNET" = "1" ]; then
    ADDITIONAL_SETCONFIG_FLAGS="--testnet"
    ADDITIONAL_DAEMON_FLAGS="--testnet"
fi

if [ -n "$ELECTRUM_SERVER_ADDRESS" ]; then
    ADDITIONAL_DAEMON_FLAGS="$ADDITIONAL_DAEMON_FLAGS -1 -s $ELECTRUM_SERVER_ADDRESS"
elif [ "$TESTNET" != "1" ]; then
    # Without a server Electrum picks random public ones, and a malicious
    # server can lie about history and broadcasts. Never on mainnet.
    echo "ELECTRUM_SERVER_ADDRESS is empty: set it to a server you own or trust." >&2
    exit 1
fi

echo $ADDITIONAL_SETCONFIG_FLAGS

electrum $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcuser $ELECTRUM_RPC_USER
electrum $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcpassword $ELECTRUM_RPC_PASSWORD
electrum $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpchost 0.0.0.0
electrum $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcport 7000
electrum daemon $ADDITIONAL_DAEMON_FLAGS "$@"

