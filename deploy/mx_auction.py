#!/usr/bin/env python3
"""
Record Mexican cattle auction prices from mexicoganadero.com. For the droplet.

WHY THIS EXISTS. The portal can price a Mexican calf the moment it reaches the
US side -- AMS 3486 gives $/cwt FOB at Douglas and Santa Teresa, and
apps/mexican_feeder_imports/ has differenced that against the CME index since
2023. What it has never had is the other half: what the same calf is worth
*inside* Mexico, before the export premium.

Mexico publishes no feeder index. Probed 2026-10-07 and recorded here so nobody
repeats it:

  * **SNIIM** (economia-sniim.gob.mx) is a SLAUGHTER-market system. `Var=Bov`
    is substantial and current -- 393 daily records across 11 states for Aug
    2026, Sonora included, MXN/kg live -- but it prices cattle delivered to a
    rastro, not feeders. `Var=Bec` is effectively dead: 15 rows in Sep 2024,
    an empty page for Aug 2026, and where it does report the calves are 45-50
    kg bob calves rather than 180-360 kg feeders.
  * **SIAP** (nube.agricultura.gob.mx/datosAbiertos/Pecuario.php) does carry
    `Precio`, by municipality, Chihuahua and Sonora included -- but ANNUAL, on
    a CARCASS basis (`Peso` is kg of meat per head slaughtered), and 2025 was
    published in August 2026. A benchmark, not a market.

This site is the only structured source found that quotes FEEDER CALVES BY
WEIGHT BAND. Tamaulipas is the one that matters: nine `BECERRO` bands from
under 150 kg to 351-400 kg, with the same inverse slide a US feeder market
shows. Yucatan and Durango come free in the same fetch and are kept for
context, but neither bands by weight.

WHAT THIS CANNOT TELL YOU, and the page must say so before it shows a spread:
**Tamaulipas is not where the cattle crossing at Douglas and Santa Teresa come
from.** Those are Sonora and Chihuahua, and neither has an auction on this
site -- the only numbers for them anywhere are association spokesmen quoted in
Mexican press. Tamaulipas is a northern border state with real feeder bands,
which makes it the closest honest comparator, not the right one.

THE SITE KEEPS TWO SALES AND NOTHING ELSE. `?subasta=anterior` returns the
previous sale and then links only back to the current one; there is no archive
and no date parameter. So history CANNOT be backfilled -- it accrues from the
first run, exactly like JSA.BOXED_BEEF.CUTOUT_AM and for the same reason. Both
pages are fetched every run so a sale is not missed when a run is skipped.

Exit codes: 0 banked or already present, 1 could not fetch or could not write.
Cron mails stderr on a non-zero exit, which is the whole alerting story.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import socket
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parent.parent

CURRENT_URL = "https://mexicoganadero.com/precios/"
PREVIOUS_URL = "https://mexicoganadero.com/precios?subasta=anterior"
SOURCES = (CURRENT_URL, PREVIOUS_URL)

TABLE = "JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES"
FX_TABLE = "JSA.CME_FEEDER_CATTLE.FX_USDMXN"

# ECB reference rates, via frankfurter.app. No key, history to 1999, and it
# answers for a date rather than only for today -- which is the whole
# requirement, because a sale has to be valued at the peso of its own day.
FX_URL = "https://api.frankfurter.app/{date}?from=USD&to=MXN"
FX_SOURCE = "ECB via frankfurter.app"

LB_PER_KG = 2.2046226218

# The auction this exists for. The others are parsed and stored because they
# arrive in the same response, not because they answer the question.
PRIMARY_AUCTION = "TAMAULIPAS"

DDL = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        AUCTION         STRING        NOT NULL,
        SALE_DATE       DATE          NOT NULL,
        CLASIFICACION   STRING        NOT NULL,
        SEX             STRING,
        WEIGHT_LOW_KG   NUMBER(6,0),
        WEIGHT_HIGH_KG  NUMBER(6,0),
        PRICE_MIN       NUMBER(12,2),
        PRICE_MAX       NUMBER(12,2),
        PRICE_AVG       NUMBER(12,2),
        UNIT            STRING        NOT NULL,
        RECORDED_AT     TIMESTAMP_NTZ NOT NULL,
        RECORDED_BY     STRING
    )""",
)

