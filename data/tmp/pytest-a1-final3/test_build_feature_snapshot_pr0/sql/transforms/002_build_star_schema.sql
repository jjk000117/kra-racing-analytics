DELETE FROM analytics.fact_sales;
DELETE FROM analytics.fact_race;
DELETE FROM analytics.dim_date;
DELETE FROM analytics.dim_meet;
DELETE FROM analytics.transform_run;

INSERT INTO analytics.transform_run
SELECT transform_version, canonical_transform_version, started_at, NULL, 'RUNNING', 0, 0, 0, 0
FROM star_context;

INSERT INTO analytics.dim_date
WITH bounds AS (
    SELECT min(race_date) AS min_date, max(race_date) AS max_date
    FROM canonical.race
),
dates AS (
    SELECT unnest(generate_series(min_date, max_date, INTERVAL 1 DAY))::DATE AS full_date,
           date_trunc('month', min_date)::DATE AS min_month,
           date_trunc('month', max_date)::DATE AS max_month
    FROM bounds
)
SELECT strftime(full_date, '%Y%m%d')::INTEGER,
       full_date,
       year(full_date)::INTEGER,
       quarter(full_date)::INTEGER,
       month(full_date)::INTEGER,
       strftime(full_date, '%Y-%m'),
       date_trunc('month', full_date)::DATE,
       isodow(full_date)::INTEGER,
       CASE isodow(full_date)
           WHEN 1 THEN '월요일' WHEN 2 THEN '화요일' WHEN 3 THEN '수요일'
           WHEN 4 THEN '목요일' WHEN 5 THEN '금요일' WHEN 6 THEN '토요일'
           ELSE '일요일'
       END,
       date_trunc('month', full_date)::DATE IN (min_month, max_month)
FROM dates;

INSERT INTO analytics.dim_meet
SELECT meet_code, meet_code, min(meet_name)
FROM canonical.race
GROUP BY meet_code;

INSERT INTO analytics.fact_race
WITH sales_profile AS (
    SELECT s.race_id,
           count(DISTINCT p.pool_code)::INTEGER AS mapped_pool_count,
           count(*)::INTEGER AS sales_row_count
    FROM canonical.sales_dividend s
    LEFT JOIN analytics.dim_pool p ON p.pool_name_raw = s.pool_code
    GROUP BY s.race_id
),
prepared AS (
    SELECT r.*,
           coalesce(sp.mapped_pool_count, 0)::INTEGER AS pool_count,
           coalesce(sp.mapped_pool_count = 7 AND sp.sales_row_count = 7, FALSE)
               AS has_all_official_pools
    FROM canonical.race r
    LEFT JOIN sales_profile sp ON sp.race_id = r.race_id
)
SELECT row_number() OVER (ORDER BY r.race_id)::BIGINT,
       r.race_id,
       strftime(r.race_date, '%Y%m%d')::INTEGER,
       r.meet_code,
       g.grade_key,
       r.race_no,
       r.distance_m,
       r.runner_count,
       r.race_status,
       r.pool_count,
       r.has_all_official_pools,
       r.race_status = 'COMPLETED' AND r.has_all_official_pools,
       1,
       r.source_batch_id,
       (SELECT transform_version FROM star_context),
       now()
FROM prepared r
JOIN analytics.dim_race_grade g ON g.race_grade_raw = r.race_grade;

INSERT INTO analytics.fact_sales
SELECT row_number() OVER (ORDER BY s.sales_id)::BIGINT,
       s.sales_id,
       s.race_id,
       strftime(r.race_date, '%Y%m%d')::INTEGER,
       r.meet_code,
       g.grade_key,
       p.pool_key,
       s.sales_amount,
       s.confirmed_odds_raw,
       s.is_post_race,
       s.source_batch_id,
       (SELECT transform_version FROM star_context),
       now()
FROM canonical.sales_dividend s
JOIN canonical.race r ON r.race_id = s.race_id
JOIN analytics.dim_race_grade g ON g.race_grade_raw = r.race_grade
JOIN analytics.dim_pool p ON p.pool_name_raw = s.pool_code;

CREATE OR REPLACE VIEW analytics.mart_complete_race AS
SELECT *
FROM analytics.fact_race
WHERE is_market_eligible;

CREATE OR REPLACE VIEW analytics.mart_market_sales AS
SELECT s.*, r.race_no, r.distance_m, r.runner_count
FROM analytics.fact_sales s
JOIN analytics.fact_race r ON r.race_id = s.race_id
WHERE r.is_market_eligible;

CREATE OR REPLACE VIEW analytics.mart_monthly_market AS
SELECT d.year_month,
       p.pool_code,
       p.pool_name_official,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       avg(s.sales_amount) AS average_sales_per_race,
       median(s.sales_amount) AS median_sales_per_race
FROM analytics.mart_market_sales s
JOIN analytics.dim_date d ON d.date_key = s.date_key
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY d.year_month, p.pool_code, p.pool_name_official;

CREATE OR REPLACE VIEW analytics.mart_meet_market AS
SELECT m.meet_code,
       m.meet_name,
       p.pool_code,
       p.pool_name_official,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       avg(s.sales_amount) AS average_sales_per_race,
       median(s.sales_amount) AS median_sales_per_race
FROM analytics.mart_market_sales s
JOIN analytics.dim_meet m ON m.meet_key = s.meet_key
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY m.meet_code, m.meet_name, p.pool_code, p.pool_name_official;

CREATE OR REPLACE VIEW analytics.mart_grade_market AS
SELECT g.race_grade_raw,
       g.grade_scope,
       p.pool_code,
       p.pool_name_official,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       avg(s.sales_amount) AS average_sales_per_race,
       median(s.sales_amount) AS median_sales_per_race
FROM analytics.mart_market_sales s
JOIN analytics.dim_race_grade g ON g.grade_key = s.grade_key
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY g.race_grade_raw, g.grade_scope, p.pool_code, p.pool_name_official;

CREATE OR REPLACE VIEW analytics.mart_grade_meet_market AS
SELECT m.meet_code,
       m.meet_name,
       g.race_grade_raw,
       g.grade_scope,
       p.pool_code,
       p.pool_name_official,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       avg(s.sales_amount) AS average_sales_per_race,
       median(s.sales_amount) AS median_sales_per_race
FROM analytics.mart_market_sales s
JOIN analytics.dim_meet m ON m.meet_key = s.meet_key
JOIN analytics.dim_race_grade g ON g.grade_key = s.grade_key
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY m.meet_code, m.meet_name, g.race_grade_raw, g.grade_scope,
         p.pool_code, p.pool_name_official;

UPDATE analytics.transform_run
SET completed_at = now(),
    status = 'COMPLETED',
    race_count = (SELECT count(*) FROM analytics.fact_race),
    sales_count = (SELECT count(*) FROM analytics.fact_sales),
    eligible_race_count = (SELECT count(*) FROM analytics.mart_complete_race),
    market_sales_count = (SELECT count(*) FROM analytics.mart_market_sales)
WHERE transform_version = (SELECT transform_version FROM star_context);
