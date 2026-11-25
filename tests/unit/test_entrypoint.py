"""
Testes estáticos do image/app/entrypoint.sh.

Não executam o entrypoint (ele cria diretórios em /app e /root); a execução
real é validada pelos testes de imagem.
"""

import os
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
        ("PJEOFFICE_JAVA_XMX", ""),
        ("LOG_MAX_MB", "50"),
        ("VNC_VIEW_ONLY", "0"),
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



# --- partida defensiva: locks velhos, Xvfb, -Xmx do PJeOffice, logs, VNC, SHA-256 ----------

def test_stale_locks_are_cleared_before_any_service(entrypoint_text):
    main = _function_body(entrypoint_text, "main")
    assert main.index("clear_stale_locks") < main.index("setup_firefox_profile") < main.index("start_xvfb")


def _fake_process(tmp_path, name):
    """Processo vivo com comm = name (cópia do bash em loop)."""
    exe = tmp_path / "fake" / name
    exe.parent.mkdir(exist_ok=True)
    exe.write_bytes(pathlib.Path(shutil.which("bash")).read_bytes())
    exe.chmod(0o755)
    proc = subprocess.Popen([str(exe), "-c", "while :; do sleep 0.2; done"])
    time.sleep(0.3)
    assert proc.poll() is None
    return proc


@pytest.mark.parametrize("owner, browsers, xlock_kept, profile_locks_kept", [
    ("gone", "", False, False),        # restart: dono do lock não existe mais
    ("other", "", False, False),       # PID reaproveitado por outro processo (o caso real)
    ("Xvfb", "", True, False),         # um Xvfb vivo é dono: fica
    ("gone", "4242", False, True),     # browser rodando: travas dos perfis ficam
])
def test_clear_stale_locks(tmp_path, owner, browsers, xlock_kept, profile_locks_kept):
    display = 900 + os.getpid() % 90  # display exclusivo do teste: o lock em /tmp é nosso
    xlock, xsock = pathlib.Path(f"/tmp/.X{display}-lock"), pathlib.Path(f"/tmp/.X11-unix/X{display}")
    proc = _fake_process(tmp_path, "Xvfb") if owner == "Xvfb" else (
        _fake_process(tmp_path, "openbox") if owner == "other" else None)
    pid = proc.pid if proc else 4_000_000
    profile = tmp_path / "perfil"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("host-123")
    firefox = tmp_path / "ff"
    firefox.mkdir()
    (firefox / "lock").symlink_to("127.0.0.1:+123")
    (firefox / ".parentlock").write_text("")
    try:
        xlock.write_text(f"{pid:>10}\n")
        xsock.parent.mkdir(exist_ok=True)
        xsock.write_text("")
        # find/browser_pids/remove_browser_temp de mentira: o teste nunca mexe no /tmp, /app, /root reais
        prelude = (f"find() {{ printf '%s\\0' '{profile / 'SingletonLock'}'; }}\n"
                   f"browser_pids() {{ [ -n '{browsers}' ] && echo {browsers}; return 0; }}\n"
                   "remove_browser_temp() { echo TEMP-LIMPO; }\n")
        result = _run_function(tmp_path, ["clear_stale_locks"], "clear_stale_locks",
                               env={"DISPLAY": f":{display}", "FIREFOX_PROFILE_DIR": str(firefox)},
                               prelude=prelude)
        assert result.returncode == 0, result.stderr
        assert xlock.exists() == xlock_kept and xsock.exists() == xlock_kept
        assert ("Removed stale Xvfb lock" in result.stdout) == (not xlock_kept)
        assert (profile / "SingletonLock").is_symlink() == profile_locks_kept
        assert (firefox / "lock").is_symlink() == profile_locks_kept
        assert ("Removed 2 stale browser profile lock(s)" in result.stdout) == (not profile_locks_kept)
        assert ("TEMP-LIMPO" in result.stdout) == (not profile_locks_kept)
    finally:
        xlock.unlink(missing_ok=True)
        xsock.unlink(missing_ok=True)
        if proc:
            proc.kill()
            proc.wait()


def test_xvfb_start_fails_fast_and_reuses_a_live_display(entrypoint_text):
    body = _function_body(entrypoint_text, "start_xvfb")
    assert body.index('xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then') < body.index("Xvfb \"${DISPLAY}\"")
    assert 'if ! kill -0 "$XVFB_PID"' in body and "Xvfb exited during startup" in body


