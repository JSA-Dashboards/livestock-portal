"""
nass_cache_client.py -- read-only USDA NASS QuickStats cache client.

This dashboard does not call the NASS API directly. A separate scheduled job
(the usda-nass-etl repo) holds NASS_API_KEY, pulls on a daily schedule, and
writes results into a shared Postgres cache. This file only reads that cache
via DATABASE_URL -- it never holds the NASS key and never calls NASS live.
That split exists because NASS registers API keys per individual, not for
public/shared use -- every visitor to a live client-facing dashboard hitting
NASS under one key is exactly what that restriction is meant to prevent.

Vendored identically across crop-conditions-dashboard, beef-weight-dashboard,
livestock-inventory-dashboard, and domestic-production-dashboard (see the
usda-nass-etl repo). Keep this file byte-for-byte the same across all four --
app-specific shaping belongs in each app's own fetch wrapper functions, not
here.
"""
import hashlib
import json
import os

try:
    import streamlit as st
except ImportError:
    st = None

_IGNORED_KEYS = {"key", "format"}


def _database_url() -> str:
    url = ""
    if st is not None:
        try:
            url = st.secrets.get("DATABASE_URL", "")
        except Exception:
            url = ""
    return (url or os.environ.get("DATABASE_URL", "")).strip()


def _cache_key(endpoint: str, params: dict) -> str:
    # Every value is cast to str before hashing so this matches
    # nass_etl.cache_key.make_cache_key exactly regardless of whether a
    # dashboard's own params dict uses int or str (e.g. year=2024 vs
    # year="2024") -- see that module's docstring for why.
    clean = {k: str(v) for k, v in params.items() if k not in _IGNORED_KEYS}
    canon = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{endpoint}|{canon}".encode()).hexdigest()


def _pg_dsn(url: str) -> str:
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def fetch_cached(params: dict, endpoint: str = "api_GET") -> dict:
    """
    Read-only cache lookup. Returns the raw NASS response shape, e.g.
    {"data": [...]}, or {"data": []} if nothing has been cached yet for this
    exact query -- add the param combo to the matching jobs/*.py list in
    usda-nass-etl and re-run pull_all.py.

    Raises only on a genuine DB connection failure (missing/bad
    DATABASE_URL) so a misconfigured secret is loud, not a silent blank
    dashboard.
    """
    url = _database_url()
    if not url:
        raise RuntimeError(
            "No DATABASE_URL found. Add it to `.streamlit/secrets.toml` "
            "or as an environment variable -- this dashboard reads NASS "
            "data from a shared cache (see usda-nass-etl), not the live API."
        )
    key = _cache_key(endpoint, params)
    import psycopg2
    conn = psycopg2.connect(_pg_dsn(url))
    try:
        cur = conn.cursor()
        cur.execute("SELECT data FROM nass_cache WHERE cache_key = %s", (key,))
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return {"data": []}
    data = row[0]
    return data if isinstance(data, dict) else json.loads(data)


def cache_freshness() -> str:
    """Most recent fetched_at timestamp across the whole cache, or None.
    Handy for an 'as of ...' footer caption."""
    url = _database_url()
    if not url:
        return None
    import psycopg2
    conn = psycopg2.connect(_pg_dsn(url))
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(fetched_at) FROM nass_cache")
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    finally:
        conn.close()
