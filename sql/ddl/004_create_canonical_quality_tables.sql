CREATE TABLE IF NOT EXISTS canonical.transform_run (
    transform_version VARCHAR PRIMARY KEY,
    race_batch_id VARCHAR NOT NULL,
    sales_batch_id VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    race_count BIGINT NOT NULL DEFAULT 0,
    runner_count BIGINT NOT NULL DEFAULT 0,
    sales_count BIGINT NOT NULL DEFAULT 0,
    issue_count BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS canonical.result_status_policy (
    policy_version VARCHAR NOT NULL,
    ord_code INTEGER NOT NULL,
    result_status VARCHAR NOT NULL,
    is_valid_start BOOLEAN NOT NULL,
    is_valid_finish BOOLEAN NOT NULL,
    note VARCHAR NOT NULL,
    PRIMARY KEY (policy_version, ord_code)
);

INSERT INTO canonical.result_status_policy VALUES
    ('race_status_v1', 0, 'NON_STANDARD_UNRESOLVED', FALSE, FALSE,
     'Meaning not inferred without official evidence'),
    ('race_status_v1', 91, 'PARTICIPATED_NON_FINISH', TRUE, FALSE,
     'Inherited project policy: counts as participation, not finish'),
    ('race_status_v1', 92, 'PARTICIPATED_NON_FINISH', TRUE, FALSE,
     'Inherited project policy: counts as participation, not finish'),
    ('race_status_v1', 93, 'NON_STANDARD_UNRESOLVED', FALSE, FALSE,
     'DNS only when the separate composite rule also matches rcTime=0'),
    ('race_status_v1', 94, 'NON_STANDARD_UNRESOLVED', FALSE, FALSE,
     'DNS only when the separate composite rule also matches rcTime=0'),
    ('race_status_v1', 95, 'NON_STANDARD_UNRESOLVED', FALSE, FALSE,
     'DNS only when the separate composite rule also matches rcTime=0'),
    ('race_status_v1', 99, 'NON_STANDARD_UNRESOLVED', FALSE, FALSE,
     'Meaning not inferred without official evidence')
ON CONFLICT (policy_version, ord_code) DO UPDATE SET
    result_status = excluded.result_status,
    is_valid_start = excluded.is_valid_start,
    is_valid_finish = excluded.is_valid_finish,
    note = excluded.note;

CREATE TABLE IF NOT EXISTS canonical.result_status_composite_rule (
    policy_version VARCHAR NOT NULL,
    ord_code INTEGER NOT NULL,
    race_time INTEGER NOT NULL,
    result_status VARCHAR NOT NULL,
    is_valid_start BOOLEAN NOT NULL,
    is_valid_finish BOOLEAN NOT NULL,
    note VARCHAR NOT NULL,
    PRIMARY KEY (policy_version, ord_code, race_time)
);

INSERT INTO canonical.result_status_composite_rule VALUES
    ('race_status_v1', 93, 0, 'DNS', FALSE, FALSE,
     'ord 93 with rcTime 0 is did-not-start'),
    ('race_status_v1', 94, 0, 'DNS', FALSE, FALSE,
     'ord 94 with rcTime 0 is did-not-start'),
    ('race_status_v1', 95, 0, 'DNS', FALSE, FALSE,
     'ord 95 with rcTime 0 is did-not-start')
ON CONFLICT (policy_version, ord_code, race_time) DO UPDATE SET
    result_status = excluded.result_status,
    is_valid_start = excluded.is_valid_start,
    is_valid_finish = excluded.is_valid_finish,
    note = excluded.note;

CREATE TABLE IF NOT EXISTS canonical.race (
    race_id VARCHAR PRIMARY KEY,
    race_date DATE NOT NULL,
    meet_code INTEGER NOT NULL,
    meet_name VARCHAR NOT NULL,
    race_no INTEGER NOT NULL,
    race_name VARCHAR,
    race_grade VARCHAR,
    distance_m INTEGER,
    weather VARCHAR,
    track_condition VARCHAR,
    runner_count INTEGER NOT NULL,
    source_batch_id VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (race_date, meet_code, race_no)
);

CREATE TABLE IF NOT EXISTS canonical.runner_result (
    runner_result_id VARCHAR PRIMARY KEY,
    race_id VARCHAR NOT NULL,
    horse_id VARCHAR NOT NULL,
    horse_name VARCHAR,
    jockey_id VARCHAR,
    jockey_name VARCHAR,
    trainer_id VARCHAR,
    trainer_name VARCHAR,
    owner_id VARCHAR,
    owner_name VARCHAR,
    gate_no INTEGER,
    horse_sex VARCHAR,
    horse_age INTEGER,
    carried_weight DECIMAL(8, 2),
    horse_weight DECIMAL(8, 2),
    race_time INTEGER,
    win_odds DECIMAL(12, 4),
    place_odds DECIMAL(12, 4),
    ord_raw VARCHAR,
    official_finish_rank INTEGER,
    result_status VARCHAR NOT NULL,
    is_valid_start BOOLEAN NOT NULL,
    is_valid_finish BOOLEAN NOT NULL,
    source_staging_row_id VARCHAR NOT NULL UNIQUE,
    source_batch_id VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (race_id, horse_id)
);

CREATE TABLE IF NOT EXISTS canonical.sales_dividend (
    sales_id VARCHAR PRIMARY KEY,
    race_id VARCHAR NOT NULL,
    pool_code VARCHAR NOT NULL,
    pool_name VARCHAR NOT NULL,
    sales_amount DECIMAL(20, 0) NOT NULL,
    confirmed_odds_raw VARCHAR NOT NULL,
    is_post_race BOOLEAN NOT NULL DEFAULT TRUE,
    source_staging_row_id VARCHAR NOT NULL UNIQUE,
    source_batch_id VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (race_id, pool_code)
);

CREATE TABLE IF NOT EXISTS quality.data_issue (
    issue_id VARCHAR PRIMARY KEY,
    rule_code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    source_table VARCHAR NOT NULL,
    source_staging_row_id VARCHAR,
    business_key VARCHAR NOT NULL,
    observed_value VARCHAR,
    message VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    transform_version VARCHAR NOT NULL,
    policy_version VARCHAR NOT NULL
);
