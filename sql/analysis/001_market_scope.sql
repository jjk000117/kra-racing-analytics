SELECT min(d.full_date) AS date_min,
       max(d.full_date) AS date_max,
       count(DISTINCT s.race_id) AS race_count,
       count(*) AS race_pool_rows,
       count(DISTINCT s.pool_key) AS pool_count,
       sum(s.sales_amount) AS total_sales
FROM analytics.mart_market_sales s
JOIN analytics.dim_date d ON d.date_key = s.date_key;
