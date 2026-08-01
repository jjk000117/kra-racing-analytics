SELECT m.meet_name,
       p.pool_code,
       p.pool_name_official,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       sum(s.sales_amount) /
           sum(sum(s.sales_amount)) OVER (PARTITION BY m.meet_name) AS market_share
FROM analytics.mart_market_sales s
JOIN analytics.dim_meet m ON m.meet_key = s.meet_key
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY m.meet_name, p.pool_code, p.pool_name_official, p.display_order
ORDER BY p.display_order, m.meet_name;
