-- Compare pool market structure without using race count or a composite score.
WITH runner_counts AS (
    SELECT race_id, count(*) FILTER (WHERE is_valid_start) AS valid_starters
    FROM canonical.runner_result
    GROUP BY race_id
), payout AS (
    SELECT sales_id, count(*) AS winning_combinations,
           median(confirmed_odds) AS race_median_odds
    FROM canonical.winning_payout
    GROUP BY sales_id
), race_pool AS (
    SELECT p.pool_code, p.pool_name_official, p.selection_count, p.order_matters,
           s.sales_amount, r.runner_count AS registered_runners, rc.valid_starters,
           w.winning_combinations, w.race_median_odds,
           CASE p.pool_code
               WHEN 'WIN' THEN rc.valid_starters
               WHEN 'PLC' THEN rc.valid_starters
               WHEN 'QNL' THEN rc.valid_starters * (rc.valid_starters - 1) / 2
               WHEN 'EXA' THEN rc.valid_starters * (rc.valid_starters - 1)
               WHEN 'QPL' THEN rc.valid_starters * (rc.valid_starters - 1) / 2
               WHEN 'TLA' THEN rc.valid_starters * (rc.valid_starters - 1) *
                                   (rc.valid_starters - 2) / 6
               WHEN 'TRI' THEN rc.valid_starters * (rc.valid_starters - 1) *
                                   (rc.valid_starters - 2)
           END::DOUBLE AS possible_combinations,
           CASE p.pool_code
               WHEN 'WIN' THEN r.runner_count
               WHEN 'PLC' THEN r.runner_count
               WHEN 'QNL' THEN r.runner_count * (r.runner_count - 1) / 2
               WHEN 'EXA' THEN r.runner_count * (r.runner_count - 1)
               WHEN 'QPL' THEN r.runner_count * (r.runner_count - 1) / 2
               WHEN 'TLA' THEN r.runner_count * (r.runner_count - 1) *
                                   (r.runner_count - 2) / 6
               WHEN 'TRI' THEN r.runner_count * (r.runner_count - 1) *
                                   (r.runner_count - 2)
           END::DOUBLE AS registered_combinations
    FROM analytics.mart_market_sales s
    JOIN analytics.dim_pool p USING (pool_key)
    JOIN canonical.race r USING (race_id)
    JOIN runner_counts rc USING (race_id)
    JOIN payout w USING (sales_id)
), summarized AS (
    SELECT pool_code, pool_name_official, selection_count, order_matters,
           sum(sales_amount) AS total_sales,
           quantile_cont(possible_combinations, 0.25) AS combinations_q25,
           median(possible_combinations) AS combinations_median,
           quantile_cont(possible_combinations, 0.75) AS combinations_q75,
           quantile_cont(winning_combinations / possible_combinations, 0.25)
               AS naive_probability_q25,
           median(winning_combinations / possible_combinations) AS naive_probability_median,
           quantile_cont(winning_combinations / possible_combinations, 0.75)
               AS naive_probability_q75,
           median(winning_combinations / registered_combinations)
               AS registered_naive_probability_median,
           median(race_median_odds) AS confirmed_odds_median,
           quantile_cont(race_median_odds, 0.95) AS confirmed_odds_q95,
           quantile_cont(race_median_odds, 0.99) AS confirmed_odds_q99
    FROM race_pool
    GROUP BY pool_code, pool_name_official, selection_count, order_matters
), metrics AS (
    SELECT *, total_sales / sum(total_sales) OVER () AS sales_share,
           confirmed_odds_q99 / confirmed_odds_median AS payout_tail_ratio
    FROM summarized
), compared AS (
    SELECT candidate.*,
           NOT EXISTS (
               SELECT 1 FROM metrics competitor
               WHERE competitor.pool_code <> candidate.pool_code
                 AND competitor.sales_share >= candidate.sales_share
                 AND competitor.naive_probability_median >=
                     candidate.naive_probability_median
                 AND competitor.combinations_median <= candidate.combinations_median
                 AND competitor.payout_tail_ratio <= candidate.payout_tail_ratio
                 AND (
                     competitor.sales_share > candidate.sales_share
                     OR competitor.naive_probability_median >
                        candidate.naive_probability_median
                     OR competitor.combinations_median < candidate.combinations_median
                     OR competitor.payout_tail_ratio < candidate.payout_tail_ratio
                 )
           ) AS is_pareto_candidate
    FROM metrics candidate
)
SELECT * FROM compared
ORDER BY selection_count, order_matters, pool_code;
