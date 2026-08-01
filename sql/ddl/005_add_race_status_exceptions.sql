ALTER TABLE canonical.race
ADD COLUMN IF NOT EXISTS race_status VARCHAR DEFAULT 'COMPLETED';

ALTER TABLE canonical.race
DROP COLUMN IF EXISTS status_reason;

CREATE TABLE IF NOT EXISTS canonical.race_status_exception (
    policy_version VARCHAR NOT NULL,
    race_id VARCHAR NOT NULL,
    race_status VARCHAR NOT NULL,
    evidence_note VARCHAR NOT NULL,
    PRIMARY KEY (policy_version, race_id)
);

ALTER TABLE canonical.race_status_exception
DROP COLUMN IF EXISTS status_reason;

INSERT INTO canonical.race_status_exception (
    policy_version, race_id, race_status, evidence_note
) VALUES
    ('race_status_v1', '2024-09-29|1|R02', 'RACE_CANCELLED',
     'KRA race search result confirmed race cancellation after a mass fall'),
    ('race_status_v1', '2025-12-26|3|R06', 'RACE_CANCELLED',
     'Race-level cancellation confirmed; source includes ord=0 rows'),
    ('race_status_v1', '2026-07-06|1|R01', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|1|R02', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|1|R03', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|1|R04', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|1|R05', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|1|R06', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|3|R01', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|3|R02', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales'),
    ('race_status_v1', '2026-07-06|3|R03', 'RESULT_NOT_FINALIZED',
     'Partial ord values observed without API179 sales')
ON CONFLICT (policy_version, race_id) DO UPDATE SET
    race_status = excluded.race_status,
    evidence_note = excluded.evidence_note;
