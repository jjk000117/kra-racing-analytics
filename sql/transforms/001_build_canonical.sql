DELETE FROM quality.data_issue;
DELETE FROM canonical.winning_payout;
DELETE FROM canonical.sales_dividend;
DELETE FROM canonical.runner_result;
DELETE FROM canonical.race;
DELETE FROM canonical.transform_run;

INSERT INTO canonical.transform_run (
    transform_version, race_batch_id, sales_batch_id, policy_version,
    started_at, completed_at, status, race_count, runner_count, sales_count,
    issue_count, winning_payout_count
)
SELECT transform_version, race_batch_id, sales_batch_id, policy_version,
       started_at, NULL, 'RUNNING', 0, 0, 0, 0, 0
FROM canonical_context;

INSERT INTO canonical.race (
    race_id, race_date, meet_code, meet_name, race_no, race_name, race_grade,
    distance_m, weather, track_condition, runner_count, source_batch_id,
    policy_version, created_at
)
SELECT
    strftime(strptime(rcDate, '%Y%m%d'), '%Y-%m-%d') || '|' ||
        CASE WHEN meet IN ('1', '서울') THEN '1' ELSE '3' END || '|R' ||
        lpad(try_cast(rcNo AS INTEGER)::VARCHAR, 2, '0'),
    strptime(rcDate, '%Y%m%d')::DATE,
    CASE WHEN meet IN ('1', '서울') THEN 1 ELSE 3 END,
    CASE WHEN meet IN ('1', '서울') THEN '서울' ELSE '부산경남' END,
    try_cast(rcNo AS INTEGER), max(nullif(trim(rcName), '')),
    max(nullif(trim(rank), '')), max(try_cast(rcDist AS INTEGER)),
    max(nullif(trim(weather), '')), max(nullif(trim(track), '')),
    count(*)::INTEGER, min(batch_id),
    (SELECT policy_version FROM canonical_context), now()
FROM staging.race_result
WHERE batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
  AND try_strptime(rcDate, '%Y%m%d') IS NOT NULL
  AND meet IN ('1', '3', '서울', '부산경남')
  AND try_cast(rcNo AS INTEGER) IS NOT NULL
GROUP BY rcDate, meet, rcNo
HAVING count(DISTINCT coalesce(rcName, '')) <= 1
   AND count(DISTINCT coalesce(rank, '')) <= 1
   AND count(DISTINCT coalesce(rcDist, '')) <= 1
   AND count(DISTINCT coalesce(weather, '')) <= 1
   AND count(DISTINCT coalesce(track, '')) <= 1
   AND count(DISTINCT batch_id) = 1;

UPDATE canonical.race r
SET race_status = e.race_status
FROM canonical.race_status_exception e
WHERE e.policy_version = (SELECT policy_version FROM canonical_context)
  AND e.race_id = r.race_id;

INSERT INTO canonical.runner_result
SELECT
    r.race_id || '|H' || s.hrNo, r.race_id, s.hrNo,
    nullif(trim(s.hrName), ''), nullif(trim(s.jkNo), ''),
    nullif(trim(s.jkName), ''), nullif(trim(s.trNo), ''),
    nullif(trim(s.trName), ''), nullif(trim(s.owNo), ''),
    nullif(trim(s.owName), ''), try_cast(s.chulNo AS INTEGER),
    nullif(trim(s.sex), ''), try_cast(s.age AS INTEGER),
    try_cast(s.wgBudam AS DECIMAL(8, 2)), try_cast(s.wgHr AS DECIMAL(8, 2)),
    try_cast(s.rcTime AS INTEGER), try_cast(s.winOdds AS DECIMAL(12, 4)),
    try_cast(s.plcOdds AS DECIMAL(12, 4)), s.ord,
    CASE WHEN r.race_status = 'COMPLETED' AND s.ord_numeric BETWEEN 1 AND 16
         THEN s.ord_numeric END,
    CASE WHEN r.race_status = 'RACE_CANCELLED' THEN 'RACE_CANCELLED'
         WHEN r.race_status = 'RESULT_NOT_FINALIZED' THEN 'RESULT_NOT_FINALIZED'
         WHEN s.ord_numeric BETWEEN 1 AND 16 THEN 'FINISHED'
         WHEN s.ord_numeric IS NULL THEN 'MISSING'
         ELSE coalesce(cr.result_status, p.result_status, 'NON_STANDARD_UNRESOLVED') END,
    CASE WHEN r.race_status <> 'COMPLETED' THEN FALSE
         WHEN s.ord_numeric BETWEEN 1 AND 16 THEN TRUE
         ELSE coalesce(cr.is_valid_start, p.is_valid_start, FALSE) END,
    CASE WHEN r.race_status <> 'COMPLETED' THEN FALSE
         WHEN s.ord_numeric BETWEEN 1 AND 16 THEN TRUE
         ELSE coalesce(cr.is_valid_finish, p.is_valid_finish, FALSE) END,
    s.staging_row_id, s.batch_id,
    (SELECT policy_version FROM canonical_context), now()
