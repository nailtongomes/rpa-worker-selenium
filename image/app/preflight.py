#!/usr/bin/env python3
"""
preflight — "este worker está pronto para trabalhar?" num comando só, com um JSON só.

    docker exec worker-01 python /app/preflight.py --json /data/preflight.json
    docker run --rm --shm-size=2g -e USE_XVFB=1 ... ghcr.io/nailtongomes/rpa-worker-selenium:latest \\
      python /app/preflight.py

Junta três verificações (cada uma também existe sozinha):
  1. browsers   Chrome (Selenium), Chrome (SeleniumBase UC) e Firefox abrem uma página
                local; com servidor X (USE_XVFB=1) em modo janela, senão headless.
                Com --url, o Chrome também abre essas URLs (pela saída configurada).
  2. a1         /app/a1_check.py, se houver A1_PFX_URL/A1_PFX_PATH (ou --a1 on / self-test).
  3. egress     /app/egress_check.py, se houver EGRESS_PROXY_URL (ou --egress on).

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
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.server
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from script_downloader import mask_text, mask_url  # noqa: E402

APP = Path(__file__).resolve().parent
PAGE_TITLE = "PREFLIGHT-OK"
SYMBOL = {"ok": "✅", "aviso": "⚠️ ", "erro": "❌", "pulado": "⏭️ "}


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
        try:
            detail = fn()
            steps.append({"status": "ok", "passo": step, "detalhe": detail})
        except Exception as exc:  # noqa: BLE001 - o relatório precisa continuar
            steps.append({"status": "erro", "passo": step,
                          "detalhe": f"{type(exc).__name__}: {mask_text(exc, *urls)[:300]}"})

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
    args = parser.parse_args(argv)

    browsers = [b.strip() for b in args.browsers.split(",") if b.strip() and b.strip() != "none"]
    started = time.time()
    checks = {}

    print("🛫 Preflight do worker\n", flush=True)
    print("== browsers ==", flush=True)
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
        print(f"{SYMBOL[status]} {name}")
    print("\n✅ worker pronto" if ok else f"\n❌ worker NÃO está pronto ({report['falhas']} falha(s))")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
