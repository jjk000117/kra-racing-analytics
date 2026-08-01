SELECT p.pool_code,
       p.pool_name_official,
       p.selection_count,
       p.order_matters,
       p.display_order,
       count(DISTINCT s.race_id) AS race_count,
       sum(s.sales_amount) AS total_sales,
       avg(s.sales_amount) AS average_sales_per_race,
       median(s.sales_amount) AS median_sales_per_race
FROM analytics.mart_market_sales s
JOIN analytics.dim_pool p ON p.pool_key = s.pool_key
GROUP BY p.pool_code, p.pool_name_official, p.selection_count,
         p.order_matters, p.display_order
ORDER BY p.display_order;
