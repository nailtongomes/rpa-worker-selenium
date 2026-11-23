"""
Testes rápidos (host) do relay de saída: image/app/egress_proxy.py com o relay de
referência de image/app/egress_testkit.py ("internet falsa", sem rede externa).
"""

import asyncio
import json
import re
import threading
import time
import warnings

import pytest

import egress_proxy as ep
import egress_testkit as tk

requests = pytest.importorskip("requests")
FAKE_IP = "203.0.113.7"


# --- EGRESS_PROXY_URL -------------------------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("socks5://u:p@relay:1080", ("socks5", "relay", 1080, "u", "p")),
        ("socks5h://relay", ("socks5", "relay", 1080, "", "")),
        ("http://user:s%40nh%3Aa@10.0.0.5:8080", ("http", "10.0.0.5", 8080, "user", "s@nh:a")),
        ("https://relay.exemplo.com.br", ("https", "relay.exemplo.com.br", 443, "", "")),
        ("HTTP://relay", ("http", "relay", 3128, "", "")),
    ],
)
def test_parse_upstream(url, expected):
    up = ep.parse_upstream(url)
    assert (up.scheme, up.host, up.port, up.username, up.password) == expected


@pytest.mark.parametrize("url, message", [("ftp://relay:21", "não suportado"), ("socks5://:1080", "host"),
                                          ("socks5://relay:abc", "porta")])
def test_parse_upstream_invalid(url, message):
    with pytest.raises(ep.EgressError, match=message):
        ep.parse_upstream(url)


def test_password_never_in_masked_or_repr():
    up = ep.parse_upstream("socks5://rpa:segredo-123@relay:1080")
    assert "segredo-123" not in up.masked and "segredo-123" not in repr(up)
    assert up.masked == "socks5://***@relay:1080"


def test_url_file_has_priority(tmp_path, monkeypatch):
    f = tmp_path / "relay"
    f.write_text("http://a:b@do-arquivo:3128\n")
    monkeypatch.setenv("EGRESS_PROXY_URL", "socks5://da-variavel:1080")
    monkeypatch.setenv("EGRESS_PROXY_URL_FILE", str(f))
    assert ep.upstream_from_env().host == "do-arquivo"


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EGRESS_PROXY_URL", raising=False)
    monkeypatch.delenv("EGRESS_PROXY_URL_FILE", raising=False)
    assert ep.upstream_from_env() is None


# --- configuração dos clientes ------------------------------------------------------------

def test_proxy_env_and_bypass(monkeypatch):
    monkeypatch.setenv("EGRESS_BYPASS", ".interno.com.br, 10.0.0.0/8;storage.local")
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-Xmx512m")
    env = ep.proxy_env(3128)
    assert env["HTTPS_PROXY"] == env["http_proxy"] == "http://127.0.0.1:3128"
    assert env["NO_PROXY"] == "localhost,127.0.0.1,::1,.interno.com.br,10.0.0.0/8,storage.local"
    java = env["JAVA_TOOL_OPTIONS"]
    assert java.startswith("-Xmx512m ")
    assert "-Dhttp.nonProxyHosts=localhost|127.0.0.1|[::1]|*.interno.com.br|10.*|storage.local" in java


def test_chrome_policy_blocks_leaks(monkeypatch):
    monkeypatch.delenv("EGRESS_BYPASS", raising=False)
    policy = ep.chrome_policy(3128)
    assert policy["ProxySettings"] == {"ProxyMode": "fixed_servers", "ProxyServer": "http://127.0.0.1:3128",
                                       "ProxyBypassList": "localhost;127.0.0.1;::1"}
    assert policy["WebRtcIPHandlingPolicy"] == "disable_non_proxied_udp" and policy["QuicAllowed"] is False


def test_configure_merges_firefox_policies_and_unconfigure_restores(tmp_path):
    chrome = [tmp_path / "chrome", tmp_path / "cft"]
    firefox = tmp_path / "distribution" / "policies.json"
    firefox.parent.mkdir()
    firefox.write_text(json.dumps({"policies": {"DisableAppUpdate": True}}))
    written = ep.configure(3128, chrome, firefox)
    assert len(written) == 3
    data = json.loads(firefox.read_text())["policies"]
    assert data["DisableAppUpdate"] is True and data["Proxy"]["HTTPProxy"] == "127.0.0.1:3128"
    ep.unconfigure(chrome, firefox)
    assert not any((d / ep.CHROME_POLICY_FILE).exists() for d in chrome)
    assert json.loads(firefox.read_text()) == {"policies": {"DisableAppUpdate": True}}


