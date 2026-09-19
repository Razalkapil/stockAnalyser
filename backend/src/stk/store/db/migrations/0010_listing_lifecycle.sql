-- Suspension / delisting detection: how many consecutive successful master snapshots a listing
-- has been ABSENT from (reset to 0 whenever it appears again), and the date the count last
-- advanced -- so re-running the master ingest the same day cannot count one absence twice.
ALTER TABLE listings ADD COLUMN missed_snapshots INTEGER NOT NULL DEFAULT 0;
ALTER TABLE listings ADD COLUMN missed_counted_on TEXT;
