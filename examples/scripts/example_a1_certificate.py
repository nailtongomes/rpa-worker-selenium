#!/usr/bin/env python3
"""
Exemplo: login com certificado A1 + assinatura de PDF em .p7s.

Roda dentro da imagem (SCRIPT_URL ou `docker run ... python este_arquivo.py`):

    docker run --rm --shm-size=2g -e USE_XVFB=1 -e USE_OPENBOX=1 \
      -e A1_PFX_URL=https://exemplo.com/a1.pfx \
      -e A1_PFX_PASSWORD_FILE=/run/secrets/a1 -v "$PWD/a1-senha.txt:/run/secrets/a1:ro" \
      -e SITE_URL=https://pje.tjrn.jus.br/pje/login.seam \
      -v "$PWD/example_a1_certificate.py:/tmp/job.py:ro" \
      ghcr.io/nailtongomes/rpa-worker-selenium:latest python /tmp/job.py

Variáveis:
    A1_PFX_URL / A1_PFX_PATH, A1_PFX_PASSWORD / A1_PFX_PASSWORD_FILE  certificado
    SITE_URL        página que pede o certificado (padrão: nenhuma, só assina)
    PDF_PATH        PDF a assinar (padrão: gera um de exemplo)
"""

import logging
import os
import sys
from pathlib import Path

import a1cert  # /app está no PYTHONPATH (entrypoint)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job")


def main() -> int:
    cert = a1cert.load_from_env()
    info = cert.summary()
    log.info("certificado: %s (CPF %s), vence em %s dias", info["titular"], info["cpf"], info["dias_restantes"])
    if not cert.is_valid_now:
        log.error("certificado fora da validade")
        return 1

    site = os.getenv("SITE_URL")
    try:
        if site:
            from urllib.parse import urlsplit

            from seleniumbase import Driver

            origin = "{0.scheme}://{0.netloc}".format(urlsplit(site))
            a1cert.install_chrome(cert, [origin])  # NSS + seleção automática só para este site
            driver = Driver(uc=True, headless=False)  # janela no Xvfb, como em produção
            try:
                driver.get(site)
                driver.sleep(5)
                log.info("página aberta com o certificado: %s", driver.title)
                # ... automação do sistema ...
            finally:
                driver.quit()

        pdf = Path(os.getenv("PDF_PATH", ""))
        if not pdf.is_file():
            import a1_testkit

            pdf = a1_testkit.make_sample_pdf(Path("/tmp/documento.pdf"))
        p7s = a1cert.sign_p7s(cert, pdf)  # documento.pdf.p7s, com o PDF embutido
        a1cert.verify_p7s(p7s, ca_certs=cert.chain)
        log.info("assinado: %s", p7s)
        return 0
    finally:
        a1cert.uninstall(cert)  # remove do NSS/policies e apaga o .pfx baixado


if __name__ == "__main__":
    sys.exit(main())
