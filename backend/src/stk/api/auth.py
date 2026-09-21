"""Single-user bearer-token auth.

Only a SHA-256 of each token is stored, so a copy of app.db is not a set of working
credentials. Tokens are 256 bits of randomness, which is why a plain (unsalted, fast) hash is
appropriate here -- there is nothing to brute-force, unlike a human-chosen password.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

TOKEN_PREFIX = "stk_"
#: last_used_at is refreshed at most this often, so a chatty client is not a write per request.
TOUCH_INTERVAL = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(conn: sqlite3.Connection, name: str) -> str:
    """Create a named token and return it. This is the ONLY time it is available in clear."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO api_tokens (name, token_sha256, created_at) VALUES (?,?,?)",
        (name, hash_token(token), datetime.now(UTC).isoformat()),
    )
    return token


def verify_token(conn: sqlite3.Connection, token: str) -> bool:
    row = conn.execute(
        "SELECT token_id, last_used_at FROM api_tokens WHERE token_sha256=? AND revoked_at IS NULL",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return False
    now = datetime.now(UTC)
    last = datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None
    if last is None or now - last > TOUCH_INTERVAL:
        conn.execute("UPDATE api_tokens SET last_used_at=? WHERE token_id=?",
                     (now.isoformat(), row["token_id"]))
    return True


def verify_configured_token(configured: str | None, presented: str) -> bool:
    """Check the token from ``STK_AUTH__TOKEN`` (settings/.env), which has no database row.

    This is the single-user path the .env file has always advertised: one token, set once,
    no `stk api token create` round trip and nothing to lose when app.db is restored from a
    backup. Compared as SHA-256 digests through ``compare_digest`` so neither the value nor
    its length leaks through timing -- the DB path gets that for free from the hash lookup.
    """
    if not configured:
        return False
    return secrets.compare_digest(hash_token(presented), hash_token(configured))


def revoke_token(conn: sqlite3.Connection, name: str) -> bool:
    cur = conn.execute(
        "UPDATE api_tokens SET revoked_at=? WHERE name=? AND revoked_at IS NULL",
        (datetime.now(UTC).isoformat(), name),
    )
    return cur.rowcount > 0


def list_tokens(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT name, created_at, last_used_at, revoked_at FROM api_tokens ORDER BY token_id"
    ).fetchall()
