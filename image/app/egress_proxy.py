#!/usr/bin/env python3
"""
egress_proxy — saída de internet do container por um relay (opcional).

Quando ``EGRESS_PROXY_URL`` está definido, o entrypoint:

  1. sobe este repassador em 127.0.0.1:3128 (proxy HTTP local, sem senha), que
     encaminha cada conexão para o relay, autenticando lá
     (SOCKS5 com usuário/senha, proxy HTTP ou HTTPS com Basic auth);
  2. aplica a configuração em Chrome, Firefox, Python/curl e Java
     (``configure``);
  3. confere a saída (``check``) e, com ``EGRESS_REQUIRED=1`` (padrão),
     interrompe o container se o relay não funcionar.

O DNS dos destinos é resolvido no relay: o nome do host segue no CONNECT/SOCKS5.
Nada de UDP sai pelo relay; QUIC e WebRTC sem proxy são desligados nos browsers.

Uso:
    egress_proxy.py serve [--listen 127.0.0.1:3128]
    egress_proxy.py configure [--port 3128]
    egress_proxy.py check [--port 3128] [--url URL]
    egress_proxy.py env [--port 3128]       # linhas `export X=...` para o entrypoint

Variáveis:
    EGRESS_PROXY_URL       socks5://usuario:senha@relay:1080 | http://usuario:senha@relay:3128 | https://...
    EGRESS_PROXY_URL_FILE  arquivo com a URL (tem prioridade; não aparece no docker inspect)
    EGRESS_BYPASS          destinos que saem direto (vírgulas): .dominio.com.br, host, 10.0.0.0/8
    EGRESS_REQUIRED        1 (padrão) = sem relay funcionando o container para
    EGRESS_CHECK_URL       URL que devolve o IP de saída (padrão https://api.ipify.org; "off" desliga)
    EGRESS_EXPECTED_IP     IP esperado na saída (o IP do cliente na whitelist)
    EGRESS_LOCAL_PORT      porta local do repassador (padrão 3128)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import ipaddress
import json
import logging
import os
import socket
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit

log = logging.getLogger("egress")

DEFAULT_PORT = 3128
DEFAULT_CHECK_URL = "https://api.ipify.org"
CONNECT_TIMEOUT = 20
HEAD_LIMIT = 64 * 1024
LOOPBACK = ["localhost", "127.0.0.1", "::1"]

CHROME_POLICY_DIRS = (
    Path("/etc/opt/chrome/policies/managed"),
    Path("/etc/opt/chrome_for_testing/policies/managed"),
)
CHROME_POLICY_FILE = "egress_proxy.json"
FIREFOX_POLICIES = Path(os.getenv("FIREFOX_DISTRIBUTION_DIR", "/opt/firefox/distribution")) / "policies.json"


class EgressError(RuntimeError):
    """Erro com mensagem pronta para o log (nunca contém a senha)."""


# --- Configuração do relay ------------------------------------------------------

@dataclass(frozen=True)
class Upstream:
    scheme: str            # socks5 | http | https
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def masked(self) -> str:
        """URL para log: nunca mostra usuário/senha."""
        auth = "***@" if self.username or self.password else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    def __repr__(self) -> str:  # a senha não aparece em tracebacks/logs
        return f"Upstream({self.masked})"


def parse_upstream(url: str) -> Upstream:
    """Interpreta EGRESS_PROXY_URL. Aceita socks5, socks5h, http e https."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme in ("socks5h", "socks"):
        scheme = "socks5"
    if scheme not in ("socks5", "http", "https"):
        raise EgressError(f"EGRESS_PROXY_URL: esquema '{parts.scheme}' não suportado (use socks5://, http:// ou https://)")
    if not parts.hostname:
        raise EgressError("EGRESS_PROXY_URL: host do relay ausente")
    try:
        port = parts.port or {"socks5": 1080, "http": 3128, "https": 443}[scheme]
    except ValueError:
        raise EgressError("EGRESS_PROXY_URL: porta inválida") from None
    return Upstream(scheme, parts.hostname, port, unquote(parts.username or ""), unquote(parts.password or ""))


