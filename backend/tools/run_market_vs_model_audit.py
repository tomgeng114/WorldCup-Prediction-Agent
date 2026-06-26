from __future__ import annotations

import json
from pathlib import Path

from app.db import SessionLocal
from app.services.market_vs_model_audit import build_market_vs_model_audit, write_market_vs_model_outputs


def main() -> None:
    years = [2018, 2022]
    with SessionLocal() as db:
        report = build_market_vs_model_audit(db, years)
        output_dir = Path(__file__).resolve().parents[1] / "reports" / "market_vs_model_audit"
        paths = write_market_vs_model_outputs(report, output_dir)

    print(
        json.dumps(
            {
                "phase": "market_vs_model_audit",
                "outputs": paths,
                "summary": report["summary"],
                "conclusion": report["conclusion"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
