"""NSE index (benchmark) price provider.

    https://nsearchives.nseindia.com/content/indices/ind_close_all_{DDMMYYYY}.csv

Verified live 2026-09-19. Needs only a non-default User-Agent, like the
rest of the nsearchives host (see providers/nse/archives.py).

Three findings from that probe that shape this module:

1. **Coverage starts 2012-02-21**, not 2010. Every weekday before that
   404s. The price archives reach 2010-01-04 (ADR 0003), so the
   benchmark series is about two years SHORTER than the price series.
   A backtest starting in 2010 has no benchmark for its first two
   years; that is a real constraint to surface, not to paper over.

2. **Non-trading dates return an honest 404**, not BSE's silent-200
   SPA shell and not a mislabeled file. Weekends, holidays and
   nonsense far-future dates all 404 cleanly, so the standard
   DataNotPublished path is sufficient here.

3. **The benchmark has been renamed twice** inside the covered range.
   See ingest.normalise.INDEX_CODE_BY_NAME -- the canonical code, not
   the printed name, is what makes a continuous series.

This is NOT a PriceProvider: CanonicalBar is an equity bar (series,
ISIN, delivery quantity) and an index has none of those. Forcing an
index into that shape would mean a pile of nulls and a lie about what
the row is.
"""

from __future__ import annotations

from datetime import date

from stk.providers.base import RawArtifact
from stk.providers.nse.archives import fetch_csv_file

_BASE = "https://nsearchives.nseindia.com/content/indices"
SOURCE = "nse_indices"

#: Earliest date confirmed to return a file (2012-02-21). Every
#: weekday probed before this 404s.
EARLIEST_DATE = date(2012, 2, 21)


def index_archive_url(business_date: date) -> str:
    return f"{_BASE}/ind_close_all_{business_date.strftime('%d%m%Y')}.csv"


class NseIndicesProvider:
    """Fetches NSE's daily all-index close file."""

    name = SOURCE
    earliest_date = EARLIEST_DATE

    def fetch_indices(self, business_date: date, *, timeout_s: float = 30.0) -> RawArtifact:
        """Fetch one date's index file, validated and ready to persist."""
        url = index_archive_url(business_date)
        return fetch_csv_file(
            url,
            source=SOURCE,
            business_date=business_date,
            expected_header_token="Index Name",
            timeout_s=timeout_s,
        )
