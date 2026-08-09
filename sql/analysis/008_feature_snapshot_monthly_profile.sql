-- Monthly Snapshot size, target rate, history availability, and prior-count quantiles.
SELECT strftime(race_date, '%Y-%m') AS year_month,
       count(DISTINCT race_id) AS race_count,
       count(*) AS runner_row_count,
       avg(place_hit::INTEGER) AS plc_positive_rate,
       avg(horse_history_available::INTEGER) AS horse_history_available_rate,
       avg(jockey_history_available::INTEGER) AS jockey_history_available_rate,
       avg(trainer_history_available::INTEGER) AS trainer_history_available_rate,
       quantile_cont(horse_prior_start_count, 0.25) AS horse_prior_count_p25,
       median(horse_prior_start_count) AS horse_prior_count_p50,
       quantile_cont(horse_prior_start_count, 0.75) AS horse_prior_count_p75,
       quantile_cont(jockey_prior_start_count, 0.25) AS jockey_prior_count_p25,
       median(jockey_prior_start_count) AS jockey_prior_count_p50,
       quantile_cont(jockey_prior_start_count, 0.75) AS jockey_prior_count_p75,
       quantile_cont(trainer_prior_start_count, 0.25) AS trainer_prior_count_p25,
       median(trainer_prior_start_count) AS trainer_prior_count_p50,
       quantile_cont(trainer_prior_start_count, 0.75) AS trainer_prior_count_p75,
       min(race_date) AS first_race_date,
       max(race_date) AS last_race_date
FROM mart.feature_snapshot_place
GROUP BY year_month
ORDER BY year_month;

-- Candidate chronological partitions. These are proposals, not an approved split contract.
WITH split_candidates AS (
    SELECT * FROM (VALUES
        ('A', 'WARMUP', DATE '2024-01-05', DATE '2024-03-31'),
        ('A', 'TRAIN', DATE '2024-04-01', DATE '2025-06-30'),
        ('A', 'VALIDATION', DATE '2025-07-01', DATE '2025-12-31'),
        ('A', 'FINAL_TEST', DATE '2026-01-01', DATE '2026-07-26'),
        ('B', 'WARMUP', DATE '2024-01-05', DATE '2024-09-30'),
        ('B', 'TRAIN', DATE '2024-10-01', DATE '2025-09-30'),
        ('B', 'VALIDATION', DATE '2025-10-01', DATE '2025-12-31'),
        ('B', 'FINAL_TEST', DATE '2026-01-01', DATE '2026-07-26'),
        ('C', 'WARMUP', DATE '2024-01-05', DATE '2024-12-31'),
        ('C', 'TRAIN', DATE '2025-01-01', DATE '2025-12-31'),
        ('C', 'VALIDATION', DATE '2026-01-01', DATE '2026-03-31'),
        ('C', 'FINAL_TEST', DATE '2026-04-01', DATE '2026-07-26')
    ) AS t(candidate, split_name, start_date, end_date)
)
SELECT c.candidate,
       c.split_name,
       c.start_date,
       c.end_date,
       count(DISTINCT s.race_id) AS race_count,
       count(*) AS runner_row_count,
       count(*) FILTER (WHERE s.place_hit) AS plc_positive_count,
       avg(s.place_hit::INTEGER) AS plc_positive_rate,
       avg(s.horse_history_available::INTEGER) AS horse_history_available_rate,
       median(s.horse_prior_start_count) AS horse_prior_count_p50,
       median(s.jockey_prior_start_count) AS jockey_prior_count_p50,
       median(s.trainer_prior_start_count) AS trainer_prior_count_p50
FROM split_candidates c
JOIN mart.feature_snapshot_place s
  ON s.race_date BETWEEN c.start_date AND c.end_date
GROUP BY c.candidate, c.split_name, c.start_date, c.end_date
ORDER BY c.candidate,
         CASE c.split_name
             WHEN 'WARMUP' THEN 1
             WHEN 'TRAIN' THEN 2
             WHEN 'VALIDATION' THEN 3
             ELSE 4
         END;
