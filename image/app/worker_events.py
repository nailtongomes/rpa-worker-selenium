#!/usr/bin/env python3
"""Eventos do worker para quem acompanha de fora (todos opcionais, desligados por padrão).

Chamado pelo entrypoint; nunca muda o exit code do worker (falhas viram aviso no log).

    status  /app/logs/status.json (WORKER_STATUS=1): fase, iteração, última execução, contadores,
            tempo de partida dos serviços
    ping    sinal de vida por execução (PING_URL ou PING_URL_FILE), no formato do healthchecks.io:
            <url>/start antes, <url>/<exit code> depois (0 = ok). Com {evento}, {status} ou
            {exit_code} na URL, ela vira um modelo (Uptime Kuma, Cronitor...)
    screens telas do Xvfb para a falha (SCREENSHOT_ON_FAIL=1): ``watch`` guarda as últimas durante a
            execução; ``keep`` tira a última e move tudo para /app/logs/falhas/<data>/
    post    fim do container (LOG_POST_URL ou LOG_POST_URL_FILE): POST com as últimas
            LOG_POST_LINES linhas do log, exit code, duração e resumo de recursos; com
            LOG_POST_FULL=1 (ou telas da falha) vira multipart com worker.txt e as telas

A URL (com token no caminho ou na query) nunca aparece no log: só esquema e host, e com o relay de saída configurado nada sai direto.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from urllib.parse import urlsplit  # noqa: E402

from script_downloader import get_filename_from_url  # noqa: E402

STATUS_FILE = Path(os.getenv("WORKER_STATUS_FILE", "/app/logs/status.json"))
WORKER_LOG = Path(os.getenv("WORKER_LOG", "/app/logs/worker.log"))
FAILURES_DIR = Path("/app/logs/falhas")
IMAGE_INFO = Path("/app/image_info.json")
FULL_LOG_MAX = 20 * 1024 * 1024  # anexo worker.txt: no máximo os últimos 20 MB
PING_TIMEOUT = 10
WATCH_FRAMES = 3  # telas guardadas durante a execução (as mais recentes)


def _timestamp() -> str:
    return time.strftime("[%Y-%m-%d %H:%M:%S]")


def say(message: str) -> None:
    print(f"{_timestamp()} {message}", flush=True)


def now_iso(offset: float = 0) -> str:
    moment = dt.datetime.now().astimezone() + dt.timedelta(seconds=offset)
    return moment.isoformat(timespec="seconds")


def hide_url(url: str) -> str:
    """Só esquema e host: em ping e webhook o segredo costuma ficar no caminho
    (UUID do healthchecks.io, token do Uptime Kuma, id do webhook do n8n)."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "***"
    return f"{parts.scheme}://{host}{port}/***"


def hide_text(text: str, url: str) -> str:
    """Mensagem de erro sem a URL: inteira, só o caminho (urllib3) ou userinfo."""
    text = str(text)
    try:
        parts = urlsplit(url)
    except ValueError:
        parts = None
    if parts:
        tail = parts.path + (f"?{parts.query}" if parts.query else "")
        for secret in (url, tail, parts.path, parts.query, parts.netloc.rpartition("@")[0]):
            if secret and secret != "/":
                text = text.replace(secret, "/***" if secret in (tail, parts.path) else "***")
    return re.sub(r"https?://[^\s'\"<>]+", lambda m: hide_url(m.group(0)), text)


def secret_url(name: str) -> Optional[str]:
    """<NAME>_FILE (preferido: não aparece no docker inspect) ou <NAME>; None se desligado."""
    url_file = os.getenv(f"{name}_FILE", "")
    if url_file:
        try:
            return Path(url_file).read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            say(f"⚠️  não foi possível ler {name}_FILE ({url_file}): {exc.strerror}")
            return None
    return os.getenv(name, "").strip() or None


def egress_blocked() -> bool:
    """Relay configurado mas ainda não ligado (o container parou antes): não sai direto."""
    configured = os.getenv("EGRESS_PROXY_URL") or os.getenv("EGRESS_PROXY_URL_FILE")
    ready = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
    return bool(configured) and not ready