# --- repassador + relay de referência ----------------------------------------------------

@pytest.fixture
def forwarder():
    """Sobe o repassador local para um relay; devolve a porta."""
    started = []

    def start(up):
        loop = asyncio.new_event_loop()
        holder = {}

        def run():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ep.serve(up, "127.0.0.1", 0, ready=lambda s: holder.update(
                port=s.sockets[0].getsockname()[1])))

        threading.Thread(target=run, daemon=True).start()
        for _ in range(100):
            if "port" in holder:
                break
            time.sleep(0.05)
        started.append(loop)
        return holder["port"]

    yield start
    for loop in started:
        loop.call_soon_threadsafe(loop.stop)


def _get(port, url, **kw):
    proxies = {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return requests.get(url, proxies=proxies, timeout=10, verify=False, **kw)


@pytest.mark.parametrize("protocol", ["socks5", "http"])
def test_http_and_https_through_relay(protocol, forwarder):
    with tk.TestRelay(protocol, "rpa", "s@nh:a", fake_ip=FAKE_IP) as relay:
        port = forwarder(ep.parse_upstream(f"{protocol}://rpa:s%40nh%3Aa@127.0.0.1:{relay.port}"))
        assert _get(port, "http://plain.egress-test.invalid/ip").text == FAKE_IP
        assert _get(port, "https://tls.egress-test.invalid/json").json() == {"ip": FAKE_IP,
                                                                            "host": "tls.egress-test.invalid"}
        # o nome chega ao relay sem ser resolvido localmente
        assert relay.hosts() == ["plain.egress-test.invalid", "tls.egress-test.invalid"]
        assert relay.auth_failures == 0


@pytest.mark.parametrize("protocol, message", [("socks5", "usuário ou senha incorretos"),
                                               ("http", "usuário ou senha incorretos (407)")])
def test_wrong_password_is_reported_clearly(protocol, message, forwarder, monkeypatch):
    with tk.TestRelay(protocol, "rpa", "certa", fake_ip=FAKE_IP) as relay:
        monkeypatch.setenv("EGRESS_PROXY_URL", f"{protocol}://rpa:errada@127.0.0.1:{relay.port}")
        monkeypatch.delenv("EGRESS_PROXY_URL_FILE", raising=False)
        port = forwarder(ep.upstream_from_env())
        # verificação do boot (URL https, como o padrão): motivo explícito e sem a senha
        with pytest.raises(ep.EgressError, match=re.escape(message)) as err:
            ep.check(port, "https://check.egress-test.invalid/ip")
        assert "errada" not in str(err.value)
        # clientes: https falha no túnel; http:// simples recebe 502 explicado (SOCKS) ou o 407 do relay
        with pytest.raises(requests.exceptions.ProxyError):
            _get(port, "https://x.egress-test.invalid/ip")
        resp = _get(port, "http://x.egress-test.invalid/ip")
        if protocol == "socks5":
            assert resp.status_code == 502 and message in resp.text and "errada" not in resp.text
        else:
            assert resp.status_code == 407
        assert relay.auth_failures >= 1


def test_relay_down_returns_502(forwarder):
    port = forwarder(ep.parse_upstream("socks5://127.0.0.1:9"))
    resp = _get(port, "http://x.egress-test.invalid/")
    assert resp.status_code == 502 and "inacessível" in resp.text


def test_check_reports_ip_and_expected_mismatch(forwarder, monkeypatch):
    with tk.TestRelay("socks5", fake_ip=FAKE_IP) as relay:
        monkeypatch.setenv("EGRESS_PROXY_URL", f"socks5://127.0.0.1:{relay.port}")
        monkeypatch.delenv("EGRESS_PROXY_URL_FILE", raising=False)
        port = forwarder(ep.upstream_from_env())
        monkeypatch.delenv("EGRESS_EXPECTED_IP", raising=False)
        assert ep.check(port, "http://check.egress-test.invalid/ip") == FAKE_IP
        monkeypatch.setenv("EGRESS_EXPECTED_IP", "198.51.100.1")
        with pytest.raises(ep.EgressError, match="diferente do esperado"):
            ep.check(port, "http://check.egress-test.invalid/ip")
        assert ep.check(port, "off") == "ok"


def test_split_host_port():
    assert ep._split_host_port("exemplo.com:8443", 443) == ("exemplo.com", 8443)
    assert ep._split_host_port("[::1]:443", 80) == ("::1", 443)
    assert ep._split_host_port("exemplo.com", 443) == ("exemplo.com", 443)
