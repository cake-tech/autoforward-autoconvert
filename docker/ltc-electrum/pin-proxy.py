#!/usr/bin/env python3
"""Loopback SOCKS5 proxy that pins where Electrum-LTC's network traffic goes.

Electrum-LTC starts an embedded mwebd for MWEB, and mwebd syncs over the
Litecoin P2P network (neutrino): it finds peers through DNS seeds and gossip,
and nothing in Electrum-LTC can pin it to a node. Its one network setting is
Electrum's proxy, which it shares with Electrum's own server connection. So
both are pointed here, and this proxy decides where every connection goes:

  - a P2P connection (to any peer on the chain's P2P port) is sent to one of
    MWEB_PEERS instead, whatever peer mwebd asked for. Every peer it believes
    it has is then one of our nodes. Refusing the others instead would leave
    a fresh wallet, whose address book holds no node of ours, never syncing.
  - a connection to the pinned Electrum server (ELECTRUM_SERVER_ADDRESS)
    passes through as is.
  - anything else is refused.

Run by docker-entrypoint.sh, which points Electrum (`-p`) at it. Standard
library only: it runs on the image's system python3.
"""
import argparse
import asyncio
import ipaddress
import itertools
import os
import socket
import struct
import sys

LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 1080
P2P_PORTS = {'mainnet': 9333, 'testnet': 19335}
CONNECT_TIMEOUT = 10

# SOCKS5 reply codes (RFC 1928).
SUCCEEDED = 0
GENERAL_FAILURE = 1
NOT_ALLOWED = 2
CONNECTION_REFUSED = 5
COMMAND_NOT_SUPPORTED = 7
ADDRESS_TYPE_NOT_SUPPORTED = 8


def log(message):
    print(f'pin-proxy: {message}', file=sys.stderr, flush=True)


def parse_host_port(value):
    """'host:port' (or '[v6]:port') -> (host, port)."""
    host, sep, port = value.strip().rpartition(':')
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f'expected host:port, got {value!r}')
    return host.strip('[]').lower(), int(port)


def parse_electrum_server(value):
    """Electrum's 'host:port:protocol' -> (host, port)."""
    host_port, sep, protocol = value.strip().rpartition(':')
    if not sep or protocol not in ('s', 't'):
        raise ValueError(f'expected host:port:s or host:port:t, got {value!r}')
    return parse_host_port(host_port)


def parse_peers(value):
    peers = [parse_host_port(p) for p in value.split(',') if p.strip()]
    if not peers:
        raise ValueError('MWEB_PEERS lists no peer')
    return peers


class PinProxy:
    def __init__(self, peers, p2p_port, electrum_server=None):
        self.peers = peers
        self.p2p_port = p2p_port
        self.electrum_server = electrum_server
        # Rotates the first peer tried, so mwebd's connections spread across
        # the nodes rather than all landing on the first.
        self._next_peer = itertools.count()

    def targets(self, host, port):
        """Where a request for host:port may go, in the order to try."""
        if (host, port) == self.electrum_server:
            return [(host, port)]
        if port == self.p2p_port:
            start = next(self._next_peer) % len(self.peers)
            return self.peers[start:] + self.peers[:start]
        return []

    async def handle(self, reader, writer):
        try:
            await self._handle(reader, writer)
        except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()

    async def _handle(self, reader, writer):
        # Greeting: VER NMETHODS METHODS. Only "no authentication" is offered.
        version, nmethods = await reader.readexactly(2)
        if version != 5:
            return
        methods = await reader.readexactly(nmethods)
        if 0 not in methods:
            writer.write(b'\x05\xff')
            await writer.drain()
            return
        writer.write(b'\x05\x00')

        # Request: VER CMD RSV ATYP DST.ADDR DST.PORT
        _, command, _, address_type = await reader.readexactly(4)
        if address_type == 1:
            host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
        elif address_type == 3:
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode('idna').lower()
        elif address_type == 4:
            host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
        else:
            await self._reply(writer, ADDRESS_TYPE_NOT_SUPPORTED)
            return
        port, = struct.unpack('!H', await reader.readexactly(2))
        if command != 1:  # CONNECT only
            await self._reply(writer, COMMAND_NOT_SUPPORTED)
            return

        targets = self.targets(host, port)
        if not targets:
            log(f'refused {host}:{port}')
            await self._reply(writer, NOT_ALLOWED)
            return

        for target_host, target_port in targets:
            try:
                upstream_reader, upstream_writer = await asyncio.wait_for(
                    asyncio.open_connection(target_host, target_port), CONNECT_TIMEOUT)
                break
            except (OSError, asyncio.TimeoutError) as e:
                log(f'{target_host}:{target_port} unreachable: {e!r}')
        else:
            await self._reply(writer, CONNECTION_REFUSED)
            return

        if (target_host, target_port) != (host, port):
            log(f'{host}:{port} -> {target_host}:{target_port}')
        await self._reply(writer, SUCCEEDED)
        try:
            await asyncio.gather(
                self._pipe(reader, upstream_writer),
                self._pipe(upstream_reader, writer))
        finally:
            upstream_writer.close()

    @staticmethod
    async def _reply(writer, code):
        # BND.ADDR/BND.PORT: 0.0.0.0:0, which clients ignore.
        writer.write(bytes([5, code, 0, 1]) + bytes(6))
        await writer.drain()

    @staticmethod
    async def _pipe(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except OSError:
            pass
        finally:
            # Half-close, so the other direction can finish.
            try:
                writer.write_eof()
            except OSError:
                pass


def config_from_env(env):
    """(peers, p2p_port, electrum_server) from the container's environment."""
    chain = 'testnet' if env.get('TESTNET') == '1' else 'mainnet'
    peers = parse_peers(env.get('MWEB_PEERS', ''))
    server = env.get('ELECTRUM_SERVER_ADDRESS', '')
    return peers, P2P_PORTS[chain], parse_electrum_server(server) if server else None


async def serve(proxy, host=LISTEN_HOST, port=LISTEN_PORT):
    server = await asyncio.start_server(proxy.handle, host, port)
    log(f'listening on {host}:{port}; P2P port {proxy.p2p_port} -> '
        + ', '.join(f'{h}:{p}' for h, p in proxy.peers)
        + (f'; Electrum server {proxy.electrum_server[0]}:{proxy.electrum_server[1]}'
           if proxy.electrum_server else ''))
    async with server:
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true',
                        help='validate the environment and exit')
    args = parser.parse_args()
    try:
        peers, p2p_port, electrum_server = config_from_env(os.environ)
        for host, _ in peers:
            ipaddress.ip_address(host)  # a name here would be resolved by DNS we do not control
    except ValueError as e:
        log(f'bad configuration: {e}')
        sys.exit(2)
    if args.check:
        return
    asyncio.run(serve(PinProxy(peers, p2p_port, electrum_server)))


if __name__ == '__main__':
    main()