#: FX IS ITS OWN SERIES, NOT A COLUMN ON THE PRICE ROW, and that is deliberate.
#: The peso moved 3% between the 24 Sep sale and 7 Oct (17.5841 to 18.0943), so
#: a rate frozen onto a price row would either go stale or force a new price
#: row every time the currency ticked -- banking a cattle correction and an FX
#: move as the same kind of event. Kept apart, prices are banked when prices
#: change, rates when rates change, and a sale is converted by joining on its
#: own date.
FX_DDL = (
    f"""CREATE TABLE IF NOT EXISTS {FX_TABLE} (
        RATE_DATE    DATE          NOT NULL,
        MXN_PER_USD  NUMBER(12,6)  NOT NULL,
        SOURCE       STRING,
        RECORDED_AT  TIMESTAMP_NTZ NOT NULL
    )""",
)

# ── Spanish dates ───────────────────────────────────────────────────────────
#
# "24/sep/2026". strptime cannot read this under any locale we can rely on --
# %b is locale-dependent and a droplet runs under C. The same trap
# letter/sterling.py records for Sterling's "Sept.", which no locale accepts
# either. A dict is the whole fix and it cannot drift.
_MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
          "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12}

_SALE = re.compile(
    r"SUBASTA\s+GANADERA\s+DE\s+([A-ZÁÉÍÓÚÑ\s]+?)\s*</b>.*?"
    r"Precios\s+del\s*<b>\s*(\d{1,2})/([a-zA-Zéí]{3})/(\d{4})\s*</b>",
    re.S | re.I)

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


#: SOME ROWS ARE PRICED PER HEAD, IN THE SAME COLUMN, WITH NOTHING SAYING SO.
#: Durango's 2026-10-01 sale lists VACA PARIDA at 32,500 beside VACA GORDA at
#: 49.25 -- a cow with a calf at side is sold by the animal, the fat cow by the
#: kilo, and the table marks neither. Averaged together the per-head figure
#: does not look like an outlier in a chart, it looks like the market moved.
#:
#: The split is by magnitude because nothing else distinguishes them, and it is
#: safe by a wide margin rather than finely tuned: Mexican cattle run roughly
#: 30-150 MXN/kg, so 1,000 is more than six times the top of the range and a
#: per-head animal is in the tens of thousands. Two orders of magnitude of
#: daylight sit between the two populations.
PER_HEAD_FLOOR = 1_000.0

PER_KG = "MXN/kg"
PER_HEAD = "MXN/head"


class Quote(NamedTuple):
    auction: str
    sale_date: date
    clasificacion: str
    sex: str | None
    low_kg: int | None
    high_kg: int | None
    minimum: float | None
    maximum: float | None
    average: float | None
    unit: str


def _text(fragment: str) -> str:
    return " ".join(_TAG.sub(" ", fragment).replace("&nbsp;", " ").split())


def _money(cell: str):
    """'$104.00' -> 104.0. Blank, '-' and junk all return None, never 0.0."""
    s = _text(cell).replace("$", "").replace(",", "").strip()
    if not s or s in {"-", "--"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_sale_date(day: str, mes: str, year: str):
    m = _MESES.get(mes[:3].lower())
    if not m:
        return None
    try:
        return date(int(year), m, int(day))
    except ValueError:
        return None


# BECERRO/BECERRA is calf; the rest are the grown classes. CARNERO/CARNERA are
# SHEEP, which Yucatan lists alongside cattle -- they are stored with the rest
# and must be excluded by any reader that is summing cattle.
_MALE = ("BECERRO", "NOVILLO", "TORETE", "TORO", "TERNERO", "SEMENTAL", "CARNERO")
_FEMALE = ("BECERRA", "NOVILLONA", "VACA", "VAQUILLA", "TERNERA", "CARNERA")


def sex_of(clasificacion: str):
    """Male/female from the class name, or None when it says neither.

    ORDER MATTERS AND THE FEMALE FORMS MUST BE TESTED FIRST. Every female name
    here contains its male counterpart as a prefix -- BECERRA starts BECERR,
    NOVILLONA starts NOVILLO, TERNERA starts TERNER -- so a male-first scan
    labels every heifer a steer and nothing raises.
    """
    c = clasificacion.upper()
    for w in _FEMALE:
        if c.startswith(w):
            return "F"
    for w in _MALE:
        if c.startswith(w):
            return "M"
    return None


# Three spellings of a weight band live on this page at the same time, all
# observed 2026-10-07:
#
#     BECERRA CN MENOR A 150KG     an upper bound, with "A"
#     BECERRO CN MENOR 150KG       an upper bound, without it
#     BECERRO CNH 251-330          a range with NO "KG" suffix at all
#
# A pattern that requires KG silently drops the third, which is a real band
# carrying real head, and a reader would never see the gap.
_BAND = re.compile(r"(\d{2,4})\s*-\s*(\d{2,4})\s*(?:KG)?\b", re.I)
_UNDER = re.compile(r"MENOR\s+(?:A\s+)?(\d{2,4})\s*(?:KG)?\b", re.I)


def weight_band(clasificacion: str):
    """(low_kg, high_kg) in kg, either end None when the class does not say."""
    c = clasificacion.upper()
    m = _BAND.search(c)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)
    m = _UNDER.search(c)
    if m:
        return (None, int(m.group(1)))
    return (None, None)


