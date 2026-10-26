"""pin-proxy.py must send mwebd's P2P connections only to MWEB_PEERS.

Runs the proxy on loopback against fake upstream servers, each of which
answers with its own name, and speaks SOCKS5 to it the way mwebd (Go's
x/net/proxy) and Electrum (aiorpcx) do.
"""
import asyncio
import importlib.util
import os
import socket
import struct
import unittest

_spec = importlib.util.spec_from_file_location(
    'pin_proxy', os.path.join(os.path.dirname(__file__), '..', 'docker', 'ltc-electrum', 'pin-proxy.py'))
pin_proxy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pin_proxy)
pin_proxy.log = lambda message: None

P2P_PORT = 9333


async def start_named_server(name):
    """Sends its name, then holds the connection until the client closes it."""
    async def handle(reader, writer):
        writer.write(name.encode())
        await writer.drain()
        await reader.read()
        writer.close()
    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    return server, server.sockets[0].getsockname()[1]


def unused_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class PinProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []
        self.peer_a = await self.named('peer-a')
        self.peer_b = await self.named('peer-b')
        self.electrum = await self.named('electrum')

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()

    async def named(self, name):
        server, port = await start_named_server(name)
        self.servers.append(server)
        return port

    async def start_proxy(self, peers):
        proxy = pin_proxy.PinProxy(
            [('127.0.0.1', p) for p in peers], P2P_PORT, ('localhost', self.electrum))
        server = await asyncio.start_server(proxy.handle, '127.0.0.1', 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def open(self, proxy_port, request):
        """SOCKS5 CONNECT, left open; returns (reader, writer)."""
        reader, writer = await asyncio.open_connection('127.0.0.1', proxy_port)
        writer.write(b'\x05\x01\x00')
        self.assertEqual(await reader.readexactly(2), b'\x05\x00')
        writer.write(request)
        return reader, writer

    @staticmethod
    async def answer(reader):
        """(reply code, the far end's name) once the proxy answers."""
        reply = await reader.readexactly(10)
        if reply[1] != pin_proxy.SUCCEEDED:
            return reply[1], await reader.read()
        return reply[1], await reader.read(64)

    async def connect(self, proxy_port, request):
        """SOCKS5 CONNECT, then close; returns (reply code, the far end's name)."""
        reader, writer = await self.open(proxy_port, request)
        try:
            return await self.answer(reader)
        finally:
            writer.close()

    @staticmethod
    def ipv4(host, port):
        return b'\x05\x01\x00\x01' + socket.inet_aton(host) + struct.pack('!H', port)

    @staticmethod
    def domain(host, port):
        return b'\x05\x01\x00\x03' + bytes([len(host)]) + host.encode() + struct.pack('!H', port)

    @staticmethod
    def ipv6(host, port):
        return b'\x05\x01\x00\x04' + socket.inet_pton(socket.AF_INET6, host) + struct.pack('!H', port)

    async def test_any_p2p_peer_lands_on_ours(self):
        proxy = await self.start_proxy([self.peer_a, self.peer_b])
        for request in (self.ipv4('203.0.113.9', P2P_PORT),
                        self.ipv6('2001:db8::1', P2P_PORT),
                        self.domain('seed.example.org', P2P_PORT)):
            code, body = await self.connect(proxy, request)
            self.assertEqual(code, pin_proxy.SUCCEEDED)
            self.assertIn(body, (b'peer-a', b'peer-b'))

    async def test_one_p2p_connection_per_peer_and_the_rest_wait(self):
        proxy = await self.start_proxy([self.peer_a, self.peer_b])
        request = self.ipv4('203.0.113.9', P2P_PORT)
        first = await self.open(proxy, request)
        second = await self.open(proxy, request)
        first_name = (await self.answer(first[0]))[1]
        second_name = (await self.answer(second[0]))[1]
        self.assertEqual({first_name, second_name}, {b'peer-a', b'peer-b'})

        # A third is held, unanswered, while both peers are in use...
        third = await self.open(proxy, request)
        reply = asyncio.ensure_future(third[0].readexactly(10))
        done, _ = await asyncio.wait({reply}, timeout=0.2)
        self.assertFalse(done)
        # ...and goes to the peer that is freed.
        first[1].close()
        await first[1].wait_closed()
        self.assertEqual((await asyncio.wait_for(reply, 2))[1], pin_proxy.SUCCEEDED)
        self.assertEqual(await third[0].read(64), first_name)
        for _, writer in (second, third):
            writer.close()

    async def test_a_down_peer_falls_back_to_the_next(self):
        proxy = await self.start_proxy([unused_port(), self.peer_b])
        code, body = await self.connect(proxy, self.ipv4('203.0.113.9', P2P_PORT))
        self.assertEqual((code, body), (pin_proxy.SUCCEEDED, b'peer-b'))

    async def test_all_peers_down_is_refused(self):
        proxy = await self.start_proxy([unused_port()])
        code, body = await self.connect(proxy, self.ipv4('203.0.113.9', P2P_PORT))
        self.assertEqual((code, body), (pin_proxy.CONNECTION_REFUSED, b''))

    async def test_electrum_server_passes_through(self):
        proxy = await self.start_proxy([self.peer_a])
        code, body = await self.connect(proxy, self.domain('LOCALHOST', self.electrum))
        self.assertEqual((code, body), (pin_proxy.SUCCEEDED, b'electrum'))

    async def test_everything_else_is_refused(self):
        proxy = await self.start_proxy([self.peer_a])
        for request in (self.domain('localhost', self.peer_a),       # a peer, off the P2P port
                        self.ipv4('127.0.0.1', self.electrum),       # the server's port, other host
                        self.domain('api.example.org', 443)):
            code, body = await self.connect(proxy, request)
            self.assertEqual((code, body), (pin_proxy.NOT_ALLOWED, b''))

    async def test_electrum_tor_probe_is_not_answered_as_tor(self):
        # util.is_tor_socks_port: greeting plus a Tor RESOLVE request in one write.
        proxy = await self.start_proxy([self.peer_a])
        reader, writer = await asyncio.open_connection('127.0.0.1', proxy)
        writer.write(b'\x05\x01\x00\x05\xf0\x00\x03\x070.0.0.0\x00\x00')
        data = await reader.read(1024)
        writer.close()
        self.assertNotEqual(data, b'\x05\x00\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        self.assertEqual(data[:2], b'\x05\x00')
        self.assertEqual(data[3], pin_proxy.COMMAND_NOT_SUPPORTED)


class ConfigTest(unittest.TestCase):
    def test_mainnet(self):
        peers, port, server = pin_proxy.config_from_env({
            'MWEB_PEERS': '203.0.113.5:9333, 198.51.100.7:9333',
            'ELECTRUM_SERVER_ADDRESS': 'LTC-Electrum.example.com:50002:s',
        })
        self.assertEqual(peers, [('203.0.113.5', 9333), ('198.51.100.7', 9333)])
        self.assertEqual(port, 9333)
        self.assertEqual(server, ('ltc-electrum.example.com', 50002))

    def test_testnet_port(self):
        _, port, server = pin_proxy.config_from_env({'TESTNET': '1', 'MWEB_PEERS': '[2001:db8::1]:19335'})
        self.assertEqual((port, server), (19335, None))

    def test_bad_values(self):
        for env in ({'MWEB_PEERS': ''},
                    {'MWEB_PEERS': ' , '},
                    {'MWEB_PEERS': '203.0.113.5'},
                    {'MWEB_PEERS': '203.0.113.5:99999'},
                    {'MWEB_PEERS': '203.0.113.5:9333', 'ELECTRUM_SERVER_ADDRESS': 'host:50002'}):
            with self.assertRaises(ValueError, msg=env):
                pin_proxy.config_from_env(env)


if __name__ == '__main__':
    unittest.main()
