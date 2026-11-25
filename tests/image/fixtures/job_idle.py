"""Script de teste sem trabalho: sai com o código combinado em WORKER_IDLE_EXIT_CODE (75)."""
import sys

print("JOB-IDLE nada a fazer", flush=True)
sys.exit(75)
