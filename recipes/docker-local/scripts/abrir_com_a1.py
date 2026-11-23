#!/usr/bin/env python3
"""
Receita docker-local: abre um site com o certificado A1 no Chrome (SeleniumBase UC, em janela).

    docker compose run --rm --service-ports worker python /scripts/abrir_com_a1.py https://pje.tjrn.jus.br/pje/login.seam

Acompanhe em http://127.0.0.1:6080/vnc.html. Um print da página fica em ./saida/.
"""

import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import a1cert  # /app está no PYTHONPATH da imagem
from seleniumbase import Driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receita")


def main() -> int:
    site = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SITE_URL", "")
    if not site:
        log.error("informe o site: python /scripts/abrir_com_a1.py https://...")
        return 2

    cert = a1cert.load_from_env()  # A1_PFX_PATH + A1_PFX_PASSWORD_FILE do compose
    info = cert.summary()
    log.info("certificado: %s, vence em %s dias", info["titular"], info["dias_restantes"])

    origin = "{0.scheme}://{0.netloc}".format(urlsplit(site))
    a1cert.install_chrome(cert, [origin])  # escolhe o certificado sozinho só neste site
    driver = Driver(uc=True, headless=False)
    try:
        driver.uc_open_with_reconnect(site, 4)
        time.sleep(int(os.getenv("ESPERA_SEGUNDOS", "20")))  # tempo para olhar no noVNC
        out = Path("/saida")
        out.mkdir(exist_ok=True)
        driver.save_screenshot(str(out / "pagina.png"))
        log.info("título: %r; print em ./saida/pagina.png", driver.title)
    finally:
        driver.quit()
        a1cert.uninstall(cert)
    return 0


if __name__ == "__main__":
    sys.exit(main())
