"""Testes rápidos (host) do image/app/preflight.py. O caminho completo roda na imagem."""

import json

import pytest

pytest.importorskip("requests")

import preflight  # noqa: E402


def test_everything_skipped_is_ok(tmp_path, monkeypatch, capsys):
    for name in ("A1_PFX_URL", "A1_PFX_PATH", "EGRESS_PROXY_URL", "EGRESS_PROXY_URL_FILE"):
        monkeypatch.delenv(name, raising=False)
    report = tmp_path / "p.json"
    assert preflight.main(["--browsers", "none", "--json", str(report)]) == 0
    data = json.loads(report.read_text())
    assert data["ok"] is True
    assert all(c.get("pulado") for c in data["verificacoes"].values())
    assert set(data["versoes"]) >= {"chrome", "firefox", "selenium", "seleniumbase", "python"}


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