def test_rotate_logs(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "egress_proxy.log").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (logs / "resources.jsonl").write_bytes(b"y" * 100)
    (logs / "egress_proxy.log.1").write_text("antigo")
    text = ENTRYPOINT.read_text(encoding="utf-8").replace("/app/logs/", f"{logs}/")
    func = _function_body(text, "rotate_logs")
    script = tmp_path / "r.sh"
    script.write_text("log_timestamp() { echo '[t]'; }\nrotate_logs() {\n" + func + "}\nrotate_logs\n")
    for max_mb, rotated in (("0", False), ("2", True)):
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                                env={"PATH": "/usr/bin:/bin", "LOG_MAX_MB": max_mb})
        assert result.returncode == 0, result.stderr
        assert ((logs / "egress_proxy.log").stat().st_size == 0) == rotated
    assert (logs / "egress_proxy.log.1").stat().st_size == 2 * 1024 * 1024 + 1
    assert (logs / "resources.jsonl").stat().st_size == 100  # abaixo do limite: intacto
    assert "Rotated" in result.stdout


def test_logs_rotate_at_start_and_between_iterations(entrypoint_text):
    assert "rotate_logs" in _function_body(entrypoint_text, "setup_directories")
    loop = _function_body(entrypoint_text, "execute_with_loop")
    assert loop.index("cleanup_iteration") < loop.index("rotate_logs") < loop.index('sleep "${WORKER_RESTART_DELAY}"')


@pytest.mark.parametrize("xmx, ok", [("512m", True), ("1G", True), ("512", False), ("1g; rm -rf /", False)])
def test_pjeoffice_launcher_with_xmx(tmp_path, xmx, ok):
    launcher = tmp_path / "pjeoffice" / "pjeoffice-pro.sh"
    launcher.parent.mkdir()
    launcher.write_text('#!/bin/bash\nnohup ./jre/bin/java \\\n-Xms20m \\\n-Xmx2048m \\\n-jar pjeoffice-pro.jar &\n')
    result = _run_function(tmp_path, ["pjeoffice_launcher_with_xmx"], f"pjeoffice_launcher_with_xmx '{xmx}'",
                           env={"PJEOFFICE_EXECUTABLE": str(launcher)})
    assert (result.returncode == 0) == ok, result.stderr
    if ok:
        custom = pathlib.Path(result.stdout.strip())
        assert custom.parent == launcher.parent  # o launcher acha o jar pelo próprio diretório
        text = custom.read_text()
        assert f"-Xmx{xmx}" in text and "-Xmx2048m" not in text and "-Xms20m" in text
        assert os.access(custom, os.X_OK)
        assert "-Xmx2048m" in launcher.read_text()  # o original não muda
    else:
        assert "keeping the launcher's -Xmx" in result.stderr


def test_pjeoffice_uses_the_xmx_launcher_only_when_asked(entrypoint_text):
    body = _function_body(entrypoint_text, "start_pjeoffice")
    assert 'if [ -n "${PJEOFFICE_JAVA_XMX}" ]; then' in body
    assert '"${launcher}" &' in body


def test_vnc_password_never_in_argv_or_children(entrypoint_text):
    body = _function_body(entrypoint_text, "start_vnc")
    assert "auth=(-nopw)" in body  # sem senha: como sempre
    assert '-passwdfile "rm:${password_file}"' in body  # x11vnc lê e apaga o arquivo
    assert "umask 077" in body and "unset VNC_PASSWORD" in body
    assert '"${auth[@]}"' in body and "-nopw \\\n" not in body
    assert 'VNC_VIEW_ONLY}" = "1"' in body and "-viewonly" in body
    # a senha só passa por printf (builtin, fora do argv) e nunca vai para o log
    for line in body.splitlines():
        if "VNC_PASSWORD}" in line and "VNC_PASSWORD_FILE" not in line:
            assert line.strip().startswith(("printf", "if [", "elif", "unset")) or "-n \"${VNC_PASSWORD" in line, line
        if line.strip().startswith("echo"):
            assert "VNC_PASSWORD}" not in line


def test_script_hash_mismatch_is_not_retried(entrypoint_text):
    body = _function_body(entrypoint_text, "download_script_with_retry")
    assert 'if [ "$rc" -eq 3 ]; then' in body
    assert body.index('"$rc" -eq 3') < body.index("sleep $wait_time")