FROM staging.race_result s
LEFT JOIN canonical.result_status_composite_rule cr
  ON cr.policy_version = (SELECT policy_version FROM canonical_context)
 AND cr.ord_code = s.ord_numeric
 AND cr.race_time = try_cast(s.rcTime AS INTEGER)
LEFT JOIN canonical.result_status_policy p
  ON p.policy_version = (SELECT policy_version FROM canonical_context)
 AND p.ord_code = s.ord_numeric
JOIN canonical.race r
  ON r.race_date = try_strptime(s.rcDate, '%Y%m%d')::DATE
 AND r.meet_code = CASE WHEN s.meet IN ('1', '서울') THEN 1 ELSE 3 END
 AND r.race_no = try_cast(s.rcNo AS INTEGER)
WHERE s.batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
  AND nullif(trim(s.hrNo), '') IS NOT NULL
QUALIFY count(*) OVER (
    PARTITION BY s.rcDate, s.meet, s.rcNo, s.hrNo
) = 1;

INSERT INTO canonical.sales_dividend
SELECT r.race_id || '|P' || s.pool, r.race_id, s.pool, s.pool,
       s.amt_numeric, s.odds, TRUE, s.staging_row_id, s.batch_id,
       (SELECT policy_version FROM canonical_context), now()
FROM staging.sales_dividend s
JOIN canonical.race r
  ON r.race_date = try_strptime(s.rcDate, '%Y%m%d')::DATE
 AND r.meet_code = CASE WHEN s.meet IN ('1', '서울') THEN 1 ELSE 3 END
 AND r.race_no = try_cast(s.rcNo AS INTEGER)
WHERE s.batch_id IN (SELECT batch_id FROM canonical_sales_batch_scope)
  AND s.amt_parse_valid AND nullif(trim(s.pool), '') IS NOT NULL
  AND nullif(trim(s.odds), '') IS NOT NULL
QUALIFY count(*) OVER (
    PARTITION BY s.rcDate, s.meet, s.rcNo, s.pool
) = 1;

INSERT INTO quality.data_issue
SELECT md5('RACE_ATTRIBUTE_CONFLICT|' || rcDate || '|' || meet || '|' || rcNo),
       'RACE_ATTRIBUTE_CONFLICT', 'ERROR', 'staging.race_result', NULL,
       rcDate || '|' || meet || '|R' || rcNo, NULL,
       'Runner rows disagree on race-level attributes', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.race_result
WHERE batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
GROUP BY rcDate, meet, rcNo
HAVING count(DISTINCT coalesce(rcName, '')) > 1
    OR count(DISTINCT coalesce(rank, '')) > 1
    OR count(DISTINCT coalesce(rcDist, '')) > 1
    OR count(DISTINCT coalesce(weather, '')) > 1
    OR count(DISTINCT coalesce(track, '')) > 1;

INSERT INTO quality.data_issue
SELECT md5('INVALID_RACE_KEY|' || staging_row_id), 'INVALID_RACE_KEY', 'ERROR',
       'staging.race_result', staging_row_id, coalesce(rcDate, '') || '|' ||
       coalesce(meet, '') || '|R' || coalesce(rcNo, '') || '|H' || coalesce(hrNo, ''),
       NULL, 'Required race or runner key is missing or invalid', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.race_result
WHERE batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
  AND (try_strptime(rcDate, '%Y%m%d') IS NULL
       OR meet NOT IN ('1', '3', '서울', '부산경남')
       OR try_cast(rcNo AS INTEGER) IS NULL OR nullif(trim(hrNo), '') IS NULL);

