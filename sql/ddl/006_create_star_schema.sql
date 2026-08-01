CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.transform_run (
    transform_version VARCHAR PRIMARY KEY,
    canonical_transform_version VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    race_count BIGINT NOT NULL DEFAULT 0,
    sales_count BIGINT NOT NULL DEFAULT 0,
    eligible_race_count BIGINT NOT NULL DEFAULT 0,
    market_sales_count BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analytics.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    year_month VARCHAR NOT NULL,
    month_start_date DATE NOT NULL,
    day_of_week INTEGER NOT NULL,
    day_name_ko VARCHAR NOT NULL,
    is_boundary_month BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_meet (
    meet_key INTEGER PRIMARY KEY,
    meet_code INTEGER NOT NULL UNIQUE,
    meet_name VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.dim_race_grade (
    grade_key INTEGER PRIMARY KEY,
    race_grade_raw VARCHAR NOT NULL UNIQUE,
    grade_scope VARCHAR NOT NULL,
    breed_scope VARCHAR NOT NULL,
    grade_level INTEGER,
    display_order INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS analytics.dim_pool (
    pool_key INTEGER PRIMARY KEY,
    pool_code VARCHAR NOT NULL UNIQUE,
    pool_name_raw VARCHAR NOT NULL UNIQUE,
    pool_name_official VARCHAR NOT NULL,
    selection_count INTEGER NOT NULL,
    order_matters BOOLEAN NOT NULL,
    winning_combinations_per_race VARCHAR NOT NULL,
    display_order INTEGER NOT NULL UNIQUE
);

INSERT INTO analytics.dim_race_grade VALUES
    (1, '1등급', 'REGULAR', 'INTEGRATED', 1, 1),
    (2, '2등급', 'REGULAR', 'INTEGRATED', 2, 2),
    (3, '국3등급', 'REGULAR', 'DOMESTIC', 3, 3),
    (4, '혼3등급', 'REGULAR', 'MIXED', 3, 4),
    (5, '국4등급', 'REGULAR', 'DOMESTIC', 4, 5),
    (6, '혼4등급', 'REGULAR', 'MIXED', 4, 6),
    (7, '국5등급', 'REGULAR', 'DOMESTIC', 5, 7),
    (8, '국6등급', 'REGULAR', 'DOMESTIC', 6, 8),
    (9, '국OPEN', 'OPEN', 'DOMESTIC', NULL, 9),
    (10, '혼OPEN', 'OPEN', 'MIXED', NULL, 10)
ON CONFLICT (grade_key) DO UPDATE SET
    race_grade_raw = excluded.race_grade_raw,
    grade_scope = excluded.grade_scope,
    breed_scope = excluded.breed_scope,
    grade_level = excluded.grade_level,
    display_order = excluded.display_order;

INSERT INTO analytics.dim_pool VALUES
    (1, 'WIN', '단식', '단승식', 1, FALSE, 'one winning horse', 1),
    (2, 'PLC', '연식', '연승식', 1, FALSE, 'multiple placed horses by field-size rule', 2),
    (3, 'QNL', '복식', '복승식', 2, FALSE, 'one unordered first-and-second pair', 3),
    (4, 'EXA', '쌍식', '쌍승식', 2, TRUE, 'one ordered first-and-second pair', 4),
    (5, 'QPL', '복연', '복연승식', 2, FALSE, 'multiple unordered placed pairs', 5),
    (6, 'TLA', '삼복', '삼복승식', 3, FALSE, 'one unordered top-three combination', 6),
    (7, 'TRI', '삼쌍', '삼쌍승식', 3, TRUE, 'one ordered top-three combination', 7)
ON CONFLICT (pool_key) DO UPDATE SET
    pool_code = excluded.pool_code,
    pool_name_raw = excluded.pool_name_raw,
    pool_name_official = excluded.pool_name_official,
    selection_count = excluded.selection_count,
    order_matters = excluded.order_matters,
    winning_combinations_per_race = excluded.winning_combinations_per_race,
    display_order = excluded.display_order;

CREATE TABLE IF NOT EXISTS analytics.fact_race (
    race_key BIGINT PRIMARY KEY,
    race_id VARCHAR NOT NULL UNIQUE,
    date_key INTEGER NOT NULL,
    meet_key INTEGER NOT NULL,
    grade_key INTEGER NOT NULL,
    race_no INTEGER NOT NULL,
    distance_m INTEGER,
    runner_count INTEGER NOT NULL,
    race_status VARCHAR NOT NULL,
    pool_count INTEGER NOT NULL,
    has_all_official_pools BOOLEAN NOT NULL,
    is_market_eligible BOOLEAN NOT NULL,
    race_count INTEGER NOT NULL,
    source_batch_id VARCHAR NOT NULL,
    transform_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics.fact_sales (
    sales_key BIGINT PRIMARY KEY,
    sales_id VARCHAR NOT NULL UNIQUE,
    race_id VARCHAR NOT NULL,
    date_key INTEGER NOT NULL,
    meet_key INTEGER NOT NULL,
    grade_key INTEGER NOT NULL,
    pool_key INTEGER NOT NULL,
    sales_amount DECIMAL(20, 0) NOT NULL,
    confirmed_odds_raw VARCHAR NOT NULL,
    is_post_race BOOLEAN NOT NULL,
    source_batch_id VARCHAR NOT NULL,
    transform_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (race_id, pool_key)
);
