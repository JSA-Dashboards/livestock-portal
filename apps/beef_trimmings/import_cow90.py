"""
Frozen 90s import prices from USDA MARS NW_LS421, and the Snowflake mirror.

WHY THIS MODULE EXISTS. `marsapi.ams.usda.gov` rejects Streamlit Community
Cloud's IPs -- confirmed 2026-10-04, the identical request returns 200 from a
droplet and 401 from Cloud -- so the import side of Beef Trimmings is fetched
by a droplet cron and the page reads `JSA.BEEF_TRIMMINGS.IMPORT_COW90` instead.

Until 2026-10-07 the fetching half lived ONLY on the droplet, in a script that
was in no repository. The page carried the reader, the writer existed nowhere
anyone could see it, and a rebuilt host would have lost it. This is that writer,
versioned, with the page's own live-fetch path now delegating here so there is
one implementation rather than two that can drift -- the rule
`scripts/bank_am_cutout.py` follows for the morning cutout, for the same reason.

MARS FLAPS, AND A SINGLE REQUEST IS NOT A VERDICT. Measured 2026-10-07: bare
GETs to marsapi and mpr.datamart both returned 503 repeatedly, while a session
retrying on 503 got 200 within 2-9 seconds. Anything here that talks to MARS
goes through `_session()` for that reason; a plain `requests.get` would report
an outage that is not happening.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MARS_BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
LS421_ID = 2823
IMPORT_ITEM = "Cow Meat (90%)"
ORIGIN_SA = "South America"
ORIGIN_ANZ = "Australia &/ New Zealand"
HISTORY_START = "01/01/2019"

TABLE = "JSA.BEEF_TRIMMINGS.IMPORT_COW90"

COLUMNS = ["report_date", "origin", "avg_price", "low", "high", "n"]

DDL = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        REPORT_DATE  DATE          NOT NULL,
        ORIGIN       STRING        NOT NULL,
        AVG_PRICE    FLOAT,
        LOW_PRICE    FLOAT,
        HIGH_PRICE   FLOAT,
        N_ROWS       NUMBER(9,0),
        FETCHED_AT   TIMESTAMP_LTZ
    )""",
)

#: How far the series may SHRINK before a write is refused. See bank().
SHRINK_TOLERANCE = 0.9


def _session(backoff: int = 3) -> requests.Session:
    """A session that retries 503, because MARS returns them intermittently."""
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=backoff,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])))
    return s


