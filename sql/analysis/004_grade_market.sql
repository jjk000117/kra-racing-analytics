WITH race_sales AS (
    SELECT s.grade_key,
           s.race_id,
           sum(s.sales_amount) AS race_sales
    FROM analytics.mart_market_sales s
    GROUP BY s.grade_key, s.race_id
)
SELECT g.race_grade_raw,
       g.grade_scope,
       g.display_order,
       count(*) AS race_count,
       sum(r.race_sales) AS total_sales,
       avg(r.race_sales) AS average_sales_per_race,
       median(r.race_sales) AS median_sales_per_race
FROM race_sales r
JOIN analytics.dim_race_grade g ON g.grade_key = r.grade_key
GROUP BY g.race_grade_raw, g.grade_scope, g.display_order
ORDER BY g.display_order;
