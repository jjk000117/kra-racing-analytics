# R1 Development Experiment Results

## Decision

`KEEP_R1` for the PLC development research line. The sealed R1 bundle produced a small average improvement over LT1 in both primary race-macro losses, repeated in three of four temporal folds. This is not an official-model promotion and Validation was not accessed.

This Development result and its no-post-hoc-change interpretation are sealed before any LR1 Validation reproduction contract is executed.

## Fixed comparison

- Population: development only, `2023-01-01 <= race_date < 2024-07-01`
- Control: LT1, 137 features, hash `1dcf5f5a630d67f216fa6dc27932d2c6532ec0a50af6360b7521917682f802e8`
- Candidate: LR1, LT1 plus the sealed seven R1 features, 144 features, hash `7fec6229b3b355d34e664823407765c9a597eacdafa11a733048ba2eaff1a85a`
- R1 registry hash: `f058c627fb68960803ed88adf450e67796fc2df25e8ad8854c372374d8875539`
- Model: the same raw Logistic Regression, preprocessing, seed, population, target and four quarterly expanding temporal folds

## Fold results

| Fold | LT1 Macro LL | LR1 Macro LL | Delta | LT1 Macro Brier | LR1 Macro Brier | Delta |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 0.534392 | 0.531234 | -0.003158 | 0.177540 | 0.176398 | -0.001142 |
| 2 | 0.524648 | 0.524450 | -0.000198 | 0.173545 | 0.173443 | -0.000102 |
| 3 | 0.517213 | 0.517616 | +0.000403 | 0.172304 | 0.172387 | +0.000083 |
| 4 | 0.531758 | 0.530945 | -0.000813 | 0.178548 | 0.178302 | -0.000246 |

Both primary metrics improved together in 3/4 folds.

## Aggregate and secondary metrics

| Metric | LT1 mean | LR1 mean | LR1 - LT1 |
|---|---:|---:|---:|
| Macro Log Loss | 0.527003 | 0.526061 | -0.000942 |
| Macro Brier | 0.175484 | 0.175132 | -0.000352 |
| Micro Log Loss | 0.524884 | 0.523939 | -0.000945 |
| Micro Brier | 0.174525 | 0.174186 | -0.000339 |
| Calibration intercept | -0.078281 | -0.064502 | +0.013780 |
| Calibration slope | 0.929170 | 0.926758 | -0.002412 |

The relative average reductions were about 0.18% for Macro Log Loss and 0.20% for Macro Brier. The gain is therefore positive but small. Calibration did not materially deteriorate, but it was diagnostic only.

## R1 coefficient audit

All seven standardized coefficients kept the same sign in all four folds:

| Feature | Mean coefficient | Sign consistency |
|---|---:|---:|
| horse_same_meet_plc_hit_rate_field_percentile | -0.315801 | negative 4/4 |
| horse_same_meet_distance_plc_hit_rate_field_percentile | -0.257155 | negative 4/4 |
| jockey_same_meet_plc_hit_rate_field_percentile | +0.225301 | positive 4/4 |
| trainer_same_meet_plc_hit_rate_field_percentile | +0.033096 | positive 4/4 |
| owner_prior_plc_hit_rate_field_percentile | +0.021613 | positive 4/4 |
| horse_trainer_prior_plc_hit_rate_field_percentile | +0.094857 | positive 4/4 |
| horse_recent5_race_time_percentile_median_field_percentile | +0.132913 | positive 4/4 |

The two negative horse same-meet coefficients are conditional coefficients in a correlated 144-feature model. They do not establish that stronger same-meet history is harmful in isolation.

## Availability diagnostic

Mean R1 availability rose from 91.38% in fold 1 to 94.98% in fold 4, while the primary deltas did not improve monotonically. With only four folds, availability cannot explain the performance change; this check is descriptive and not causal.

## Protection and reproducibility

- Validation access remained unchanged; no row on or after `2024-07-01` was loaded or evaluated.
- The shared database, sealed baseline contracts and artifacts, prior A1/T1/M1/RA1 results, and the R1 implementation contract retained their protection hashes.
- LT1 reproduced its locked reference metrics within `1e-12` in every fold and metric.
- Reproducible CSV/JSON outputs are stored under `data/exports/modeling/post_baseline_v2_relative_r1_development_v1/` and remain ignored analytical artifacts.

## What is and is not known

Confirmed: the sealed seven-feature bundle adds a small, temporally repeated development improvement as a whole. Not established: which individual R1 feature causes the gain, whether the gain will reproduce on Validation, or whether it changes betting value. No post-hoc feature removal or further transformation is authorized by this result.
