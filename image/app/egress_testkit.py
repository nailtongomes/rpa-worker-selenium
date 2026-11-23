#!/usr/bin/env python3
"""
egress_testkit — relay de referência (SOCKS5 / proxy HTTP) para testar a saída do container.

Dois usos:

1. **Relay de referência, com internet de verdade.** Roda em qualquer máquina com
   Python 3.11+ (só biblioteca padrão), por exemplo um computador na rede do cliente,
   para validar o container antes do seu relay definitivo ficar pronto:

       python3 egress_testkit.py relay --protocol socks5 --listen 0.0.0.0:1080 \\
           --user rpa --password 'troque-esta-senha'

   No container: EGRESS_PROXY_URL=socks5://rpa:troque-esta-senha@<ip-da-maquina>:1080

2. **"Internet falsa" para os testes automáticos** (``--fake-ip``): o relay não sai
   para a internet. Responde ele mesmo a qualquer host (HTTP e HTTPS autoassinado) com
   uma página que mostra o host pedido e o IP "residencial" falso, e registra cada destino.
   Assim os testes provam, sem internet, que todo o tráfego passa pelo relay e que o
   DNS não é resolvido no container (hosts ``.invalid`` só funcionam pelo relay).

Use o modo 1 só para testes: ele não tem limites de taxa nem lista de destinos.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import ipaddress
import json
import ssl
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

OK_TITLE = "EGRESS-OK"


class _Reject(Exception):
    pass


class TestRelay:
    """Relay SOCKS5 ou HTTP com autenticação opcional. Roda numa thread própria."""

    def __init__(self, protocol: str = "socks5", username: str = "", password: str = "",
                 fake_ip: Optional[str] = None, host: str = "127.0.0.1", port: int = 0,
                 record_file: Optional[str] = None):
        assert protocol in ("socks5", "http")
        self.protocol, self.username, self.password = protocol, username, password
        self.record_file = record_file
        self.fake_ip, self.host, self.port = fake_ip, host, port
        self.records: list = []        # {"host", "port", "via"}
        self.auth_failures = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server = None
        self._thread: Optional[threading.Thread] = None
        self._tls: Optional[ssl.SSLContext] = None
        self._tmp = tempfile.TemporaryDirectory()

    # --- ciclo de vida ---
    def start(self) -> "TestRelay":
        ready = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._server = self._loop.run_until_complete(
                asyncio.start_server(self._handle, self.host, self.port, limit=65536))
            self.port = self._server.sockets[0].getsockname()[1]
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(10)
        return self

    def stop(self) -> None:
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._tmp.cleanup()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def url(self) -> str:
        auth = f"{self.username}:{self.password}@" if self.username or self.password else ""
        return f"{self.protocol}://{auth}127.0.0.1:{self.port}"

    def hosts(self) -> list:
        return [r["host"] for r in self.records]

    # --- protocolo ---
    async def _handle(self, reader, writer):
        try:
            if self.protocol == "socks5":
                host, port = await self._socks5(reader, writer)
                head = None
            else:
                host, port, head = await self._http(reader, writer)
            record = {"host": host, "port": port, "via": self.protocol}
            self.records.append(record)
            if self.record_file:
                with open(self.record_file, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
            if self.fake_ip:
                await self._fake_site(reader, writer, host, port, head)
            else:
                await self._forward(reader, writer, host, port, head)
        except (_Reject, asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    def _auth_failed(self) -> None:
        self.auth_failures += 1
        if self.record_file:
            with open(self.record_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"auth_failure": True, "via": self.protocol}) + "\n")

    async def _socks5(self, reader, writer):
        ver, n = await reader.readexactly(2)
        methods = await reader.readexactly(n)
        need_auth = bool(self.username or self.password)
        method = 0x02 if need_auth else 0x00
        if ver != 5 or method not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            raise _Reject()
        writer.write(bytes([5, method]))
        await writer.drain()
        if need_auth:
            await reader.readexactly(1)
            user = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
            pw = (await reader.readexactly((await reader.readexactly(1))[0])).decode()
            if (user, pw) != (self.username, self.password):
                self._auth_failed()
                writer.write(b"\x01\x01")
                await writer.drain()
                raise _Reject()
            writer.write(b"\x01\x00")
        _, cmd, _, atyp = await reader.readexactly(4)
        if atyp == 1:
            host = str(ipaddress.IPv4Address(await reader.readexactly(4)))
        elif atyp == 4:
            host = str(ipaddress.IPv6Address(await reader.readexactly(16)))
        else:
            host = (await reader.readexactly((await reader.readexactly(1))[0])).decode("idna")
        port = int.from_bytes(await reader.readexactly(2), "big")
        if cmd != 1:
            writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
            await writer.drain()
            raise _Reject()
        writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
        await writer.drain()
        return host, port

    async def _http(self, reader, writer):
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = lines[0].split(" ", 2)
        if self.username or self.password:
            expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            auth = [h for h in lines[1:] if h.lower().startswith("proxy-authorization:")]
            if not auth or auth[0].split(":", 1)[1].strip() != f"Basic {expected}":
                self._auth_failed()
                writer.write(b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                             b"Proxy-Authenticate: Basic realm=\"relay\"\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                raise _Reject()
        if method.upper() == "CONNECT":
            host, _, port = target.rpartition(":")
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            return host.strip("[]"), int(port), None
        from urllib.parse import urlsplit

        url = urlsplit(target)
        path = (url.path or "/") + (f"?{url.query}" if url.query else "")
        kept = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-", "connection:"))]
        new_head = "\r\n".join([f"{method} {path} HTTP/1.1", *kept, "Connection: close"]) + "\r\n\r\n"
        return url.hostname, url.port or 80, new_head.encode("latin-1")

    async def _forward(self, reader, writer, host, port, head):
        peer_reader, peer_writer = await asyncio.wait_for(asyncio.open_connection(host, port), 20)
        if head:
            peer_writer.write(head)
            await peer_writer.drain()

        async def pipe(src, dst):
            try:
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            except (ConnectionError, OSError):
                pass
            finally:
                try:
                    dst.close()
                except OSError:
                    pass

        await asyncio.gather(pipe(reader, peer_writer), pipe(peer_reader, writer))

    # --- "internet falsa" ---
    def _tls_context(self) -> ssl.SSLContext:
        if self._tls is None:
            import datetime as dt

            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.x509.oid import NameOID

            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "egress-test")])
            now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now).not_valid_after(now + dt.timedelta(days=2))
                    .sign(key, hashes.SHA256()))
            tmp = Path(self._tmp.name)
            (tmp / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (tmp / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                                          serialization.PrivateFormat.PKCS8,
                                                          serialization.NoEncryption()))
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(tmp / "c.pem", tmp / "k.pem")
            self._tls = ctx
        return self._tls

    async def _fake_site(self, reader, writer, host, port, head):
        if head is None:
            if port == 443:
                await writer.start_tls(self._tls_context())
            head = await reader.readuntil(b"\r\n\r\n")
        path = head.split(b" ", 2)[1].decode("latin-1")
        if path.startswith("/ip"):
            body, ctype = self.fake_ip.encode(), "text/plain"
        elif path.startswith("/json"):
            body, ctype = json.dumps({"ip": self.fake_ip, "host": host}).encode(), "application/json"
        else:
            body = (f"<html><head><title>{OK_TITLE}</title></head><body><p id='host'>{host}</p>"
                    f"<p id='ip'>{self.fake_ip}</p></body></html>").encode()
            ctype = "text/html; charset=utf-8"
        writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
                     "Connection: close\r\n\r\n".encode() + body)
        await writer.drain()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("relay", help="sobe um relay de referência")
    p.add_argument("--protocol", choices=["socks5", "http"], default="socks5")
    p.add_argument("--listen", default="127.0.0.1:1080")
    p.add_argument("--user", default="")
    p.add_argument("--password", default="")
    p.add_argument("--fake-ip", help="não sai para a internet: responde com este IP (testes)")
    p.add_argument("--record", help="grava cada destino (JSON por linha) neste arquivo")
    args = parser.parse_args(argv)
    host, _, port = args.listen.rpartition(":")
    relay = TestRelay(args.protocol, args.user, args.password, args.fake_ip, host or "127.0.0.1", int(port),
                      args.record)
    relay.start()
    mode = f"internet falsa, IP {args.fake_ip}" if args.fake_ip else "internet real"
    print(f"relay {args.protocol} em {host}:{relay.port} ({mode}); Ctrl+C para sair", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        relay.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
