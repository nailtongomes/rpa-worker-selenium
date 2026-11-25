"""Testes rápidos (host) do image/app/preflight.py. O caminho completo roda na imagem."""

import json

import pytest

pytest.importorskip("requests")

import preflight  # noqa: E402


def test_everything_skipped_is_ok(tmp_path, monkeypatch, capsys):
    for name in ("A1_PFX_URL", "A1_PFX_PATH", "EGRESS_PROXY_URL", "EGRESS_PROXY_URL_FILE"):
        monkeypatch.delenv(name, raising=False)
    report = tmp_path / "p.json"
    assert preflight.main(["--browsers", "none", "--clock-url", "off", "--json", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["ok"] is True
    checks = data["verificacoes"]
    assert all(c.get("pulado") for name, c in checks.items() if name != "ambiente")
    assert set(data["versoes"]) >= {"chrome", "firefox", "selenium", "seleniumbase", "python"}
    assert data["imagem"]["arquitetura"] and "imagem" in checks["ambiente"]


@pytest.mark.parametrize("mode, env, expected", [
    ("auto", {}, False), ("auto", {"A1_PFX_URL": "https://x/a.pfx"}, True),
    ("off", {"A1_PFX_URL": "https://x/a.pfx"}, False), ("on", {}, True), ("self-test", {}, True),
])
def test_enabled(monkeypatch, mode, env, expected):
    monkeypatch.delenv("A1_PFX_URL", raising=False)
    monkeypatch.delenv("A1_PFX_PATH", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert preflight._enabled(mode, ("A1_PFX_URL", "A1_PFX_PATH")) is expected


@pytest.mark.parametrize("exit_code, report_ok, expected", [(0, True, True), (1, False, False), (1, True, False)])
def test_run_tool_trusts_exit_code(tmp_path, monkeypatch, exit_code, report_ok, expected):
    tool = tmp_path / "fake_check.py"
    tool.write_text(
        "import json, sys\n"
        "path = sys.argv[sys.argv.index('--json') + 1]\n"
        f"json.dump({{'ok': {report_ok}, 'falhas': 0, 'passos': []}}, open(path, 'w'))\n"
        f"sys.exit({exit_code})\n"
    )
    monkeypatch.setattr(preflight, "APP", tmp_path)
    data = preflight.run_tool("fake_check.py", [])
    assert data["ok"] is expected and data["exit_code"] == exit_code
    if not expected:
        assert data["falhas"] >= 1


def test_run_tool_without_report(tmp_path, monkeypatch):
    (tmp_path / "crash.py").write_text("import sys; sys.exit(3)\n")
    monkeypatch.setattr(preflight, "APP", tmp_path)
    data = preflight.run_tool("crash.py", [])
    assert data["ok"] is False and data["passos"][0]["detalhe"] == "não gerou relatório"


def test_failed_part_fails_preflight(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "run_tool", lambda script, args: {"ok": False, "falhas": 2, "passos": []})
    monkeypatch.setenv("A1_PFX_URL", "https://x/a.pfx")
    monkeypatch.delenv("EGRESS_PROXY_URL", raising=False)
    monkeypatch.delenv("EGRESS_PROXY_URL_FILE", raising=False)
    report = tmp_path / "p.json"
    assert preflight.main(["--browsers", "none", "--json", str(report)]) == 1
    data = json.loads(report.read_text())
    assert data["ok"] is False and data["falhas"] == 2


def test_attempt_ok_first_try():
    step = preflight.attempt("abre", lambda: "aberta")
    assert step["status"] == "ok"
    assert step["detalhe"].startswith("aberta [")


def test_attempt_second_try_is_warning():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("Timed out receiving message from renderer")
        return "aberta"

    step = preflight.attempt("abre", flaky)
    assert len(calls) == 2
    assert step["status"] == "aviso"
    assert "tentativa 2" in step["detalhe"] and "renderer" in step["detalhe"]


def test_attempt_fails_every_try_and_masks_urls():
    url = "https://pje.example/x?token=SEGREDO-PREFLIGHT"
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError(f"falhou em {url}")

    step = preflight.attempt("abre", broken, [url])
    assert len(calls) == preflight.BROWSER_TRIES
    assert step["status"] == "erro"
    assert "SEGREDO" not in step["detalhe"]


# --- ambiente do container -------------------------------------------------------

class _DateServer:
    """Servidor HTTP local que responde com a hora deslocada em ``offset`` segundos."""

    def __init__(self, offset: float, status: int = 204):
        import email.utils
        import http.server
        import threading
        import time

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):  # noqa: N802
                self.send_response(status)
                self.send_header("Date", email.utils.formatdate(time.time() + offset, usegmt=True))
                self.end_headers()

            def log_message(self, *args):
                pass

        # Date do servidor HTTP padrão é sobrescrito pelo nosso: send_response já o envia
        Handler.date_time_string = lambda self, timestamp=None: email.utils.formatdate(time.time() + offset,
                                                                                         usegmt=True)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def no_egress(monkeypatch):
    for name in ("EGRESS_PROXY_URL", "EGRESS_PROXY_URL_FILE", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
                 "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("offset, status", [(0, 204), (-120, 204), (300, 404)])
def test_clock_offset(no_egress, offset, status):
    server = _DateServer(offset, status)
    try:
        measured, rtt = preflight.clock_offset(server.url)
    finally:
        server.close()
    assert abs(measured + offset) <= 2 and rtt < 5


def _steps(result):
    return {s["passo"]: s for s in result["passos"]}


def test_environment_warns_about_clock(no_egress):
    server = _DateServer(-120)  # servidor 2 min atrás = relógio local 2 min adiantado
    try:
        steps = _steps(preflight.check_environment(server.url))
    finally:
        server.close()
    assert steps["relógio"]["status"] == "aviso" and "adiantado" in steps["relógio"]["detalhe"]


def test_environment_clock_unreachable_is_skipped(no_egress):
    steps = _steps(preflight.check_environment("http://127.0.0.1:9/"))
    assert steps["relógio"]["status"] == "pulado"


def test_clock_goes_through_relay_when_configured(monkeypatch):
    """Com o relay configurado, a hora é pedida ao repassador local, nunca direto."""
    import http.server
    import threading

    seen = []

    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):  # noqa: N802
            seen.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    monkeypatch.setenv("EGRESS_PROXY_URL", "socks5://u:p@relay.invalid:1080")
    monkeypatch.setenv("EGRESS_LOCAL_PORT", str(proxy.server_address[1]))
    try:
        preflight.clock_offset("http://hora.example.com/")
    finally:
        proxy.shutdown()
    assert seen == ["http://hora.example.com/"]


def test_environment_limits_from_cgroup(tmp_path, monkeypatch):
    import resource_usage

    cg = tmp_path / "cg"
    cg.mkdir()
    (cg / "memory.current").write_text(str(300 * 1024 * 1024))
    (cg / "memory.stat").write_text("inactive_file 0\n")
    (cg / "cpu.stat").write_text("usage_usec 1\n")
    (cg / "memory.max").write_text(str(1024 * 1024 * 1024))
    (cg / "cpu.max").write_text("50000 100000")
    monkeypatch.setattr(resource_usage, "CGROUP_ROOT", cg)
    monkeypatch.setenv("USE_PJEOFFICE", "1")

    real_statvfs = preflight.os.statvfs

    class SmallShm:
        f_blocks, f_frsize, f_bavail = 16384, 4096, 16384  # 64 MB

    monkeypatch.setattr(preflight.os, "statvfs",
                        lambda path: SmallShm() if path == "/dev/shm" else real_statvfs(path))
    result = preflight.check_environment("off")
    steps = _steps(result)
    assert result["ok"] is True and result["avisos"] >= 3  # só avisos: nunca reprova o worker
    assert steps["/dev/shm"]["status"] == "aviso" and "--shm-size" in steps["/dev/shm"]["detalhe"]
    assert steps["memória"]["status"] == "aviso" and "PJeOffice" in steps["memória"]["detalhe"]
    assert steps["CPU"]["status"] == "aviso" and "0.5" in steps["CPU"]["detalhe"]
    assert steps["relógio"]["status"] == "pulado"
    assert result["limites"]["memoria_mb"] == 1024



@pytest.mark.parametrize("env_xmx, launcher_xmx, expected, origin", [
    ("", "-Xmx2048m", 2048 * 1024 ** 2, "launcher do PJeOffice"),
    ("512m", "-Xmx2048m", 512 * 1024 ** 2, "PJEOFFICE_JAVA_XMX"),
    ("1G", "", 1024 ** 3, "PJEOFFICE_JAVA_XMX"),
    ("", "", None, ""),
])
def test_pjeoffice_xmx(tmp_path, monkeypatch, env_xmx, launcher_xmx, expected, origin):
    launcher = tmp_path / "pjeoffice-pro.sh"
    launcher.write_text(f"nohup ./jre/bin/java -Xms20m {launcher_xmx} -jar pjeoffice-pro.jar &\n")
    monkeypatch.setenv("PJEOFFICE_EXECUTABLE", str(launcher))
    monkeypatch.setenv("PJEOFFICE_JAVA_XMX", env_xmx)
    assert preflight.pjeoffice_xmx() == (expected, origin)


@pytest.mark.parametrize("env_xmx, status", [("", "aviso"), ("512m", "ok")])
def test_environment_warns_when_pjeoffice_heap_can_take_the_container(tmp_path, monkeypatch, env_xmx, status):
    import resource_usage

    cg = tmp_path / "cg"
    cg.mkdir()
    (cg / "memory.current").write_text(str(300 * 1024 * 1024))
    (cg / "memory.stat").write_text("inactive_file 0\n")
    (cg / "cpu.stat").write_text("usage_usec 1\n")
    (cg / "memory.max").write_text(str(2048 * 1024 * 1024))
    (cg / "cpu.max").write_text("max 100000")
    monkeypatch.setattr(resource_usage, "CGROUP_ROOT", cg)
    launcher = tmp_path / "pjeoffice-pro.sh"
    launcher.write_text("nohup ./jre/bin/java -Xmx2048m -jar pjeoffice-pro.jar &\n")
    monkeypatch.setenv("PJEOFFICE_EXECUTABLE", str(launcher))
    monkeypatch.setenv("PJEOFFICE_JAVA_XMX", env_xmx)
    monkeypatch.setenv("USE_PJEOFFICE", "1")
    result = preflight.check_environment("off")
    step = _steps(result)["Java do PJeOffice"]
    assert result["ok"] is True and step["status"] == status
    if status == "aviso":
        assert "PJEOFFICE_JAVA_XMX=512m" in step["detalhe"] and "2,0 GB" in step["detalhe"]
