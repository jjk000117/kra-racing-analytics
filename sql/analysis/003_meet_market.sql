WITH race_sales AS (
    SELECT s.meet_key,
           s.race_id,
           sum(s.sales_amount) AS race_sales
    FROM analytics.mart_market_sales s
    GROUP BY s.meet_key, s.race_id
)
SELECT m.meet_code,
       m.meet_name,
       count(*) AS race_count,
       sum(r.race_sales) AS total_sales,
       avg(r.race_sales) AS average_sales_per_race,
       median(r.race_sales) AS median_sales_per_race
FROM race_sales r
JOIN analytics.dim_meet m ON m.meet_key = r.meet_key
GROUP BY m.meet_code, m.meet_name
ORDER BY m.meet_code;