def upstream_from_env() -> Optional[Upstream]:
    """EGRESS_PROXY_URL_FILE (preferido) ou EGRESS_PROXY_URL; None se o recurso está desligado."""
    url_file = os.getenv("EGRESS_PROXY_URL_FILE")
    if url_file:
        try:
            return parse_upstream(Path(url_file).read_text(encoding="utf-8").strip())
        except OSError as exc:
            raise EgressError(f"não foi possível ler EGRESS_PROXY_URL_FILE ({url_file}): {exc.strerror}") from None
    url = os.getenv("EGRESS_PROXY_URL", "").strip()
    return parse_upstream(url) if url else None


def bypass_list() -> list:
    """Loopback + EGRESS_BYPASS (sem duplicatas, ordem preservada)."""
    extra = [b.strip() for b in os.getenv("EGRESS_BYPASS", "").replace(";", ",").split(",") if b.strip()]
    return list(dict.fromkeys(LOOPBACK + extra))


# --- Túnel até o destino, passando pelo relay ----------------------------------------

async def _read_head(reader: asyncio.StreamReader) -> bytes:
    try:
        return await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError:
        raise EgressError("cabeçalho grande demais") from None
    except asyncio.IncompleteReadError as exc:
        raise EgressError("conexão encerrada antes do fim do cabeçalho") from exc


async def _connect_relay(up: Upstream):
    ctx = None
    if up.scheme == "https":
        ctx = ssl.create_default_context()
    try:
        return await asyncio.wait_for(
            asyncio.open_connection(up.host, up.port, ssl=ctx, server_hostname=up.host if ctx else None,
                                    limit=HEAD_LIMIT),
            CONNECT_TIMEOUT,
        )
    except (OSError, asyncio.TimeoutError) as exc:
        raise EgressError(f"relay {up.host}:{up.port} inacessível: {exc or 'timeout'}") from None


def _socks_address(host: str) -> bytes:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raw = host.encode("idna")
        if len(raw) > 255:
            raise EgressError("nome de host longo demais") from None
        return b"\x03" + bytes([len(raw)]) + raw  # nome: o relay resolve o DNS
    return (b"\x01" if ip.version == 4 else b"\x04") + ip.packed


SOCKS_ERRORS = {
    1: "falha geral do servidor SOCKS", 2: "conexão não permitida pelas regras do relay",
    3: "rede inacessível", 4: "host inacessível", 5: "conexão recusada pelo destino",
    6: "TTL expirado", 7: "comando não suportado", 8: "tipo de endereço não suportado",
}


async def _socks5_handshake(reader, writer, up: Upstream) -> None:
    methods = b"\x02" if (up.username or up.password) else b"\x00"
    writer.write(b"\x05\x01" + methods)
    await writer.drain()
    ver, method = await reader.readexactly(2)
    if ver != 5:
        raise EgressError("o relay não respondeu como SOCKS5")
    if method == 0xFF:
        raise EgressError("relay SOCKS5 recusou o método de autenticação")
    if method == 0x02:
        user, pw = up.username.encode(), up.password.encode()
        writer.write(b"\x01" + bytes([len(user)]) + user + bytes([len(pw)]) + pw)
        await writer.drain()
        _, status = await reader.readexactly(2)
        if status != 0:
            raise EgressError("relay SOCKS5: usuário ou senha incorretos")
    elif method != 0x00:
        raise EgressError(f"relay SOCKS5 escolheu método desconhecido ({method})")


async def _socks5_connect(reader, writer, host: str, port: int) -> None:
    writer.write(b"\x05\x01\x00" + _socks_address(host) + port.to_bytes(2, "big"))
    await writer.drain()
    ver, rep, _, atyp = await reader.readexactly(4)
    if rep != 0:
        raise EgressError(f"relay SOCKS5 não conectou {host}:{port}: {SOCKS_ERRORS.get(rep, rep)}")
    skip = {1: 4, 4: 16}.get(atyp)
    if skip is None:
        skip = (await reader.readexactly(1))[0]
    await reader.readexactly(skip + 2)


def _proxy_auth(up: Upstream) -> str:
    if not (up.username or up.password):
        return ""
    token = base64.b64encode(f"{up.username}:{up.password}".encode()).decode()
    return f"Proxy-Authorization: Basic {token}\r\n"


