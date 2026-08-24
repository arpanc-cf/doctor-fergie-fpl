"""SQLite-backed cache with a refresh-if-stale pattern.

Every fetched payload is stored as JSON under a string key alongside its
fetch timestamp. If a live re-fetch fails (e.g. the FPL API is briefly down
near a deadline), get_or_fetch falls back to the last-known-good cached
value instead of raising, so the dashboard keeps working.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "fpl_cache.db"


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        "key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)"
    )
    return conn


def read(key):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT payload, fetched_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None, None
    payload, fetched_at = row
    return json.loads(payload), datetime.fromisoformat(fetched_at)


def delete(key):
    conn = _connect()
    try:
        conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


def delete_prefix(key_prefix):
    """Delete every cache entry whose key starts with key_prefix (e.g. all
    'entry:{team_id}...' rows for one team) via SQL LIKE, escaping any
    literal '%'/'_' in the prefix so it can't match more than intended.
    """
    escaped = key_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM cache WHERE key LIKE ? ESCAPE '\\'", (escaped + "%",)
        )
        conn.commit()
    finally:
        conn.close()


def write(key, payload):
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO cache (key, payload, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET payload = excluded.payload, "
            "fetched_at = excluded.fetched_at",
            (key, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_or_fetch(key, fetch_fn, max_age_seconds=3600, force_refresh=False):
    """Return (data, fetched_at, is_stale_fallback, error_message).

    - Serves the cache when it's fresh enough and no refresh was forced.
    - Otherwise calls fetch_fn() and refreshes the cache.
    - If fetch_fn() raises and a cached value exists, falls back to it
      (is_stale_fallback=True, error_message set) rather than failing.
    - If fetch_fn() raises and there's no cache at all, re-raises.
    """
    cached_data, cached_at = read(key)
    now = datetime.now(timezone.utc)
    is_stale = cached_at is None or (now - cached_at).total_seconds() > max_age_seconds

    if not force_refresh and cached_data is not None and not is_stale:
        return cached_data, cached_at, False, None

    try:
        fresh = fetch_fn()
    except Exception as e:
        if cached_data is not None:
            return cached_data, cached_at, True, str(e)
        raise
    write(key, fresh)
    return fresh, datetime.now(timezone.utc), False, None
