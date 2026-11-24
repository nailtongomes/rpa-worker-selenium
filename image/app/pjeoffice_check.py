#!/usr/bin/env python3
"""
pjeoffice_check — o PJeOffice assina com o certificado A1? Testa de verdade, não só "o processo está vivo".

Faz o mesmo que uma pessoa na página de teste do próprio PJeOffice
(http://127.0.0.1:8800/pjeOffice/welcome?file=test/test.html, botão "Testar"):

  1. aponta o PJeOffice para o .pfx (list.a1 em ~/.pjeoffice-pro/pjeoffice-pro.config) e o reinicia
     (ele só lê a configuração ao iniciar);
  2. o Chrome abre a página de teste e clica em "Testar": o browser pede ao PJeOffice, pelo
     localhost, uma assinatura simplificada (tarefa util.test), como o PJe faz;
  3. o PJeOffice abre a janela "Informe a senha" no servidor X; este script digita a senha
     (xdotool, pela entrada padrão: nunca na linha de comando) e confirma;
  4. a página mostra "Teste concluído com sucesso!" com o nome e o CPF do certificado.

No fim, a configuração do PJeOffice volta a ser a de antes e ele fica como estava
(rodando ou parado).

Precisa de servidor X (USE_XVFB=1) e do PJeOffice (BUILD_PJEOFFICE=1). O A1 vem de
A1_PFX_PATH/A1_PFX_URL + senha, como em a1cert.load_from_env(), ou de --self-test.

    docker run --rm --shm-size=2g -e USE_XVFB=1 -e USE_OPENBOX=1 ... \\
      ghcr.io/nailtongomes/rpa-worker-selenium:latest python /app/pjeoffice_check.py --self-test

Exit 0 se o PJeOffice assinou, 1 caso contrário. Também roda dentro do a1_check (e do
preflight) quando o PJeOffice está ligado (USE_PJEOFFICE=1).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

log = logging.getLogger("pjeoffice_check")

EXECUTABLE = Path(os.getenv("PJEOFFICE_EXECUTABLE", "/opt/pjeoffice/pjeoffice-pro.sh"))
BASE_URL = "http://127.0.0.1:8800"
PING_URL = f"{BASE_URL}/pjeOffice/"
TEST_PAGE = f"{BASE_URL}/pjeOffice/welcome?file=test/test.html"
JAR_MARK = "pjeoffice-pro.jar"

# Janelas do PJeOffice (Swing) que o teste reconhece
PASSWORD_DIALOG = "Informe a senha"
FAILURE_DIALOGS = {
    "Alerta de segura": "o PJeOffice recusou a senha do certificado",
    "Seleção de certificado": "o PJeOffice não encontrou o certificado configurado",
    "Atenção!": "o PJeOffice cancelou a operação",
}
PASSWORD_FIELD_Y = 90   # campo Senha/PIN: ~90 px abaixo do topo da janela "Informe a senha"
MAX_PASSWORD_PROMPTS = 4  # ele pede 2 vezes (leitura do certificado + assinatura)


class PJeOfficeError(RuntimeError):
    """O PJeOffice não assinou; a mensagem diz em que ponto."""


def installed() -> bool:
    return EXECUTABLE.is_file()


def config_file() -> Path:
    # o PJeOffice grava em ~/.pjeoffice-pro (user.home do Java), não em PJEOFFICE_CONFIG_DIR
    return Path.home() / ".pjeoffice-pro" / "pjeoffice-pro.config"


def running_pids() -> list:
    """PIDs do Java do PJeOffice (o pjeoffice-pro.sh só dispara o Java e sai)."""
    pids = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            argv = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if any(a.endswith(JAR_MARK.encode()) for a in argv) and any(a.endswith(b"java") for a in argv):
            pids.append(int(proc.name))
    return pids


def responding(timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(PING_URL, timeout=timeout) as resp:  # noqa: S310 - localhost fixo
            return resp.status == 200
    except OSError:
        return False


def stop(timeout: float = 20) -> None:
    for pid in running_pids():
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
    deadline = time.time() + timeout
    while running_pids() and time.time() < deadline:
        time.sleep(0.3)
    for pid in running_pids():
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def start(timeout: float = 90) -> float:
    """Inicia o PJeOffice e espera o servidor local responder; devolve o tempo gasto."""
    started = time.time()
    subprocess.run([str(EXECUTABLE)], cwd=str(EXECUTABLE.parent), stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=30, check=False)
    while time.time() - started < timeout:
        if responding():
            return time.time() - started
        time.sleep(0.5)
    raise PJeOfficeError(f"o PJeOffice não respondeu em {PING_URL} em {timeout:.0f}s")


def _with_a1(original: str, pfx: Path) -> str:
    lines = [line for line in original.splitlines() if not line.startswith("list.a1=")]
    lines.append(f"list.a1={pfx}")
    return "\n".join(lines) + "\n"


@contextmanager
def configured(pfx: Path):
    """PJeOffice reiniciado com o .pfx em list.a1; no fim, configuração e estado de antes."""
    cfg = config_file()
    original = cfg.read_text(encoding="utf-8") if cfg.is_file() else None
    was_running = bool(running_pids())
    stop()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(_with_a1(original or "", pfx), encoding="utf-8")
    try:
        start()
        yield
    finally:
        stop()  # ele regrava a configuração ao sair: restaurar só depois
        if original is None:
            cfg.unlink(missing_ok=True)
        else:
            cfg.write_text(original, encoding="utf-8")
        if was_running:
            try:
                start()
            except PJeOfficeError as exc:
                log.warning("PJeOffice não voltou a rodar: %s", exc)


# --- janelas do PJeOffice (xdotool) ------------------------------------------------------

def _xdotool(*args: str, stdin: Optional[str] = None) -> str:
    proc = subprocess.run(["xdotool", *args], capture_output=True, text=True, input=stdin, timeout=15)
    return proc.stdout.strip()


def _windows(title_regex: str) -> list:
    return _xdotool("search", "--onlyvisible", "--name", title_regex).split()


def _geometry(window: str) -> dict:
    out = _xdotool("getwindowgeometry", "--shell", window)
    return {k: int(v) for k, v in (line.split("=", 1) for line in out.splitlines() if "=" in line)
            if v.lstrip("-").isdigit()}


class DialogAnswerer(threading.Thread):
    """Responde às janelas de senha do PJeOffice e registra janelas de erro."""

    def __init__(self, password: str) -> None:
        super().__init__(name="pjeoffice-dialogs", daemon=True)
        self._password = password
        self._stop = threading.Event()
        self._seen: set = set()
        self.prompts = 0
        self.error = ""

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set() and not self.error:
            for window in _windows(f"^{PASSWORD_DIALOG}$"):
                if window not in self._seen:
                    self._seen.add(window)
                    self._answer(window)
            for title, reason in FAILURE_DIALOGS.items():
                if _windows(f"^{title}"):
                    self.error = reason
            self._stop.wait(0.5)

    def _answer(self, window: str) -> None:
        self.prompts += 1
        if self.prompts > MAX_PASSWORD_PROMPTS:
            self.error = f"o PJeOffice pediu a senha {self.prompts} vezes"
            return
        time.sleep(1.0)  # a janela termina de desenhar antes de aceitar o foco
        geo = _geometry(window)
        x = geo.get("X", 0) + geo.get("WIDTH", 0) // 2
        y = geo.get("Y", 0) + PASSWORD_FIELD_Y
        _xdotool("mousemove", str(x), str(y), "click", "1")
        time.sleep(0.4)
        _xdotool("key", "ctrl+a", "BackSpace")
        _xdotool("type", "--delay", "40", "--file", "-", stdin=self._password)  # senha só pelo stdin
        time.sleep(0.3)
        _xdotool("key", "Return")


def _last_log_error() -> str:
    """Última exceção do log do PJeOffice (ajuda a entender a falha; não contém a senha)."""
    path = config_file().parent / "pjeoffice-pro.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    found = [line.strip() for line in lines if re.match(r"^(\S+Exception|Caused by:)", line.strip())]
    return found[-1][:200] if found else ""


def _open_browser():
    import a1_testkit as kit  # Chrome for Testing + chromedriver da imagem, headless

    return kit.open_chrome(headless=True)


def signature_test(pfx: os.PathLike, password: str, timeout: float = 180) -> dict:
    """Clica em "Testar" na página do PJeOffice e devolve titular/CPF da assinatura.

    Levanta PJeOfficeError com o motivo se o PJeOffice não assinar.
    """
    import a1_testkit as kit

    if not installed():
        raise PJeOfficeError(f"PJeOffice não instalado ({EXECUTABLE})")
    if not kit.has_display():
        raise PJeOfficeError("precisa de servidor X: as janelas do PJeOffice são desenhadas nele (USE_XVFB=1)")
    if not shutil.which("xdotool"):
        raise PJeOfficeError("xdotool ausente")
    pfx = Path(pfx).resolve()
    started = time.time()
    with configured(pfx):
        answerer = DialogAnswerer(password)
        answerer.start()
        driver = _open_browser()
        try:
            driver.get(TEST_PAGE)
            driver.find_element("id", "btnTest").click()
            state = ""
            while time.time() - started < timeout and not answerer.error:
                state = driver.execute_script(
                    "const s = id => document.getElementById(id).style.display;"
                    "return s('result') === 'none' ? '' : (s('success') !== 'none' ? 'ok' : 'falha');")
                if state:
                    break
                time.sleep(0.5)
            if state == "ok":
                data = driver.execute_script(
                    "const t = id => (document.getElementById(id) || {}).innerText || '';"
                    "return {titular: t('pf.name') || t('pj.business.name'), cpf: t('pf.cpf'), cnpj: t('pj.cnpj')};")
                return {**{k: v.strip() for k, v in data.items() if v}, "janelas_de_senha": answerer.prompts,
                        "segundos": round(time.time() - started, 1)}
            reason = answerer.error or ("a página de teste mostrou falha" if state else
                                        f"sem resposta em {timeout:.0f}s")
            detail = _last_log_error()
            raise PJeOfficeError(reason + (f" ({detail})" if detail else ""))
        finally:
            answerer.stop()
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="ICP de teste gerada na hora")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--json", help="grava o resultado em JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    import a1cert
    import a1_testkit as kit

    workdir = Path(tempfile.mkdtemp(prefix="pjeoffice-check-"))
    result: dict = {"ok": False}
    try:
        if args.self_test:
            pki = kit.make_test_pki(workdir / "pki", "senha-de-teste")
            pfx, password = pki["pfx"], pki["password"]
        else:
            cert = a1cert.load_from_env(workdir)
            pfx, password = cert.path, cert.password
        print("🖊️  PJeOffice: botão \"Testar\" da página local (assinatura com o A1)", flush=True)
        result = {"ok": True, **signature_test(pfx, password, args.timeout)}
        who = " | ".join(filter(None, (result.get("titular"), result.get("cpf") or result.get("cnpj"))))
        print(f"✅ PJeOffice assinou com o certificado: {who} [{result['segundos']}s]")
    except (PJeOfficeError, a1cert.A1Error) as exc:
        result = {"ok": False, "erro": str(exc)}
        print(f"❌ PJeOffice não assinou: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
