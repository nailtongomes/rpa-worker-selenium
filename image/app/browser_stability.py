#!/usr/bin/env python3
"""Estabilidade do Chrome/ChromeDriver em uso de verdade (muitas navegações, sessão longa, falhas de rede).

Roda dentro da imagem: no portão de qualidade (scripts/test-image.sh) e no servidor de produção, para
reproduzir um problema com os mesmos limites do worker:

    python /app/browser_stability.py                                  # cenários locais (determinísticos)
    python /app/browser_stability.py --external                       # + sites públicos (poucas requisições)
    python /app/browser_stability.py --scenarios prolongada --duration 900 --mode uc-headless
    docker run --rm --memory=2g --cpus=1 --shm-size=2g --init <imagem> python /app/browser_stability.py

Cenários (--scenarios, separados por vírgula):
  sequencial   uma sessão, várias páginas por rodada: título, URL final, conteúdo, JavaScript, driver vivo
  sessoes      cria, navega e fecha N sessões; confere processos que sobraram e zombies
  prolongada   uma sessão por N segundos alternando navegação, espera e JavaScript
  recuperacao  página lenta, travada, conexão cortada, 500, 503 e redirecionamento; depois de cada uma a
               sessão continua válida, navega de novo, roda JavaScript e fecha direito
  uc_especial  modo UC abrindo páginas 4xx/5xx e com reCAPTCHA: o SeleniumBase reabre o ChromeDriver nelas
  modos        Selenium, SeleniumBase, UC e UC + cft, headless e headful (com DISPLAY): driver usado,
               caminho e versão
  externos     (--external) sites públicos de teste; site fora do ar é aviso, sessão perdida é falha

Classes de falha: DNS_ERROR, TCP_CONNECTION_ERROR, TLS_ERROR, HTTP_ERROR, NAVIGATION_TIMEOUT (rede/site) e
CHROME_CRASH, CHROMEDRIVER_EXITED, WEBDRIVER_CONNECTION_REFUSED, SESSION_LOST, RESOURCE_EXHAUSTED (browser);
CONTENT_MISMATCH (a página abriu, mas sem o conteúdo esperado) e UNKNOWN.

Exit 1 se um cenário local falhar ou se qualquer navegação (local ou externa) perder a sessão/driver/browser;
falha de rede de site externo só gera aviso. Nada é repetido: a primeira falha do browser fica registrada.

Saída: uma linha por cenário, `STABILITY_SUMMARY {json}` no fim e, em --out (padrão /app/logs/stability):
<label>.json e, por falha, falhas/<cenário>-<n>-<classe>/ com diag.json (versões, driver, PIDs e exit code,
processos e zombies, memória e OOM do cgroup, /dev/shm, Xvfb, PJeOffice), traceback.txt, screenshot.png,
console do browser e o log detalhado do ChromeDriver (SE_DEBUG). Logs de cenários que passaram são apagados.

Variáveis: STABILITY_EXTERNAL_URLS (`url|texto esperado|fim da URL final`, separadas por espaço ou vírgula).
Não registra credenciais: URLs aparecem sem usuário/senha e sem query string.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import http.server
import json
import logging
import os
import random
import re
import shutil
import socket
import statistics
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# --- classes de falha ---------------------------------------------------------------------------

DNS_ERROR = "DNS_ERROR"
TCP_CONNECTION_ERROR = "TCP_CONNECTION_ERROR"
TLS_ERROR = "TLS_ERROR"
HTTP_ERROR = "HTTP_ERROR"
NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
CHROME_CRASH = "CHROME_CRASH"
CHROMEDRIVER_EXITED = "CHROMEDRIVER_EXITED"
WEBDRIVER_CONNECTION_REFUSED = "WEBDRIVER_CONNECTION_REFUSED"
SESSION_LOST = "SESSION_LOST"
RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
CONTENT_MISMATCH = "CONTENT_MISMATCH"
UNKNOWN = "UNKNOWN"

# Falhas de rede/site: num site externo são aviso (o site pode estar fora do ar).
NETWORK_CLASSES = frozenset({DNS_ERROR, TCP_CONNECTION_ERROR, TLS_ERROR, HTTP_ERROR, NAVIGATION_TIMEOUT,
                             CONTENT_MISMATCH})
# Falhas do browser/driver: sempre reprovam, inclusive em site externo.
BROWSER_CLASSES = frozenset({CHROME_CRASH, CHROMEDRIVER_EXITED, WEBDRIVER_CONNECTION_REFUSED, SESSION_LOST,
                             RESOURCE_EXHAUSTED, UNKNOWN})

NET_ERRORS = (
    (re.compile(r"ERR_NAME_NOT_RESOLVED|ERR_NAME_RESOLUTION_FAILED|ERR_DNS_"), DNS_ERROR),
    (re.compile(r"ERR_(CERT_|SSL_|BAD_SSL|CERTIFICATE)"), TLS_ERROR),
    (re.compile(r"ERR_TIMED_OUT|ERR_CONNECTION_TIMED_OUT"), NAVIGATION_TIMEOUT),
    (re.compile(r"ERR_(CONNECTION_|EMPTY_RESPONSE|ADDRESS_UNREACHABLE|NETWORK_|INTERNET_DISCONNECTED|"
                r"SOCKET_|PROXY_CONNECTION_FAILED|TUNNEL_CONNECTION_FAILED|INVALID_HTTP_RESPONSE)"),
     TCP_CONNECTION_ERROR),
    (re.compile(r"ERR_HTTP_|ERR_TOO_MANY_REDIRECTS|ERR_INVALID_RESPONSE"), HTTP_ERROR),
)

CHROME_DIR = "/opt/chrome/"
SHIPPED_CHROMEDRIVER = "/usr/local/bin/chromedriver"
DRIVER_NAMES = ("chromedriver", "uc_driver")
DEFAULT_OUT = Path(os.getenv("STABILITY_OUT", "/app/logs/stability"))
DEFAULT_SCENARIOS = ("modos", "sequencial", "sessoes", "recuperacao", "uc_especial", "prolongada")
MODES = ("selenium-headless", "sb-headless", "uc-headless", "uccft-headless",
         "selenium-headful", "sb-headful", "uc-headful", "uccft-headful")

# Páginas feitas para teste automatizado: as de teste do projeto Selenium e o httpbingo ("HTTP Client Testing
# Service"). example.com/example.org ficam de fora: pedem para não serem usados em testes e monitoramento.
EXTERNAL_DEFAULT = (
    "https://www.selenium.dev/selenium/web/web-form.html|Web form",
    "https://www.selenium.dev/selenium/web/formPage.html|We Leave From Here",
    "https://www.selenium.dev/selenium/web/xhtmlTest.html|XHTML Test Page",
    "https://httpbingo.org/html|Herman Melville",
    "https://httpbingo.org/redirect/2|headers|/get",
)


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def say(emoji: str, msg: str) -> None:
    print(f"[{now()}] {emoji} {msg}", flush=True)


def mask_url(url: str) -> str:
    """Sem usuário/senha e sem query string (podem carregar token)."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return "<url inválida>"
    host = p.hostname or ""
    if p.port:
        host = f"{host}:{p.port}"
    query = "?…" if p.query else ""
    return urllib.parse.urlunsplit((p.scheme, host, p.path, "", "")) + query


