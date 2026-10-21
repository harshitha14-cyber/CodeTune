# Digital Twin report: `work` (c)

Baseline: predicted cost **475.0**, measured **475.3**, code size 48, stack 24 bytes.

## Recommendation

**adaptive (selector)** - 'adaptive (selector)' has the lowest predicted cost: 23.4% below the original (364 vs 475 cost units).

## Strategy comparison

| Strategy | Valid | Predicted | Measured | Error % | Saving % | Size | Stack B |
|---|---|---|---|---|---|---|---|
| baseline (no optimization) | yes | 475.0 | 475.3 | 0.1 | 0.0 | 48 | 24 |
| only CP | yes | 475.0 | 475.3 | 0.1 | 0.0 | 48 | 24 |
| only CF | yes | 471.0 | 471.3 | 0.1 | 0.8 | 44 | 24 |
| only SR | yes | 475.0 | 475.3 | 0.1 | 0.0 | 48 | 24 |
| only DCE | yes | 471.0 | 471.3 | 0.1 | 0.8 | 44 | 20 |
| canonical order x1 | yes | 365.0 | 365.1 | 0.0 | 23.2 | 38 | 16 |
| reverse order x1 | yes | 467.0 | 467.3 | 0.1 | 1.7 | 40 | 20 |
| canonical to fixpoint | yes | 364.0 | 364.1 | 0.0 | 23.4 | 36 | 12 |
| adaptive (selector) | yes | 364.0 | 364.1 | 0.0 | 23.4 | 36 | 12 |

## Prediction accuracy

- mean error vs measured: **0.1%** (target: within 15%)
- strategies predicted within 15%: **100%**
- strategy pairs ranked the same as reality: **100%**
- predicted winner is also the measured winner: **yes**

## Version history

- v0: original - cost 475.0, size 48
- v1 (head): adaptive (selector) - cost 364.0, size 36

Cost model: one cost unit ~ one CPU cycle (modelled, not measured on hardware)
