"""Script de teste do worker: imprime um marcador e usa o helper de /app/src."""
import os

import helper_mod

print(f"JOB-OK worker={os.getenv('WORKER_ID', '?')} {helper_mod.MARKER}", flush=True)