INSERT INTO quality.data_issue
SELECT md5('DUPLICATE_RUNNER_KEY|' || staging_row_id), 'DUPLICATE_RUNNER_KEY',
       'ERROR', 'staging.race_result', staging_row_id,
       rcDate || '|' || meet || '|R' || rcNo || '|H' || hrNo, NULL,
       'Conflicting source rows share the runner business key', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.race_result
WHERE batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
QUALIFY count(*) OVER (PARTITION BY rcDate, meet, rcNo, hrNo) > 1;

INSERT INTO quality.data_issue
SELECT md5('INVALID_SALES_ROW|' || staging_row_id), 'INVALID_SALES_ROW', 'ERROR',
       'staging.sales_dividend', staging_row_id, coalesce(rcDate, '') || '|' ||
       coalesce(meet, '') || '|R' || coalesce(rcNo, '') || '|P' || coalesce(pool, ''),
       amt, 'Required sales key, amount, or odds is missing or invalid', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.sales_dividend
WHERE batch_id IN (SELECT batch_id FROM canonical_sales_batch_scope)
  AND (try_strptime(rcDate, '%Y%m%d') IS NULL
       OR meet NOT IN ('1', '3', '서울', '부산경남')
       OR try_cast(rcNo AS INTEGER) IS NULL OR nullif(trim(pool), '') IS NULL
       OR NOT amt_parse_valid OR nullif(trim(odds), '') IS NULL);

INSERT INTO quality.data_issue
SELECT md5('DUPLICATE_SALES_KEY|' || staging_row_id), 'DUPLICATE_SALES_KEY',
       'ERROR', 'staging.sales_dividend', staging_row_id,
       rcDate || '|' || meet || '|R' || rcNo || '|P' || pool, NULL,
       'Conflicting source rows share the sales business key', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.sales_dividend
WHERE batch_id IN (SELECT batch_id FROM canonical_sales_batch_scope)
QUALIFY count(*) OVER (PARTITION BY rcDate, meet, rcNo, pool) > 1;

INSERT INTO quality.data_issue
SELECT md5('NON_STANDARD_ORD|' || staging_row_id), 'NON_STANDARD_ORD', 'WARNING',
       'staging.race_result', staging_row_id,
       rcDate || '|' || meet || '|R' || rcNo || '|H' || hrNo, ord,
       'ord is not an official finish rank from 1 through 16', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.race_result
WHERE batch_id IN (SELECT batch_id FROM canonical_race_batch_scope)
  AND NOT coalesce(ord_numeric BETWEEN 1 AND 16, FALSE);

INSERT INTO quality.data_issue
SELECT md5('RACE_WITHOUT_SALES|' || r.race_id), 'RACE_WITHOUT_SALES', 'WARNING',
       'canonical.race', NULL, r.race_id, NULL,
       'Race result exists without API179_1 sales rows', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM canonical.race r
LEFT JOIN canonical.sales_dividend s ON s.race_id = r.race_id
WHERE s.race_id IS NULL;

INSERT INTO quality.data_issue
SELECT md5('SALES_WITHOUT_RACE|' || s.staging_row_id), 'SALES_WITHOUT_RACE', 'ERROR',
       'staging.sales_dividend', s.staging_row_id,
       s.rcDate || '|' || s.meet || '|R' || s.rcNo, s.pool,
       'Sales row has no matching canonical race', now(),
       (SELECT transform_version FROM canonical_context),
       (SELECT policy_version FROM canonical_context)
FROM staging.sales_dividend s
LEFT JOIN canonical.race r
  ON r.race_date = try_strptime(s.rcDate, '%Y%m%d')::DATE
 AND r.meet_code = CASE WHEN s.meet IN ('1', '서울') THEN 1 ELSE 3 END
 AND r.race_no = try_cast(s.rcNo AS INTEGER)
WHERE s.batch_id IN (SELECT batch_id FROM canonical_sales_batch_scope)
  AND r.race_id IS NULL;

UPDATE canonical.transform_run
SET completed_at = now(), status = 'COMPLETED',
    race_count = (SELECT count(*) FROM canonical.race),
    runner_count = (SELECT count(*) FROM canonical.runner_result),
    sales_count = (SELECT count(*) FROM canonical.sales_dividend),
    issue_count = (SELECT count(*) FROM quality.data_issue)
WHERE transform_version = (SELECT transform_version FROM canonical_context);
