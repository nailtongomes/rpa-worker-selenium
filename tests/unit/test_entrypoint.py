"""
Testes estáticos do image/app/entrypoint.sh.

Não executam o entrypoint (ele cria diretórios em /app e /root); a execução
real é validada pelos testes de imagem.
"""

import re
import shutil
import subprocess

import pytest

from conftest import ENTRYPOINT


def _function_body(text: str, name: str) -> str:
    """Retorna o corpo de uma função bash `name() { ... }` (até o '}' de coluna 0)."""
    match = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", text, re.MULTILINE | re.DOTALL)
    assert match, f"função {name}() não encontrada no entrypoint.sh"
    return match.group(1)


def test_entrypoint_is_executable():
    assert ENTRYPOINT.stat().st_mode & 0o111, "entrypoint.sh precisa ser executável (git update-index --chmod=+x)"


def test_entrypoint_bash_syntax():
    result = subprocess.run(["bash", "-n", str(ENTRYPOINT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck não instalado")
def test_entrypoint_shellcheck_errors():
    """Só erros (severity=error) quebram; warnings ficam para a Fase 2."""
    result = subprocess.run(
        ["shellcheck", "--severity=error", str(ENTRYPOINT)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "var, default",
    [
        ("WORKER_MODE", "pull"),
        ("WORKER_LOOP", "0"),
        ("WORKER_TIMEOUT", "3600"),
        ("WORKER_RESTART_DELAY", "120"),
        ("TASK_SERVER_PORT", "8080"),
        ("DISPLAY", ":99"),
        ("PJEOFFICE_EXECUTABLE", "/opt/pjeoffice/pjeoffice-pro.sh"),
    ],
)
def test_entrypoint_env_defaults(entrypoint_text, var, default):
    """Os defaults fazem parte do contrato da imagem: mudar exige decisão explícita."""
    assert f"export {var}=${{{var}:-{default}}}" in entrypoint_text


def test_main_starts_services_in_dependency_order(entrypoint_text):
    main = _function_body(entrypoint_text, "main")
    order = [
        "setup_directories",
        "download_chrome_profile",
        "start_xvfb",
        "start_openbox",
        "start_pjeoffice",
        "start_vnc",
        "start_novnc",
        "start_screen_recording",
    ]
    positions = [main.find(step) for step in order]
    assert all(p >= 0 for p in positions), dict(zip(order, positions))
    assert positions == sorted(positions), f"ordem esperada: {order}"


def test_standby_mode_is_checked_before_loop_mode(entrypoint_text):
    main = _function_body(entrypoint_text, "main")
    assert 'WORKER_MODE}" = "standby"' in main
    assert main.find("WORKER_MODE") < main.find("WORKER_LOOP")
    assert "/app/task_server.py" in main


@pytest.mark.parametrize("service", ["start_openbox", "start_vnc", "start_screen_recording"])
def test_display_services_require_xvfb(entrypoint_text, service):
    assert 'USE_XVFB}" != "1"' in _function_body(entrypoint_text, service)


def test_novnc_requires_vnc(entrypoint_text):
    assert 'USE_VNC}" != "1"' in _function_body(entrypoint_text, "start_novnc")


def test_sigterm_handler_stops_every_background_service(entrypoint_text):
    handler = _function_body(entrypoint_text, "handle_sigterm")
    for pid in ["NOVNC_PID", "VNC_PID", "FFMPEG_PID", "XVFB_PID", "OPENBOX_PID", "PJEOFFICE_PID"]:
        assert f'kill -TERM "${pid}"' in handler, f"{pid} não é finalizado no SIGTERM"
    assert "trap handle_sigterm SIGTERM SIGINT" in entrypoint_text


def test_entrypoint_references_only_files_shipped_in_image(entrypoint_text, app_dir):
    """Todo /app/<arquivo> citado no entrypoint precisa existir em image/app/."""
    referenced = set(re.findall(r"/app/([A-Za-z0-9_]+\.(?:py|sh))", entrypoint_text))
    assert referenced, "nenhuma referência a /app/*.py encontrada"
    missing = sorted(f for f in referenced if not (app_dir / f).is_file())
    assert not missing, f"arquivos referenciados mas ausentes em image/app/: {missing}"
