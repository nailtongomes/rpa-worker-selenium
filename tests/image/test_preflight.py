#!/usr/bin/env python3
"""
/app/preflight.py dentro da imagem: browsers + A1 (ICP de teste) num JSON só.

Roda no cenário do certificado A1 do portão (Xvfb + OpenBox).
"""

import json
import os
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.trixie]


def _preflight(tmp_path, *args, env=None):
    report = tmp_path / "preflight.json"
    result = subprocess.run([sys.executable, "/app/preflight.py", *args, "--json", str(report)],
                            capture_output=True, text=True, timeout=900, env={**os.environ, **(env or {})})
    print(result.stdout + result.stderr)
    return result, json.loads(report.read_text())


def test_preflight_all_ok_with_a1_self_test(tmp_path):
    result, data = _preflight(tmp_path, "--a1", "self-test")
    assert result.returncode == 0
    assert data["ok"] is True and data["falhas"] == 0
    checks = data["verificacoes"]
    assert {s["passo"] for s in checks["browsers"]["passos"]} == {
        "Chrome (Selenium) abre página local", "Chrome (SeleniumBase UC) abre página local", "Firefox abre página local"}
    assert all(s["status"] == "ok" for s in checks["browsers"]["passos"])
    assert checks["a1"]["ok"] is True and not checks["a1"].get("pulado")
    assert any("apresenta o certificado" in s["passo"] for s in checks["a1"]["passos"])
    assert checks["egress"].get("pulado") is True  # sem EGRESS_PROXY_URL
    assert data["versoes"]["chrome"] and data["versoes"]["seleniumbase"]


def test_preflight_fails_when_a1_is_broken(tmp_path):
    result, data = _preflight(tmp_path, "--browsers", "none",
                              env={"A1_PFX_PATH": str(tmp_path / "nao-existe.pfx"), "A1_PFX_PASSWORD": "x"})
    assert result.returncode == 1
    assert data["ok"] is False and data["verificacoes"]["a1"]["ok"] is False
    assert data["verificacoes"]["browsers"].get("pulado") is True


def test_preflight_masks_urls(tmp_path):
    """URLs com token passadas em --url não vão para a saída nem para o JSON."""
    result, data = _preflight(tmp_path, "--browsers", "none", "--a1", "off",
                              "--url", "http://127.0.0.1:9/x?token=SEGREDO-PREFLIGHT")
    assert "SEGREDO-PREFLIGHT" not in result.stdout + result.stderr
    assert "SEGREDO-PREFLIGHT" not in json.dumps(data)