def fmt_s(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " s"


# --- servidor local com falhas controladas ------------------------------------------------------

PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{title}</title></head>
<body><h1>{title}</h1><p id="marker">{marker}</p>{extra}
<script>window.__estavel = "{marker}";</script></body></html>"""

FORM_EXTRA = '<form><input id="campo" name="campo" type="text"><button type="button">ok</button></form>'
# O SeleniumBase (UC) procura este texto na resposta para decidir abrir a página "especial" (nova aba +
# reconexão do ChromeDriver). Fica num comentário: o browser não baixa nada de fora.
CAPTCHA_EXTRA = "<!-- https://www.google.com/recaptcha/api.js -->"


class FaultServer:
    """HTTP em 127.0.0.1 com páginas normais, lentas, travadas, conexão cortada, 4xx/5xx e redirecionamentos."""

    def __init__(self) -> None:
        stop = self.stop_event = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # noqa: D401 - silencioso
                pass

            def _send(self, code: int, title: str, marker: str, extra: str = "") -> None:
                body = PAGE.format(title=title, marker=marker, extra=extra).encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802 - API do http.server
                path = urllib.parse.urlsplit(self.path).path
                parts = [p for p in path.split("/") if p]
                head = parts[0] if parts else "page"
                arg = parts[1] if len(parts) > 1 else "1"
                if head == "page":
                    return self._send(200, f"Página {arg}", f"estavel-{arg}")
                if head == "form":
                    return self._send(200, "Formulário", "estavel-form", FORM_EXTRA)
                if head == "captcha":
                    return self._send(200, "Verificação", "estavel-captcha", CAPTCHA_EXTRA)
                if head == "redirect":
                    n = int(arg) if arg.isdigit() else 1
                    target = f"/redirect/{n - 1}" if n > 1 else "/page/destino"
                    self.send_response(302)
                    self.send_header("Location", target)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if head == "slow":
                    stop.wait(min(int(arg) if arg.isdigit() else 1000, 60000) / 1000)
                    return self._send(200, "Lenta", f"estavel-lenta-{arg}")
                if head == "hang":
                    stop.wait(60)
                    return self._send(200, "Travada", "estavel-travada")
                if head == "drop":
                    self.close_connection = True
                    with contextlib.suppress(OSError):
                        self.connection.shutdown(socket.SHUT_RDWR)
                    return None
                if head == "status":
                    code = int(arg) if arg.isdigit() else 500
                    return self._send(code, f"HTTP {code}", f"estavel-status-{code}")
                return self._send(404, "HTTP 404", "estavel-404")

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):  # browser desistiu da página lenta: normal
                if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
                    super().handle_error(request, client_address)

        self.httpd = Server(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FaultServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop_event.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return self.base + path


# --- processos, cgroup e ambiente ---------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _kv(path: Path) -> dict:
    out = {}
    for line in _read(path).splitlines():
        key, _, value = line.partition(" ")
        if value.strip().lstrip("-").isdigit():
            out[key] = int(value)
    return out


def _int_or(value: str):
    return int(value) if value.isdigit() else (value or None)


def cgroup_snapshot(root: Path = Path("/sys/fs/cgroup")) -> dict:
    """Memória (atual, pico, limite, eventos de OOM), PIDs e CPU do cgroup do container."""
    mb = 1024 * 1024
    if (root / "memory.current").exists():
        current, peak = _int_or(_read(root / "memory.current")), _int_or(_read(root / "memory.peak"))
        limit = _int_or(_read(root / "memory.max"))
        return {
            "versao": 2,
            "memoria_mb": round(current / mb, 1) if isinstance(current, int) else None,
            "memoria_pico_mb": round(peak / mb, 1) if isinstance(peak, int) else None,
            "memoria_limite_mb": round(limit / mb, 1) if isinstance(limit, int) else None,
            "memory_events": _kv(root / "memory.events"),
            "pids": _int_or(_read(root / "pids.current")),
            "pids_max": _int_or(_read(root / "pids.max")),
            "cpu_max": _read(root / "cpu.max") or None,
            "cpu_throttled_usec": _kv(root / "cpu.stat").get("throttled_usec"),
        }
    mem = root / "memory"
    if (mem / "memory.usage_in_bytes").exists():
        current = _int_or(_read(mem / "memory.usage_in_bytes"))
        peak = _int_or(_read(mem / "memory.max_usage_in_bytes"))
        limit = _int_or(_read(mem / "memory.limit_in_bytes"))
        oom = _kv(mem / "memory.oom_control")
        return {
            "versao": 1,
            "memoria_mb": round(current / mb, 1) if isinstance(current, int) else None,
            "memoria_pico_mb": round(peak / mb, 1) if isinstance(peak, int) else None,
            "memoria_limite_mb": round(limit / mb, 1) if isinstance(limit, int) and limit < 1 << 60 else None,
            "memory_events": {"oom_kill": oom.get("oom_kill", 0), "under_oom": oom.get("under_oom", 0)},
            "pids": _int_or(_read(root / "pids" / "pids.current")),
            "pids_max": _int_or(_read(root / "pids" / "pids.max")),
        }
    return {"versao": None}


def oom_kills(snapshot: dict) -> int:
    events = snapshot.get("memory_events") or {}
    return int(events.get("oom_kill", 0) or 0)


@dataclass
class Proc:
    pid: int
    ppid: int
    state: str
    name: str
    exe: str
    rss_mb: float


def processes(proc: Path = Path("/proc")) -> list:
    out = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
        except OSError:
            continue
        name = stat[stat.find("(") + 1:stat.rfind(")")]
        fields = stat[stat.rfind(")") + 2:].split()
        try:
            exe = os.readlink(entry / "exe")
        except OSError:
            exe = ""
        rss = 0.0
        with contextlib.suppress(OSError, ValueError, IndexError):
            rss = int((entry / "statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
        out.append(Proc(int(entry.name), int(fields[1]), fields[0], name, exe, round(rss, 1)))
    return out


def is_browser_proc(p: Proc) -> bool:
    exe = p.exe.replace(" (deleted)", "")
    return exe.startswith(CHROME_DIR) or os.path.basename(exe) in DRIVER_NAMES or p.name in DRIVER_NAMES


def process_summary(procs: Optional[list] = None) -> dict:
    procs = processes() if procs is None else procs
    states: dict = {}
    for p in procs:
        states[p.state] = states.get(p.state, 0) + 1
    chrome = [p for p in procs if p.exe.startswith(CHROME_DIR)]
    return {
        "total": len(procs),
        "por_estado": states,
        "zombies": states.get("Z", 0),
        "zombies_lista": [f"{p.pid}:{p.name}(pai {p.ppid})" for p in procs if p.state == "Z"][:20],
        "chrome": {"processos": len(chrome), "rss_mb": round(sum(p.rss_mb for p in chrome), 1)},
        "drivers": [{"pid": p.pid, "exe": p.exe, "estado": p.state} for p in procs
                    if os.path.basename(p.exe.replace(" (deleted)", "")) in DRIVER_NAMES or p.name in DRIVER_NAMES],
        "maiores_rss": [{"pid": p.pid, "nome": p.name, "rss_mb": p.rss_mb, "estado": p.state}
                        for p in sorted(procs, key=lambda x: x.rss_mb, reverse=True)[:8]],
        "pid1": next((p.name for p in procs if p.pid == 1), "?"),
    }


def shm_usage(path: str = "/dev/shm") -> dict:
    try:
        st = os.statvfs(path)
    except OSError:
        return {}
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    mb = 1024 * 1024
    return {"total_mb": round(total / mb, 1), "usado_mb": round((total - free) / mb, 1),
            "uso_pct": round(100 * (total - free) / total, 1) if total else None}


def service_state(procs: list) -> dict:
    display = os.getenv("DISPLAY", "")
    xvfb = [p for p in procs if p.name == "Xvfb"]
    java = [p for p in procs if p.name == "java" and "pjeoffice" in _read(Path(f"/proc/{p.pid}/cmdline")).lower()]
    return {
        "display": display or None,
        "xvfb": {"rodando": bool(xvfb), "pids": [p.pid for p in xvfb],
                 "socket": bool(display) and Path(f"/tmp/.X11-unix/X{display.lstrip(':').split('.')[0]}").exists()},
        "pjeoffice": {"rodando": bool(java), "rss_mb": round(sum(p.rss_mb for p in java), 1)},
        "use_pjeoffice": os.getenv("USE_PJEOFFICE", "0"),
    }


def listener_pid(port: int, proc: Path = Path("/proc")) -> Optional[int]:
    """PID que escuta em 127.0.0.1:<port>. No modo UC o SeleniumBase sobe o ChromeDriver duas vezes na
    partida e service.process fica com a cópia que saiu (exit 1): quem atende é outro processo."""
    inodes = set()
    for table in ("tcp", "tcp6"):
        for line in _read(proc / "net" / table).splitlines()[1:]:
            cols = line.split()
            if len(cols) > 9 and cols[3] == "0A" and int(cols[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(cols[9])
    if not inodes:
        return None
    targets = {f"socket:[{i}]" for i in inodes}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        with contextlib.suppress(OSError):
            for fd in (entry / "fd").iterdir():
                with contextlib.suppress(OSError):
                    if os.readlink(fd) in targets:
                        return int(entry.name)
    return None


def x_display_ready() -> bool:
    """DISPLAY definido E o servidor X atendendo (a imagem define DISPLAY mesmo sem Xvfb)."""
    display = os.getenv("DISPLAY", "")
    match = re.fullmatch(r":(\d+)(\.\d+)?", display)
    return bool(match) and Path(f"/tmp/.X11-unix/X{match.group(1)}").exists()


def sha256_prefix(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()[:16]
    except OSError:
        return ""


def versions() -> dict:
    from importlib import metadata

    out = {}
    for pkg in ("selenium", "seleniumbase", "urllib3"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = None
    info = Path(__file__).resolve().parent / "image_info.json"
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(info.read_text(encoding="utf-8"))
        out.update({k: data.get(k) for k in ("tag", "chrome", "chromedriver", "arquitetura")})
    out["chromedriver_imagem_sha256"] = sha256_prefix(SHIPPED_CHROMEDRIVER)
    return out


# --- classificação ------------------------------------------------------------------------------

def exception_text(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def classify_net_error(code: str) -> str:
    for pattern, cls in NET_ERRORS:
        if pattern.search(code or ""):
            return cls
    return TCP_CONNECTION_ERROR if (code or "").startswith("ERR_") else UNKNOWN


def classify(exc: BaseException, driver_alive: Optional[bool] = None, chrome_alive: Optional[bool] = None,
             oom_delta: int = 0) -> str:
    """Classe da falha a partir da exceção e do estado dos processos (quando conhecido)."""
    if oom_delta > 0:
        return RESOURCE_EXHAUSTED
    text = exception_text(exc)
    low = text.lower()
    name = type(exc).__name__
    if re.search(r"cannot allocate memory|resource temporarily unavailable|no space left on device|"
                 r"out of memory|errno 12\b", low):
        return RESOURCE_EXHAUSTED
    refused = "connection refused" in low or "newconnectionerror" in low or "errno 111" in low
    if refused and re.search(r"localhost|127\.0\.0\.1", low):
        return CHROMEDRIVER_EXITED if driver_alive is False else WEBDRIVER_CONNECTION_REFUSED
    if "remotedisconnected" in low or "connection aborted" in low or "connection reset by peer" in low:
        return CHROMEDRIVER_EXITED if driver_alive is False else WEBDRIVER_CONNECTION_REFUSED
    if "session deleted because of page crash" in low or "tab crashed" in low or "page crash" in low:
        return CHROME_CRASH
    if re.search(r"chrome not reachable|cannot connect to chrome|unable to discover open pages|"
                 r"not connected to devtools|disconnected: |chrome failed to start|devtoolsactiveport", low):
        return CHROME_CRASH if chrome_alive is False else SESSION_LOST
    if re.search(r"invalid session id|no such session|session not created|no such window|"
                 r"web view not found|target window already closed", low) or name in (
            "InvalidSessionIdException", "NoSuchWindowException", "SessionNotCreatedException"):
        return CHROME_CRASH if chrome_alive is False else SESSION_LOST
    if name == "TimeoutException" or "timed out receiving message from renderer" in low or "timeout: " in low:
        return NAVIGATION_TIMEOUT
    match = re.search(r"net::(ERR_[A-Z_]+)", text)
    if match:
        return classify_net_error(match.group(1))
    if name in ("ReadTimeoutError", "ReadTimeout") or "read timed out" in low:
        return WEBDRIVER_CONNECTION_REFUSED if driver_alive is False else NAVIGATION_TIMEOUT
    return UNKNOWN


# --- sessão (driver + processos + log do ChromeDriver) ------------------------------------------

@contextlib.contextmanager
def chromedriver_verbose_log(path: Path):
    """SE_DEBUG faz o Selenium iniciar o ChromeDriver com --verbose e a saída em sys.stderr: durante a
    criação do driver, sys.stderr aponta para o arquivo (as reconexões do UC reaproveitam o mesmo)."""
    fh = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    old_env, old_err = os.environ.get("SE_DEBUG"), sys.stderr
    os.environ["SE_DEBUG"] = "1"
    sys.stderr = fh
    try:
        yield fh
    finally:
        sys.stderr = old_err
        # Um handler criado nesse meio-tempo ficaria preso ao arquivo (fechado no quit): volta ao stderr.
        loggers = [logging.getLogger()] + [lg for lg in logging.Logger.manager.loggerDict.values()
                                           if isinstance(lg, logging.Logger)]
        for lg in loggers:
            for handler in lg.handlers:
                if isinstance(handler, logging.StreamHandler) and handler.stream is fh:
                    handler.setStream(old_err)
                    handler.setLevel(logging.ERROR)
        if old_env is None:
            os.environ.pop("SE_DEBUG", None)
        else:
            os.environ["SE_DEBUG"] = old_env


class Session:
    """Um driver com o que é preciso para diagnosticar: PID/porta do ChromeDriver, processos do Chrome
    criados por ele, binário realmente usado e log detalhado."""

    def __init__(self, mode: str, log_path: Path, page_load_timeout: Optional[float] = None) -> None:
        self.mode = mode
        self.log_path = log_path
        self.driver = None
        self.log_file = None
        before = {p.pid for p in processes() if is_browser_proc(p)}
        started = time.monotonic()
        kind, _, view = mode.partition("-")
        headless = view != "headful"
        if not headless and not x_display_ready():
            raise RuntimeError(f"{mode} precisa de um servidor X (USE_XVFB=1)")
        self._log_cm = chromedriver_verbose_log(log_path)
        self.log_file = self._log_cm.__enter__()
        try:
            if kind == "selenium":
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service

                opts = webdriver.ChromeOptions()
                if headless:
                    opts.add_argument("--headless=new")
                opts.add_argument("--no-sandbox")
                opts.add_argument("--window-size=1280,900")
                opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
                self.driver = webdriver.Chrome(options=opts, service=Service(service_args=["--enable-chrome-logs"]))
            elif kind in ("sb", "uc", "uccft"):
                from seleniumbase import Driver

                kwargs = {"cft": True} if kind == "uccft" else {}
                self.driver = Driver(uc=kind in ("uc", "uccft"), headless=headless, **kwargs)
            else:
                raise ValueError(f"modo desconhecido: {mode}")
        except BaseException:
            with contextlib.suppress(Exception):
                self.log_file.close()
            raise
        finally:
            self._log_cm.__exit__(None, None, None)
        self.start_secs = time.monotonic() - started
        if page_load_timeout:
            self.driver.set_page_load_timeout(page_load_timeout)
        self.browser_pids = {p.pid for p in processes() if is_browser_proc(p)} - before
        self.info = self.driver_info()

    # estado do ChromeDriver ----------------------------------------------------------------------
    @property
    def service(self):
        return getattr(self.driver, "service", None)

    def driver_pid(self) -> Optional[int]:
        """Quem escuta na porta do ChromeDriver; sem ninguém, o processo que o Selenium iniciou."""
        port = getattr(self.service, "port", None)
        pid = listener_pid(port) if port else None
        if pid:
            return pid
        proc = getattr(self.service, "process", None)
        return getattr(proc, "pid", None)

    def driver_exit_code(self) -> Optional[int]:
        """Exit code do processo que o Selenium iniciou (None enquanto vivo ou se outro atende a porta)."""
        port = getattr(self.service, "port", None)
        if port and listener_pid(port):
            return None
        proc = getattr(self.service, "process", None)
        return proc.poll() if proc is not None else None

    def driver_alive(self) -> bool:
        port = getattr(self.service, "port", None)
        if port and listener_pid(port):
            return True
        proc = getattr(self.service, "process", None)
        return proc is not None and proc.poll() is None

    def driver_status(self) -> dict:
        port = getattr(self.service, "port", None)
        if not port:
            return {"porta": None}
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as resp:
                body = json.loads(resp.read().decode() or "{}")
            return {"porta": port, "http": resp.status, "ready": (body.get("value") or {}).get("ready")}
        except Exception as exc:  # noqa: BLE001 - estado, não falha
            return {"porta": port, "erro": f"{type(exc).__name__}: {str(exc)[:120]}"}

    def chrome_alive(self) -> Optional[bool]:
        alive = {p.pid for p in processes() if p.exe.startswith(CHROME_DIR) and p.state != "Z"}
        tracked = {pid for pid in self.browser_pids}
        if not tracked:
            return None
        return bool(alive & tracked)

    def driver_info(self) -> dict:
        info: dict = {"modo": self.mode, "partida_s": round(self.start_secs, 2)}
        caps = {}
        with contextlib.suppress(Exception):
            caps = self.driver.capabilities or {}
        info["browser_versao"] = caps.get("browserVersion")
        info["chromedriver_versao"] = ((caps.get("chrome") or {}).get("chromedriverVersion") or "").split(" ")[0]
        info["service_path"] = getattr(self.service, "path", None)
        pid = self.driver_pid()
        exe = ""
        with contextlib.suppress(OSError, TypeError):
            exe = os.readlink(f"/proc/{pid}/exe")
        info["chromedriver_pid"] = pid
        info["chromedriver_exe"] = exe
        info["chromedriver_sha256"] = sha256_prefix(exe) if exe else ""
        info["chromedriver_da_imagem"] = bool(exe) and info["chromedriver_sha256"] == sha256_prefix(
            SHIPPED_CHROMEDRIVER)
        chrome_exes = sorted({p.exe for p in processes() if p.pid in self.browser_pids
                              and p.exe.startswith(CHROME_DIR)})
        info["chrome_exe"] = chrome_exes[0] if chrome_exes else None
        return info

    def quit(self) -> dict:
        """Fecha o driver e confere o que sobrou dos processos que esta sessão criou."""
        error = None
        try:
            self.driver.quit()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160] if str(exc) else ''}"
        leftovers: list = []
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            leftovers = [p for p in processes() if p.pid in self.browser_pids and p.state != "Z"]
            if not leftovers:
                break
            time.sleep(0.25)
        with contextlib.suppress(Exception):
            self.log_file.close()
        return {"erro_quit": error,
                "processos_residuais": [f"{p.pid}:{p.name}" for p in leftovers]}


# --- navegação e checagens ----------------------------------------------------------------------

@dataclass
class Expect:
    url: str
    text: str = ""
    title: str = ""
    url_suffix: str = ""
    expect_class: Optional[str] = None  # recuperação: classe esperada (ex.: NAVIGATION_TIMEOUT)


@dataclass
class NavResult:
    url: str
    ok: bool
    secs: float
    cls: Optional[str] = None
    detail: str = ""
    final_url: str = ""
    http_status: Optional[int] = None
    exc: Optional[BaseException] = field(default=None, repr=False)


PAGE_STATE_JS = """
var nav = (performance.getEntriesByType && performance.getEntriesByType('navigation')[0]) || {};
var err = document.querySelector('#main-frame-error') || /^chrome-error:/.test(location.href);
var code = '';
if (err) { var m = (document.documentElement.innerHTML || '').match(/(ERR_[A-Z_]+)/); code = m ? m[1] : 'ERR_UNKNOWN'; }
return {href: location.href, title: document.title, status: nav.responseStatus || 0, err: code,
        text: (document.body ? document.body.innerText : '').slice(0, 20000), ready: document.readyState};
"""


def navigate(session: Session, exp: Expect) -> NavResult:
    """Abre a URL e valida título, URL final, conteúdo e status; erro da página vira classe de rede."""
    started = time.monotonic()
    try:
        session.driver.get(exp.url)
        state = session.driver.execute_script(PAGE_STATE_JS) or {}
    except Exception as exc:  # noqa: BLE001 - tudo vira classe
        secs = time.monotonic() - started
        cls = classify(exc, session.driver_alive(), session.chrome_alive())
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return NavResult(exp.url, False, secs, cls, f"{type(exc).__name__}: {first[:200]}", exc=exc)
    secs = time.monotonic() - started
    final, status = state.get("href", ""), int(state.get("status") or 0)
    res = NavResult(exp.url, True, secs, final_url=final, http_status=status or None)
    if state.get("err"):
        res.ok, res.cls, res.detail = False, classify_net_error(state["err"]), state["err"]
    elif status >= 400:
        res.ok, res.cls, res.detail = False, HTTP_ERROR, f"HTTP {status}"
    elif exp.title and exp.title not in (state.get("title") or ""):
        res.ok, res.cls, res.detail = False, CONTENT_MISMATCH, f"título {state.get('title')!r}"
    elif exp.text and exp.text not in f"{state.get('title') or ''}\n{state.get('text') or ''}":
        res.ok, res.cls, res.detail = False, CONTENT_MISMATCH, f"sem {exp.text!r} na página"
    elif exp.url_suffix and not urllib.parse.urlsplit(final).path.endswith(exp.url_suffix):
        res.ok, res.cls, res.detail = False, CONTENT_MISMATCH, f"URL final {mask_url(final)}"
    return res


def js_check(session: Session) -> Optional[str]:
    """JavaScript simples depois da navegação; None se ok, senão a descrição do erro."""
    try:
        value = session.driver.execute_script("return [6 * 7, document.readyState, typeof window.__estavel];")
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:160] if str(exc).strip() else ''}"
    return None if value and value[0] == 42 else f"JavaScript devolveu {value!r}"


def health_check(session: Session) -> Optional[str]:
    """ChromeDriver vivo e respondendo /status, e a sessão ainda válida."""
    if not session.driver_alive():
        return f"ChromeDriver saiu (exit {session.driver_exit_code()})"
    status = session.driver_status()
    if status.get("erro"):
        return f"ChromeDriver não responde /status: {status['erro']}"
    try:
        session.driver.current_url  # noqa: B018 - comando WebDriver que exige sessão válida
    except Exception as exc:  # noqa: BLE001
        return f"sessão inválida: {type(exc).__name__}: {str(exc).strip().splitlines()[0][:160]}"
    return None


# --- relatório e diagnóstico --------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    mode: str
    ok: bool = True
    skipped: str = ""
    secs: float = 0.0
    nav_times: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        times = sorted(self.nav_times)
        stats = {}
        if times:
            stats = {"n": len(times), "mediana_s": round(statistics.median(times), 3),
                     "p95_s": round(times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))], 3),
                     "max_s": round(times[-1], 3)}
        return {"cenario": self.name, "modo": self.mode, "ok": self.ok, "pulado": self.skipped or None,
                "duracao_s": round(self.secs, 1), "navegacoes": stats, "falhas": self.failures,
                "avisos": self.warnings, "detalhes": self.details}


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.label = args.label
        self.out = Path(args.out)
        self.work = self.out / self.label
        self.work.mkdir(parents=True, exist_ok=True)
        self.failure_count = 0
        self.results: list = []
        self.cg_start = cgroup_snapshot()
        self.zombies_start = process_summary()["zombies"]
        self.zombies_max = self.zombies_start
        self.rng = random.Random(1234)

    # diagnóstico completo de uma falha ----------------------------------------------------------
    def collect(self, scenario: str, session: Optional[Session], cls: str, url: str, secs: float,
                exc: Optional[BaseException], note: str = "") -> str:
        self.failure_count += 1
        target = self.work / "falhas" / f"{scenario}-{self.failure_count}-{cls}"
        target.mkdir(parents=True, exist_ok=True)
        procs = processes()
        diag = {
            "classe": cls, "cenario": scenario, "nota": note, "url": mask_url(url) if url else None,
            "tempo_navegacao_s": round(secs, 2), "quando": now(), "versoes": versions(),
            "processos": process_summary(procs), "cgroup": cgroup_snapshot(), "cgroup_inicio": self.cg_start,
            "dev_shm": shm_usage(), "servicos": service_state(procs),
        }
        if session is not None:
            diag["driver"] = dict(session.info)
            diag["chromedriver"] = {"pid": session.driver_pid(), "vivo": session.driver_alive(),
                                    "exit_code": session.driver_exit_code(), "status": session.driver_status()}
            diag["chrome"] = {"pids_da_sessao": sorted(session.browser_pids), "vivo": session.chrome_alive()}
            self._screenshot_and_console(session, target)
            if session.log_path.exists():
                self._copy_tail(session.log_path, target / "chromedriver.log")
        if exc is not None:
            (target / "traceback.txt").write_text(exception_text(exc), encoding="utf-8")
        (target / "diag.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2, default=str),
                                          encoding="utf-8")
        return str(target)

    @staticmethod
    def _copy_tail(src: Path, dst: Path, limit: int = 8 * 1024 * 1024) -> None:
        with contextlib.suppress(OSError):
            size = src.stat().st_size
            with open(src, "rb") as fh, open(dst, "wb") as out:
                if size > limit:
                    fh.seek(size - limit)
                    out.write(b"[... inicio cortado ...]\n")
                shutil.copyfileobj(fh, out)

    @staticmethod
    def _screenshot_and_console(session: Session, target: Path) -> None:
        def work():
            with contextlib.suppress(Exception):
                session.driver.save_screenshot(str(target / "screenshot.png"))
            with contextlib.suppress(Exception):
                logs = session.driver.get_log("browser")
                (target / "console.json").write_text(json.dumps(logs[-200:], ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

        if not session.driver_alive():
            return
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(20)

    # helpers dos cenários -----------------------------------------------------------------------
    def open(self, res: ScenarioResult, mode: str, tag: str, timeout: Optional[float] = None) -> Optional[Session]:
        log_path = self.work / f"chromedriver-{res.name}-{tag}.log"
        started = time.monotonic()
        try:
            session = Session(mode, log_path, timeout)
        except Exception as exc:  # noqa: BLE001
            cls = classify(exc)
            cls = SESSION_LOST if cls == UNKNOWN else cls
            where = self.collect(res.name, None, cls, "", time.monotonic() - started, exc, "criar sessão")
            if log_path.exists():
                self._copy_tail(log_path, Path(where) / "chromedriver.log")
            self.fail(res, cls, "", f"não abriu o browser: {type(exc).__name__}: {str(exc)[:200]}", where)
            return None
        res.details.setdefault("drivers", [])
        if session.info not in res.details["drivers"]:
            res.details["drivers"].append(session.info)
        if not session.info.get("chromedriver_da_imagem"):
            res.warnings.append(f"ChromeDriver diferente do da imagem: {session.info.get('chromedriver_exe')} "
                                f"({session.info.get('chromedriver_versao')})")
        return session

    def close(self, res: ScenarioResult, session: Session, discard_log: bool = True) -> None:
        state = session.quit()
        if state["erro_quit"]:
            res.warnings.append(f"quit: {state['erro_quit']}")
        if state["processos_residuais"]:
            self.fail(res, UNKNOWN, "", f"processos do browser vivos 10 s depois do quit: "
                      f"{', '.join(state['processos_residuais'])}", "")
        summary = process_summary()
        zombies = summary["zombies"]
        self.zombies_max = max(self.zombies_max, zombies)
        res.details["zombies_depois"] = zombies
        if discard_log and res.ok:
            with contextlib.suppress(OSError):
                session.log_path.unlink()

    def fail(self, res: ScenarioResult, cls: str, url: str, detail: str, where: str) -> None:
        res.ok = False
        res.failures.append({"classe": cls, "url": mask_url(url) if url else None, "detalhe": detail,
                             "diagnostico": where or None})
        say("❌", f"{res.name} ({res.mode}): {cls} {mask_url(url) if url else ''} — {detail}"
                  + (f" — diagnóstico em {where}" if where else ""))

    def nav_and_check(self, res: ScenarioResult, session: Session, exp: Expect, external: bool = False) -> bool:
        """Navega, valida e confere JS + driver vivo. Falha de site externo é aviso; do browser, falha."""
        nav = navigate(session, exp)
        res.nav_times.append(nav.secs)
        if not nav.ok:
            if nav.cls in BROWSER_CLASSES:
                oom = oom_kills(cgroup_snapshot()) - oom_kills(self.cg_start)
                cls = RESOURCE_EXHAUSTED if oom > 0 else nav.cls
                where = self.collect(res.name, session, cls, exp.url, nav.secs, nav.exc, nav.detail)
                self.fail(res, cls, exp.url, f"{nav.detail} (depois de {fmt_s(nav.secs)})", where)
                return False
            if external:
                res.warnings.append(f"{nav.cls} {mask_url(exp.url)}: {nav.detail} (site externo, não reprova)")
            else:
                where = self.collect(res.name, session, nav.cls, exp.url, nav.secs, nav.exc, nav.detail)
                self.fail(res, nav.cls, exp.url, nav.detail, where)
                return False
        problem = js_check(session) or health_check(session)
        if problem:
            err = RuntimeError(problem)
            cls = classify(err, session.driver_alive(), session.chrome_alive())
            cls = SESSION_LOST if cls == UNKNOWN else cls
            where = self.collect(res.name, session, cls, exp.url, nav.secs, err, problem)
            self.fail(res, cls, exp.url, problem, where)
            return False
        return True

    def finish(self, res: ScenarioResult, started: float) -> None:
        res.secs = time.monotonic() - started
        self.results.append(res)
        d = res.as_dict()
        if res.skipped:
            say("⏭️ ", f"{res.name} ({res.mode}): pulado — {res.skipped}")
            return
        nav = d["navegacoes"]
        timing = (f"{nav['n']} navegações, mediana {fmt_s(nav['mediana_s'])}, p95 {fmt_s(nav['p95_s'])}"
                  if nav else "sem navegações")
        say("✅" if res.ok else "❌", f"{res.name} ({res.mode}): {timing}, {fmt_s(res.secs)}"
            + (f", {len(res.warnings)} aviso(s)" if res.warnings else ""))
        for warning in res.warnings:
            say("⚠️ ", f"   {warning}")

    # cenários ------------------------------------------------------------------------------------
    def local_pages(self, srv: FaultServer) -> list:
        return [
            Expect(srv.url("/page/1"), "estavel-1", "Página 1", "/page/1"),
            Expect(srv.url("/redirect/2"), "estavel-destino", "Página destino", "/page/destino"),
            Expect(srv.url("/form"), "estavel-form", "Formulário", "/form"),
            Expect(srv.url("/slow/300"), "estavel-lenta-300", "Lenta", "/slow/300"),
            Expect(srv.url("/page/2"), "estavel-2", "Página 2", "/page/2"),
        ]

    def scenario_sequencial(self, srv: FaultServer) -> None:
        res, started = ScenarioResult("sequencial", self.args.mode), time.monotonic()
        session = self.open(res, self.args.mode, "s")
        if session:
            for rnd in range(self.args.rounds):
                for exp in self.local_pages(srv):
                    if not self.nav_and_check(res, session, exp):
                        break
                    if exp.url.endswith("/form") and not self.form_check(res, session, exp):
                        break
                if not res.ok:
                    break
            res.details["rodadas"] = self.args.rounds
            self.close(res, session)
        self.finish(res, started)

    def form_check(self, res: ScenarioResult, session: Session, exp: Expect) -> bool:
        try:
            field_el = session.driver.find_element("id", "campo")
            field_el.send_keys("rpa-worker")
            value = session.driver.execute_script("return document.getElementById('campo').value")
        except Exception as exc:  # noqa: BLE001
            cls = classify(exc, session.driver_alive(), session.chrome_alive())
            where = self.collect(res.name, session, cls, exp.url, 0, exc, "formulário")
            self.fail(res, cls, exp.url, f"formulário: {type(exc).__name__}", where)
            return False
        if value != "rpa-worker":
            self.fail(res, CONTENT_MISMATCH, exp.url, f"campo ficou {value!r}", "")
            return False
        return True

    def scenario_sessoes(self, srv: FaultServer) -> None:
        res, started = ScenarioResult("sessoes", self.args.mode), time.monotonic()
        starts = []
        for i in range(self.args.sessions):
            session = self.open(res, self.args.mode, f"n{i + 1}")
            if not session:
                break
            starts.append(session.start_secs)
            ok = all(self.nav_and_check(res, session, exp) for exp in self.local_pages(srv)[:2])
            self.close(res, session)
            if not ok or not res.ok:
                break
        res.details["sessoes"] = len(starts)
        res.details["partida_s"] = [round(s, 2) for s in starts]
        self.finish(res, started)

    def scenario_prolongada(self, srv: FaultServer) -> None:
        res, started = ScenarioResult("prolongada", self.args.mode), time.monotonic()
        session = self.open(res, self.args.mode, "p")
        samples = []
        if session:
            pages = self.local_pages(srv)
            deadline = time.monotonic() + self.args.duration
            next_sample, i = 0.0, 0
            while time.monotonic() < deadline and res.ok:
                if not self.nav_and_check(res, session, pages[i % len(pages)]):
                    break
                i += 1
                time.sleep(self.rng.uniform(0.2, 1.5))
                if time.monotonic() >= next_sample:
                    cg = cgroup_snapshot()
                    chrome = process_summary()["chrome"]
                    samples.append({"t_s": round(time.monotonic() - started), "memoria_mb": cg.get("memoria_mb"),
                                    "chrome_rss_mb": chrome["rss_mb"], "chrome_processos": chrome["processos"]})
                    next_sample = time.monotonic() + 15
            res.details["ciclos"] = i
            res.details["amostras"] = samples
            self.close(res, session)
        self.finish(res, started)

    def scenario_recuperacao(self, srv: FaultServer) -> None:
        res, started = ScenarioResult("recuperacao", self.args.mode), time.monotonic()
        session = self.open(res, self.args.mode, "r", timeout=self.args.page_load_timeout)
        outcomes = {}
        if session:
            faults = [
                ("lenta", Expect(srv.url("/slow/8000"), expect_class=NAVIGATION_TIMEOUT)),
                ("travada", Expect(srv.url("/hang"), expect_class=NAVIGATION_TIMEOUT)),
                ("conexao_cortada", Expect(srv.url("/drop"), expect_class=TCP_CONNECTION_ERROR)),
                ("http_500", Expect(srv.url("/status/500"), expect_class=HTTP_ERROR)),
                ("http_503", Expect(srv.url("/status/503"), expect_class=HTTP_ERROR)),
                ("redirecionamentos", Expect(srv.url("/redirect/3"), "estavel-destino", "Página destino",
                                             "/page/destino")),
            ]
            ok_page = Expect(srv.url("/page/ok"), "estavel-ok", "Página ok", "/page/ok")
            for name, exp in faults:
                nav = navigate(session, exp)
                got = nav.cls if not nav.ok else None
                outcomes[name] = {"classe": got, "esperada": exp.expect_class, "segundos": round(nav.secs, 2)}
                if got in BROWSER_CLASSES:
                    where = self.collect(res.name, session, got, exp.url, nav.secs, nav.exc, f"falha {name}")
                    self.fail(res, got, exp.url, f"{name}: {nav.detail}", where)
                    break
                if got != exp.expect_class:
                    self.fail(res, got or "OK", exp.url,
                              f"{name}: esperado {exp.expect_class or 'OK'}, veio {got or 'OK'} ({nav.detail})", "")
                # depois da falha controlada: driver vivo, sessão válida, navega de novo e roda JS
                if not self.nav_and_check(res, session, ok_page):
                    outcomes[name]["recuperou"] = False
                    break
                outcomes[name]["recuperou"] = True
            res.details["falhas_controladas"] = outcomes
            self.close(res, session)
        self.finish(res, started)

    def scenario_uc_especial(self, srv: FaultServer) -> None:
        """Regressão do SeleniumBase 4.58+: driver.get em página 4xx/5xx/reCAPTCHA no modo UC abre nova aba
        com window.open e fecha a atual; com o bloqueador de popups ativo, o Chrome fica sem abas, o
        ChromeDriver novo não acha página por 60 s e o próximo comando dá Connection refused."""
        mode = self.args.mode if self.args.mode.startswith("uc-") else "uc-headless"
        res, started = ScenarioResult("uc_especial", mode), time.monotonic()
        session = self.open(res, mode, "u")
        if session:
            steps = [
                Expect(srv.url("/page/1"), "estavel-1", "Página 1"),
                Expect(srv.url("/status/503"), expect_class=HTTP_ERROR),
                Expect(srv.url("/page/2"), "estavel-2", "Página 2"),
                Expect(srv.url("/captcha"), "estavel-captcha", "Verificação"),
                Expect(srv.url("/status/403"), expect_class=HTTP_ERROR),
                Expect(srv.url("/page/3"), "estavel-3", "Página 3"),
            ]
            for exp in steps:
                if exp.expect_class:
                    nav = navigate(session, exp)
                    res.nav_times.append(nav.secs)
                    if nav.cls != exp.expect_class:
                        cls = nav.cls or "OK"
                        where = self.collect(res.name, session, cls, exp.url, nav.secs, nav.exc, nav.detail) \
                            if nav.cls in BROWSER_CLASSES else ""
                        self.fail(res, cls, exp.url, f"esperado {exp.expect_class}: {nav.detail}", where)
                        break
                    problem = js_check(session) or health_check(session)
                    if problem:
                        err = RuntimeError(problem)
                        cls = classify(err, session.driver_alive(), session.chrome_alive())
                        cls = SESSION_LOST if cls == UNKNOWN else cls
                        where = self.collect(res.name, session, cls, exp.url, nav.secs, err, problem)
                        self.fail(res, cls, exp.url, f"{problem} (depois de {fmt_s(nav.secs)})", where)
                        break
                elif not self.nav_and_check(res, session, exp):
                    break
            res.details["abas"] = None
            with contextlib.suppress(Exception):
                res.details["abas"] = len(session.driver.window_handles)
            self.close(res, session)
        self.finish(res, started)

    def scenario_modos(self, srv: FaultServer) -> None:
        for mode in self.args.modes:
            res, started = ScenarioResult("modos", mode), time.monotonic()
            if mode.endswith("-headful") and not x_display_ready():
                res.skipped = "sem servidor X (USE_XVFB=1)"
                self.finish(res, started)
                continue
            session = self.open(res, mode, mode)
            if session:
                self.nav_and_check(res, session, self.local_pages(srv)[1])
                info = session.info
                say("🔎", f"   {mode}: ChromeDriver {info.get('chromedriver_versao')} {info.get('chromedriver_exe')} "
                          f"(sha256 {info.get('chromedriver_sha256')}, da imagem: "
                          f"{'sim' if info.get('chromedriver_da_imagem') else 'NÃO'}), Chrome "
                          f"{info.get('browser_versao')} {info.get('chrome_exe')}, partida {fmt_s(session.start_secs)}")
                self.close(res, session)
            self.finish(res, started)

    def scenario_externos(self, _srv: FaultServer) -> None:
        res, started = ScenarioResult("externos", self.args.mode), time.monotonic()
        urls = parse_external(os.getenv("STABILITY_EXTERNAL_URLS", ""))
        res.details["urls"] = [mask_url(e.url) for e in urls]
        session = self.open(res, self.args.mode, "e")
        if session:
            for _ in range(self.args.external_rounds):
                for exp in urls:
                    if not self.nav_and_check(res, session, exp, external=True):
                        break
                    time.sleep(1)  # baixo volume: no máximo ~1 requisição por segundo por site
                if not res.ok:
                    break
            self.close(res, session)
        self.finish(res, started)

    # execução ------------------------------------------------------------------------------------
    def run(self) -> int:
        say("🧪", f"Estabilidade do browser [{self.label}] modo {self.args.mode}, cenários "
                  f"{', '.join(self.args.scenarios)}")
        env = {"cgroup": self.cg_start, "dev_shm": shm_usage(), "servicos": service_state(processes()),
               "pid1": process_summary()["pid1"]}
        vers = versions()
        say("🏷️ ", f"selenium {vers.get('selenium')} · seleniumbase {vers.get('seleniumbase')} · Chrome "
                   f"{vers.get('chrome')} · ChromeDriver {vers.get('chromedriver')} · "
                   f"limite {env['cgroup'].get('memoria_limite_mb')} MB · shm {env['dev_shm'].get('total_mb')} MB · "
                   f"PID 1 {env['pid1']}")
        started = time.monotonic()
        with FaultServer() as srv:
            for name in self.args.scenarios:
                getattr(self, f"scenario_{name}")(srv)
        cg_end = cgroup_snapshot()
        local_failed = [r for r in self.results if not r.ok]
        report = {
            "label": self.label, "inicio": self.args.started_at, "fim": now(),
            "duracao_s": round(time.monotonic() - started, 1), "versoes": vers, "ambiente": env,
            "recursos": {"memoria_pico_mb": cg_end.get("memoria_pico_mb"),
                         "memoria_limite_mb": cg_end.get("memoria_limite_mb"),
                         "oom_kill": oom_kills(cg_end) - oom_kills(self.cg_start),
                         "memory_events": cg_end.get("memory_events"), "zombies_max": self.zombies_max,
                         "dev_shm": shm_usage()},
            "cenarios": [r.as_dict() for r in self.results],
            "resultado": "falha" if local_failed else "ok",
        }
        end = process_summary()
        report["recursos"]["zombies_fim"] = end["zombies"]
        report["recursos"]["zombies_lista"] = end["zombies_lista"]
        report["ambiente_fim"] = {"servicos": service_state(processes()), "chrome": end["chrome"]}
        if end["zombies"] > self.zombies_start:
            names: dict = {}
            for item in end["zombies_lista"]:
                key = item.split(":", 1)[1]
                names[key] = names.get(key, 0) + 1
            say("⚠️ ", f"{end['zombies']} processo(s) zombie no fim (PID 1: {end['pid1']}): "
                       + ", ".join(f"{n}× {k}" for k, n in names.items())
                       + (" — o UC deixa um ChromeDriver sem wait() a cada reconexão" if any("uc_driver" in k for k in names) else ""))
        if report["recursos"]["oom_kill"]:
            say("❌", f"o kernel matou {report['recursos']['oom_kill']} processo(s) por falta de memória (OOM)")
            report["resultado"] = "falha"
        path = self.out / f"{self.label}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        all_navs = sorted(t for r in self.results for t in r.nav_times)
        summary = {"label": self.label, "resultado": report["resultado"],
                   "cenarios": {f"{r.name}/{r.mode}": ("pulado" if r.skipped else "ok" if r.ok else "falha")
                                for r in self.results},
                   "classes": sorted({f["classe"] for r in self.results for f in r.failures}),
                   "navegacoes": len(all_navs),
                   "mediana_s": round(statistics.median(all_navs), 3) if all_navs else None,
                   "memoria_pico_mb": report["recursos"]["memoria_pico_mb"],
                   "oom_kill": report["recursos"]["oom_kill"], "zombies_max": self.zombies_max,
                   "relatorio": str(path)}
        say("📄", f"relatório: {path}")
        print("STABILITY_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
        return 0 if report["resultado"] == "ok" else 1


def parse_external(raw: str) -> list:
    """`url|texto esperado|fim da URL final`, separadas por espaço ou vírgula (padrão: EXTERNAL_DEFAULT)."""
    items = [x for x in re.split(r"[\s,]+", raw.strip()) if x] if raw.strip() else list(EXTERNAL_DEFAULT)
    out = []
    for item in items:
        parts = item.split("|")
        url = parts[0]
        if not re.match(r"^https?://", url):
            raise ValueError(f"URL externa inválida: {mask_url(url)}")
        out.append(Expect(url, parts[1] if len(parts) > 1 else "", "", parts[2] if len(parts) > 2 else ""))
    return out


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS),
                        help="cenários separados por vírgula (padrão: %(default)s)")
    parser.add_argument("--mode", default="uc-headless", choices=MODES,
                        help="modo dos cenários sequencial/sessoes/prolongada/recuperacao/externos")
    parser.add_argument("--modes", default=",".join(MODES),
                        help="modos do cenário 'modos' (headful só com DISPLAY)")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--duration", type=float, default=120, help="segundos da sessão prolongada")
    parser.add_argument("--page-load-timeout", type=float, default=4)
    parser.add_argument("--external", action="store_true", help="inclui o cenário 'externos'")
    parser.add_argument("--external-rounds", type=int, default=1)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--label", default="estabilidade")
    args = parser.parse_args(argv)
    args.scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    if args.external and "externos" not in args.scenarios:
        args.scenarios.append("externos")
    unknown = [s for s in args.scenarios if not hasattr(Runner, f"scenario_{s}")]
    if unknown:
        parser.error(f"cenário desconhecido: {', '.join(unknown)}")
    args.modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    bad = [m for m in args.modes if m not in MODES]
    if bad:
        parser.error(f"modo desconhecido: {', '.join(bad)}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.label):
        parser.error("--label só com letras, números, ponto, hífen e sublinhado")
    args.started_at = now()
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    return Runner(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
