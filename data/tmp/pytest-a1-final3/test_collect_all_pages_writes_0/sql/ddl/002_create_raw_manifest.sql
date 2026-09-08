CREATE TABLE IF NOT EXISTS raw.collection_batch (
    batch_id VARCHAR PRIMARY KEY,
    api_name VARCHAR NOT NULL,
    scope_json JSON NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status VARCHAR NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    no_data_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw.api_request (
    request_id VARCHAR PRIMARY KEY,
    batch_id VARCHAR NOT NULL,
    api_name VARCHAR NOT NULL,
    request_year INTEGER NOT NULL,
    meet_code INTEGER NOT NULL,
    page_no INTEGER NOT NULL,
    page_size INTEGER NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    request_url_redacted VARCHAR NOT NULL,
    http_status INTEGER,
    api_status VARCHAR NOT NULL,
    result_code VARCHAR,
    total_count INTEGER,
    item_count INTEGER NOT NULL DEFAULT 0,
    error_message VARCHAR,
    FOREIGN KEY (batch_id) REFERENCES raw.collection_batch(batch_id)
);

CREATE TABLE IF NOT EXISTS raw.raw_file (
    raw_file_id VARCHAR PRIMARY KEY,
    request_id VARCHAR NOT NULL UNIQUE,
    relative_path VARCHAR NOT NULL UNIQUE,
    sha256 VARCHAR NOT NULL,
    size_bytes BIGINT NOT NULL,
    written_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (request_id) REFERENCES raw.api_request(request_id)
);