def fetch_live(mars_key: str, timeout: int = 90) -> pd.DataFrame:
    """The whole weekly series from NW_LS421, by origin.

    Returns the empty frame with the right columns when the report carries no
    Details section, which is what MARS serves for a sectioned slug asked the
    wrong way -- never an exception, so a caller cannot mistake "no section" for
    "no data" by catching the wrong thing.

    THE UPPER BOUND IS TODAY PLUS TWO DAYS. MARS filters on report_begin_date
    and a bound of exactly today drops a report published for the current week,
    which is how a Friday report goes missing from a Friday run.
    """
    hi = (datetime.now() + timedelta(days=2)).strftime("%m/%d/%Y")
    resp = _session().get(
        f"{MARS_BASE}/{LS421_ID}",
        params={"q": f"report_begin_date={HISTORY_START}:{hi}", "allSections": "true"},
        auth=(mars_key, ""), timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    details = next((s["results"] for s in payload
                    if s.get("reportSection") == "Report Details"), [])
    if not details:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.DataFrame(details)
    df = df[df["commodity"] == IMPORT_ITEM].copy()
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["low"] = pd.to_numeric(df["low_price"], errors="coerce")
    df["high"] = pd.to_numeric(df["high_price"], errors="coerce")
    df["mid"] = df[["low", "high"]].mean(axis=1)
    df = df.dropna(subset=["report_date", "mid"])

    origin_map = {ORIGIN_SA: "South America", ORIGIN_ANZ: "Australia/NZ"}
    df = df[df["country_of_origin"].isin(origin_map)].copy()
    df["origin"] = df["country_of_origin"].map(origin_map)

    weekly = (df.groupby(["report_date", "origin"], as_index=False)
                .agg(avg_price=("mid", "mean"), low=("low", "mean"),
                     high=("high", "mean"), n=("mid", "size")))
    return weekly.sort_values("report_date").reset_index(drop=True)


def ensure_table(conn) -> str:
    """Create the table only when it is genuinely absent.

    IT LOOKS BEFORE IT CREATES, AND THAT IS NOT THE SAME AS
    `CREATE TABLE IF NOT EXISTS`. That statement still requires CREATE TABLE on
    the schema even when it does nothing at all, and this table lives in
    `JSA.BEEF_TRIMMINGS`, where the ingest identity has DML and no DDL. The
    no-op therefore failed the whole run with "Insufficient privileges to
    operate on schema 'BEEF_TRIMMINGS'" while the table sat right there, fully
    populated -- a permission error that reads like a missing table and is
    neither.

    The other two crons in this repo create their own tables in
    `JSA.CME_FEEDER_CATTLE` and `JSA.BOXED_BEEF`, where they do hold DDL, so
    the plain IF NOT EXISTS is correct there. Copying it here was the mistake.
    """
    schema, table = TABLE.split(".")[1], TABLE.split(".")[2]
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM JSA.INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s", (schema, table))
            if int(cur.fetchone()[0] or 0):
                return ""
            for stmt in DDL:
                cur.execute(stmt)
        finally:
            cur.close()
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def bank(conn, df: pd.DataFrame, force: bool = False) -> tuple[int, str]:
    """
    Replace the whole series with `df`. Returns (rows written, error).

    A FULL REWRITE, NOT AN APPEND, and that is the existing contract rather
    than a choice: every row in the table shares one FETCHED_AT because the
    source republishes its whole history and USDA revises it in place. An
    append would accumulate duplicate weeks and the page, which does no
    de-duplication, would plot each week several times.

    Rewriting also keeps FETCHED_AT as a HEARTBEAT. It is the only evidence
    that the job ran at all on a day it found nothing new, and on 2026-10-07 it
    is exactly what distinguished "the cron is dead" from "USDA published late"
    -- the table's newest report was 09-25 while FETCHED_AT said the job had
    run on 10-05. A skip-when-unchanged optimisation would have destroyed that
    signal to save one write of 260 rows.

    IT REFUSES A SERIES THAT HAS SHRUNK, which is the guard a rewrite needs and
    the reason this is not a bare DELETE-then-INSERT. MARS flaps: a request can
    return 200 with a partial Details section, and a rewrite would then replace
    seven years of history with whatever came back, destroying data no later
    run can rebuild because the page's own copy is the only one. Anything below
    SHRINK_TOLERANCE of the current row count stops and says so; `force=True`
    is the deliberate override for a source that has genuinely been cut back.
    """
    if df is None or df.empty:
        return 0, "refusing to write an empty series over the existing one"
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        before = int(cur.fetchone()[0] or 0)
        if not force and before and len(df) < before * SHRINK_TOLERANCE:
            return 0, (f"refusing to shrink the series: {len(df)} rows fetched "
                       f"against {before} already held. MARS returns partial "
                       f"payloads when it flaps; re-run, or pass --force if the "
                       f"source really has been cut back.")
        now = datetime.now()
        rows = [(r.report_date.date() if hasattr(r.report_date, "date") else r.report_date,
                 r.origin,
                 None if pd.isna(r.avg_price) else float(r.avg_price),
                 None if pd.isna(r.low) else float(r.low),
                 None if pd.isna(r.high) else float(r.high),
                 None if pd.isna(r.n) else int(r.n),
                 now)
                for r in df.itertuples(index=False)]
        # Delete and insert inside one transaction: a failure between them
        # would otherwise leave the page with no import series at all.
        cur.execute("BEGIN")
        cur.execute(f"DELETE FROM {TABLE}")
        cur.executemany(
            f"INSERT INTO {TABLE} (REPORT_DATE, ORIGIN, AVG_PRICE, LOW_PRICE, "
            "HIGH_PRICE, N_ROWS, FETCHED_AT) VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)
        cur.execute("COMMIT")
        return len(rows), ""
    except Exception as e:
        try:
            cur.execute("ROLLBACK")
        except Exception:
            pass
        return 0, f"Could not write to Snowflake: {e}"
    finally:
        cur.close()
