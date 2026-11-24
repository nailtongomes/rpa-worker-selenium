#!/usr/bin/env python3
"""
a1_check — verifica se o ambiente da imagem está pronto para um certificado A1.

Uso (certificado real, fora do GitHub):
    docker run --rm --shm-size=2g -e USE_XVFB=1 -e USE_OPENBOX=1 \\
      -e A1_PFX_URL=https://.../certificado.pfx \\
      -e A1_PFX_PASSWORD_FILE=/run/secrets/a1 -v ./a1-senha.txt:/run/secrets/a1:ro \\
      ghcr.io/nailtongomes/rpa-worker-selenium:latest python /app/a1_check.py

    python /app/a1_check.py --self-test   # usa uma ICP de teste gerada na hora

Passos: abrir o .pfx com a senha → dados/validade → assinatura .p7s attached
(+ verificação) → PDF assinado (PAdES) → Java/PJeOffice lê o .pfx → o PJeOffice assina
(botão "Testar" da página local dele, com o PJeOffice ligado) → importação no NSS do
Chrome e do Firefox → os browsers apresentam o certificado a um servidor HTTPS local
que exige certificado de cliente → limpeza.

Nada é enviado para fora do container. Saída: exit 0 se tudo passou, 1 se algo falhou.

Opções:
    --self-test          ICP de teste em vez de A1_PFX_URL/A1_PFX_PATH
    --pdf ARQUIVO        PDF a assinar (padrão: um PDF de exemplo gerado na hora)
    --out DIR            onde salvar .p7s e PDF assinado (padrão: /tmp/a1-check)
    --browsers LISTA     chrome,uc,firefox (padrão: todos)
    --pjeoffice auto|on|off  teste de assinatura no PJeOffice (pjeoffice_check.py); auto = com
                         servidor X e o PJeOffice ligado (USE_PJEOFFICE=1 ou rodando)
    --keep               não remove o certificado do NSS/policies ao final
    --warn-days N        avisa se faltar menos de N dias para vencer (padrão: 30)
    --json ARQUIVO       grava o resultado em JSON (para Kestra/monitoramento)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import a1_testkit as kit  # noqa: E402
import a1cert  # noqa: E402
import pjeoffice_check  # noqa: E402

OK, WARN, FAIL = "✅", "⚠️ ", "❌"


class Report:
    def __init__(self) -> None:
        self.failures = 0
        self.warnings = 0
        self.steps: list = []

    def line(self, status: str, step: str, detail: str = "") -> None:
        if status == FAIL:
            self.failures += 1
        elif status == WARN:
            self.warnings += 1
        level = {OK: "ok", WARN: "aviso", FAIL: "erro"}[status]
        self.steps.append({"status": level, "passo": step, "detalhe": detail})
        print(f"{status} {step}" + (f": {detail}" if detail else ""), flush=True)

    def step(self, name: str, fn):
        """Executa ``fn``; exceção vira ❌ com a mensagem (sem traceback para A1Error)."""
        try:
            return fn()
        except a1cert.A1Error as exc:
            self.line(FAIL, name, str(exc))
        except Exception as exc:  # noqa: BLE001 - o relatório precisa continuar
            self.line(FAIL, name, f"{type(exc).__name__}: {exc}")
            if os.getenv("A1_CHECK_DEBUG") == "1":
                traceback.print_exc()
        return None


def _load(args, report: Report, workdir: Path):
    if args.self_test:
        pki = kit.make_test_pki(workdir / "pki", "senha-de-teste")
        cert = a1cert.load_pfx(pki["pfx"], pki["password"])
        report.line(OK, "ICP de teste gerada", str(pki["pfx"]))
        return cert
    return a1cert.load_from_env()


def _pjeoffice_wanted(mode: str) -> bool:
    if mode != "auto":
        return mode == "on"
    if not (pjeoffice_check.installed() and kit.has_display()):
        return False
    return os.getenv("USE_PJEOFFICE") == "1" or bool(pjeoffice_check.running_pids())


def _pjeoffice_step(cert, report: Report) -> None:
    name = "PJeOffice assina com o certificado"
    if a1cert.java_password_problem(cert):
        report.line(WARN, name, "pulado: o Java do PJeOffice não abre este .pfx (veja acima)")
        return
    try:
        result = pjeoffice_check.signature_test(cert.path, cert.password)
    except pjeoffice_check.PJeOfficeError as exc:
        report.line(FAIL, name, str(exc))
        return
    who = " | ".join(filter(None, (result.get("titular"), result.get("cpf") or result.get("cnpj"))))
    report.line(OK, name, f"botão \"Testar\" da página local: {who} [{result['segundos']}s]")


def _browser_checks(cert, args, report: Report, workdir: Path) -> None:
    wanted = {b.strip() for b in args.browsers.split(",") if b.strip()}
    headless = not kit.has_display()
    mode = "headless" if headless else f"janela no {os.getenv('DISPLAY')}"
    trusted = list(cert.chain) + [cert.certificate]
    if not cert.chain:
        report.line(WARN, "cadeia", "o .pfx não traz a cadeia (AC); alguns servidores e browsers recusam")

    with kit.MTLSServer(trusted) as server:
        if wanted & {"chrome", "uc"}:
            if report.step("Chrome: importar no NSS + policy",
                           lambda: a1cert.install_chrome(cert, [server.origin])) is not None:
                report.line(OK, "Chrome: importado no NSS + policy AutoSelectCertificateForUrls")
                for name, opener in (("chrome", lambda: kit.open_chrome(headless)),
                                     ("uc", lambda: kit.open_seleniumbase(uc=True, headless=headless))):
                    if name in wanted:
                        label = "Chrome (Selenium)" if name == "chrome" else "Chrome (SeleniumBase UC)"
                        _visit(report, f"{label} apresenta o certificado [{mode}]", opener, server, cert)

        if "firefox" in wanted:
            profile = workdir / "firefox-profile"
            shutil.copytree(a1cert.FIREFOX_PROFILE_DIR, profile)
            if report.step("Firefox: importar no NSS do profile",
                           lambda: a1cert.install_firefox(cert, profile)) is not None:
                report.line(OK, "Firefox: importado no NSS do profile (cópia de selenium.default-release)")
                _visit(report, f"Firefox apresenta o certificado [{mode}]",
                       lambda: kit.open_firefox(str(profile), headless), server, cert)


def _visit(report: Report, name: str, opener, server, cert) -> None:
    driver = report.step(name, opener)
    if driver is None:
        return
    try:
        subject = kit.read_subject(driver, server.url)
        if subject == cert.subject_cn:
            report.line(OK, name, subject)
        else:
            errors = "; ".join(server.handshake_errors[-2:]) or driver.title
            report.line(FAIL, name, f"servidor não recebeu o certificado ({errors})")
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


def _write_json(path, report: Report, info: dict) -> None:
    if not path:
        return
    Path(path).write_text(json.dumps({
        "ok": report.failures == 0,
        "falhas": report.failures,
        "avisos": report.warnings,
        "certificado": info,
        "passos": report.steps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--pdf")
    parser.add_argument("--out", default="/tmp/a1-check")
    parser.add_argument("--browsers", default="chrome,uc,firefox")
    parser.add_argument("--pjeoffice", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--warn-days", type=int, default=30)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    report = Report()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="a1-check-"))
    print("🔐 Verificação do certificado A1\n", flush=True)

    cert = report.step("abrir o .pfx com a senha", lambda: _load(args, report, workdir))
    if cert is None:
        _write_json(args.json, report, {})
        print("\n❌ não foi possível continuar sem abrir o certificado")
        return 1

    info = cert.summary()
    report.line(OK, "certificado aberto", f"{info['titular']} | emissor: {info['emissor']} | formato: {info['formato']}")
    doc = f"CPF {info['cpf']}" if info["cpf"] else (f"CNPJ {info['cnpj']}" if info["cnpj"] else "")
    if doc:
        report.line(OK, "identificação ICP-Brasil", doc)
    else:
        report.line(WARN, "identificação ICP-Brasil", "CPF/CNPJ não encontrado no certificado")
    if not cert.is_valid_now:
        report.line(FAIL, "validade", f"fora da validade ({info['valido_de']} a {info['valido_ate']})")
    elif cert.days_left < args.warn_days:
        report.line(WARN, "validade", f"vence em {cert.days_left} dias ({info['valido_ate']})")
    else:
        report.line(OK, "validade", f"{cert.days_left} dias restantes ({info['valido_ate']})")

    for level, subject, message in a1cert.usage_findings(cert):
        report.line({"ok": OK, "aviso": WARN, "erro": FAIL}[level], subject, message)

    pdf = Path(args.pdf) if args.pdf else kit.make_sample_pdf(workdir / "documento.pdf")

    def p7s_step():
        p7s = a1cert.sign_p7s(cert, pdf, out / (pdf.name + ".p7s"), attached=True)
        content = a1cert.verify_p7s(p7s, ca_certs=cert.chain)
        if content != pdf.read_bytes():
            raise a1cert.A1Error("o conteúdo do .p7s difere do PDF original")
        chain = "assinatura e cadeia" if cert.chain else "assinatura (sem cadeia para validar)"
        report.line(OK, "PDF → .p7s attached (CAdES-BES)", f"{p7s} — {chain} verificadas com openssl cms")
        return p7s

    report.step("PDF → .p7s attached", p7s_step)

    def pades_step():
        signed = a1cert.sign_pdf(cert, pdf, out / (pdf.stem + "-assinado.pdf"))
        results = a1cert.verify_pdf(signed, cert.chain)
        if not results or not all(r[0] and r[1] for r in results):
            raise a1cert.A1Error(f"verificação falhou: {results}")
        report.line(OK, "PDF assinado (PAdES)", str(signed))
        return signed

    report.step("PDF assinado (PAdES)", pades_step)

    if report.step("Java/PJeOffice lê o .pfx", lambda: a1cert.java_can_read(cert)):
        report.line(OK, "Java/PJeOffice lê o .pfx (keytool)")
    elif shutil.which("keytool"):
        reason = a1cert.java_password_problem(cert) or "keytool não abriu o .pfx ou não achou a chave privada"
        report.line(FAIL, "Java/PJeOffice lê o .pfx", reason)

    if _pjeoffice_wanted(args.pjeoffice):
        report.step("PJeOffice assina com o certificado", lambda: _pjeoffice_step(cert, report))

    try:
        _browser_checks(cert, args, report, workdir)
    finally:
        if not args.keep:
            a1cert.uninstall_chrome(cert)
            left = cert.nickname in a1cert.nss_nicknames(a1cert.CHROME_NSS_DB)
            if not args.self_test:
                try:
                    if cert.path.resolve().is_relative_to(a1cert.WORK_DIR.resolve()):
                        cert.path.unlink(missing_ok=True)  # .pfx baixado de A1_PFX_URL
                except OSError:
                    pass
            report.line(FAIL if left else OK, "limpeza", "certificado removido do NSS e policies apagadas"
                        if not left else "o certificado ficou no NSS do Chrome")
        shutil.rmtree(workdir, ignore_errors=True)

    _write_json(args.json, report, info)
    print()
    if report.failures:
        print(f"❌ {report.failures} verificação(ões) falharam")
        return 1
    print("✅ ambiente pronto para o certificado A1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
