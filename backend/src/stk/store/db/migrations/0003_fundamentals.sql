-- Phase 3: parsed XBRL line items.
--
-- Each parsed filing (one fundamentals_snapshots 'meta' row) yields
-- line items under three period kinds -- 'quarter' (the discrete quarter),
-- 'ytd' (year-to-date; the full year in an annual filing) and 'instant'
-- (balance sheet at period end). See stk.ingest.xbrl for why the kind comes
-- from the XBRL context ID and not its printed dates.
--
-- Derived metrics (ROCE, D/E, CAGR, TTM EPS) are NOT stored: they are
-- computed from these rows by stk.domain.fundamentals, so a change to a
-- formula can never leave a stale cached value behind.

CREATE TABLE fundamentals_line_items (
  item_id         INTEGER PRIMARY KEY,
  snapshot_id     INTEGER NOT NULL REFERENCES fundamentals_snapshots(snapshot_id),
  security_id     INTEGER NOT NULL REFERENCES securities(security_id),
  period_kind     TEXT NOT NULL CHECK (period_kind IN ('quarter','ytd','instant')),
  item            TEXT NOT NULL,
  value           REAL NOT NULL,
  unit            TEXT,
  source_tag      TEXT NOT NULL,
  parser_version  INTEGER NOT NULL,
  UNIQUE (snapshot_id, period_kind, item)
);
CREATE INDEX ix_line_items_security ON fundamentals_line_items(security_id, item);

CREATE TABLE fundamentals_parse_status (
  snapshot_id     INTEGER PRIMARY KEY REFERENCES fundamentals_snapshots(snapshot_id),
  status          TEXT NOT NULL CHECK (status IN ('parsed','partial','unsupported_format','malformed')),
  detail_json     TEXT NOT NULL DEFAULT '{}',
  raw_sha256      TEXT,
  parser_version  INTEGER NOT NULL,
  parsed_at       TEXT NOT NULL
);
