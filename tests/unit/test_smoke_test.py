"""Testes de funções puras do image/app/smoke_test.py (fallback quando SCRIPT_URL não é definido)."""

import importlib

import pytest


@pytest.fixture()
def smoke_test(monkeypatch):
    monkeypatch.delenv("TARGET_URL", raising=False)
    import smoke_test as module

    return importlib.reload(module)


@pytest.mark.parametrize(
    "html, expected",
    [
        ("<html><head><title>Test Title</title></head></html>", "Test Title"),
        ("<html><body>No title</body></html>", "Desconhecido"),
        ("<html><head><title></title></head></html>", "Desconhecido"),
        ("<html><head><title>  Spaced  Title  </title></head></html>", "Spaced Title"),
        ("<html><head><title>Multi\nLine\nTitle</title></head></html>", "Multi Line Title"),
        ("<html><head><TITLE>Uppercase Title</TITLE></head></html>", "Uppercase Title"),
    ],
)
def test_extract_title(smoke_test, html, expected):
    assert smoke_test.extract_title_from_html(html) == expected


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("TARGET_URL", "https://example.com/test")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "custom"))
    import smoke_test as module

    module = importlib.reload(module)

    assert module.TARGET_URL == "https://example.com/test"
    assert module.CACHE_DIR == tmp_path / "custom"
    assert module.CACHE_DIR.is_dir()
