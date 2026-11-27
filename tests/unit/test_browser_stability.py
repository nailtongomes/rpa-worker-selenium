"""Testes rápidos (host) do image/app/browser_stability.py: classificação das falhas, servidor de falhas
controladas, cgroup, /proc e argumentos. Os cenários com browser rodam na imagem (scripts/test-image.sh)."""

import os
import socket
import urllib.error
import urllib.request

import pytest

import browser_stability as bs


class FakeTimeoutException(Exception):
    pass


FakeTimeoutException.__name__ = "TimeoutException"


def _refused():
    try:
        raise ConnectionRefusedError(111, "Connection refused")
    except ConnectionRefusedError as inner:
        try:
            raise RuntimeError("HTTPConnectionPool(host='localhost', port=46449): Max retries exceeded with url: "
                               "/session/x/url (Caused by NewConnectionError(\"Failed to establish a new "
                               "connection: [Errno 111] Connection refused\"))") from inner
        except RuntimeError as exc:
            return exc


@pytest.mark.parametrize("driver_alive, expected", [
    (False, bs.CHROMEDRIVER_EXITED),
    (True, bs.WEBDRIVER_CONNECTION_REFUSED),
    (None, bs.WEBDRIVER_CONNECTION_REFUSED),
])
def test_connection_refused_on_the_driver_port(driver_alive, expected):
    """O erro da produção: quem decide entre driver morto e porta recusada é o estado do processo."""
    assert bs.classify(_refused(), driver_alive=driver_alive) == expected


@pytest.mark.parametrize("message, chrome_alive, expected", [
    ("unknown error: session deleted because of page crash", True, bs.CHROME_CRASH),
    ("tab crashed", None, bs.CHROME_CRASH),
    ("session not created: cannot connect to chrome at 127.0.0.1:9222 from unknown error: "
     "unable to discover open pages", True, bs.SESSION_LOST),
    ("chrome not reachable", False, bs.CHROME_CRASH),
    ("invalid session id", True, bs.SESSION_LOST),
    ("no such window: target window already closed", True, bs.SESSION_LOST),
    ("unknown error: net::ERR_NAME_NOT_RESOLVED", None, bs.DNS_ERROR),
    ("unknown error: net::ERR_CERT_AUTHORITY_INVALID", None, bs.TLS_ERROR),
    ("unknown error: net::ERR_CONNECTION_RESET", None, bs.TCP_CONNECTION_ERROR),
    ("OSError: [Errno 12] Cannot allocate memory", None, bs.RESOURCE_EXHAUSTED),
    ("algo totalmente diferente", None, bs.UNKNOWN),
])
def test_classify_messages(message, chrome_alive, expected):
    assert bs.classify(RuntimeError(message), driver_alive=True, chrome_alive=chrome_alive) == expected


def test_timeout_and_oom():
    assert bs.classify(FakeTimeoutException("timeout: Timed out receiving message from renderer: 4.000")) \
        == bs.NAVIGATION_TIMEOUT
    # OOM do cgroup vence qualquer outra leitura: o processo morreu porque o kernel matou
    assert bs.classify(_refused(), driver_alive=False, oom_delta=1) == bs.RESOURCE_EXHAUSTED


@pytest.mark.parametrize("code, expected", [
    ("ERR_NAME_NOT_RESOLVED", bs.DNS_ERROR),
    ("ERR_CONNECTION_REFUSED", bs.TCP_CONNECTION_ERROR),
    ("ERR_EMPTY_RESPONSE", bs.TCP_CONNECTION_ERROR),
    ("ERR_CONNECTION_TIMED_OUT", bs.NAVIGATION_TIMEOUT),
    ("ERR_SSL_PROTOCOL_ERROR", bs.TLS_ERROR),
    ("ERR_CERT_DATE_INVALID", bs.TLS_ERROR),
    ("ERR_TOO_MANY_REDIRECTS", bs.HTTP_ERROR),
    ("ERR_SOMETHING_NEW", bs.TCP_CONNECTION_ERROR),
    ("", bs.UNKNOWN),
])
def test_chrome_error_pages(code, expected):
    assert bs.classify_net_error(code) == expected


