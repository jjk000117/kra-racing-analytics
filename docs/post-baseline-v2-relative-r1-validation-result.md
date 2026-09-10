# LR1 Validation reproduction result

## Result

The sealed LT1-versus-LR1 check returned `REPRODUCE_R1`. This is a reproduction check on the previously exposed 2024-07 to 2025-06 Validation period, not a fresh final test.

| Candidate | Race-macro Log Loss | Race-macro Brier |
|---|---:|---:|
| LT1 137 | 0.533332 | 0.177797 |
| LR1 144 | 0.532780 | 0.177586 |
| LR1 - LT1 | -0.000552 | -0.000211 |

Both sealed primary metrics improved, so the predeclared rule yields `REPRODUCE_R1`. The reductions are about 0.10% and 0.12% respectively and are small.

## Secondary diagnostics

| Metric | LT1 | LR1 | LR1 - LT1 |
|---|---:|---:|---:|
| Micro Log Loss | 0.530992 | 0.530406 | -0.000586 |
| Micro Brier | 0.176809 | 0.176581 | -0.000228 |
| Calibration intercept | 0.034218 | 0.042160 | +0.007943 |
| Calibration slope | 1.014303 | 1.016116 | +0.001812 |
| Top-1 PLC hit rate | 0.596930 | 0.598067 | +0.001137 |
| Recall@3 | 0.494882 | 0.491281 | -0.003601 |
| NDCG@3 | 0.518946 | 0.516545 | -0.002401 |

The micro probability losses and Top-1 hit rate moved in the favorable direction. Recall@3 and NDCG@3 declined slightly. These ranking diagnostics are secondary and cannot override the sealed probability-loss rule.

## Development consistency and limits

Development and Validation agree in the direction of both primary metrics: LR1 improved Macro Log Loss and Macro Brier in each comparison. The Validation effect remains small and does not establish betting value, a fresh-test result, or the value of any individual R1 feature.

Two implementation attempts failed before any result row was returned: first on a reserved SQL alias and then on incorrectly binding derived R1 columns to the source table. Both failure ledgers were preserved; the user-authorized resume completed the single actual Validation load and evaluation.

Validation contained 18,615 runners and 1,759 races from 2024-07-05 through 2025-06-29. No row on or after 2025-07-01 was loaded. Feature definitions, Logistic settings, preprocessing, temporal OOF sigmoid procedure and protected artifacts were unchanged.
