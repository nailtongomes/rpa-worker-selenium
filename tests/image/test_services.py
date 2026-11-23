#!/usr/bin/env python3
"""
Serviços iniciados pelo entrypoint (roda DENTRO da imagem).

Cada teste só roda quando o serviço foi pedido via variável de ambiente
(USE_XVFB, USE_OPENBOX, USE_PJEOFFICE, USE_VNC, USE_NOVNC, USE_SCREEN_RECORDING);
caso contrário é pulado. scripts/test-image.sh liga todos os da imagem publicada.
"""

import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.trixie]

DISPLAY = os.getenv("DISPLAY", ":99")


def _enabled(var: str) -> bool:
    return os.getenv(var, "0") == "1"


def _needs(var: str):
    return pytest.mark.skipif(not _enabled(var), reason=f"{var}!=1")


def _wait_process(pattern: str, timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0:
            return True
        time.sleep(0.5)
    return False


def _wait_port(port: int, timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


@_needs("USE_XVFB")
def test_xvfb_display_accessible():
    assert _wait_process("Xvfb"), "Xvfb não está rodando"
    result = subprocess.run(["xdpyinfo", "-display", DISPLAY], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    width, height = os.getenv("SCREEN_WIDTH", "1600"), os.getenv("SCREEN_HEIGHT", "900")
    assert f"{width}x{height}" in result.stdout, "resolução do Xvfb diferente de SCREEN_WIDTHxSCREEN_HEIGHT"


@_needs("USE_OPENBOX")
def test_openbox_running():
    assert _wait_process("openbox"), "OpenBox não está rodando"


@_needs("USE_PJEOFFICE")
def test_pjeoffice_running():
    assert _wait_process("pjeoffice", timeout=30), "PJeOffice não está rodando"


@_needs("USE_VNC")
def test_vnc_listening():
    port = int(os.getenv("VNC_PORT", "5900"))
    assert _wait_process("x11vnc"), "x11vnc não está rodando"
    assert _wait_port(port), f"VNC não escuta na porta {port}"


@_needs("USE_NOVNC")
def test_novnc_serves_web_client():
    port = int(os.getenv("NOVNC_PORT", "6080"))
    assert _wait_port(port), f"noVNC não escuta na porta {port}"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/vnc.html", timeout=10) as resp:
        assert resp.status == 200
        assert b"noVNC" in resp.read()


@_needs("USE_SCREEN_RECORDING")
def test_screen_recording_writes_file():
    assert _wait_process("ffmpeg"), "FFmpeg não está gravando"
    recordings = Path(os.getenv("RECORDING_DIR", "/app/recordings"))
    deadline = time.time() + 20
    while time.time() < deadline:
        files = [f for f in recordings.glob("*.mp4") if f.stat().st_size > 0]
        if files:
            return
        time.sleep(1)
    pytest.fail(f"nenhum .mp4 com conteúdo em {recordings}")
