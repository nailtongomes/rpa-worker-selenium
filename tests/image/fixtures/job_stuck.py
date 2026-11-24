"""Script de teste do loop: deixa um Chrome aberto fora do grupo de processos (como um browser
esquecido sem quit()) e depois trava ignorando o SIGTERM. O entrypoint precisa matá-lo com
SIGKILL (WORKER_KILL_AFTER) e fechar o Chrome antes da próxima iteração."""
import signal
import subprocess
import time

subprocess.Popen(
    ["/opt/chrome/chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     "--user-data-dir=/tmp/.org.chromium.Chromium.job-stuck", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
)
signal.signal(signal.SIGTERM, lambda *_: print("JOB-STUCK ignorando SIGTERM", flush=True))
print("JOB-STUCK travado", flush=True)
while True:
    time.sleep(0.5)
