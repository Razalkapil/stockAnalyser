"""Named SQL for the DuckDB query layer.

Each .sql file holds one or more queries separated by `-- name: <key>`
headers, loaded by stk.store.duck.named_query. SQL lives in files, not
in Python string literals, so it stays readable, diffable and runnable
by hand against `duckdb data/duck.db` while debugging.
"""