def test_browser_and_network_classes_do_not_overlap():
    assert not bs.BROWSER_CLASSES & bs.NETWORK_CLASSES
    assert {bs.CHROMEDRIVER_EXITED, bs.WEBDRIVER_CONNECTION_REFUSED, bs.SESSION_LOST, bs.CHROME_CRASH,
            bs.RESOURCE_EXHAUSTED} <= bs.BROWSER_CLASSES


@pytest.mark.parametrize("url, expected", [
    ("https://user:senha@example.com/a/b?token=x", "https://example.com/a/b?…"),
    ("http://127.0.0.1:8080/page/1", "http://127.0.0.1:8080/page/1"),
])
def test_mask_url_hides_credentials_and_query(url, expected):
    assert bs.mask_url(url) == expected


def test_external_urls_default_and_custom(monkeypatch):
    default = bs.parse_external("")
    assert [e.url for e in default] == [x.split("|")[0] for x in bs.EXTERNAL_DEFAULT]
    assert default[-1].url_suffix == "/get" and default[0].text == "Web form"
    assert not any("example.com" in e.url or "example.org" in e.url for e in default)
    custom = bs.parse_external("https://a.example/|Olá, https://b.example/x|Texto|/y")
    assert [(e.url, e.text, e.url_suffix) for e in custom] == [
        ("https://a.example/", "Olá", ""), ("https://b.example/x", "Texto", "/y")]
    with pytest.raises(ValueError):
        bs.parse_external("ftp://a.example/")


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, resp.geturl(), resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, url, err.read().decode()


def test_fault_server_routes():
    with bs.FaultServer() as srv:
        status, _, body = _get(srv.url("/page/7"))
        assert status == 200 and "<title>Página 7</title>" in body and "estavel-7" in body
        status, final, body = _get(srv.url("/redirect/3"))
        assert status == 200 and final.endswith("/page/destino")
        assert _get(srv.url("/status/503"))[0] == 503
        assert _get(srv.url("/status/500"))[0] == 500
        status, _, body = _get(srv.url("/captcha"))
        assert "com/recaptcha/api.js" in body  # é isso que o SeleniumBase (UC) procura
        assert "id=\"campo\"" in _get(srv.url("/form"))[2]
        assert "estavel-lenta-50" in _get(srv.url("/slow/50"))[2]
        with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
            urllib.request.urlopen(srv.url("/drop"), timeout=5).read()
        # /hang segura até o servidor fechar; aqui basta não responder dentro do timeout
        with pytest.raises((socket.timeout, TimeoutError, urllib.error.URLError)):
            urllib.request.urlopen(srv.url("/hang"), timeout=0.5).read()


def test_cgroup_v2_snapshot(tmp_path):
    (tmp_path / "memory.current").write_text("104857600\n")
    (tmp_path / "memory.peak").write_text("209715200\n")
    (tmp_path / "memory.max").write_text("2147483648\n")
    (tmp_path / "memory.events").write_text("low 0\nhigh 0\nmax 3\noom 1\noom_kill 1\n")
    (tmp_path / "pids.current").write_text("57\n")
    (tmp_path / "pids.max").write_text("max\n")
    (tmp_path / "cpu.max").write_text("100000 100000\n")
    (tmp_path / "cpu.stat").write_text("usage_usec 10\nthrottled_usec 99\n")
    snap = bs.cgroup_snapshot(tmp_path)
    assert snap["memoria_mb"] == 100.0 and snap["memoria_pico_mb"] == 200.0
    assert snap["memoria_limite_mb"] == 2048.0 and snap["pids"] == 57 and snap["pids_max"] == "max"
    assert snap["memory_events"]["oom_kill"] == 1 and bs.oom_kills(snap) == 1
    assert snap["cpu_throttled_usec"] == 99


