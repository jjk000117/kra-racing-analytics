DELETE FROM mart.feature_snapshot_place;
DELETE FROM mart.feature_snapshot_run;

INSERT INTO mart.feature_snapshot_run
SELECT snapshot_version, canonical_transform_version, star_transform_version,
       policy_version, started_at, NULL, 'RUNNING', 0, 0, 0, 0
FROM feature_snapshot_context;

INSERT INTO mart.feature_snapshot_place
WITH base AS (
    SELECT rr.race_id,
           rr.horse_id,
           r.race_date,
           r.meet_code,
           coalesce(nullif(trim(r.race_grade), ''), 'UNKNOWN') AS race_grade,
           r.distance_m,
           r.runner_count AS registered_runner_count,
           rr.gate_no,
           coalesce(nullif(trim(rr.horse_sex), ''), 'UNKNOWN') AS horse_sex,
           rr.horse_age,
           rr.carried_weight,
           try_cast(s.rating AS INTEGER) AS rating,
           rr.jockey_id,
           rr.trainer_id,
           rr.official_finish_rank,
           rr.result_status,
           rr.is_valid_start,
           rr.is_valid_finish,
           rr.source_batch_id,
           rr.policy_version,
           EXISTS (
               SELECT 1
               FROM canonical.winning_payout wp
               WHERE wp.race_id = rr.race_id
                 AND wp.pool_code = '연식'
                 AND wp.selection_count = 1
                 AND wp.horse_no_1 = rr.gate_no
           ) AS place_hit
    FROM canonical.runner_result rr
    JOIN canonical.race r USING (race_id)
    JOIN analytics.fact_race fr USING (race_id)
    JOIN staging.race_result s
      ON s.staging_row_id = rr.source_staging_row_id
    WHERE fr.is_market_eligible
      AND rr.is_valid_start
),
horse_history AS (
    SELECT cur.race_id,
           cur.horse_id,
           count(hist.race_id)::INTEGER AS prior_start_count,
           count(hist.race_id) FILTER (WHERE hist.is_valid_finish)::INTEGER
               AS prior_finish_count,
           count(hist.race_id) FILTER (WHERE hist.place_hit)::INTEGER AS prior_plc_hit_count,
           avg(hist.official_finish_rank) FILTER (WHERE hist.is_valid_finish)
               AS prior_avg_finish_rank,
           max(hist.race_date) AS last_start_date,
           count(hist.race_id) FILTER (
               WHERE hist.distance_m = cur.distance_m
           )::INTEGER AS same_distance_start_count,
           count(hist.race_id) FILTER (
               WHERE hist.distance_m = cur.distance_m AND hist.place_hit
           )::INTEGER AS same_distance_plc_hit_count,
           max(hist.race_date) AS source_max_event_date
    FROM base cur
    LEFT JOIN base hist
      ON hist.horse_id = cur.horse_id
     AND hist.race_date < cur.race_date
    GROUP BY cur.race_id, cur.horse_id
),
recent5_ranked AS (
    SELECT cur.race_id,
           cur.horse_id,
           hist.race_id AS history_race_id,
           hist.race_date,
           hist.is_valid_finish,
           hist.official_finish_rank,
           hist.place_hit,
           row_number() OVER (
               PARTITION BY cur.race_id, cur.horse_id
               ORDER BY hist.race_date DESC, hist.race_id DESC
           ) AS recency_rank
    FROM base cur
    JOIN base hist
      ON hist.horse_id = cur.horse_id
     AND hist.race_date < cur.race_date
),
recent5 AS (
    SELECT race_id,
           horse_id,
           count(*)::INTEGER AS recent_start_count,
           count(*) FILTER (WHERE is_valid_finish)::INTEGER AS recent_finish_count,
           count(*) FILTER (WHERE place_hit)::INTEGER AS recent_plc_hit_count,
           avg(official_finish_rank) FILTER (WHERE is_valid_finish)
               AS recent_avg_finish_rank
    FROM recent5_ranked
    WHERE recency_rank <= 5
    GROUP BY race_id, horse_id
),
jockey_history AS (
    SELECT cur.race_id,
           cur.horse_id,
           CASE WHEN cur.jockey_id IS NULL THEN NULL
                ELSE count(hist.race_id)::INTEGER END AS prior_start_count,
           CASE WHEN cur.jockey_id IS NULL THEN NULL
                ELSE count(hist.race_id) FILTER (WHERE hist.place_hit)::INTEGER END
               AS prior_plc_hit_count,
           max(hist.race_date) AS source_max_event_date
    FROM base cur
    LEFT JOIN base hist
      ON cur.jockey_id IS NOT NULL
     AND hist.jockey_id = cur.jockey_id
     AND hist.race_date < cur.race_date
    GROUP BY cur.race_id, cur.horse_id, cur.jockey_id
),
trainer_history AS (
    SELECT cur.race_id,
           cur.horse_id,
           CASE WHEN cur.trainer_id IS NULL THEN NULL
                ELSE count(hist.race_id)::INTEGER END AS prior_start_count,
           CASE WHEN cur.trainer_id IS NULL THEN NULL
                ELSE count(hist.race_id) FILTER (WHERE hist.place_hit)::INTEGER END
               AS prior_plc_hit_count,
           max(hist.race_date) AS source_max_event_date
    FROM base cur
    LEFT JOIN base hist
      ON cur.trainer_id IS NOT NULL
     AND hist.trainer_id = cur.trainer_id
     AND hist.race_date < cur.race_date
    GROUP BY cur.race_id, cur.horse_id, cur.trainer_id
),
history_bounds AS (
    SELECT min(race_date) AS history_window_start_date
    FROM canonical.race
)
SELECT md5((SELECT snapshot_version FROM feature_snapshot_context) || '|' ||
           cur.race_id || '|' || cur.horse_id),
       (SELECT snapshot_version FROM feature_snapshot_context),
       cur.race_id,
       cur.horse_id,
       cur.race_date,
       cur.race_date,
       cur.meet_code,
       cur.race_grade,
       cur.distance_m,
       cur.registered_runner_count,
       cur.gate_no,
       cur.horse_sex,
       cur.horse_age,
       cur.carried_weight,
       cur.rating,
       hh.prior_start_count,
       hh.prior_finish_count,
       hh.prior_finish_count::DOUBLE / nullif(hh.prior_start_count, 0),
       hh.prior_plc_hit_count,
       hh.prior_plc_hit_count::DOUBLE / nullif(hh.prior_start_count, 0),
       hh.prior_avg_finish_rank,
       date_diff('day', hh.last_start_date, cur.race_date)::INTEGER,
       hh.prior_start_count > 0,
       coalesce(r5.recent_start_count, 0),
       r5.recent_finish_count::DOUBLE / nullif(r5.recent_start_count, 0),
       r5.recent_plc_hit_count::DOUBLE / nullif(r5.recent_start_count, 0),
       r5.recent_avg_finish_rank,
       hh.same_distance_start_count,
       hh.same_distance_plc_hit_count::DOUBLE /
           nullif(hh.same_distance_start_count, 0),
       jh.prior_start_count,
       jh.prior_plc_hit_count::DOUBLE / nullif(jh.prior_start_count, 0),
       coalesce(jh.prior_start_count > 0, FALSE),
       th.prior_start_count,
       th.prior_plc_hit_count::DOUBLE / nullif(th.prior_start_count, 0),
       coalesce(th.prior_start_count > 0, FALSE),
       cur.jockey_id,
       cur.trainer_id,
       cur.source_batch_id,
       cur.policy_version,
       hb.history_window_start_date,
       greatest(hh.source_max_event_date,
                jh.source_max_event_date,
                th.source_max_event_date),
       FALSE,
       'POST_RACE_VALID_START_PROXY',
       cur.place_hit,
       cur.result_status,
       cur.is_valid_start,
       cur.is_valid_finish,
       NULL,
       now()
FROM base cur
JOIN horse_history hh USING (race_id, horse_id)
LEFT JOIN recent5 r5 USING (race_id, horse_id)
JOIN jockey_history jh USING (race_id, horse_id)
JOIN trainer_history th USING (race_id, horse_id)
CROSS JOIN history_bounds hb;

UPDATE mart.feature_snapshot_run
SET completed_at = now(),
    status = 'COMPLETED',
    row_count = (SELECT count(*) FROM mart.feature_snapshot_place),
    race_count = (SELECT count(DISTINCT race_id) FROM mart.feature_snapshot_place),
    positive_count = (SELECT count(*) FROM mart.feature_snapshot_place WHERE place_hit),
    no_horse_history_count = (
        SELECT count(*) FROM mart.feature_snapshot_place
        WHERE NOT horse_history_available
    )
WHERE snapshot_version = (SELECT snapshot_version FROM feature_snapshot_context);
