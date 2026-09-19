"""The virtual playground: paper portfolios, orders, a delayed-feed fill engine, and P&L.

Everything here is a LEDGER. Money is Decimal in memory and TEXT in SQLite; cash is always the
last ``cash_ledger.balance_after`` (never a separately maintained number); and every fill
records where its price came from (``delayed_intraday`` vs ``eod_fallback``) so the UI can say so.
"""
