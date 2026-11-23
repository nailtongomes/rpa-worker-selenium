"""Testes do image/app/script_downloader.py (download de SCRIPT_URL e HELPER_URLS)."""

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
