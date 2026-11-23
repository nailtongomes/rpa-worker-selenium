#!/usr/bin/env python3
"""
egress_check — confere se TODO o tráfego do container sai pelo relay.

Rode no container já configurado (o entrypoint sobe o repassador quando
EGRESS_PROXY_URL está definido):

    docker run --rm --shm-size=2g -e USE_XVFB=1 \\
      -e EGRESS_PROXY_URL_FILE=/run/secrets/relay -v "$PWD/relay-url.txt:/run/secrets/relay:ro" \\
      -e EGRESS_EXPECTED_IP=200.200.200.200 \\
      ghcr.io/nailtongomes/rpa-worker-selenium:latest \\
      python /app/egress_check.py --url https://pje.tjrn.jus.br/pje/login.seam

Passos: configuração aplicada (repassador, variáveis, policies do Chrome/Firefox,
Java) → IP de saída visto por Python, Chrome, SeleniumBase UC, Firefox e Java
(PJeOffice) → (opcional) acesso aos sistemas da whitelist (--url) → (opcional)
comparação com o IP do servidor sem relay (--compare-direct).

Exit 0 se tudo passou; 1 se algo falhou. --json grava o resultado.

Opções:
    --check-url URL     devolve o IP de saída (padrão: EGRESS_CHECK_URL ou https://api.ipify.org)
    --expected-ip IP    IP do cliente na whitelist (padrão: EGRESS_EXPECTED_IP)
    --url URL           sistema que deve abrir pelo relay (repetível)
    --browsers LISTA    chrome,uc,firefox (padrão: todos)
    --compare-direct    mostra também o IP do servidor SEM relay (faz 1 acesso direto)
    --insecure          não valida certificados HTTPS (só para relays de teste)
    --json ARQUIVO
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import egress_proxy as ep  # noqa: E402
from script_downloader import mask_text, mask_url  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,7}\b", re.I)


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.steps: list = []

    def line(self, status: str, step: str, detail: str = "") -> None:
        if status == FAIL:
            self.failures += 1
        self.steps.append({"status": {OK: "ok", WARN: "aviso", FAIL: "erro"}[status], "passo": step,
                           "detalhe": detail})
        print(f"{status} {step}" + (f": {detail}" if detail else ""), flush=True)


def _ip_in(text: str) -> str:
    match = IP_RE.search(text or "")
    return match.group(0) if match else (text or "").strip()[:60]


def _judge(report: Report, step: str, seen: str, expected: str, reference: str) -> None:
    ip = _ip_in(seen)
    if not ip:
        report.line(FAIL, step, "não obteve resposta")
    elif expected and ip != expected:
        report.line(FAIL, step, f"saiu por {ip}, esperado {expected}")
    elif reference and ip != reference:
        report.line(FAIL, step, f"saiu por {ip}, diferente do Python ({reference}): não está usando o relay")
    else:
        report.line(OK, step, ip)


def _browser_text(open_driver, url: str) -> str:
    from selenium.webdriver.common.by import By

    driver = open_driver()
    try:
        driver.get(url)
        time.sleep(1)
        return driver.find_element(By.TAG_NAME, "body").text
    finally:
        driver.quit()


def _chrome(headless: bool, insecure: bool):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    opts = webdriver.ChromeOptions()
    for arg in ["--no-sandbox", "--disable-dev-shm-usage"] + (["--headless=new"] if headless else []) \
            + (["--ignore-certificate-errors"] if insecure else []):
        opts.add_argument(arg)
    return webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=opts)


def _uc(headless: bool, insecure: bool):
    from seleniumbase import Driver

    kwargs = {"chromium_arg": "--ignore-certificate-errors"} if insecure else {}
    return Driver(uc=True, headless=headless, **kwargs)


def _firefox(headless: bool, insecure: bool):
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service

    opts = webdriver.FirefoxOptions()
    if headless:
        opts.add_argument("-headless")
    opts.accept_insecure_certs = insecure
    return webdriver.Firefox(service=Service("/usr/local/bin/geckodriver"), options=opts)


def java_fetch(url: str, insecure: bool = False) -> str:
    """GET pelo Java do PJeOffice (jjs), com o JAVA_TOOL_OPTIONS do container."""
    jjs = next((p for p in ("/opt/pjeoffice/jre/bin/jjs", shutil.which("jjs") or "") if p and os.path.exists(p)), "")
    if not jjs:
        raise RuntimeError("jjs não encontrado (JRE do PJeOffice ausente)")
    script = f"""
