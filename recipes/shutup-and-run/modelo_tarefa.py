#!/usr/bin/env python3
"""
Modelo de tarefa para o worker no PC (shutup-and-run) ou em qualquer lugar.

Publique este arquivo (preenchido) numa URL e passe-a em SCRIPT_URL. O worker baixa e roda.
Só a função ``executar`` muda de uma tarefa para outra; o resto é o contrato:

  - certificado A1: A1_PFX_PATH + A1_PFX_PASSWORD_FILE (no shutup-and-run, os caminhos fixos
    do repasse de certificado; ver recipes/shutup-and-run/README.md);
  - browser em janela no Xvfb (USE_XVFB=1), SeleniumBase UC: menos chance de ser marcado como bot;
  - resultado: JSON enviado por POST para RESULT_URL (com API_TOKEN como Bearer, se houver).
    O container é apagado no fim: o que não for enviado se perde;
  - exit 0 = sucesso, 1 = falhou (o orquestrador recebe o exit_code no callback do shutup-and-run).

Variáveis: SITE_URL (página inicial), RESULT_URL, API_TOKEN, WORKER_ID.
"""

import json
import logging
import os
import sys
import time
import traceback
from urllib.parse import urlsplit

import requests

import a1cert  # /app está no PYTHONPATH da imagem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tarefa")


def executar(driver, cert) -> dict:
    """A automação em si. Devolve o que deve ir para RESULT_URL."""
    site = os.getenv("SITE_URL", "")
    if site:
        driver.uc_open_with_reconnect(site, 4)
        time.sleep(3)
    # ... login com certificado, consulta, download, protocolo ...
    return {"titulo": driver.title, "certificado": cert.summary()["titular"] if cert else None}


def enviar_resultado(resultado: dict) -> None:
    url = os.getenv("RESULT_URL")
    if not url:
        log.info("sem RESULT_URL: resultado só no log: %s", json.dumps(resultado, ensure_ascii=False)[:2000])
        return
    headers = {"Authorization": f"Bearer {os.environ['API_TOKEN']}"} if os.getenv("API_TOKEN") else {}
    resp = requests.post(url, json=resultado, headers=headers, timeout=60)
    resp.raise_for_status()
    log.info("resultado enviado (HTTP %s)", resp.status_code)


def main() -> int:
    from seleniumbase import Driver

    inicio = time.time()
    resultado = {"worker": os.getenv("WORKER_ID", ""), "ok": False}
    cert = driver = None
    try:
        if os.getenv("A1_PFX_PATH") or os.getenv("A1_PFX_URL"):
            cert = a1cert.load_from_env()
            site = os.getenv("SITE_URL")
            # seleção automática do certificado só para o site da tarefa
            origens = ["{0.scheme}://{0.netloc}".format(urlsplit(site))] if site else ["*"]
            a1cert.install_chrome(cert, origens)
        driver = Driver(uc=True, headless=False)
        resultado.update(executar(driver, cert), ok=True)
    except Exception as exc:  # noqa: BLE001 - o orquestrador precisa saber o motivo
        resultado["erro"] = f"{type(exc).__name__}: {exc}"[:2000]
        log.error("falhou: %s", traceback.format_exc())
    finally:
        if driver is not None:
            driver.quit()
        if cert is not None:
            a1cert.uninstall(cert)
    resultado["duracao_s"] = round(time.time() - inicio, 1)
    enviar_resultado(resultado)
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
