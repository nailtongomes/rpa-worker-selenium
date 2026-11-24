"""
Testes estáticos do image/app/entrypoint.sh.

Não executam o entrypoint (ele cria diretórios em /app e /root); a execução
real é validada pelos testes de imagem.
"""

import pathlib
import re
import shutil
import subprocess
import time

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
        ("EGRESS_REQUIRED", "1"),
        ("EGRESS_LOCAL_PORT", "3128"),
        ("RESOURCE_SUMMARY", "1"),
        ("RESOURCE_SAMPLE_SECS", "1"),
        ("RESOURCE_LOG", "/app/logs/resources.jsonl"),
        ("RESOURCE_PROCESSES", "1"),
        ("WORKER_KILL_AFTER", "30"),
        ("WORKER_CLEANUP", "1"),
        ("PREFLIGHT_ON_START", "0"),
        ("PREFLIGHT_ARGS", ""),
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


def test_egress_relay_is_set_up_before_any_download(entrypoint_text):
    """Com relay ligado, nenhum download (profile do Chrome, SCRIPT_URL) pode sair direto."""
    main = _function_body(entrypoint_text, "main")
    assert main.index("setup_egress_proxy") < main.index("download_chrome_profile")
    assert main.index("setup_egress_proxy") < main.index("execute_with_loop")


def test_egress_relay_is_off_without_url(entrypoint_text):
    body = _function_body(entrypoint_text, "setup_egress_proxy")
    assert 'if [ -z "${EGRESS_PROXY_URL:-}" ] && [ -z "${EGRESS_PROXY_URL_FILE:-}" ]; then' in body
    assert "egress_proxy.py unconfigure" in body


def test_egress_failure_stops_container_when_required(entrypoint_text):
    body = _function_body(entrypoint_text, "egress_fail")
    assert 'if [ "${EGRESS_REQUIRED}" = "1" ]; then' in body and "exit 1" in body


# --- quick wins: URLs mascaradas, loop sem duplicação, relay antes de cada iteração --------

def test_download_functions_are_defined_once(entrypoint_text):
    """O loop usa as mesmas funções da execução única (antes havia uma cópia num heredoc)."""
    assert entrypoint_text.count("download_script_with_retry() {") == 1
    assert "SCRIPT_EOF" not in entrypoint_text
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert "export -f" in loop and "download_and_execute" in loop
    assert "bash -c 'trap : TERM; download_and_execute'" in loop


def test_urls_are_masked_in_logs(entrypoint_text):
    """Nenhum echo imprime SCRIPT_URL/url crus (tokens em query ou user:senha)."""
    for line in entrypoint_text.splitlines():
        if line.strip().startswith("echo"):
            unmasked = re.sub(r'\$\(mask_url "[^"]*"\)', "", line)
            assert not re.search(r'\$\{?(SCRIPT_URL|url|HELPER_URLS)\b', unmasked), line
    assert "mask_url" in _function_body(entrypoint_text, "download_script_with_retry")
    assert "mask_url" in _function_body(entrypoint_text, "download_and_execute")


def test_mask_url_reads_from_stdin(entrypoint_text):
    body = _function_body(entrypoint_text, "mask_url")
    assert "--mask" in body and "printf" in body  # URL pelo stdin, nunca no argv (ps)


def test_loop_checks_egress_before_each_iteration(entrypoint_text):
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert loop.index("egress_ready") < loop.index("Starting iteration")
    ready = _function_body(entrypoint_text, "egress_ready")
    assert '[ -n "${EGRESS_PID}" ] || return 0' in ready  # sem relay: não faz nada
    assert "egress_proxy.py check" in ready


def test_scripts_run_measured(entrypoint_text):
    """Script baixado e smoke test passam pelo resource_usage.py (média e picos no fim)."""
    body = _function_body(entrypoint_text, "download_and_execute")
    assert 'run_measured "$(basename "$SCRIPT_PATH")" python "$SCRIPT_PATH"' in body
    assert "run_measured smoke_test.py python /app/smoke_test.py" in body
    measured = _function_body(entrypoint_text, "run_measured")
    assert 'python /app/resource_usage.py run --label "${label}" -- "$@"' in measured
    assert 'RESOURCE_SUMMARY}" = "1"' in measured
    # o loop roda as iterações num bash filho: a função precisa ser exportada
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert re.search(r"export -f .*\brun_measured\b", loop)


def test_passthrough_command_is_untouched(entrypoint_text):
    """`docker run imagem <comando>` continua com exec direto (sem medidor no meio)."""
    assert 'exec "$@"' in _function_body(entrypoint_text, "main")


def test_first_log_line_shows_image(entrypoint_text):
    main = _function_body(entrypoint_text, "main")
    assert main.find("log_image_info") < main.find("setup_directories")
    assert "python /app/image_info.py" in _function_body(entrypoint_text, "log_image_info")


def test_run_measured_keeps_exit_code(tmp_path):
    """run_measured devolve o exit code do comando, com e sem medição."""
    func = _function_body(ENTRYPOINT.read_text(encoding="utf-8"), "run_measured")
    script = tmp_path / "t.sh"
    script.write_text("run_measured() {\n" + func + "}\nrun_measured x bash -c 'exit 7'\n")
    for value in ("0", "1"):
        result = subprocess.run(["bash", str(script)], env={"RESOURCE_SUMMARY": value, "PATH": "/usr/bin:/bin"})
        assert result.returncode == 7


# --- limpeza entre iterações, timeout com SIGKILL, preflight na partida ---------------