var trustAll = {str(insecure).lower()};
if (trustAll) {{
  var TM = Java.extend(Java.type('javax.net.ssl.X509TrustManager'), {{
    checkClientTrusted: function() {{}}, checkServerTrusted: function() {{}},
    getAcceptedIssuers: function() {{ return null; }} }});
  var ctx = Java.type('javax.net.ssl.SSLContext').getInstance('TLS');
  ctx.init(null, Java.to([new TM()], 'javax.net.ssl.TrustManager[]'), null);
  Java.type('javax.net.ssl.HttpsURLConnection').setDefaultSSLSocketFactory(ctx.getSocketFactory());
  Java.type('javax.net.ssl.HttpsURLConnection').setDefaultHostnameVerifier(function() {{ return true; }});
}}
var c = new java.net.URL({json.dumps(url)}).openConnection();
c.setConnectTimeout(20000); c.setReadTimeout(20000);
var s = new java.util.Scanner(c.getInputStream()).useDelimiter('\\\\A');
print(s.hasNext() ? s.next() : '');
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
    try:
        result = subprocess.run([jjs, fh.name],
                                capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(fh.name)
    lines = [ln for ln in result.stdout.splitlines() if not ln.startswith("Picked up JAVA_TOOL_OPTIONS")]
    if result.returncode != 0:
        err = [ln for ln in result.stderr.splitlines()
               if ("Exception" in ln or "Error" in ln) and not ln.startswith("Picked up")]
        raise RuntimeError((err[:1] or [result.stderr.strip()[-200:]])[0])
    return "\n".join(lines).strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check-url", default=os.getenv("EGRESS_CHECK_URL") or ep.DEFAULT_CHECK_URL)
    parser.add_argument("--expected-ip", default=os.getenv("EGRESS_EXPECTED_IP", ""))
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--browsers", default="chrome,uc,firefox")
    parser.add_argument("--compare-direct", action="store_true")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    report = Report()
    port = int(os.getenv("EGRESS_LOCAL_PORT", ep.DEFAULT_PORT))
    print("🌐 Verificação da saída pelo relay\n", flush=True)

    # 1. configuração
    try:
        up = ep.upstream_from_env()
    except ep.EgressError as exc:
        up = None
        report.line(FAIL, "EGRESS_PROXY_URL", str(exc))
    if up is None:
        if not report.failures:
            report.line(FAIL, "EGRESS_PROXY_URL", "não definido: o container está saindo direto pela internet do servidor")
        return _finish(report, args)
    report.line(OK, "relay", up.masked)
    if ep.wait_port(port, 3):
        report.line(OK, "repassador local", f"127.0.0.1:{port}")
    else:
        report.line(FAIL, "repassador local", f"nada escutando em 127.0.0.1:{port} (o entrypoint rodou?)")
        return _finish(report, args)
    local = f"http://127.0.0.1:{port}"
    env_ok = all(os.getenv(k) == local for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"))
    report.line(OK if env_ok else FAIL, "variáveis HTTP(S)_PROXY", local if env_ok else "não apontam para o repassador")
    report.line(OK if "proxyHost=127.0.0.1" in os.getenv("JAVA_TOOL_OPTIONS", "") else FAIL,
                "Java (JAVA_TOOL_OPTIONS)", "proxy configurado para o PJeOffice")
    for d in ep.CHROME_POLICY_DIRS:
        f = d / ep.CHROME_POLICY_FILE
        ok = f.exists() and json.loads(f.read_text()).get("ProxySettings", {}).get("ProxyServer") == local
        report.line(OK if ok else FAIL, f"policy do Chrome ({d.parent.parent.name})",
                    "ProxySettings + WebRTC/QUIC bloqueados" if ok else f"{f} ausente ou diferente")
    ff = ep.FIREFOX_POLICIES
    ok = ff.exists() and json.loads(ff.read_text())["policies"].get("Proxy", {}).get("HTTPProxy") == f"127.0.0.1:{port}"
    report.line(OK if ok else FAIL, "policy do Firefox", "Proxy travado + WebRTC/HTTP3 bloqueados" if ok else str(ff))
    report.line(OK, "exceções (sem relay)", ", ".join(ep.bypass_list()))

    # 2. IP de saída por componente
    import requests

    verify = not args.insecure
    python_ip = ""
    try:
        python_ip = _ip_in(requests.get(args.check_url, timeout=30, verify=verify).text)
    except Exception as exc:  # noqa: BLE001
        report.line(FAIL, "Python (requests)", str(exc)[:200])
    if python_ip:
        _judge(report, "Python (requests)", python_ip, args.expected_ip, "")
    reference = args.expected_ip or python_ip

    headless = not os.getenv("DISPLAY") or subprocess.run(
        ["xdpyinfo", "-display", os.getenv("DISPLAY", "")], capture_output=True).returncode != 0
    wanted = {b.strip() for b in args.browsers.split(",") if b.strip()}
    for key, label, opener in (("chrome", "Chrome (Selenium)", _chrome), ("uc", "Chrome (SeleniumBase UC)", _uc),
                               ("firefox", "Firefox", _firefox)):
        if key not in wanted:
            continue
        try:
            text = _browser_text(lambda: opener(headless, args.insecure), args.check_url)
            _judge(report, label, text, args.expected_ip, reference)
        except Exception as exc:  # noqa: BLE001
            report.line(FAIL, label, f"{type(exc).__name__}: {str(exc)[:160]}")
    try:
        _judge(report, "Java (PJeOffice)", java_fetch(args.check_url, args.insecure), args.expected_ip, reference)
    except Exception as exc:  # noqa: BLE001
        report.line(WARN, "Java (PJeOffice)", f"não foi possível testar: {str(exc)[:160]}")

    # 3. sistemas da whitelist
    for url in args.url:
        try:
            resp = requests.get(url, timeout=40, verify=verify, allow_redirects=True)
            status = FAIL if resp.status_code in (403, 407, 451) or resp.status_code >= 500 else OK
            report.line(status, f"acesso a {mask_url(url)}", f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            report.line(FAIL, f"acesso a {mask_url(url)}", mask_text(exc, url)[:200])

    # 4. comparação com a saída direta
    if args.compare_direct:
        try:
            direct = _ip_in(requests.get(args.check_url, timeout=20, verify=verify,
                                         proxies={"http": "", "https": ""}).text)
            if direct and direct == reference:
                report.line(FAIL, "IP do servidor sem relay", f"{direct} — igual ao IP pelo relay")
            else:
                report.line(OK, "IP do servidor sem relay", f"{direct} (diferente do relay, como esperado)")
        except Exception as exc:  # noqa: BLE001
            report.line(WARN, "IP do servidor sem relay", f"saída direta indisponível: {str(exc)[:120]}")

    return _finish(report, args)


def _finish(report: Report, args) -> int:
    if args.json:
        Path(args.json).write_text(json.dumps({"ok": report.failures == 0, "falhas": report.failures,
                                               "passos": report.steps}, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
    print()
    if report.failures:
        print(f"❌ {report.failures} verificação(ões) falharam")
        return 1
    print("✅ todo o tráfego testado sai pelo relay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