def unit_of(values) -> str:
    """PER_KG or PER_HEAD for one row's (min, max, avg).

    Decided on the LARGEST value present, not the average. A row whose maximum
    is per-head is a per-head row even when its minimum is blank, and a single
    class must never end up with two units across its three columns.
    """
    present = [v for v in values if v is not None]
    if present and max(present) >= PER_HEAD_FLOOR:
        return PER_HEAD
    return PER_KG


def parse(html: str):
    """Every quote on one page, across all auctions it carries.

    The page is one <table> per auction, each preceded by its own name and sale
    date. Rows are split on the heading rather than on table boundaries because
    the markup nests tables and the headings are the only reliable separator.
    """
    out = []
    marks = list(_SALE.finditer(html or ""))
    for i, m in enumerate(marks):
        auction = " ".join(m.group(1).split()).upper()
        sale_date = parse_sale_date(m.group(2), m.group(3), m.group(4))
        if sale_date is None:
            continue
        block = html[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(html)]
        for row in _ROW.findall(block):
            cells = _CELL.findall(row)
            if len(cells) < 4:
                continue
            name = _text(cells[0])
            # Spacer rows (<tr><td></td>...) and the header row both land here.
            if not name or name.lower().startswith("clasificacion"):
                continue
            lo, hi = weight_band(name)
            # Only the first three value columns are taken. Yucatan's table
            # carries three more -- prior sale, month, year-ago month -- which
            # are averages OF this series and would be stored twice.
            vals = (_money(cells[1]), _money(cells[2]), _money(cells[3]))
            out.append(Quote(auction, sale_date, name, sex_of(name), lo, hi,
                             *vals, unit_of(vals)))
    return out


#: The page serves NO charset, in the header or in a meta tag -- checked
#: 2026-10-07, `charset=` appears nowhere in the first 3 KB. So `requests`
#: falls back to chardet, which guesses windows-1250 and is wrong: VACA
#: PREÑADA arrives as the single byte 0xD1, which is Ñ in cp1252 and Ń in
#: 1250. Neither `r.text` nor a UTF-8 decode gets it right, and the failure is
#: cosmetic in exactly the way that survives review -- a mangled class NAME
#: still carries correct PRICES, so nothing looks broken.
ENCODING = "cp1252"


def usd_per_cwt(mxn_per_kg, mxn_per_usd):
    """MXN/kg -> USD/cwt, the unit AMS 3486 quotes the border in.

    Two conversions in one step, so the comparison is like for like: kilos to
    pounds, then pesos to dollars, then per-pound to per-hundredweight. None
    propagates rather than defaulting -- a missing rate must leave the cell
    empty, never silently price a calf at an implied 1.0 peso.
    """
    if mxn_per_kg is None or not mxn_per_usd:
        return None
    return float(mxn_per_kg) / LB_PER_KG / float(mxn_per_usd) * 100.0


