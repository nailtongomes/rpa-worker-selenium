"""Fixtures dos testes que rodam dentro da imagem."""

import http.server
import os
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def local_site():
    """Servidor HTTP local servindo tests/image/fixtures (testes offline)."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(FIXTURES), **kwargs)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="session")
def artifacts_dir():
    """Diretório para screenshots (TEST_ARTIFACTS_DIR, padrão /tmp/test-artifacts)."""
    path = Path(os.getenv("TEST_ARTIFACTS_DIR", "/tmp/test-artifacts"))
    path.mkdir(parents=True, exist_ok=True)
    return path
