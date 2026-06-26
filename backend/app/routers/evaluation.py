"""API endpoint for standardized backtest evaluation report."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.evaluation import evaluate_from_database, compute_summary, format_report_text

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/score-backtest")
def score_backtest(db: Session = Depends(get_db)):
    """Return per-match score evaluation as JSON (for frontend table)."""
    rows, summary = evaluate_from_database()
    return {
        "rows": [
            {
                "id": r.index,
                "match": r.match_label,
                "score": r.actual_score,
                "top1": r.top1_score,
                "top3": " / ".join(r.top3_scores),
                "hit1": r.hit1,
                "hit3": r.hit3,
                "lamH": r.lambda_home,
                "lamA": r.lambda_away,
                "resultHit": r.hit_result,
            }
            for r in rows
        ],
        "summary": {
            "totalMatches": summary.total_matches,
            "top1Accuracy": summary.top1_accuracy,
            "top3Accuracy": summary.top3_accuracy,
            "lambdaError": summary.lambda_error,
            "highScoreMissed": summary.high_score_top3_missed,
        },
    }


@router.get("/score-backtest/text")
def score_backtest_text(db: Session = Depends(get_db)):
    """Return per-match score evaluation as plain text (for console/logs)."""
    rows, summary = evaluate_from_database()
    return {"text": format_report_text(rows, summary)}
