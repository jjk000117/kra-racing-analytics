WITH race_sales AS (
    SELECT d.year_month,
           s.race_id,
           sum(s.sales_amount) AS race_sales
    FROM analytics.mart_market_sales s
    JOIN analytics.dim_date d ON d.date_key = s.date_key
    GROUP BY d.year_month, s.race_id
)
SELECT year_month,
       count(*) AS race_count,
       sum(race_sales) AS total_sales,
       avg(race_sales) AS average_sales_per_race,
       median(race_sales) AS median_sales_per_race
FROM race_sales
GROUP BY year_month
ORDER BY year_month;