def script_name() -> str:
    url = os.getenv("SCRIPT_URL", "")
    if not url:
        return ""
    try:
        return get_filename_from_url(url)
    except Exception:  # noqa: BLE001 - só identificação
        return ""


def image_revision() -> dict:
    try:
        info = json.loads(IMAGE_INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: info[k] for k in ("tag", "revisao", "criada_em", "arquitetura") if k in info}


# --- status -------------------------------------------------------------------

def parse_value(raw: str):
    """``@now`` = agora; ``@in:N`` = daqui a N s; números viram números; o resto, texto."""
    if raw == "@now":
        return now_iso()
    if raw.startswith("@in:"):
        try:
            return now_iso(float(raw[4:]))
        except ValueError:
            return raw
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    if re.fullmatch(r"-?\d+\.\d+", raw):
        return float(raw)
    return raw


def apply_updates(status: dict, updates: list) -> dict:
    """``a.b=valor`` grava, ``+a.b`` soma 1, ``~a`` apaga. Mudar ``fase`` atualiza ``desde``."""
    for item in updates:
        if item.startswith("+") or item.startswith("~"):
            key, value = item[1:], None
        elif "=" in item:
            key, raw = item.split("=", 1)
            value = parse_value(raw)
        else:
            continue
        *parents, leaf = key.split(".")
        node = status
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        if item.startswith("+"):
            node[leaf] = int(node.get(leaf) or 0) + 1
        elif item.startswith("~"):
            node.pop(leaf, None)
        else:
            if key == "fase" and status.get("fase") != value:
                status["desde"] = now_iso()
            node[leaf] = value
    status["atualizado_em"] = now_iso()
    return status


def read_status(path: Optional[Path] = None) -> dict:
    path = path or STATUS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(status: dict, path: Optional[Path] = None) -> None:
    """Troca atômica: quem lê nunca vê o arquivo pela metade."""
    path = path or STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def cmd_status(args) -> int:
    if args.init:
        status = {"container": socket.gethostname(), "imagem": image_revision(),
                  "script": script_name(), "iniciado_em": now_iso(),
                  "contadores": {"ok": 0, "falha": 0, "tempo_esgotado": 0, "sem_trabalho": 0}}
    else:
        status = read_status()
    write_status(apply_updates(status, args.updates))
    return 0


# --- ping ---------------------------------------------------------------------

def ping_url(base: str, event: str, exit_code: Optional[int]) -> str:
    """healthchecks.io: <url>/start e <url>/<exit code>; com {evento}/{status}/{exit_code}, modelo."""
    if any(f"{{{key}}}" in base for key in ("evento", "status", "exit_code")):
        status = "down" if event == "fail" else "up"
        return (base.replace("{evento}", event).replace("{status}", status)
                .replace("{exit_code}", "" if exit_code is None else str(exit_code)))
    base = base.rstrip("/")
    return f"{base}/start" if event == "start" else f"{base}/{exit_code if exit_code is not None else 0}"


def cmd_ping(args) -> int:
    base = secret_url("PING_URL")
    if not base:
        return 0
    if egress_blocked():
        say("⚠️  PING_URL: relay de saída ainda não ligado, o ping não sai direto")
        return 0
    import requests  # noqa: PLC0415 - só quando há ping

    exit_code = args.exit_code
    event = "start" if args.event == "start" else ("ok" if exit_code == 0 else "fail")
    url = ping_url(base, event, exit_code)
    try:
        response = requests.get(url, timeout=PING_TIMEOUT)
        if response.status_code >= 400:
            say(f"⚠️  PING_URL respondeu HTTP {response.status_code} ({hide_url(url)})")
    except requests.RequestException as exc:
        say(f"⚠️  PING_URL falhou: {hide_text(exc, url)}")
    return 0


# --- telas --------------------------------------------------------------------

