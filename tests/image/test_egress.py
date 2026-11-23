#!/usr/bin/env python3
"""
Saída de internet pelo relay (roda DENTRO da imagem, sem internet).

O cenário do portão (scripts/test-image.sh) sobe, antes do entrypoint, um relay
SOCKS5 de teste com senha que NÃO sai para a internet: ele responde a qualquer host
com uma página mostrando o host pedido e um IP "residencial" falso (203.0.113.7), e
grava cada destino em EGRESS_TEST_RECORDS. O entrypoint configura tudo a partir de
EGRESS_PROXY_URL, como em produção.

Os hosts usados terminam em ``.invalid`` (não existem no DNS): se algo funcionar com
eles, é porque o nome foi resolvido no relay e o tráfego passou por lá.
"""

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, "/app")

import egress_proxy as ep  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.trixie,
    pytest.mark.skipif(not os.getenv("EGRESS_TEST_RECORDS"), reason="rode pelo cenário de relay do test-image.sh"),
]

FAKE_IP = os.getenv("EGRESS_EXPECTED_IP", "203.0.113.7")
RECORDS = Path(os.getenv("EGRESS_TEST_RECORDS", "/tmp/egress-records.jsonl"))
PORT = int(os.getenv("EGRESS_LOCAL_PORT", "3128"))


def _hosts() -> list:
    if not RECORDS.exists():
        return []
    return [json.loads(line).get("host") for line in RECORDS.read_text().splitlines() if line.strip()]


def _assert_via_relay(host: str) -> None:
    for _ in range(20):
        if host in _hosts():
            return
        time.sleep(0.25)
    pytest.fail(f"{host} não passou pelo relay (destinos: {sorted(set(_hosts()))})")


def _has_display() -> bool:
    return subprocess.run(["xdpyinfo", "-display", os.getenv("DISPLAY", ":99")], capture_output=True).returncode == 0


def _modes():
    return [True, pytest.param(False, marks=pytest.mark.requires_display)]


