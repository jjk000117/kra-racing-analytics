# LR1 Validation reproduction contract

## Status and question

Status: `SEALED_BEFORE_LR1_VALIDATION_REPRODUCTION`.

The only question is whether the small Development improvement from the sealed seven-feature R1 bundle reproduces on the existing Validation period. This is not a fresh final test because the same period was previously used for L133 selection and diagnostics.

## Fixed candidates and dates

- Control: `LT1`, 137 features, hash `1dcf5f5a630d67f216fa6dc27932d2c6532ec0a50af6360b7521917682f802e8`
- Candidate: `LR1`, LT1 plus the sealed R1 seven, 144 features, hash `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- R1 registry hash: `f058c627fb68960803ed88adf450e67796fc2df25e8ad8854c372374d8875539`
- Train: `2023-01-01 <= race_date < 2024-07-01`
- Validation: `2024-07-01 <= race_date < 2025-07-01`
- Population and target: the existing sealed PLC population and official `place_hit`

Both candidates use the same Logistic parameters, Train-only preprocessing, population, target and seed. R1 is the only input difference. Feature removal, definition changes, threshold tuning and hyperparameter tuning are forbidden.

## Fixed probability procedure

Both LT1 and LR1 use the existing Train temporal expanding-window OOF sigmoid procedure. Preprocessing in every OOF fold is fitted on that fold's training portion only, and the calibrator is fitted only from Train-period OOF raw probabilities and targets. Raw probabilities may be retained for contract reconciliation, but raw versus sigmoid is not compared or reselected.

## Metrics

Primary metrics, computed as race-level macro averages:

- Log Loss
- Brier Score

Secondary diagnostics:

- Micro Log Loss and Micro Brier
- Calibration intercept and slope
- Top-1 PLC hit rate
- Recall@3
- NDCG@3

Secondary metrics cannot override the primary decision. Sigmoid is monotonic, so it does not change within-race ranks except for deterministic tie handling.

## Sealed decision rule

- `REPRODUCE_R1`: LR1 has lower Validation race-macro Log Loss and lower Validation race-macro Brier than LT1.
- `FAIL_TO_REPRODUCE_R1`: either primary metric is equal or worse for LR1 than LT1.

No practical-effect threshold is introduced. Any numerical improvement must be reported at its actual magnitude, and a small improvement must be described as small. Results may not trigger post-hoc R1 removal, percentile redesign, threshold tuning or calibration reselection.

## Access and protection

This document does not load or evaluate Validation data and does not change an access ledger. A future execution must record the access as reuse of an already exposed model-development Validation period, not as a fresh or unseen final test.

The unopened period beginning `2025-07-01` remains prohibited. No target, prediction, metric or diagnostic from that period may be accessed during LR1 Validation reproduction. Existing sealed artifacts and prior PROMOTE/KEEP/DROP decisions remain unchanged.