def grab_screen(target: Path, display: str) -> bool:
    """Tela inteira do Xvfb em JPEG (Pillow; ``import`` do ImageMagick se o Pillow não tiver X11)."""
    try:
        from PIL import ImageGrab  # noqa: PLC0415

        ImageGrab.grab(xdisplay=display).convert("RGB").save(target, "JPEG", quality=85)
        return True
    except Exception:  # noqa: BLE001 - tenta o ImageMagick
        pass
    if shutil.which("import"):
        result = subprocess.run(["import", "-display", display, "-window", "root", "-quality", "85",
                                 str(target)], capture_output=True, timeout=30, check=False)
        return result.returncode == 0 and target.exists()
    return False


def frames(directory: Path) -> list:
    return sorted(directory.glob("tela-*.jpg"))


def cmd_screens_watch(args) -> int:
    """Durante a execução: uma tela a cada ``--interval`` s, só as últimas WATCH_FRAMES ficam."""
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        target = directory / f"tela-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
        grab_screen(target, args.display)
        for old in frames(directory)[:-WATCH_FRAMES]:
            old.unlink(missing_ok=True)
        time.sleep(args.interval)


def cmd_screens_keep(args) -> int:
    """Falhou: tira a última tela e guarda as da execução em /app/logs/falhas/<data>/."""
    directory = Path(args.dir)
    directory.mkdir(parents=True, exist_ok=True)
    grab_screen(directory / f"tela-{time.strftime('%Y%m%d-%H%M%S')}-fim.jpg", args.display)
    saved = frames(directory)
    if not saved:
        say("⚠️  SCREENSHOT_ON_FAIL: não foi possível capturar a tela")
        return 0
    dest = Path(args.to) / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for frame in saved:
        shutil.move(str(frame), dest / frame.name)
    shutil.rmtree(directory, ignore_errors=True)
    old_dirs = sorted(p for p in Path(args.to).iterdir() if p.is_dir())
    for old in old_dirs[:-max(args.keep, 1)]:
        shutil.rmtree(old, ignore_errors=True)
    say(f"📸 Tela da falha: {dest} ({len(saved)} imagem(ns))")
    return 0


# --- post ---------------------------------------------------------------------

def tail_lines(path: Path, count: int) -> list:
    """Últimas ``count`` linhas sem ler o arquivo inteiro."""
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block, data = 64 * 1024, b""
            while size > 0 and data.count(b"\n") <= count:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    return lines[-count:]


def last_resource_summary(path: Path) -> Optional[dict]:
    summary = None
    for line in tail_lines(path, 5000):
        if line.startswith("RESOURCE_SUMMARY "):
            try:
                summary = json.loads(line.split(" ", 1)[1])
            except ValueError:
                pass
    return summary


def failure_screens(started_at: float) -> list:
    """Telas da última falha desta execução do container (nenhuma de execuções anteriores)."""
    if not FAILURES_DIR.is_dir():
        return []
    dirs = sorted(p for p in FAILURES_DIR.iterdir() if p.is_dir() and p.stat().st_mtime >= started_at)
    return frames(dirs[-1]) if dirs else []


def int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value >= minimum else default


def build_report(exit_code: int, stopped: bool, mode: str, started_at: float, lines: int) -> dict:
    ended = time.time()
    tail = tail_lines(WORKER_LOG, lines)
    if stopped:
        reason = "parado"
    else:
        reason = "concluido" if exit_code == 0 else "falha"
    report = {
        "evento": "fim_do_container",
        "container": socket.gethostname(),
        "worker_id": os.getenv("WORKER_ID", ""),
        "imagem": image_revision(),
        "modo": mode,
        "script": script_name(),
        "exit_code": exit_code,
        "motivo": reason,
        "inicio": dt.datetime.fromtimestamp(started_at).astimezone().isoformat(timespec="seconds"),
        "fim": dt.datetime.fromtimestamp(ended).astimezone().isoformat(timespec="seconds"),
        "duracao_s": round(max(ended - started_at, 0), 1),
        "recursos": last_resource_summary(WORKER_LOG),
        "linhas": len(tail),
        "log": "\n".join(tail),
    }
    if os.getenv("WORKER_STATUS") == "1":
        report["status"] = read_status()
    return report


