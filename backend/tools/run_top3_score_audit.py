from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.top3_score_audit import build_top3_score_audit, write_top3_score_outputs


def main() -> None:
    with SessionLocal() as db:
        report = build_top3_score_audit(db)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "top3_score_audit"
        paths = write_top3_score_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "top3_score_audit",
                "outputs": paths,
                "sample_sizes": report["sample_sizes"],
                "top1_vs_top3": report["top1_vs_top3"],
                "conditional_top3": report["conditional_top3"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