async def _http_connect(reader, writer, up: Upstream, host: str, port: int) -> None:
    target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{_proxy_auth(up)}\r\n".encode())
    await writer.drain()
    head = await _read_head(reader)
    status = head.split(b"\r\n", 1)[0].decode("latin-1")
    code = status.split(" ")[1] if " " in status else "?"
    if code == "407":
        raise EgressError("relay HTTP: usuário ou senha incorretos (407)")
    if code != "200":
        raise EgressError(f"relay HTTP recusou CONNECT {target}: {status}")


async def open_tunnel(up: Upstream, host: str, port: int):
    """Conexão TCP até host:port passando pelo relay. Devolve (reader, writer)."""
    reader, writer = await _connect_relay(up)
    try:
        if up.scheme == "socks5":
            await asyncio.wait_for(_socks5_handshake(reader, writer, up), CONNECT_TIMEOUT)
            await asyncio.wait_for(_socks5_connect(reader, writer, host, port), CONNECT_TIMEOUT)
        else:
            await asyncio.wait_for(_http_connect(reader, writer, up, host, port), CONNECT_TIMEOUT)
    except asyncio.IncompleteReadError:
        writer.close()
        raise EgressError("o relay encerrou a conexão durante a negociação") from None
    except asyncio.TimeoutError:
        writer.close()
        raise EgressError("o relay não respondeu a tempo") from None
    except BaseException:
        writer.close()
        raise
    return reader, writer


# --- Servidor local (proxy HTTP em 127.0.0.1) ------------------------------------------

async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            if writer.can_write_eof():
                writer.write_eof()
        except (OSError, RuntimeError):
            pass


async def _relay_both(a_reader, a_writer, b_reader, b_writer) -> None:
    tasks = {asyncio.ensure_future(_pipe(a_reader, b_writer)), asyncio.ensure_future(_pipe(b_reader, a_writer))}
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    if pending:  # meia conexão fechada: dá um tempo para o outro lado terminar e encerra
        _, still = await asyncio.wait(pending, timeout=30)
        for task in still:
            task.cancel()
    for w in (a_writer, b_writer):
        try:
            w.close()
        except OSError:
            pass


def _split_host_port(value: str, default_port: int) -> Tuple[str, int]:
    if value.startswith("["):
        host, _, rest = value[1:].partition("]")
        return host, int(rest[1:]) if rest.startswith(":") else default_port
    if value.count(":") == 1:
        host, port = value.split(":")
        return host, int(port)
    return value, default_port


def _rewrite_plain_request(head: bytes, origin_form: bool, up: Upstream) -> Tuple[bytes, str, int]:
    """Pedido http:// absoluto: ajusta cabeçalhos e devolve (cabeçalho, host, porta)."""
    lines = head.decode("latin-1").split("\r\n")
    method, target, version = lines[0].split(" ", 2)
    url = urlsplit(target)
    if url.scheme != "http" or not url.hostname:
        raise EgressError(f"pedido não suportado: {lines[0][:80]}")
    host, port = url.hostname, url.port or 80
    keep = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-", "connection:", "keep-alive:"))]
    path = url.path or "/"
    if url.query:
        path += "?" + url.query
    first = f"{method} {path if origin_form else target} {version}"
    extra = ["Connection: close"]
    if not origin_form and (up.username or up.password):
        extra.append(_proxy_auth(up).strip())
    return ("\r\n".join([first, *keep, *extra]) + "\r\n\r\n").encode("latin-1"), host, port