def full_log() -> bytes:
    try:
        with WORKER_LOG.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(size - FULL_LOG_MAX, 0))
            return fh.read()
    except OSError:
        return b""


def cmd_post(args) -> int:
    url = secret_url("LOG_POST_URL")
    if not url:
        return 0
    if egress_blocked():
        say("⚠️  LOG_POST_URL: relay de saída ainda não ligado, o log não sai direto")
        return 0
    import requests  # noqa: PLC0415

    time.sleep(0.3)  # o tee termina de gravar as últimas linhas
    deadline = time.monotonic() + max(args.timeout, 1)
    report = build_report(args.exit_code, args.stopped, args.mode, args.started_at,
                          int_env("LOG_POST_LINES", 100))
    files = {}
    if os.getenv("LOG_POST_FULL") == "1":
        files["log"] = ("worker.txt", full_log(), "text/plain; charset=utf-8")
    screens = failure_screens(args.started_at) if os.getenv("SCREENSHOT_ON_FAIL") == "1" else []
    for i, frame in enumerate(screens, 1):
        files[f"tela_{i}"] = (frame.name, frame.read_bytes(), "image/jpeg")
    if screens:
        report["telas"] = [frame.name for frame in screens]

    extras = []
    if "log" in files:
        extras.append("worker.txt")
    if screens:
        extras.append(f"{len(screens)} tela(s)")
    what = f"{report['linhas']} linhas" + (" + " + " + ".join(extras) if extras else "")

    attempt = 0
    while True:
        attempt += 1
        remaining = deadline - time.monotonic()
        try:
            if files:
                response = requests.post(url, data={"dados": json.dumps(report, ensure_ascii=False)},
                                         files=files, timeout=max(remaining, 1))
            else:
                response = requests.post(url, json=report, timeout=max(remaining, 1))
            if response.status_code < 400:
                say(f"📤 Log enviado para {hide_url(url)} (HTTP {response.status_code}, {what})")
                return 0
            problem = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            problem = hide_text(exc, url)
        if attempt >= 3 or deadline - time.monotonic() < 2:
            say(f"⚠️  Não foi possível enviar o log para {hide_url(url)}: {problem}")
            return 0
        time.sleep(1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="atualiza /app/logs/status.json")
    p.add_argument("--init", action="store_true", help="começa um arquivo novo")
    p.add_argument("updates", nargs="*", help="chave.sub=valor, +contador, ~chave")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ping", help="sinal de vida (PING_URL)")
    p.add_argument("event", choices=["start", "end"])
    p.add_argument("--exit-code", type=int, default=None)
    p.set_defaults(func=cmd_ping)

    p = sub.add_parser("screens", help="telas do Xvfb para a falha")
    p.add_argument("action", choices=["watch", "keep"])
    p.add_argument("--dir", default="/app/tmp/telas")
    p.add_argument("--to", default=str(FAILURES_DIR))
    p.add_argument("--display", default=os.getenv("DISPLAY", ":99"))
    p.add_argument("--interval", type=float, default=10)
    p.add_argument("--keep", type=int, default=20)
    p.set_defaults(func=lambda a: cmd_screens_watch(a) if a.action == "watch" else cmd_screens_keep(a))

    p = sub.add_parser("post", help="envia o log no fim do container (LOG_POST_URL)")
    p.add_argument("--exit-code", type=int, required=True)
    p.add_argument("--stopped", action="store_true", help="parado por sinal (docker stop)")
    p.add_argument("--mode", default="")
    p.add_argument("--started-at", type=float, default=time.time())
    p.add_argument("--timeout", type=float, default=8)
    p.set_defaults(func=cmd_post)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - observabilidade nunca derruba o worker
        say(f"⚠️  worker_events {args.command}: {exc}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
