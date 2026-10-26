#!/bin/sh
set -e

# trap 'pkill -TERM -P1; electrum-ltc.appimage stop; exit 0' SIGTERM

rm -f .electrum-ltc/daemon .electrum-ltc/testnet/daemon

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

# MWEB syncs over Litecoin P2P (Electrum-LTC's embedded mwebd), from whatever
# peers it finds; Electrum's proxy is the one setting it obeys. pin-proxy.py
# sends all of its P2P connections to MWEB_PEERS and lets Electrum reach only
# its server. Restarted if it dies: without it Electrum and mwebd reach nothing.
if [ -n "$MWEB_PEERS" ]; then
    python3 ./pin-proxy.py --check
    (while :; do python3 ./pin-proxy.py; echo "pin-proxy.py exited ($?), restarting" >&2; sleep 1; done) &
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        python3 -c "import socket; socket.create_connection(('127.0.0.1', 1080), 1)" 2>/dev/null && break
        sleep 1
    done
    ADDITIONAL_DAEMON_FLAGS="$ADDITIONAL_DAEMON_FLAGS -p socks5:127.0.0.1:1080"
elif [ "$TESTNET" != "1" ]; then
    echo "MWEB_PEERS is empty: set it to Litecoin nodes you own or trust (ip:port,...)." >&2
    exit 1
fi

./squashfs-root/AppRun $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcuser $ELECTRUM_RPC_USER
./squashfs-root/AppRun $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcpassword $ELECTRUM_RPC_PASSWORD
./squashfs-root/AppRun $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpchost 0.0.0.0
./squashfs-root/AppRun $ADDITIONAL_SETCONFIG_FLAGS --offline setconfig rpcport 7000
./squashfs-root/AppRun daemon $ADDITIONAL_DAEMON_FLAGS "$@"