async def handle_client(up: Upstream, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer_writer = None
    try:
        head = await asyncio.wait_for(_read_head(reader), 60)
        request_line = head.split(b"\r\n", 1)[0].decode("latin-1")
        method, target, _ = request_line.split(" ", 2)
        if method.upper() == "CONNECT":
            host, port = _split_host_port(target, 443)
            peer_reader, peer_writer = await open_tunnel(up, host, port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
        else:
            if up.scheme == "socks5":
                new_head, host, port = _rewrite_plain_request(head, True, up)
                peer_reader, peer_writer = await open_tunnel(up, host, port)
            else:
                new_head, host, port = _rewrite_plain_request(head, False, up)
                peer_reader, peer_writer = await _connect_relay(up)
            peer_writer.write(new_head)
            await peer_writer.drain()
        log.debug("%s %s:%s", method, host, port)
        await _relay_both(reader, writer, peer_reader, peer_writer)
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira 502 para o cliente
        message = str(exc) if isinstance(exc, EgressError) else f"{type(exc).__name__}: {exc}"
        log.warning("falha na saída pelo relay: %s", message)
        try:
            body = f"egress relay: {message}\n".encode()
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain; charset=utf-8\r\n"
                         + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except (OSError, RuntimeError):
            pass
        writer.close()
        if peer_writer:
            peer_writer.close()


async def serve(up: Upstream, host: str = "127.0.0.1", port: int = DEFAULT_PORT, ready=None) -> None:
    server = await asyncio.start_server(lambda r, w: handle_client(up, r, w), host, port, limit=HEAD_LIMIT)
    log.info("repassador em %s:%s -> %s", host, port, up.masked)
    if ready is not None:
        ready(server)
    async with server:
        await server.serve_forever()


# --- Configuração dos clientes (browsers, Python, Java) ------------------------------

def proxy_env(port: int = DEFAULT_PORT) -> dict:
    """Variáveis que fazem Python/curl/pip usarem o repassador local."""
    local = f"http://127.0.0.1:{port}"
    no_proxy = ",".join(bypass_list())
    env = {}
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env[name] = env[name.lower()] = local
    env["NO_PROXY"] = env["no_proxy"] = no_proxy
    java = [f"-Dhttp.proxyHost=127.0.0.1", f"-Dhttp.proxyPort={port}",
            f"-Dhttps.proxyHost=127.0.0.1", f"-Dhttps.proxyPort={port}",
            "-Dhttp.nonProxyHosts=" + "|".join(_java_pattern(b) for b in bypass_list())]
    current = os.getenv("JAVA_TOOL_OPTIONS", "")
    env["JAVA_TOOL_OPTIONS"] = (current + " " if current else "") + " ".join(java)
    return env


def _java_pattern(entry: str) -> str:
    if entry == "::1":
        return "[::1]"
    if entry.startswith("."):
        return "*" + entry
    if "/" in entry:  # CIDR: o Java só aceita curingas simples
        net = ipaddress.ip_network(entry, strict=False)
        octets = str(net.network_address).split(".")
        keep = net.prefixlen // 8
        return ".".join(octets[:keep]) + ".*" if net.version == 4 and keep else str(net.network_address)
    return entry


def chrome_policy(port: int = DEFAULT_PORT) -> dict:
    return {
        "ProxySettings": {
            "ProxyMode": "fixed_servers",
            "ProxyServer": f"http://127.0.0.1:{port}",
            "ProxyBypassList": ";".join(bypass_list()),
        },
        "WebRtcIPHandlingPolicy": "disable_non_proxied_udp",
        "QuicAllowed": False,
    }


def firefox_policies(port: int = DEFAULT_PORT) -> dict:
    locked = {"Status": "locked"}
    return {
        "policies": {
            "Proxy": {
                "Mode": "manual",
                "Locked": True,
                "HTTPProxy": f"127.0.0.1:{port}",
                "UseHTTPProxyForAllProtocols": True,
                "Passthrough": ", ".join(bypass_list()),
            },
            "DNSOverHTTPS": {"Enabled": False, "Locked": True},
            "Preferences": {
                "network.http.http3.enable": {"Value": False, **locked},
                "media.peerconnection.ice.proxy_only": {"Value": True, **locked},
                "network.proxy.allow_hijacking_localhost": {"Value": False, **locked},
            },
        }
    }


def configure(port: int = DEFAULT_PORT, chrome_dirs=CHROME_POLICY_DIRS, firefox_file: Path = FIREFOX_POLICIES) -> list:
    """Grava as policies de proxy do Chrome e do Firefox. Devolve os arquivos escritos."""
    written = []
    for d in map(Path, chrome_dirs):
        d.mkdir(parents=True, exist_ok=True)
        target = d / CHROME_POLICY_FILE
        target.write_text(json.dumps(chrome_policy(port), indent=2), encoding="utf-8")
        written.append(target)
    firefox_file = Path(firefox_file)
    firefox_file.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if firefox_file.exists():
        try:
            current = json.loads(firefox_file.read_text(encoding="utf-8"))
        except ValueError:
            current = {}
    merged = current.get("policies", {})
    merged.update(firefox_policies(port)["policies"])
    firefox_file.write_text(json.dumps({"policies": merged}, indent=2), encoding="utf-8")
    written.append(firefox_file)
    return written


def unconfigure(chrome_dirs=CHROME_POLICY_DIRS, firefox_file: Path = FIREFOX_POLICIES) -> None:
    """Remove as policies de proxy (usado quando o recurso está desligado)."""
    for d in map(Path, chrome_dirs):
        (d / CHROME_POLICY_FILE).unlink(missing_ok=True)
    firefox_file = Path(firefox_file)
    if firefox_file.exists():
        try:
            data = json.loads(firefox_file.read_text(encoding="utf-8"))
        except ValueError:
            return
        policies = data.get("policies", {})
        for key in ("Proxy", "DNSOverHTTPS", "Preferences"):
            policies.pop(key, None)
        if policies:
            firefox_file.write_text(json.dumps({"policies": policies}, indent=2), encoding="utf-8")
        else:
            firefox_file.unlink()


# --- Verificação -----------------------------------------------------------------------

def wait_port(port: int, timeout: float = 10) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def fetch_via_local(url: str, port: int = DEFAULT_PORT, timeout: int = 30) -> str:
    """GET pela porta local (o mesmo caminho dos scripts). Devolve o corpo."""
    import requests

    proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
    resp = requests.get(url, proxies=proxies, timeout=timeout)
    if resp.status_code == 502 and "egress relay:" in resp.text:
        raise EgressError(resp.text.split("egress relay:", 1)[1].strip())
    resp.raise_for_status()
    return resp.text.strip()


async def _probe_relay(up: Upstream) -> None:
    reader, writer = await _connect_relay(up)
    try:
        if up.scheme == "socks5":
            await asyncio.wait_for(_socks5_handshake(reader, writer, up), CONNECT_TIMEOUT)
    finally:
        writer.close()


async def _probe_tunnel(up: Upstream, host: str, port: int) -> None:
    _, writer = await open_tunnel(up, host, port)
    writer.close()


def check(port: int = DEFAULT_PORT, url: Optional[str] = None) -> str:
    """Confere a saída. Devolve o IP/texto visto em EGRESS_CHECK_URL (ou 'ok')."""
    up = upstream_from_env()
    if up is None:
        raise EgressError("EGRESS_PROXY_URL não definido")
    if not wait_port(port, 5):
        raise EgressError(f"repassador local não está escutando em 127.0.0.1:{port}")
    url = url or os.getenv("EGRESS_CHECK_URL", DEFAULT_CHECK_URL)
    if url.lower() in ("off", "0", "none", ""):
        asyncio.run(_probe_relay(up))
        return "ok"
    # Negocia direto com o relay antes: senha errada/relay recusando viram mensagem clara
    target = urlsplit(url)
    asyncio.run(_probe_tunnel(up, target.hostname or "", target.port or (443 if target.scheme == "https" else 80)))
    try:
        seen = fetch_via_local(url, port)
    except EgressError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise EgressError(f"{url} não respondeu pelo relay: {exc}") from None
    expected = os.getenv("EGRESS_EXPECTED_IP", "").strip()
    if expected and expected not in seen:
        raise EgressError(f"IP de saída {seen[:60]!r} diferente do esperado ({expected})")
    return seen[:120]


# --- CLI -----------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--listen", default=f"127.0.0.1:{DEFAULT_PORT}")
    for name in ("configure", "check", "env", "unconfigure"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=int(os.getenv("EGRESS_LOCAL_PORT", DEFAULT_PORT)))
        if name == "check":
            p.add_argument("--url")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if os.getenv("EGRESS_DEBUG") == "1" else logging.INFO,
                        format="%(asctime)s egress %(levelname)s %(message)s")
    try:
        if args.cmd == "serve":
            up = upstream_from_env()
            if up is None:
                raise EgressError("EGRESS_PROXY_URL não definido")
            host, port = _split_host_port(args.listen, DEFAULT_PORT)
            asyncio.run(serve(up, host, port))
        elif args.cmd == "configure":
            for f in configure(args.port):
                print(f)
        elif args.cmd == "unconfigure":
            unconfigure()
        elif args.cmd == "env":
            import shlex

            for key, value in proxy_env(args.port).items():
                print(f"export {key}={shlex.quote(value)}")
        elif args.cmd == "check":
            print(check(args.port, args.url))
    except EgressError as exc:
        print(f"egress: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