@pytest.fixture(scope="module")
def local_page():
    """Página em 127.0.0.1 (exceção: não passa pelo relay)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = b"<html><head><title>LOCAL-OK</title></head><body>local</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


# --- configuração aplicada pelo entrypoint ------------------------------------------------

def test_forwarder_running_and_env_exported():
    assert ep.wait_port(PORT, 5), "repassador local não está escutando"
    local = f"http://127.0.0.1:{PORT}"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        assert os.environ.get(name) == local, name
    no_proxy = os.environ["NO_PROXY"].split(",")
    assert {"localhost", "127.0.0.1", "::1"} <= set(no_proxy)
    java = os.environ["JAVA_TOOL_OPTIONS"]
    assert f"-Dhttps.proxyPort={PORT}" in java and "-Dhttp.nonProxyHosts=localhost|127.0.0.1|[::1]" in java


def test_relay_password_not_exposed():
    """A URL do relay (com senha) não vai para as variáveis dos scripts nem para o log."""
    password = ep.upstream_from_env().password
    assert password, "o cenário de teste usa relay com senha"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "JAVA_TOOL_OPTIONS", "NO_PROXY"):
        assert password not in os.environ.get(name, "")
    log = Path("/app/logs/egress_proxy.log")
    assert not log.exists() or password not in log.read_text()


def test_chrome_and_firefox_policies():
    for d in ep.CHROME_POLICY_DIRS:
        policy = json.loads((d / ep.CHROME_POLICY_FILE).read_text())
        assert policy["ProxySettings"]["ProxyServer"] == f"http://127.0.0.1:{PORT}"
        assert policy["WebRtcIPHandlingPolicy"] == "disable_non_proxied_udp"
        assert policy["QuicAllowed"] is False
    firefox = json.loads(ep.FIREFOX_POLICIES.read_text())["policies"]
    assert firefox["Proxy"]["HTTPProxy"] == f"127.0.0.1:{PORT}" and firefox["Proxy"]["Locked"] is True
    assert firefox["Preferences"]["media.peerconnection.ice.proxy_only"]["Value"] is True


def test_names_are_not_resolvable_locally():
    """Controle: os hosts de teste não existem no DNS do container."""
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("dns.egress-test.invalid", 80)


# --- Python, curl e Java ---------------------------------------------------------------

def test_python_requests_http_and_https():
    import requests

    assert requests.get("http://py.egress-test.invalid/ip", timeout=20).text == FAKE_IP
    data = requests.get("https://pys.egress-test.invalid/json", timeout=20, verify=False).json()
    assert data == {"ip": FAKE_IP, "host": "pys.egress-test.invalid"}
    _assert_via_relay("py.egress-test.invalid")
    _assert_via_relay("pys.egress-test.invalid")


def test_curl_uses_relay():
    out = subprocess.run(["curl", "-sk", "--max-time", "20", "https://curl.egress-test.invalid/ip"],
                         capture_output=True, text=True)
    assert out.stdout == FAKE_IP, out.stderr
    _assert_via_relay("curl.egress-test.invalid")


def test_java_pjeoffice_runtime_uses_relay():
    import egress_check

    assert FAKE_IP in egress_check.java_fetch("http://java.egress-test.invalid/ip")
    _assert_via_relay("java.egress-test.invalid")


def test_localhost_bypasses_relay(local_page):
    import requests

    before = len(_hosts())
    assert "LOCAL-OK" in requests.get(local_page, timeout=10).text
    assert len(_hosts()) == before, "tráfego local passou pelo relay"


# --- browsers ----------------------------------------------------------------------------

def _open(driver, url: str) -> str:
    from selenium.webdriver.common.by import By

    try:
        driver.get(url)
        for _ in range(20):
            if driver.title in ("EGRESS-OK", "LOCAL-OK"):
                break
            time.sleep(0.5)
        if driver.title == "EGRESS-OK":
            return driver.find_element(By.ID, "host").text + "|" + driver.find_element(By.ID, "ip").text
        return driver.title
    finally:
        driver.quit()


@pytest.mark.parametrize("headless", _modes())
def test_chrome_selenium_uses_relay(headless):
    if not headless and not _has_display():
        pytest.skip("sem servidor X")
    import egress_check

    host = f"chrome-{'h' if headless else 'w'}.egress-test.invalid"
    assert _open(egress_check._chrome(headless, True), f"http://{host}/") == f"{host}|{FAKE_IP}"
    _assert_via_relay(host)


@pytest.mark.parametrize("headless", _modes())
def test_seleniumbase_uc_uses_relay(headless):
    if not headless and not _has_display():
        pytest.skip("sem servidor X")
    import egress_check

    host = f"uc-{'h' if headless else 'w'}.egress-test.invalid"
    assert _open(egress_check._uc(headless, True), f"http://{host}/") == f"{host}|{FAKE_IP}"
    _assert_via_relay(host)


@pytest.mark.parametrize("headless", _modes())
def test_firefox_uses_relay(headless):
    if not headless and not _has_display():
        pytest.skip("sem servidor X")
    import egress_check

    host = f"firefox-{'h' if headless else 'w'}.egress-test.invalid"
    assert _open(egress_check._firefox(headless, True), f"http://{host}/") == f"{host}|{FAKE_IP}"
    _assert_via_relay(host)


def test_browsers_still_reach_localhost(local_page):
    """PJeOffice, mTLS local e páginas em 127.0.0.1 continuam diretos."""
    import egress_check

    assert _open(egress_check._chrome(True, True), local_page) == "LOCAL-OK"
    assert _open(egress_check._firefox(True, True), local_page) == "LOCAL-OK"


WEBRTC_JS = """
const done = arguments[arguments.length - 1];
const pc = new RTCPeerConnection({iceServers: [{urls: 'stun:stun.egress-test.invalid:3478'}]});
const found = [];
pc.onicecandidate = e => { if (e.candidate && e.candidate.candidate) found.push(e.candidate.candidate); };
pc.createDataChannel('x');
pc.createOffer().then(o => pc.setLocalDescription(o));
setTimeout(() => { pc.close(); done(found); }, 4000);
"""


@pytest.mark.parametrize("browser", ["chrome", "firefox"])
def test_webrtc_does_not_leak_udp(browser, local_page):
    """WebRTC é a forma mais comum de um site descobrir o IP real: nenhum candidato UDP."""
    import egress_check

    driver = egress_check._chrome(True, True) if browser == "chrome" else egress_check._firefox(True, True)
    try:
        driver.get(local_page)
        driver.set_script_timeout(15)
        candidates = driver.execute_async_script(WEBRTC_JS)
    finally:
        driver.quit()
    import re

    # Permitido: candidato "host" mDNS (<uuid>.local), que não revela o IP.
    # Proibido: qualquer IP literal ou candidato srflx/relay (IP público via STUN/TURN).
    ip = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,7}\b", re.I)
    leaks = [c for c in candidates if ip.search(c.split(" typ ")[0].split(" ", 4)[-1]) or
             re.search(r"typ (srflx|prflx|relay)", c)]
    assert leaks == [], f"candidatos WebRTC revelando IP: {leaks}"


def test_chrome_loaded_proxy_and_webrtc_policies():
    """chrome://policy mostra as policies aplicadas (prova que o Chrome as leu)."""
    import egress_check
    from selenium.webdriver.common.by import By

    driver = egress_check._chrome(True, True)
    try:
        driver.get("chrome://policy")
        text = ""
        for _ in range(20):
            text = driver.find_element(By.TAG_NAME, "body").text
            if "ProxySettings" in text:
                break
            time.sleep(0.5)
    finally:
        driver.quit()
    for name in ("ProxySettings", "WebRtcIPHandlingPolicy", "QuicAllowed"):
        assert name in text, f"{name} não aparece em chrome://policy"


# --- verificador ---------------------------------------------------------------------------

def test_egress_check_cli(tmp_path):
    report = tmp_path / "egress.json"
    result = subprocess.run(
        [sys.executable, "/app/egress_check.py", "--check-url", "http://check.egress-test.invalid/ip",
         "--url", "https://sistema.egress-test.invalid/login", "--insecure", "--json", str(report)],
        capture_output=True, text=True, timeout=600,
    )
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0, output
    assert ep.upstream_from_env().password not in output
    data = json.loads(report.read_text())
    assert data["ok"] is True
    steps = {s["passo"]: s for s in data["passos"]}
    for name in ("Python (requests)", "Chrome (Selenium)", "Chrome (SeleniumBase UC)", "Firefox", "Java (PJeOffice)"):
        assert steps[name]["status"] == "ok" and steps[name]["detalhe"] == FAKE_IP, steps.get(name)
