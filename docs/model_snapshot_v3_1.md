# Model Snapshot — Baseline v3.1

> Generated: 2026-06-21  
> Status: **LOCKED**  
> Draw Threshold: **0.30**

## Prediction Pipeline

```
ELO (27%) → Form (20%) → Odds (18%) → xG/Lambda → Poisson(0-8) → MC (10%) → H2H (3%)
  → Weighted Fusion
  → Draw Specialist (narrow gate: λ<2.5 & ELO<80)
  → _pick_result_v2 (d≥0.30 → Draw, 0.25≤d<0.30 → Gray, d<0.25 → argmax)
  → _diverse_top_scores (original, probability-based)
  → PredictionPayload
```

## Module Status

| Module | Status |
|--------|:------:|
| ELO | ENABLED (dp 14-38%) |
| Form | ENABLED (dp 14-38%) |
| Odds | ENABLED |
| xG / Lambda | ENABLED (decoupled from dp) |
| Poisson | ENABLED (0-8 matrix) |
| Dixon-Coles | ENABLED |
| Monte Carlo | ENABLED (100k samples) |
| H2H | ENABLED (dp 14-38%) |
| Draw Specialist | ENABLED |
| Lambda Calibration | DISABLED |
| Match Type Classification | DELETED |
| Draw Calibration Layer | DELETED |
| Anti-Flip Guard | DELETED |
| Draw Cap | DELETED |
| Top3 Forced Diversification | DELETED |

## Key Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| Draw Threshold | **0.30** | predictor.py:316 |
| Gray Zone | 0.25 | predictor.py:321 |
| dp range (ELO) | 14-38% | predictor.py:66 |
| dp range (Form) | 14-38% | predictor.py:73 |
| dp range (H2H) | 14-38% | predictor.py:203 |
| Poisson max_goals | 8 | predictor.py:129 |
| MC runs | 100,000 | predictor.py:10 |
| λ decoupled | YES | predictor.py:86-91 |

## Backtest Results

| Dataset | Acc | DrawR | DrawP | WD |
|---------|:---:|:-----:|:-----:|:--:|
| 2026 (44) | 65.9% | 16.7% | 100% | 2 |
| 2018 (64) | 53.1% | 42.9% | — | 7 |
| 2022 (64) | 56.2% | 40.0% | — | 11 |
| All (128) | 54.7% | 41.4% | — | 18 |

## Frozen Modules

The following SHALL NOT be modified without explicit authorization:

- Draw Threshold (0.30)
- ELO algorithm
- Form algorithm
- Odds algorithm
- Lambda formula
- Poisson matrix
- Monte Carlo
- Draw Specialist
- Top3 logic
- Fusion weights

## Change Log

| Version | Date | Change |
|---------|------|--------|
| v1 | 2026-06-11 | Original ELO+Poisson baseline |
| v2 | 2026-06-15 | +Draw Specialist +Decision Layer v2 |
| v2.1 | 2026-06-16 | +Draw Calibration x1.25 (reverted) |
| v2.2 | 2026-06-18 | +Match Type Classification (reverted) |
| v3.0 | 2026-06-19 | dp caps 14-38% + λ decoupled + Poisson 0-8 + threshold 0.33 |
| v3.1 | 2026-06-21 | Threshold 0.33→0.30 (final) |