def fx_for(when: date, timeout: int = 20):
    """(rate_date, mxn_per_usd) for `when`, or (None, None).

    RETURNS THE DATE ECB ACTUALLY PRICED, WHICH IS OFTEN NOT THE ONE ASKED FOR.
    Rates publish on TARGET business days only, and a request for a weekend or
    a holiday answers 200 with the previous business day's rate and that day's
    date in the body -- a Saturday asked for on 2026-10-03 comes back stamped
    2026-10-02. Storing it under the requested date would invent a rate for a
    day the ECB never priced, and the error would be invisible because the
    number itself is real.

    A future date is a 404, which is correct and not an error worth raising:
    an auction cannot be banked before it happens.
    """
    import requests
    try:
        r = requests.get(FX_URL.format(date=when.isoformat()), timeout=timeout)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        body = r.json()
        rate = (body.get("rates") or {}).get("MXN")
        stamped = body.get("date")
        if rate is None or not stamped:
            return None, None
        y, m, d = (int(x) for x in stamped.split("-"))
        return date(y, m, d), float(rate)
    except Exception:
        return None, None


def bank_fx(rates) -> tuple[int, str]:
    """Insert rates not already held. `rates` is {rate_date: mxn_per_usd}."""
    if not rates:
        return 0, ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        def go(cur):
            n = 0
            for rate_date, rate in sorted(rates.items()):
                cur.execute(
                    f"SELECT MXN_PER_USD FROM {FX_TABLE} WHERE RATE_DATE = %s "
                    "ORDER BY RECORDED_AT DESC LIMIT 1", (rate_date,))
                existing = cur.fetchone()
                if existing is not None and round(float(existing[0]), 6) == round(rate, 6):
                    continue
                cur.execute(
                    f"INSERT INTO {FX_TABLE} (RATE_DATE, MXN_PER_USD, SOURCE, "
                    "RECORDED_AT) VALUES (%s,%s,%s,%s)",
                    (rate_date, round(rate, 6), FX_SOURCE, now))
                n += 1
            return n
        return _run(go) or 0, ""
    except Exception as e:
        return 0, f"Could not write FX to Snowflake: {e}"


def fetch(url: str, timeout: int = 30) -> str:
    import requests  # imported here so the parser can be tested without it
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    # Forgiving rather than strict: one bad byte in a label must not cost the
    # whole sale's prices.
    return r.content.decode(ENCODING, errors="replace")


# ── Snowflake ───────────────────────────────────────────────────────────────

def _load_db():
    """snowflake_db.py by path under a private name, never by bare import.

    CLAUDE.md records that file existing five times in this repo and resolving
    by whichever page loaded first. A cron job binding whichever copy happens
    to be importable, unattended, is exactly the thing not to add.
    """
    path = REPO / "apps" / "mexican_feeder_imports" / "snowflake_db.py"
    if not path.exists():
        raise SystemExit(f"{path} is missing -- is this a full checkout?")
    spec = importlib.util.spec_from_file_location("_cron_mx_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cron_mx_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_CONN = None


def _conn():
    global _CONN
    if _CONN is None:
        _CONN = _load_db().get_conn()
    return _CONN


def _run(fn):
    """fn(cursor), reconnecting once -- a cached connection outlives its token."""
    global _CONN
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except Exception:
            try:
                if _CONN is not None:
                    _CONN.close()
            except Exception:
                pass
            _CONN = None
            if attempt == 2:
                raise
    return None


def _who() -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    return f"mx_auction@{host}"[:128]


def _round(v):
    """Compare at the precision NUMBER(9,2) holds, so a float that round-trips
    through the column does not read as a changed price."""
    return None if v is None else round(float(v), 2)


def ensure_table() -> str:
    try:
        _run(lambda cur: [cur.execute(s) for s in (*DDL, *FX_DDL)])
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def bank(quotes) -> tuple[int, str]:
    """
    Insert the quotes that are new or changed. Returns (inserted, error).

    APPEND-ONLY, NEWEST WINS per (AUCTION, SALE_DATE, CLASIFICACION) -- the
    shape JSA.LETTER.DRAFTS and CUTOUT_AM both use. Re-running costs two
    fetches and writes nothing, which is what lets the crontab be a blunt sweep
    rather than a guess at when a sale posts. A quote that genuinely CHANGES
    gets its own row, so a corrected sale and the figure first published both
    survive.
    """
    if not quotes:
        return 0, ""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    who = _who()
    try:
        def go(cur):
            n = 0
            for q in quotes:
                cur.execute(
                    f"SELECT PRICE_MIN, PRICE_MAX, PRICE_AVG FROM {TABLE} "
                    "WHERE AUCTION = %s AND SALE_DATE = %s AND CLASIFICACION = %s "
                    "ORDER BY RECORDED_AT DESC LIMIT 1",
                    (q.auction, q.sale_date, q.clasificacion))
                existing = cur.fetchone()
                new = (_round(q.minimum), _round(q.maximum), _round(q.average))
                if existing is not None and tuple(_round(v) for v in existing) == new:
                    continue
                cur.execute(
                    f"INSERT INTO {TABLE} (AUCTION, SALE_DATE, CLASIFICACION, SEX, "
                    "WEIGHT_LOW_KG, WEIGHT_HIGH_KG, PRICE_MIN, PRICE_MAX, "
                    "PRICE_AVG, UNIT, RECORDED_AT, RECORDED_BY) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (q.auction, q.sale_date, q.clasificacion, q.sex,
                     q.low_kg, q.high_kg, *new, q.unit, now, who))
                n += 1
            return n
        return _run(go) or 0, ""
    except Exception as e:
        return 0, f"Could not write to Snowflake: {e}"


