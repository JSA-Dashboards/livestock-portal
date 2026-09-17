"""
nass_cache_client.py -- read-only USDA NASS QuickStats cache client.

This dashboard does not call the NASS API directly. A separate scheduled job
(the usda-nass-etl repo) holds NASS_API_KEY, pulls on a daily schedule, and
writes results into a shared cache. This file only reads that cache -- it
never holds the NASS key and never calls NASS live.

That split exists because NASS registers API keys per individual, not for
public/shared use -- every visitor to a live client-facing dashboard hitting
NASS under one key is exactly what that restriction is meant to prevent.

Vendored identically across crop-conditions-dashboard, beef-weight-dashboard,
livestock-inventory-dashboard, and domestic-production-dashboard (see the
usda-nass-etl repo). Keep this file byte-for-byte the same across all four --
app-specific shaping belongs in each app's own fetch wrapper functions, not here.

Backends (priority order):
  Snowflake  -- USE_SNOWFLAKE=1 + SNOWFLAKE_ACCOUNT/USER (+ optional ROLE,
                WAREHOUSE, DATABASE, SCHEMA). Auth is key-pair: a key file at
                SNOWFLAKE_PRIVATE_KEY_FILE, or PEM text in
                SNOWFLAKE_PRIVATE_KEY, plus SNOWFLAKE_PRIVATE_KEY_PASSPHRASE if
                the key is encrypted. SNOWFLAKE_PASSWORD is a fallback only.
                Target: JSA.NASS_CACHE.
  PostgreSQL -- DATABASE_URL (Supabase, legacy).
"""
import hashlib
import json
import os

try:
    import streamlit as st
except ImportError:
    st = None

_IGNORED_KEYS = {"key", "format"}


def _secret(key: str, default: str = "") -> str:
    """Read from st.secrets first, fall back to os.environ."""
    if st is not None:
        try:
            v = st.secrets.get(key, "")
            if v:
                return str(v).strip()
        except Exception:
            pass
    return os.environ.get(key, default).strip()


def _use_sf() -> bool:
    return _secret("USE_SNOWFLAKE").lower() in ("1", "true", "yes", "on")


def _database_url() -> str:
    return _secret("DATABASE_URL")


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


DEFAULT_KEY_FILE = "~/.snowflake/keys/snowflake_rsa_key.p8"


def _key_pair_kwargs() -> dict:
    """
    Connector kwargs for key-pair auth, or {} if no key material is configured.

    Mirrors snowflake_db._key_pair_kwargs(), which the index dashboards already
    use against this same account. That account has no SAML IdP and no password
    set, so key-pair is the only way in. Without this the client sent
    password="" and Snowflake answered "251006: Password is empty", which reads
    like a missing secret rather than an auth method the account does not have.

    Two key sources, because the two runtimes differ. A key FILE covers local
    runs and scheduled jobs. PEM TEXT in SNOWFLAKE_PRIVATE_KEY covers Streamlit
    Community Cloud, whose secrets are TOML with no filesystem to hold a .p8 --
    the connector's inline `private_key` wants DER rather than PEM, so it is
    re-serialised here instead of handed over raw. The file wins when both are
    present: it is the better-tested path.

    The connector does NOT read SNOWFLAKE_PRIVATE_KEY_PASSPHRASE itself (that
    name is honoured only by the `snow` CLI), so it is passed explicitly as
    private_key_file_pwd -- omitting it raises "Password was not given but
    private key is encrypted".
    """
    passphrase = _secret("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")

    key_file = os.path.expanduser(
        _secret("SNOWFLAKE_PRIVATE_KEY_FILE") or DEFAULT_KEY_FILE
    )
    if os.path.exists(key_file):
        kw = {"private_key_file": key_file, "authenticator": "SNOWFLAKE_JWT"}
        if passphrase:
            kw["private_key_file_pwd"] = passphrase
        return kw

    pem = _secret("SNOWFLAKE_PRIVATE_KEY")
    if pem:
        from cryptography.hazmat.primitives import serialization

        loaded = serialization.load_pem_private_key(
            pem.encode(), password=passphrase.encode() if passphrase else None
        )
        return {
            "private_key": loaded.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            "authenticator": "SNOWFLAKE_JWT",
        }

    return {}


def _sf_connect():
    import snowflake.connector

    kwargs = dict(
        account=_secret("SNOWFLAKE_ACCOUNT"),
        user=_secret("SNOWFLAKE_USER"),
        role=_secret("SNOWFLAKE_ROLE") or None,
        warehouse=_secret("SNOWFLAKE_WAREHOUSE") or None,
        database=_secret("SNOWFLAKE_DATABASE") or "JSA",
        schema=_secret("SNOWFLAKE_SCHEMA") or "NASS_CACHE",
        login_timeout=30,
    )
    auth = _key_pair_kwargs()
    if auth:
        kwargs.update(auth)
    elif _secret("SNOWFLAKE_PASSWORD"):
        # Retained so a password-configured deployment keeps working. Key-pair
        # wins whenever key material is present.
        kwargs["password"] = _secret("SNOWFLAKE_PASSWORD")
    else:
        raise RuntimeError(
            "No Snowflake credentials for the NASS cache. Provide a key-pair via "
            "SNOWFLAKE_PRIVATE_KEY_FILE (default " + DEFAULT_KEY_FILE + ") or "
            "SNOWFLAKE_PRIVATE_KEY (PEM text), plus "
            "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE if the key is encrypted. "
            "SNOWFLAKE_PASSWORD is accepted as a fallback."
        )
    return snowflake.connector.connect(**kwargs)


def fetch_cached(params: dict, endpoint: str = "api_GET") -> dict:
    """
    Read-only cache lookup. Returns the raw NASS response shape, e.g.
    {"data": [...]}, or {"data": []} if nothing has been cached yet for this
    exact query -- add the param combo to the matching jobs/*.py list in
    usda-nass-etl and re-run pull_all.py.

    Raises only on a genuine backend connection failure so a misconfigured
    secret is loud, not a silent blank dashboard.
    """
    key = _cache_key(endpoint, params)

    if _use_sf():
        conn = _sf_connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT data FROM nass_cache WHERE cache_key = %s", (key,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row is None:
            return {"data": []}
        data = row[0]
        # Snowflake VARIANT columns are returned as Python dicts by the connector
        return data if isinstance(data, (dict, list)) else json.loads(data)

    url = _database_url()
    if not url:
        raise RuntimeError(
            "No NASS cache backend configured. Set USE_SNOWFLAKE=1 (+ SNOWFLAKE_*) "
            "or DATABASE_URL in `.streamlit/secrets.toml` / environment -- "
            "this dashboard reads NASS data from a shared cache (see usda-nass-etl), "
            "not the live API."
        )
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
    try:
        if _use_sf():
            conn = _sf_connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT MAX(fetched_at) FROM nass_cache")
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else None
            finally:
                conn.close()

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
    except Exception:
        return None
