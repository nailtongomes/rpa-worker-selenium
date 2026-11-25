"""Testes do image/app/script_downloader.py (download de SCRIPT_URL e HELPER_URLS)."""

import hashlib
import http.server
import threading

import pytest

import script_downloader as sd


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://example.com/script.py", "script.py"),
        ("https://example.com/path/to/my_script.py", "my_script.py"),
        ("https://raw.githubusercontent.com/user/repo/main/test.py", "test.py"),
        ("https://example.com/a/worker.py?token=abc", "worker.py"),
    ],
)
def test_filename_from_url(url, expected):
    assert sd.get_filename_from_url(url) == expected


def test_filename_fallback_is_stable_hash():
    name = sd.get_filename_from_url("https://example.com/download?id=42")
    assert name.startswith("script_") and name.endswith(".py")
    assert name == sd.get_filename_from_url("https://example.com/download?id=42")


@pytest.mark.parametrize("value", ["", None, " , "])
def test_helper_scripts_empty_input(tmp_path, value):
    assert sd.download_helper_scripts(value, str(tmp_path)) == []


@pytest.fixture()
def http_server(tmp_path):
    """Servidor HTTP local servindo tmp_path/www (sem internet)."""
    www = tmp_path / "www"
    www.mkdir()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(www), **kwargs)

        def log_message(self, *args):  # silencia o log
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield www, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def no_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_download_main_script(http_server, tmp_path, no_proxy):
    www, base = http_server
    (www / "job.py").write_text("print('ok')\n")
    dest = tmp_path / "out"

    path = sd.download_main_script(f"{base}/job.py", temp_dir=str(dest))

    assert path is not None
    assert (dest / "job.py").read_text() == "print('ok')\n"


def test_download_main_script_404_returns_none(http_server, tmp_path, no_proxy):
    _, base = http_server
    assert sd.download_main_script(f"{base}/missing.py", temp_dir=str(tmp_path)) is None


def test_download_helper_scripts(http_server, tmp_path, no_proxy):
    www, base = http_server
    (www / "helper_a.py").write_text("A = 1\n")
    (www / "helper_b.py").write_text("B = 2\n")
    scripts_dir = tmp_path / "src"

    downloaded = sd.download_helper_scripts(f"{base}/helper_a.py, {base}/helper_b.py", str(scripts_dir))

    assert len(downloaded) == 2
    assert (scripts_dir / "helper_a.py").read_text() == "A = 1\n"
    assert (scripts_dir / "helper_b.py").read_text() == "B = 2\n"


# --- URLs mascaradas nos logs ------------------------------------------------------------

@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://example.com/a/job.py", "https://example.com/a/job.py"),
        ("https://raw.githubusercontent.com/o/r/main/job.py?token=GHSAT0AAA",
         "https://raw.githubusercontent.com/o/r/main/job.py?token=***"),
        ("https://ghp_abc123@raw.githubusercontent.com/o/r/main/job.py",
         "https://***@raw.githubusercontent.com/o/r/main/job.py"),
        ("https://user:s3nh4@host:8443/x.py?a=1&b=2", "https://***@host:8443/x.py?a=***&b=***"),
        ("https://bucket.s3.amazonaws.com/job.py?X-Amz-Signature=deadbeef&X-Amz-Credential=AKIA",
         "https://bucket.s3.amazonaws.com/job.py?X-Amz-Signature=***&X-Amz-Credential=***"),
        ("https://acct.blob.core.windows.net/c/job.py?sv=2022&sig=abc%2Bdef", "https://acct.blob.core.windows.net/c/job.py?sv=***&sig=***"),
        ("https://example.com/job.py?onlyflag", "https://example.com/job.py?***"),
        ("https://example.com/job.py#frag-token", "https://example.com/job.py#***"),
        ("", ""),
    ],
)
def test_mask_url(url, expected):
    assert sd.mask_url(url) == expected


def test_mask_text_masks_urls_inside_error_messages():
    url = "https://example.com/job.py?token=SEGREDO"
    msg = f"404 Client Error: Not Found for url: {url}"
    assert sd.mask_text(msg, url) == "404 Client Error: Not Found for url: https://example.com/job.py?token=***"
    assert "SEGREDO" not in sd.mask_text(f"falhou ({url})")


def test_mask_cli_reads_url_from_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("https://u:p@h/x.py?t=SEGREDO\n"))
    assert sd.main(["--mask"]) == 0
    assert capsys.readouterr().out.strip() == "https://***@h/x.py?t=***"


def test_downloader_never_logs_tokens(tmp_path, monkeypatch, capsys):
    """Download com sucesso, helper com 404 e erro de conexão: nenhum token na saída."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/ok.py"):
                body = b"print('ok')\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://user:SEGREDO-1@127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.setenv("SCRIPT_URL", f"{base}/ok.py?token=SEGREDO-2")
        monkeypatch.setenv("HELPER_URLS", f"{base}/missing.py?sig=SEGREDO-3,http://127.0.0.1:9/x.py?k=SEGREDO-4")
        monkeypatch.setenv("SCRIPTS_DIR", str(tmp_path / "src"))
        monkeypatch.setattr(sd, "download_main_script", lambda url: sd.download_file(url, tmp_path / "ok.py") and "ok")
        assert sd.main([]) == 0
    finally:
        server.shutdown()
    out = capsys.readouterr().out
    assert "SEGREDO" not in out, out
    assert "token=***" in out and "404" in out


def test_mask_text_masks_query_repeated_without_host():
    url = "http://127.0.0.1:9/x.py?k=SEGREDO-4"
    msg = "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: /x.py?k=SEGREDO-4"
    assert "SEGREDO" not in sd.mask_text(msg, url)



# --- SCRIPT_SHA256 -----------------------------------------------------------------

def _run_main_with_hash(http_server, tmp_path, monkeypatch, expected):
    www, base = http_server
    (www / "job.py").write_text("print('oi')\n")
    monkeypatch.setenv("SCRIPT_URL", f"{base}/job.py")
    monkeypatch.delenv("HELPER_URLS", raising=False)
    if expected is None:
        monkeypatch.delenv("SCRIPT_SHA256", raising=False)
    else:
        monkeypatch.setenv("SCRIPT_SHA256", expected)
    target = tmp_path / "out"
    monkeypatch.setattr(sd, "download_main_script", lambda url: sd.download_file(url, target) and str(target))
    return sd.main([]), target


def test_script_sha256_ok(http_server, tmp_path, monkeypatch, capsys, no_proxy):
    good = hashlib.sha256(b"print('oi')\n").hexdigest()
    for expected in (good, good.upper(), f"sha256:{good}", None):
        rc, target = _run_main_with_hash(http_server, tmp_path, monkeypatch, expected)
        assert rc == 0 and target.exists()
    assert "SHA-256 OK" in capsys.readouterr().out


@pytest.mark.parametrize("expected", ["0" * 64, "abc"])
def test_script_sha256_mismatch_deletes_and_exits_3(http_server, tmp_path, monkeypatch, capsys, no_proxy, expected):
    rc, target = _run_main_with_hash(http_server, tmp_path, monkeypatch, expected)
    assert rc == sd.EXIT_HASH_MISMATCH == 3
    assert not target.exists()  # nunca roda um script trocado
    assert "ERROR" in capsys.readouterr().out