def test_loop_timeout_kills_a_script_that_ignores_sigterm(entrypoint_text):
    """SIGTERM no WORKER_TIMEOUT e SIGKILL WORKER_KILL_AFTER depois. O bash da iteração segura o
    TERM (trap) para esperar o script: se ele morresse antes, o timeout voltaria na hora e o script
    seguiria rodando na próxima iteração."""
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert ('timeout --kill-after="${WORKER_KILL_AFTER}" "${WORKER_TIMEOUT}" '
            "bash -c 'trap : TERM; download_and_execute'") in loop
    assert "-eq 137" in loop


def test_loop_cleans_up_right_after_each_iteration(entrypoint_text):
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert loop.index("timeout --kill-after") < loop.index("cleanup_iteration") < loop.index("sleep \"${WORKER_RESTART_DELAY}\"")
    body = _function_body(entrypoint_text, "cleanup_iteration")
    assert 'WORKER_CLEANUP}" = "1" ] || return 0' in body
    assert "kill -TERM" in body and "kill -KILL" in body


def test_cleanup_only_matches_browsers_and_drivers(entrypoint_text):
    """Serviços (Xvfb, OpenBox, PJeOffice, VNC, relay) nunca entram na limpeza."""
    body = _function_body(entrypoint_text, "browser_pids")
    patterns = re.search(r"case \"\$exe\" in\n\s*(.*?)\)", body).group(1)
    for wanted in ("/opt/chrome/*", "/opt/firefox/*", "*/chromedriver", "*/uc_driver", "*/geckodriver"):
        assert wanted in patterns
    for service in ("Xvfb", "openbox", "pjeoffice", "java", "vnc", "python"):
        assert service not in patterns


def _run_function(tmp_path, names, call, env=None, prelude=""):
    text = ENTRYPOINT.read_text(encoding="utf-8")
    script = tmp_path / "t.sh"
    funcs = "".join(f"{n}() {{\n{_function_body(text, n)}}}\n" for n in names)
    script.write_text("log_timestamp() { echo '[t]'; }\n" + prelude + funcs + call + "\n")
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", **(env or {})})


@pytest.mark.parametrize("cleanup, survives", [("1", False), ("0", True)])
def test_cleanup_closes_leftover_driver(tmp_path, cleanup, survives):
    """Um "chromedriver" esquecido pela iteração é fechado; com WORKER_CLEANUP=0 fica."""
    # Uma cópia do bash chamada chromedriver: /proc/<pid>/exe termina em /chromedriver. (Uma cópia do
    # sleep não serve: no runner do CI ele sai na hora fora do lugar de origem.)
    fake = tmp_path / "bin" / "chromedriver"
    fake.parent.mkdir()
    fake.write_bytes(pathlib.Path(shutil.which("bash")).read_bytes())
    fake.chmod(0o755)
    proc = subprocess.Popen([str(fake), "-c", "while :; do sleep 0.2; done"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(0.3)
        assert proc.poll() is None, f"o chromedriver falso não ficou rodando: {proc.stdout.read()}"
        # O teste roda no host: rm vira no-op (perfis temporários de verdade ficam) e o kill só
        # alcança o processo falso (browsers/drivers de quem roda o pytest ficam)
        prelude = ("rm() { :; }\n"
                   f'kill() {{ local s="$1" p; shift; for p in "$@"; do [ "$p" = {proc.pid} ] && command kill "$s" "$p"; done; return 0; }}\n')
        result = _run_function(tmp_path, ["browser_pids", "cleanup_iteration"], "cleanup_iteration",
                               env={"WORKER_CLEANUP": cleanup}, prelude=prelude)
        assert result.returncode == 0, result.stderr
        time.sleep(0.2)
        assert (proc.poll() is None) == survives
        if not survives:
            assert re.search(r"Closing \d+ browser/driver process\(es\)", result.stdout)
    finally:
        proc.kill()
        proc.wait()


def test_preflight_on_start_runs_after_services_and_before_any_task(entrypoint_text):
    main = _function_body(entrypoint_text, "main")
    assert main.index("start_screen_recording") < main.index("preflight_on_start") < main.index("WORKER_MODE")
    body = _function_body(entrypoint_text, "preflight_on_start")
    assert 'PREFLIGHT_ON_START}" = "1" ] || return 0' in body
    assert "python /app/preflight.py --json /app/logs/preflight.json" in body


@pytest.mark.parametrize("enabled, preflight_rc, rc, calls", [
    ("0", 1, 0, ""),           # desligado (padrão): nem roda
    ("1", 0, 0, "--json /app/logs/preflight.json --browsers chrome --url https://x.example.com/a?b=1"),
    ("1", 1, 1, "--json /app/logs/preflight.json --browsers chrome --url https://x.example.com/a?b=1"),
])
def test_preflight_on_start_stops_the_container_when_it_fails(tmp_path, enabled, preflight_rc, rc, calls):
    calls_file = tmp_path / "calls"
    prelude = (f'python() {{ shift; echo "$*" > {calls_file}; return {preflight_rc}; }}\n')
    result = _run_function(tmp_path, ["preflight_on_start"], "preflight_on_start; echo SEGUIU",
                           env={"PREFLIGHT_ON_START": enabled,
                                "PREFLIGHT_ARGS": "--browsers chrome --url https://x.example.com/a?b=1"},
                           prelude=prelude)
    assert result.returncode == rc, result.stdout + result.stderr
    assert ("SEGUIU" in result.stdout) == (rc == 0)
    assert (calls_file.read_text().strip() if calls_file.exists() else "") == calls
    if rc:
        assert "Preflight failed: stopping before the first task" in result.stdout
