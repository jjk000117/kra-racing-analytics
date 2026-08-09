-- Target-rate decomposition by registered runner count.
-- This is descriptive only and does not train, select, or modify a model.
WITH period_rows AS (
    SELECT CASE
               WHEN race_date < DATE '2026-05-01' THEN 'STABLE'
               ELSE 'DEGRADED'
           END AS period,
           registered_runner_count,
           place_hit::DOUBLE AS place_hit
    FROM mart.feature_snapshot_place
    WHERE race_date >= DATE '2025-10-01'
      AND race_date < DATE '2026-08-01'
), stable_rates AS (
    SELECT registered_runner_count,
           avg(place_hit) AS stable_positive_rate
    FROM period_rows
    WHERE period = 'STABLE'
    GROUP BY registered_runner_count
), degraded_mix AS (
    SELECT registered_runner_count,
           count(*)::DOUBLE / sum(count(*)) OVER () AS degraded_row_share
    FROM period_rows
    WHERE period = 'DEGRADED'
    GROUP BY registered_runner_count
), period_rates AS (
    SELECT period, avg(place_hit) AS positive_rate
    FROM period_rows
    GROUP BY period
)
SELECT (SELECT positive_rate FROM period_rates WHERE period = 'STABLE') AS stable_actual_rate,
       (SELECT sum(m.degraded_row_share * r.stable_positive_rate)
        FROM degraded_mix m
        JOIN stable_rates r USING (registered_runner_count)) AS degraded_mix_at_stable_rates,
       (SELECT positive_rate FROM period_rates WHERE period = 'DEGRADED') AS degraded_actual_rate;

SELECT CASE
           WHEN race_date < DATE '2026-05-01' THEN 'STABLE'
           ELSE 'DEGRADED'
       END AS period,
       registered_runner_count,
       count(*) AS runner_rows,
       avg(place_hit::INTEGER) AS plc_positive_rate
FROM mart.feature_snapshot_place
WHERE race_date >= DATE '2025-10-01'
  AND race_date < DATE '2026-08-01'
GROUP BY period, registered_runner_count
ORDER BY registered_runner_count, period;
