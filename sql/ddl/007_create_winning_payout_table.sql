ALTER TABLE canonical.transform_run
ADD COLUMN IF NOT EXISTS winning_payout_count BIGINT DEFAULT 0;

CREATE TABLE IF NOT EXISTS canonical.winning_payout (
    winning_payout_id VARCHAR PRIMARY KEY,
    sales_id VARCHAR NOT NULL,
    race_id VARCHAR NOT NULL,
    pool_code VARCHAR NOT NULL,
    combination_no INTEGER NOT NULL,
    selection_count INTEGER NOT NULL,
    horse_no_1 INTEGER NOT NULL,
    horse_no_2 INTEGER,
    horse_no_3 INTEGER,
    combination_key VARCHAR NOT NULL,
    order_matters BOOLEAN NOT NULL,
    confirmed_odds DECIMAL(12, 4) NOT NULL,
    confirmed_odds_raw VARCHAR NOT NULL,
    parse_status VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    source_staging_row_id VARCHAR NOT NULL,
    source_batch_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (sales_id, combination_no),
    UNIQUE (sales_id, combination_key)
);
