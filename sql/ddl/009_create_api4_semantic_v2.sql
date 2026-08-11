CREATE SCHEMA IF NOT EXISTS semantic;

CREATE OR REPLACE VIEW semantic.api4_runner_event_v2 AS
WITH parsed AS (
    SELECT
        s.*,
        try_strptime(s.rcDate, '%Y%m%d')::DATE AS race_date,
        CASE WHEN s.meet IN ('1', '서울') THEN 1
             WHEN s.meet IN ('3', '부산경남') THEN 3 END AS meet_code,
        try_cast(s.rcDist AS INTEGER) AS distance_m,
        try_cast(s.rcTime AS DECIMAL(8, 1)) AS race_time_seconds,
        try_cast(regexp_extract(s.wgHr, '^\s*([0-9]{2,3})', 1) AS INTEGER)
            AS horse_weight_kg,
        try_cast(regexp_extract(s.wgHr, '\(\s*([+-]?[0-9]+)\s*\)', 1) AS INTEGER)
            AS horse_weight_change_kg,
        nullif(trim(regexp_replace(s.track, '\s*\([0-9]+%\)\s*$', '')), '')
            AS track_condition,
        try_cast(regexp_extract(s.track, '\(\s*([0-9]+)\s*%\s*\)', 1) AS INTEGER)
            AS track_moisture_percent
    FROM staging.race_result s
), sectionals AS (
    SELECT
        p.*,
        CASE WHEN meet_code = 1
             THEN nullif(try_cast(seS1fAccTime AS DECIMAL(8, 1)), 0)
             WHEN meet_code = 3
             THEN nullif(try_cast(buS1fTime AS DECIMAL(8, 1)), 0)
        END AS s1f_seconds,
        nullif(try_cast(seG3fAccTime AS DECIMAL(8, 1)), 0)
            AS se_g3f_acc_time_seconds,
        nullif(try_cast(seG1fAccTime AS DECIMAL(8, 1)), 0)
            AS se_g1f_acc_time_seconds,
        nullif(try_cast(bu_3fGTime AS DECIMAL(8, 1)), 0)
            AS bu_g3f_to_finish_seconds,
        nullif(try_cast(bu_1fGTime AS DECIMAL(8, 1)), 0)
            AS bu_g1f_to_finish_seconds,
        nullif(try_cast(buG3fAccTime AS DECIMAL(8, 1)), 0)
            AS bu_g3f_acc_time_seconds,
        nullif(try_cast(buG1fAccTime AS DECIMAL(8, 1)), 0)
            AS bu_g1f_acc_time_seconds
    FROM parsed p
)
SELECT
    staging_row_id,
    batch_id,
    request_id,
    raw_file_id,
    raw_sha256,
    source_row_number,
    race_date,
    meet_code,
    try_cast(rcNo AS INTEGER) AS race_no,
    nullif(trim(hrNo), '') AS horse_id,
    try_cast(chulNo AS INTEGER) AS gate_no,
    distance_m,
    nullif(trim(rank), '') AS race_grade,
    nullif(trim(weather), '') AS weather,
    nullif(trim(track), '') AS track_raw,
    track_condition,
    track_moisture_percent,
    nullif(trim(rcTime), '') AS race_time_raw,
    race_time_seconds,
    nullif(race_time_seconds, 0) AS valid_race_time_seconds,
    nullif(trim(wgHr), '') AS horse_weight_raw,
    horse_weight_kg,
    horse_weight_change_kg,
    s1f_seconds,
    se_g3f_acc_time_seconds,
    se_g1f_acc_time_seconds,
    bu_g3f_to_finish_seconds,
    bu_g1f_to_finish_seconds,
    bu_g3f_acc_time_seconds,
    bu_g1f_acc_time_seconds,
    CASE
        WHEN meet_code = 1 AND nullif(race_time_seconds, 0) IS NOT NULL
            THEN nullif(race_time_seconds - se_g3f_acc_time_seconds, 0)
        WHEN meet_code = 3 THEN bu_g3f_to_finish_seconds
    END AS historical_g3f_seconds,
    CASE
        WHEN meet_code = 1 AND nullif(race_time_seconds, 0) IS NOT NULL
            THEN nullif(race_time_seconds - se_g1f_acc_time_seconds, 0)
        WHEN meet_code = 3 THEN bu_g1f_to_finish_seconds
    END AS historical_g1f_seconds,
    CASE
        WHEN meet_code = 1 THEN 'SEOUL_SE_ACC_FIELDS'
        WHEN meet_code = 3 THEN 'BUSAN_BU_SPLIT_FIELDS'
        ELSE 'UNSUPPORTED_MEET'
    END AS sectional_mapping,
    CASE WHEN s1f_seconds IS NOT NULL THEN 'S1F_AVAILABLE'
         ELSE 'STRUCTURAL_OR_RESULT_MISSING' END AS sectional_status,
    source_item_json,
    'api4_runner_event_v2' AS semantic_version
FROM sectionals;
