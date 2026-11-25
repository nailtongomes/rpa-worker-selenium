#!/usr/bin/env python3
"""
preflight — "este worker está pronto para trabalhar?" num comando só, com um JSON só.

    docker exec worker-01 python /app/preflight.py --json /data/preflight.json
    docker run --rm --shm-size=2g -e USE_XVFB=1 ... ghcr.io/nailtongomes/rpa-worker-selenium:latest \\
      python /app/preflight.py

Começa pelo ambiente do container (só avisos, nunca falha): /dev/shm, disco livre, limite de
memória e de CPU e o relógio (comparado com o horário de um servidor HTTPS, pela saída
configurada). A imagem (revisão, arquitetura, browsers) vai no JSON em "imagem".

Junta três verificações (cada uma também existe sozinha):
  1. browsers   Chrome (Selenium), Chrome (SeleniumBase UC) e Firefox abrem uma página
                local; com servidor X (USE_XVFB=1) em modo janela, senão headless.
                Com --url, o Chrome também abre essas URLs (pela saída configurada).
  2. a1         /app/a1_check.py, se houver A1_PFX_URL/A1_PFX_PATH (ou --a1 on / self-test).
                Com o PJeOffice ligado (USE_PJEOFFICE=1), inclui o teste de assinatura dele
                (/app/pjeoffice_check.py: o botão "Testar" da página local).
  3. egress     /app/egress_check.py, se houver EGRESS_PROXY_URL (ou --egress on).

Cada browser/URL tem uma nova tentativa: abrir só na segunda vira aviso (máquina com
pouca CPU), não falha.

Exit 0 se nada falhou (avisos não falham), 1 caso contrário. O JSON junta os
relatórios de cada parte em "verificacoes" (para Kestra/monitoramento). Senhas
nunca aparecem: a1_check e egress_check já as omitem e as URLs vão mascaradas.

Opções:
    --json ARQUIVO          grava o relatório combinado
    --browsers LISTA        chrome,uc,firefox (padrão) ou "none"
    --a1 auto|on|off|self-test       padrão auto
    --egress auto|on|off             padrão auto
    --url URL               (repetível) URL que o worker precisa alcançar
    --insecure              aceita certificado TLS inválido (relay de teste, homologação)
    --clock-url URL         servidor para conferir o relógio (padrão PREFLIGHT_CLOCK_URL ou
                            https://www.google.com/generate_204; "off" não confere)
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import http.server
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import image_info  # noqa: E402
import resource_usage  # noqa: E402
from script_downloader import mask_text, mask_url  # noqa: E402

APP = Path(__file__).resolve().parent
PAGE_TITLE = "PREFLIGHT-OK"
SYMBOL = {"ok": "✅", "aviso": "⚠️ ", "erro": "❌", "pulado": "⏭️ "}
BROWSER_TRIES = 2  # 1 nova tentativa por browser/URL (ver attempt)

GB = 1024 ** 3
SHM_MIN = 1 * GB            # Chrome usa /dev/shm; o padrão do Docker (64 MB) derruba abas
DISK_MIN = 2 * GB           # perfis, downloads, gravações e logs
MEMORY_MIN = 1 * GB         # browsers
MEMORY_MIN_PJEOFFICE = 2 * GB  # browsers + PJeOffice (pico medido ~1,1 GB)
BROWSER_MEMORY = 1 * GB     # o que sobra do container para Chrome/Xvfb/script além do Java do PJeOffice
CLOCK_MAX_SKEW = 30         # segundos; TLS tolera mais, mas tokens e códigos de login não
CLOCK_URL = "https://www.google.com/generate_204"


def _has_display() -> bool:
    try:
        return subprocess.run(["xdpyinfo", "-display", os.getenv("DISPLAY", ":99")],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _cmd_version(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def versions() -> dict:
    from importlib import metadata

    out = {
        "chrome": _cmd_version(["chrome", "--version"]),
        "chromedriver": _cmd_version(["chromedriver", "--version"]).split(" (")[0],
        "firefox": _cmd_version(["firefox", "--version"]),
        "geckodriver": _cmd_version(["geckodriver", "--version"]).splitlines()[0:1],
        "python": platform.python_version(),
    }
    out["geckodriver"] = out["geckodriver"][0] if out["geckodriver"] else ""
    for pkg in ("selenium", "seleniumbase"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = ""
    return out


class _LocalPage:
    """Página em 127.0.0.1 (não depende de internet nem do relay)."""

    def __enter__(self) -> str:
        body = f"<html><head><title>{PAGE_TITLE}</title></head><body>preflight</body></html>".encode()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def __exit__(self, *exc) -> None:
        self.server.shutdown()


def _open_title(driver, url: str, wait_for: str = "") -> str:
    try:
        driver.set_page_load_timeout(60)
        driver.get(url)
        for _ in range(20):
            if driver.title and (not wait_for or driver.title == wait_for):
                break
            time.sleep(0.5)
        return driver.title
    finally:
        driver.quit()


def check_browsers(names: list, urls: list, insecure: bool) -> dict:
    import egress_check as ec

    openers = {"chrome": ("Chrome (Selenium)", ec._chrome), "uc": ("Chrome (SeleniumBase UC)", ec._uc),
               "firefox": ("Firefox", ec._firefox)}
    windowed = _has_display()
    mode = "janela" if windowed else "headless"
    steps = []

    def run(step: str, fn) -> None:
        steps.append(attempt(step, fn, urls))

    with _LocalPage() as page:
        for name in names:
            if name not in openers:
                steps.append({"status": "erro", "passo": name, "detalhe": "browser desconhecido"})
                continue
            label, opener = openers[name]

            def visit(opener=opener):
                title = _open_title(opener(not windowed, insecure), page, PAGE_TITLE)
                if title != PAGE_TITLE:
                    raise RuntimeError(f"página local não abriu (título: {title!r})")
                return f"página local aberta ({mode})"

            run(f"{label} abre página local", visit)

    for url in urls:
        def reach(url=url):
            title = _open_title(ec._chrome(True, insecure), url)
            return f"título: {title[:80]!r}"

        run(f"Chrome abre {mask_url(url)}", reach)
    return _summary(steps)


def attempt(step: str, fn, urls: list = (), tries: int = BROWSER_TRIES) -> dict:
    """Roda ``fn`` até ``tries`` vezes. Passar só numa nova tentativa é aviso, não erro:
    com pouca CPU (ex.: 1 núcleo no shutup-and-run, PJeOffice subindo junto) a primeira
    abertura de um browser pode estourar o tempo e a segunda abrir normalmente."""
    first_error = ""
    for n in range(1, tries + 1):
        started = time.time()
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - o relatório precisa continuar
            error = f"{type(exc).__name__}: {mask_text(exc, *urls)[:300]}"
            first_error = first_error or error
            if n == tries:
                return {"status": "erro", "passo": step, "detalhe": error}
            continue
        took = f"{time.time() - started:.0f}s"
        if n == 1:
            return {"status": "ok", "passo": step, "detalhe": f"{detail} [{took}]"}
        return {"status": "aviso", "passo": step,
                "detalhe": f"{detail} [{took}] na tentativa {n}; antes: {first_error[:200]} "
                           "(browser lento: pouca CPU ou máquina ocupada)"}
    raise AssertionError("tries precisa ser >= 1")


def _gb(value: float) -> str:
    return f"{value / GB:.1f} GB".replace(".", ",")


def _env_step(step: str, ok: bool, detail: str, advice: str = "") -> dict:
    if ok:
        return {"status": "ok", "passo": step, "detalhe": detail}
    return {"status": "aviso", "passo": step, "detalhe": f"{detail}: {advice}" if advice else detail}


def pjeoffice_xmx() -> tuple:
    """(-Xmx efetivo do Java do PJeOffice em bytes, de onde veio); (None, "") se não der para saber."""
    value, origin = os.getenv("PJEOFFICE_JAVA_XMX", "").strip(), "PJEOFFICE_JAVA_XMX"
    if not value:
        launcher = os.getenv("PJEOFFICE_EXECUTABLE", "/opt/pjeoffice/pjeoffice-pro.sh")
        try:
            match = re.search(r"-Xmx(\d+[mMgG])\b", Path(launcher).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None, ""
        value, origin = (match.group(1) if match else ""), "launcher do PJeOffice"
    match = re.fullmatch(r"(\d+)([mMgG])", value)
    if not match:
        return None, ""
    return int(match.group(1)) * (GB if match.group(2) in "gG" else 1024 ** 2), origin


def _egress_configured() -> bool:
    return bool(os.getenv("EGRESS_PROXY_URL") or os.getenv("EGRESS_PROXY_URL_FILE"))


def clock_offset(url: str, timeout: float = 10) -> tuple:
    """(segundos que o relógio local está à frente do servidor, ida e volta em s).

    Com o relay de saída configurado, a consulta passa pelo repassador local (nunca sai
    direto); sem ele, usa a saída normal do container."""
    if _egress_configured():
        local = f"http://127.0.0.1:{os.getenv('EGRESS_LOCAL_PORT', '3128')}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": local, "https": local}))
    else:
        opener = urllib.request.build_opener()
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "rpa-worker-preflight"})
    sent = time.time()
    try:
        with opener.open(request, timeout=timeout) as resp:
            header = resp.headers.get("Date")
    except urllib.error.HTTPError as exc:  # 4xx/5xx também trazem a hora do servidor
        header = exc.headers.get("Date")
    received = time.time()
    if not header:
        raise RuntimeError("o servidor não informou a hora (cabeçalho Date)")
    # Date vem truncado no segundo: o horário real do servidor está, em média, 0,5 s depois
    server = email.utils.parsedate_to_datetime(header).timestamp() + 0.5
    return (sent + received) / 2 - server, received - sent


def check_environment(clock_url: str = CLOCK_URL) -> dict:
    """O container tem o que os browsers precisam? Só avisos: nada aqui reprova o worker."""
    steps = []
    info = image_info.load()
    steps.append({"status": "ok", "passo": "imagem", "detalhe": image_info.summary_line(info)})

    try:
        st = os.statvfs("/dev/shm")
        shm = st.f_blocks * st.f_frsize
        steps.append(_env_step("/dev/shm", shm >= SHM_MIN * 0.95, _gb(shm),
                               "pouco para o Chrome (abas travam com 'page crash'); use --shm-size=1g ou mais"))
    except OSError as exc:
        steps.append(_env_step("/dev/shm", False, f"não deu para ler ({exc})", "o Chrome usa /dev/shm"))

    seen = set()
    for path in ("/tmp", "/app"):
        try:
            st = os.statvfs(path)
            device = os.stat(path).st_dev
        except OSError:
            continue
        if device in seen:
            continue
        seen.add(device)
        free = st.f_bavail * st.f_frsize
        steps.append(_env_step(f"disco livre em {path}", free >= DISK_MIN, _gb(free),
                               f"abaixo de {_gb(DISK_MIN)}; perfis, downloads e logs podem lotar o disco"))

    cg = resource_usage.Cgroup.detect()
    lim = resource_usage.limits(cg)
    pjeoffice = os.getenv("USE_PJEOFFICE") == "1"
    need = MEMORY_MIN_PJEOFFICE if pjeoffice else MEMORY_MIN
    used = cg.memory_bytes() if cg else None
    in_use = f", {resource_usage.fmt_mb(used / resource_usage.MB)} em uso agora" if used is not None else ""
    if lim["memoria_mb"]:
        limit = lim["memoria_mb"] * 1024 * 1024
        steps.append(_env_step("memória", limit >= need * 0.95, f"limite {_gb(limit)}{in_use}",
                               f"recomendado {_gb(need)} ou mais" + (" com o PJeOffice" if pjeoffice else "")
                               + "; abaixo disso o browser pode ser morto por falta de memória"))
    else:
        host = (lim["host_memoria_mb"] or 0) * 1024 * 1024
        steps.append(_env_step("memória", not host or host >= need,
                               f"sem limite no container (máquina: {_gb(host)}){in_use}",
                               f"a máquina tem menos que os {_gb(need)} recomendados"))

    xmx, xmx_origin = pjeoffice_xmx() if pjeoffice else (None, "")
    if xmx and lim["memoria_mb"]:
        limit = lim["memoria_mb"] * 1024 * 1024
        steps.append(_env_step("Java do PJeOffice", xmx + BROWSER_MEMORY <= limit * 1.05,
                               f"pode crescer até {_gb(xmx)} (-Xmx, {xmx_origin}) num container de {_gb(limit)}",
                               f"sobra menos de {_gb(BROWSER_MEMORY)} para o Chrome; se a memória apertar, limite com "
                               "PJEOFFICE_JAVA_XMX=512m (ele costuma usar 130-150 MB)"))

    cpus = lim["cpu_nucleos"]
    if cpus:
        steps.append(_env_step("CPU", cpus >= 0.95, f"limite {cpus:g} núcleo(s) (máquina: {lim['host_cpus']})",
                               "menos de 1 núcleo: browsers e PJeOffice ficam lentos e estouram tempos"))
    else:
        steps.append(_env_step("CPU", True, f"sem limite no container (máquina: {lim['host_cpus']} núcleo(s))"))

    if not clock_url or clock_url == "off":
        steps.append({"status": "pulado", "passo": "relógio", "detalhe": "conferência desligada"})
    else:
        try:
            offset, rtt = clock_offset(clock_url)
        except Exception as exc:  # noqa: BLE001 - sem internet não é problema do relógio
            steps.append({"status": "pulado", "passo": "relógio",
                          "detalhe": f"sem resposta de {mask_url(clock_url)} ({type(exc).__name__})"})
        else:
            side = "adiantado" if offset > 0 else "atrasado"
            detail = f"{abs(offset):.0f}s {side} em relação a {mask_url(clock_url)}"
            if rtt > 10:
                steps.append({"status": "pulado", "passo": "relógio",
                              "detalhe": f"{detail}, mas a resposta demorou {rtt:.0f}s (medida imprecisa)"})
            else:
                steps.append(_env_step("relógio", abs(offset) <= CLOCK_MAX_SKEW, detail,
                                       "acerte o relógio da máquina (NTP); hora errada quebra TLS, "
                                       "logins com código e a data das assinaturas"))
    summary = _summary(steps)
    summary["imagem"] = info
    summary["limites"] = lim
    return summary


def _summary(steps: list) -> dict:
    failures = sum(s["status"] == "erro" for s in steps)
    warnings = sum(s["status"] == "aviso" for s in steps)
    return {"ok": failures == 0, "falhas": failures, "avisos": warnings, "passos": steps}


def run_tool(script: str, args: list, timeout: int = 900) -> dict:
    """Roda a1_check/egress_check (saída ao vivo) e devolve o JSON que ele grava."""
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        report = Path(tmp) / "report.json"
        try:
            proc = subprocess.run([sys.executable, str(APP / script), *args, "--json", str(report)], timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "falhas": 1, "avisos": 0,
                    "passos": [{"status": "erro", "passo": script, "detalhe": f"não terminou em {timeout}s"}]}
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"passos": [{"status": "erro", "passo": script, "detalhe": "não gerou relatório"}]}
    # o exit code manda: um relatório "ok" com exit != 0 ainda é falha
    data["ok"] = proc.returncode == 0 and data.get("ok", False)
    if not data["ok"] and not data.get("falhas"):
        data["falhas"] = 1
    data["exit_code"] = proc.returncode
    return data


def _enabled(mode: str, env_names: tuple) -> bool:
    if mode == "auto":
        return any(os.getenv(n) for n in env_names)
    return mode != "off"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json")
    parser.add_argument("--browsers", default="chrome,uc,firefox")
    parser.add_argument("--a1", choices=["auto", "on", "off", "self-test"], default="auto")
    parser.add_argument("--egress", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--clock-url", default=os.getenv("PREFLIGHT_CLOCK_URL") or CLOCK_URL)
    args = parser.parse_args(argv)

    browsers = [b.strip() for b in args.browsers.split(",") if b.strip() and b.strip() != "none"]
    started = time.time()
    checks = {}

    print("🛫 Preflight do worker\n", flush=True)
    print("== ambiente ==", flush=True)
    checks["ambiente"] = check_environment(args.clock_url)
    for step in checks["ambiente"]["passos"]:
        print(f"{SYMBOL[step['status']]} {step['passo']}: {step['detalhe']}", flush=True)

    print("\n== browsers ==", flush=True)
    if browsers or args.url:
        checks["browsers"] = check_browsers(browsers, args.url, args.insecure)
        for step in checks["browsers"]["passos"]:
            print(f"{SYMBOL[step['status']]} {step['passo']}: {step['detalhe']}", flush=True)
    else:
        checks["browsers"] = {"ok": True, "pulado": True, "motivo": "--browsers none"}

    print("\n== certificado A1 ==", flush=True)
    if _enabled(args.a1, ("A1_PFX_URL", "A1_PFX_PATH")):
        a1_args = ["--browsers", ",".join(browsers) or "none"]
        if args.a1 == "self-test":
            a1_args.append("--self-test")
        checks["a1"] = run_tool("a1_check.py", a1_args)
    else:
        checks["a1"] = {"ok": True, "pulado": True, "motivo": "A1_PFX_URL/A1_PFX_PATH não definidos"}
        print(f"{SYMBOL['pulado']} {checks['a1']['motivo']}", flush=True)

    print("\n== saída de internet (relay) ==", flush=True)
    if _enabled(args.egress, ("EGRESS_PROXY_URL", "EGRESS_PROXY_URL_FILE")):
        eg_args = ["--browsers", ",".join(browsers) or "none"]
        for url in args.url:
            eg_args += ["--url", url]
        if args.insecure:
            eg_args.append("--insecure")
        checks["egress"] = run_tool("egress_check.py", eg_args)
    else:
        checks["egress"] = {"ok": True, "pulado": True, "motivo": "EGRESS_PROXY_URL não definido (saída direta)"}
        print(f"{SYMBOL['pulado']} {checks['egress']['motivo']}", flush=True)

    ok = all(c.get("ok") for c in checks.values())
    report = {
        "ok": ok,
        "gerado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "duracao_s": round(time.time() - started, 1),
        "host": platform.node(),
        "imagem": checks["ambiente"]["imagem"],
        "versoes": versions(),
        "falhas": sum(c.get("falhas", 0) for c in checks.values()),
        "avisos": sum(c.get("avisos", 0) for c in checks.values()),
        "verificacoes": checks,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== resumo ==")
    for name, result in checks.items():
        status = "pulado" if result.get("pulado") else ("ok" if result.get("ok") else "erro")
        if status == "ok" and result.get("avisos"):
            status = "aviso"
        print(f"{SYMBOL[status]} {name}")
    print("\n✅ worker pronto" if ok else f"\n❌ worker NÃO está pronto ({report['falhas']} falha(s))")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
