from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.confidence_calibration_audit import (
    build_confidence_calibration_audit,
    write_confidence_calibration_outputs,
)


def main() -> None:
    with SessionLocal() as db:
        report = build_confidence_calibration_audit(db)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "confidence_calibration_audit"
        paths = write_confidence_calibration_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "confidence_calibration_audit",
                "outputs": paths,
                "sample_sizes": report["sample_sizes"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
