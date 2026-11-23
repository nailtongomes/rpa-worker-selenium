"""Script de teste que falha: o exit code deve chegar ao container."""
import sys

print("JOB-FAIL", flush=True)
sys.exit(3)