def test_cgroup_v1_and_missing(tmp_path):
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "memory.usage_in_bytes").write_text("1048576\n")
    (mem / "memory.max_usage_in_bytes").write_text("2097152\n")
    (mem / "memory.limit_in_bytes").write_text("9223372036854771712\n")
    (mem / "memory.oom_control").write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 2\n")
    snap = bs.cgroup_snapshot(tmp_path)
    assert snap["versao"] == 1 and snap["memoria_pico_mb"] == 2.0 and snap["memoria_limite_mb"] is None
    assert bs.oom_kills(snap) == 2
    assert bs.cgroup_snapshot(tmp_path / "nada") == {"versao": None}


def _fake_proc(root, pid, name, state, ppid, exe=None, fds=()):
    d = root / str(pid)
    (d / "fd").mkdir(parents=True)
    (d / "stat").write_text(f"{pid} ({name}) {state} {ppid} 1 1 0 -1\n")
    (d / "statm").write_text("100 256 0 0 0 0 0\n")
    if exe:
        os.symlink(exe, d / "exe")
    for i, target in enumerate(fds):
        os.symlink(target, d / "fd" / str(i))


def test_processes_zombies_and_listener(tmp_path):
    _fake_proc(tmp_path, 1, "docker-init", "S", 0, "/sbin/docker-init")
    _fake_proc(tmp_path, 7, "python", "S", 1, "/usr/bin/python3")
    _fake_proc(tmp_path, 40, "uc_driver", "Z", 7)
    _fake_proc(tmp_path, 41, "uc_driver", "S", 7, "/opt/venv/x/uc_driver", fds=["socket:[555]", "pipe:[1]"])
    _fake_proc(tmp_path, 50, "chrome", "S", 1, "/opt/chrome/chrome")
    net = tmp_path / "net"
    net.mkdir()
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    # 0100007F:B5B1 = 127.0.0.1:46513, estado 0A (LISTEN), inode 555
    (net / "tcp").write_text(header + "   0: 0100007F:B5B1 00000000:0000 0A 00000000:00000000 00:00000000 "
                                      "00000000     0        0 555 1 0000000000000000 100 0 0 10 0\n")
    procs = bs.processes(tmp_path)
    summary = bs.process_summary(procs)
    assert summary["zombies"] == 1 and summary["zombies_lista"] == ["40:uc_driver(pai 7)"]
    assert summary["pid1"] == "docker-init" and summary["chrome"]["processos"] == 1
    assert {p.pid for p in procs if bs.is_browser_proc(p)} == {40, 41, 50}
    assert bs.listener_pid(46513, tmp_path) == 41
    assert bs.listener_pid(1234, tmp_path) is None


def test_args(monkeypatch):
    args = bs.parse_args(["--scenarios", "sequencial,uc_especial", "--external", "--label", "base"])
    assert args.scenarios == ["sequencial", "uc_especial", "externos"] and args.mode == "uc-headless"
    assert "uccft-headless" in args.modes and "uccft-headful" in args.modes
    for bad in (["--scenarios", "nada"], ["--label", "a/b"], ["--modes", "firefox"]):
        with pytest.raises(SystemExit):
            bs.parse_args(bad)


def test_x_display_ready(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":987654")
    assert bs.x_display_ready() is False  # DISPLAY definido sem servidor X (como na imagem sem Xvfb)
    monkeypatch.delenv("DISPLAY")
    assert bs.x_display_ready() is False


def test_scenario_result_stats():
    res = bs.ScenarioResult("sequencial", "uc-headless", nav_times=[0.1, 0.2, 0.3, 0.4, 2.0])
    d = res.as_dict()
    assert d["navegacoes"] == {"n": 5, "mediana_s": 0.3, "p95_s": 2.0, "max_s": 2.0}
    assert d["ok"] is True and d["pulado"] is None
