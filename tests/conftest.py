"""
Fixtures compartilhadas pelos testes.

Layout:
    tests/unit/   -> rodam no host, sem Docker, em segundos
    tests/image/  -> rodam DENTRO da imagem (browsers, display, PJeOffice)
"""

import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "image" / "app"          # copiado para /app na imagem
DOCKERFILE = REPO_ROOT / "Dockerfile.trixie"
ENTRYPOINT = APP_DIR / "entrypoint.sh"


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def app_dir() -> pathlib.Path:
    return APP_DIR


@pytest.fixture(scope="session")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def entrypoint_text() -> str:
    return ENTRYPOINT.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    """smoke_test.py cria CACHE_DIR no import; nunca deixe isso cair em /data."""
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
