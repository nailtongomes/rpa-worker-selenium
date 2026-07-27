import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from seleniumbase import sb_cdp
from seleniumbase import Driver


REPORT_DIR = Path(os.getenv("CLEARCOTE_REPORT_DIR", "/app/reports/clearcote"))
MIN_SCORE = int(os.getenv("CLEARCOTE_MIN_SCORE", "0"))
AUDIT_URL = os.getenv("CLEARCOTE_AUDIT_URL", "https://www.clearcotelabs.com/audit")


def write_report(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / "clearcote_report.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"CLEARCOTE_REPORT={report_path}")


def extract_score(text: str) -> int:
    match = re.search(r"\d+", text or "")
    if not match:
        raise ValueError(f"Não foi possível extrair a nota do texto: {text!r}")
    return int(match.group())

def get_report():

    try:
        d = Driver(uc=True, headless=False)
        d.get('https://abrahamjuliot.github.io/creepjs/')
        d.sleep(12)
        d.save_screenshot('/app/creepjs.png')
        pdf_path = REPORT_DIR / "creepjs.pdf"
        sb.save_as_pdf(pdf_path.name, str(REPORT_DIR))
        d.quit()
        
    except Exception as exc:
        payload = {
            "status": "error",
            "score": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        write_report(payload)

def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sb = None
    started_at = datetime.now(timezone.utc)

    try:
        sb = sb_cdp.Chrome()
        sb.goto(AUDIT_URL)
        sb.click('button[aria-label="Marker 1"]')
        sb.click('button[aria-label="Marker 2"]')
        sb.click('button[aria-label="Marker 3"]')
        sb.press_keys("input", "audit")
        sb.set_value('input[type="range"]', "100")
        sb.click_and_hold("button[data-interaction-hold]")
        sb.select_option_by_text("select", "Mouse")
        sb.click('button:contains("Run the audit")')
        sb.sleep(6)
        sb.assert_element("div.text-successText", timeout=20)

        score_text = sb.get_text("div.text-successText")
        score = extract_score(score_text)

        pdf_path = REPORT_DIR / "clearcote_audit_results.pdf"
        sb.save_as_pdf(pdf_path.name, str(REPORT_DIR))

        passed = score >= MIN_SCORE
        payload = {
            "status": "passed" if passed else "below_threshold",
            "score": score,
            "minimum_score": MIN_SCORE,
            "score_text": score_text,
            "audit_url": AUDIT_URL,
            "pdf_path": str(pdf_path),
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        write_report(payload)

        print(f"CLEARCOTE_SCORE={score}")
        print(f"CLEARCOTE_MIN_SCORE={MIN_SCORE}")
        print(f"CLEARCOTE_PDF={pdf_path}")

        if passed:
            print(f"✅ ClearCote audit concluído. Nota: {score}")
            return 0

        print(f"❌ ClearCote abaixo do limite. Nota: {score}; mínimo: {MIN_SCORE}")
        return 1

    except Exception as exc:
        payload = {
            "status": "error",
            "score": None,
            "minimum_score": MIN_SCORE,
            "audit_url": AUDIT_URL,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        write_report(payload)
        print(f"CLEARCOTE_ERROR={type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    finally:
        if sb is not None:
            try:
                sb.quit()
            except Exception as quit_exc:
                print(f"Falha ao encerrar o navegador: {quit_exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