def collect():
    """Every quote both pages carry, de-duplicated across them."""
    seen, out, errors = set(), [], []
    for url in SOURCES:
        try:
            for q in parse(fetch(url)):
                key = (q.auction, q.sale_date, q.clasificacion)
                if key in seen:
                    continue
                seen.add(key)
                out.append(q)
        except Exception as e:
            errors.append(f"{url}: {e}")
    return out, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and parse, print a summary, write nothing")
    ap.add_argument("--all-auctions", action="store_true",
                    help="bank Yucatan and Durango too (default: Tamaulipas only)")
    args = ap.parse_args(argv)

    quotes, errors = collect()
    for e in errors:
        print(f"fetch failed -- {e}", file=sys.stderr)
    if not quotes:
        print("no quotes parsed", file=sys.stderr)
        return 1

    if not args.all_auctions:
        quotes = [q for q in quotes if q.auction == PRIMARY_AUCTION]
        if not quotes:
            print(f"no {PRIMARY_AUCTION} quotes on either page", file=sys.stderr)
            return 1

    sales = sorted({(q.auction, q.sale_date) for q in quotes})
    for a, d in sales:
        n = sum(1 for q in quotes if q.auction == a and q.sale_date == d)
        banded = sum(1 for q in quotes
                     if q.auction == a and q.sale_date == d and q.high_kg)
        print(f"{a} {d}: {n} classes, {banded} weight-banded")

    # One lookup per distinct SALE DATE, not one per quote -- a sale of thirty
    # classes shares one peso. Keyed by the date ECB stamped, so a Saturday
    # sale and the Friday before it collapse to the one rate that exists.
    rates = {}
    for sale_date in sorted({q.sale_date for q in quotes}):
        rate_date, rate = fx_for(sale_date)
        if rate is not None:
            rates[rate_date] = rate
            rates[sale_date] = rates.get(sale_date, rate)
    fx_of = {d: r for d, r in rates.items()}

    if args.dry_run:
        for q in quotes[:10]:
            fx = fx_of.get(q.sale_date)
            usd = usd_per_cwt(q.average, fx) if q.unit == PER_KG else None
            band = f"{q.low_kg or ''}-{q.high_kg or ''}"
            print(f"   {q.clasificacion:<28} {band:>9}kg  "
                  f"{(q.average if q.average is not None else 0):>7.2f} {q.unit:<8}"
                  + (f"= ${usd:>6.2f}/cwt  @{fx:.4f} MXN/USD" if usd else ""))
        return 0

    err = ensure_table()
    if err:
        print(err, file=sys.stderr)
        return 1
    fn, err = bank_fx({d: r for d, r in rates.items()})
    if err:
        print(err, file=sys.stderr)
        return 1
    n, err = bank(quotes)
    if err:
        print(err, file=sys.stderr)
        return 1
    print(f"banked {n} new or changed quote(s), {fn} new FX rate(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
