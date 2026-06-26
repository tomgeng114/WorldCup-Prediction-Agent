from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.audit_report import build_audit_report, write_audit_outputs


def main() -> None:
    output_dir = Path(__file__).resolve().parents[1] / "reports"
    with SessionLocal() as db:
        report = build_audit_report(db)
        paths = write_audit_outputs(report, output_dir)
    print(json.dumps({"outputs": paths, "overall": report["overall"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
