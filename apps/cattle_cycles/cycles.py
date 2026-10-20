"""
Cattle price cycles -- dating bull and bear phases, and placing the current one.

WHAT THIS ANSWERS. "The cattle market is cyclical every ten years" is the
received wisdom. It is close to right about the HERD and wrong about the
PRICE, and this module exists to show which: on USDA's own monthly price
received, deflated, the median trough-to-trough cycle since 1913 is about
7.4 years, not ten. The ten-year figure belongs to the January 1 inventory
cycle, which turns roughly every eleven years peak to peak. They are two
different clocks -- the herd sets the slow rhythm and price turns more often
because demand, feed cost, drought and trade shocks move it in between.

NOTHING HERE WRITES A CYCLE LENGTH INTO PROSE. Every figure the page quotes
is computed at render time off the series the reader is looking at, the rule
`southeast.py` already follows for its high and low. A caption that states a
median goes stale against the chart above it the first time the data moves
or the reader changes a setting, and nothing makes it fail.

THE PRICE CYCLE AND THE HERD CYCLE ARE INVERSE, which is the thing that makes
"bullish cattle cycle" ambiguous and is why this module dates PRICE and says
so. Cows going to town is herd liquidation and it is price-BULLISH: fewer
calves next year. Expansion is eventually bearish and bullish first, because
a retained heifer is a heifer not slaughtered. So a phase labelled "bull"
here is a phase of RISING PRICE and is not a claim about the herd. US Cow
Herd's `expansion.py` answers the herd question and this module does not
duplicate it.

THE SERIES IS SELECTED BY EXACT short_desc AND THAT IS LOAD-BEARING.
NASS carries both

    CATTLE, GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT            1909->
    CATTLE, STEERS & HEIFERS, GE 500 LBS - PRICE RECEIVED, ...          1953->

and they share the tail `GE 500 LBS - PRICE RECEIVED, MEASURED IN $ / CWT`,
which is a substring of BOTH. (The second does NOT contain the first whole --
"CATTLE, GE 500 LBS" against "HEIFERS, GE 500 LBS" -- so the trap is the shared
tail. Worth being exact about: the looser claim invites a reader to test
`broad in narrow`, get False, and conclude the trap is not real.) Any match
that is not anchored at both ends -- `in`, `endswith`, a SQL LIKE -- silently
merges them: they overlap on 884 months and differ on all
884, so the result is a plausible-looking series that is two different price
definitions spliced at random. That is not hypothetical -- it is how the
first cut of this analysis was built, and it moved the headline median from
7.4 years to 10.1 while rendering perfectly. `tests/test_cattle_cycles.py`
pins the exact-match rule and asserts the two series really do differ.

DEFLATION IS NOT OPTIONAL AND THE BASE IS NOT FROZEN. In nominal dollars the
1970s look like a non-event and every cycle looks bigger than the last, so
every phase this module dates is dated on REAL price. The seed file stores
what each agency published -- nominal price and CPI side by side -- and the
deflation happens here, against the newest CPI month available. Storing real
values would bake a base year into a committed file and quietly restate the
whole record the first time anyone regenerated it with a different one.

A TURN NEAR THE END OF THE SERIES CANNOT BE DATED, and pretending otherwise
is the most likely way this page misleads. A peak is only knowable once price
has fallen away from it for long enough to rule out a pause, so a candidate
inside `END_BUFFER_MONTHS` of the last observation is returned SEPARATELY as
provisional and is never counted in a median, a rank or a phase. The page
shows it as an open question rather than a date.

MIN_PHASE IS A REAL CHOICE AND THE PAGE EXPOSES IT. The number of cycles --
and therefore the median length -- moves with the minimum phase length the
dating allows:

    min_phase   cycles   median trough-to-trough
            9       15       6.8 yr
           12       13       7.4 yr
           15       13       7.4 yr
           18       10      10.3 yr
           24        3      16.3 yr

Ten years is reachable, at a setting that merges runs no trader would merge:
at 18 months the 1990-02 peak and the 1991-12 trough disappear and a 22-month
break is absorbed into a rally. The default is 12 and the control is on the
page, because a single number presented as fact would be hiding the knob that
produced it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# Bump whenever load(), phases(), overlay() or context() changes the SHAPE of
# what it returns. st.cache_data keys on the decorated function's own code and
# arguments and never on the modules it calls, so without this a reshaped
# return value is served from a cache built before the reshape and the tile
# reading a new key renders an em dash with nothing raising.
SCHEMA = 1

DATA = Path(__file__).parent / "data" / "cattle_cycles.json"

# The droplet job writes here; the file above is the seed it starts from.
# deploy/refresh_cattle_cycles.py owns every write.
TABLE = "JSA.CME_FEEDER_CATTLE.CATTLE_CYCLE_PRICES"

# Exact short_desc -> the key used throughout. Never match these by substring.
SERIES = {
    "cattle_ge500": "All cattle, 500 lb and over",
    "calves": "Calves",
    "cows": "Cows",
}
DEFAULT_SERIES = "cattle_ge500"

# The SERIES value CPI-U is stored under, in both the seed and the table. It is
# not one of SERIES above: it is the deflator, not a price the page can chart.
CPI_KEY = "cpi_u"

MIN_PHASE_MONTHS = 12          # shortest run the dating will call a phase
MIN_PHASE_CHOICES = (9, 12, 15, 18)
END_BUFFER_MONTHS = 6          # a turn this close to the end is not datable
SMOOTH_MONTHS = 13             # centred, so it cannot lead or lag the turn
REFINE_WINDOW_MONTHS = 6       # snap a smoothed turn back onto the real extreme


def _from_file() -> dict | None:
    """The committed seed: nominal monthly prices plus CPI-U, never deflated."""
    try:
        d = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return None
    d["source"] = "file"
    return d


def _from_snowflake(conn) -> dict | None:
    """Newest row per (series, period). Returns None on any trouble -- never raises.

    NO IMPORT IS ADDED FOR THIS. The connection is handed in from app.py and
    this module only calls .cursor() on it, exactly as southeast.py does, so
    `cycles.py` still imports nothing but stdlib, numpy and pandas and the page
    cannot acquire an HTTP or database path THROUGH it. The guard in
    tests/test_cattle_cycles.py that pins that import set therefore needed no
    loosening, which is the point -- a read path that forced it open would have
    been the wrong shape.

    The committed seed is a seed, not a live series: it only moves when someone
    regenerates it. deploy/refresh_cattle_cycles.py keeps this table current
    from the droplet instead, which is where the 464MB NASS bulk dump can
    reasonably be streamed.
    """
    try:
        cur = conn.cursor().execute(
            f"SELECT SERIES, PERIOD, VALUE FROM {TABLE} "
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY SERIES, PERIOD "
            f"ORDER BY RECORDED_AT DESC) = 1")
        rows = cur.fetchall()
    except Exception:
        return None
    if not rows:
        return None
    by: dict[str, dict[str, float]] = {}
    for series, period, value in rows:
        if value is None:
            continue
        by.setdefault(str(series), {})[str(period)] = float(value)
    cpi = by.pop(CPI_KEY, {})
    if not cpi or not any(by.get(k) for k in SERIES):
        return None
    return {"series": {k: {"rows": by.get(k, {})} for k in SERIES},
            "cpi_u": {"rows": cpi}, "source": "snowflake"}


def _at_least_as_long(live: dict, seed: dict) -> bool:
    """Does the table carry every series the file does, and no series shorter?

    ALL OR NOTHING, AND THAT IS DELIBERATE. The obvious alternative is to take
    whichever source is longer per series -- which would mean deflating a
    Snowflake price series by a file CPI, or charting one series from the table
    beside another from the file. Every cycle date on this page is a product of
    the price series AND the deflator together, so a mixed read is a splice,
    and a splice here is the exact failure the module note opens with: it
    renders perfectly and moves the headline.

    A table SHORTER than the file is not a stale table, it is a broken one --
    the job writes the whole series every run and only skips periods whose
    value has not moved, so it can never legitimately shrink. Falling back
    whole costs the advancement and keeps the past intact, which is the right
    way round.
    """
    for key in SERIES:
        want = len((seed.get("series", {}).get(key) or {}).get("rows") or {})
        if len((live.get("series", {}).get(key) or {}).get("rows") or {}) < want:
            return False
    want_cpi = len((seed.get("cpi_u") or {}).get("rows") or {})
    return len((live.get("cpi_u") or {}).get("rows") or {}) >= want_cpi


def load(conn=None) -> dict | None:
    """Nominal monthly prices plus CPI-U. Snowflake first, the committed file after.

    THE FALLBACK IS NOT DECORATION. If the droplet job has never run, or the
    table is empty, or Snowflake is unreachable, the page still draws the
    record as of the last rebuild. It stops advancing; it does not vanish --
    and because it does not vanish, a silent failure of that job is INVISIBLE
    on the chart. Check MAX(RECORDED_AT) in the table, not the page.

    `source` rides on the returned dict so the page can name where the numbers
    came from rather than leaving a reader to assume they are live.
    """
    seed = _from_file()
    live = _from_snowflake(conn) if conn is not None else None
    if live and (seed is None or _at_least_as_long(live, seed)):
        return live
    return seed


def _series(rows: dict) -> pd.Series:
    s = pd.Series({pd.Timestamp(f"{k}-01"): float(v) for k, v in rows.items()})
    return s.sort_index()


def cpi_series(seed: dict) -> pd.Series:
    """CPI-U, with single-month holes bridged.

    BLS did not publish October 2025. A hole there is not a missing price --
    the cattle series has all 1,405 months -- but dividing by a NaN drops the
    month from the real series and puts a gap inside the centred smoothing
    window. `limit_area="inside"` interpolates between known points and will
    never extrapolate past the ends.
    """
    return _series(seed["cpi_u"]["rows"]).asfreq("MS").interpolate(limit_area="inside")


def nominal(seed: dict, key: str = DEFAULT_SERIES) -> pd.Series:
    return _series(seed["series"][key]["rows"])


def deflate(nom: pd.Series, cpi: pd.Series) -> tuple[pd.Series, pd.Timestamp]:
    """Express `nom` in the dollars of the newest CPI month. Returns the base too.

    The base moves as CPI is published, which is correct and is why the page
    prints which month's dollars it is quoting rather than saying "real".
    """
    base_at = cpi.last_valid_index()
    return (nom / cpi * cpi[base_at]).dropna(), base_at


def price(seed: dict, key: str = DEFAULT_SERIES, real: bool = True):
    """The series the page charts, plus the label describing its units."""
    nom = nominal(seed, key)
    if not real:
        return nom, "$/cwt, nominal"
    s, base_at = deflate(nom, cpi_series(seed))
    return s, f"$/cwt in {base_at:%b %Y} dollars"


def _months(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def turning_points(s: pd.Series, min_phase: int = MIN_PHASE_MONTHS,
                   end_buffer: int = END_BUFFER_MONTHS):
    """Bry-Boschan style dating. Returns (dated, provisional).

    Works on LOG price so a phase's amplitude is symmetric -- a halving and a
    doubling are the same distance, which they are not in levels.
    """
    if s is None or len(s) < SMOOTH_MONTHS * 2:
        return [], []
    ls = np.log(s)
    sm = ls.rolling(SMOOTH_MONTHS, center=True).mean().dropna()
    if len(sm) < 3:
        return [], []

    cand = []
    for i in range(1, len(sm) - 1):
        lo, mid, hi = sm.iloc[i - 1], sm.iloc[i], sm.iloc[i + 1]
        if mid >= lo and mid > hi:
            cand.append((sm.index[i], "P"))
        elif mid <= lo and mid < hi:
            cand.append((sm.index[i], "T"))

    # Snap each smoothed turn back onto the real extreme near it. The smoother
    # is what finds the turn; it is not what dates it.
    refined = []
    for dt, kind in cand:
        w = ls[(ls.index >= dt - pd.DateOffset(months=REFINE_WINDOW_MONTHS))
               & (ls.index <= dt + pd.DateOffset(months=REFINE_WINDOW_MONTHS))]
        if w.empty:
            continue
        refined.append((w.idxmax() if kind == "P" else w.idxmin(), kind))

    # Peaks and troughs must alternate; of two in a row keep the more extreme.
    alt: list[tuple[pd.Timestamp, str]] = []
    for dt, kind in refined:
        if alt and alt[-1][1] == kind:
            prev = alt[-1][0]
            higher = ls[dt] > ls[prev]
            alt[-1] = (dt if higher == (kind == "P") else prev, kind)
        else:
            alt.append((dt, kind))

    # Drop phases shorter than min_phase, re-alternating after each removal.
    changed = True
    while changed and len(alt) > 1:
        changed = False
        for i in range(len(alt) - 1):
            if _months(alt[i][0], alt[i + 1][0]) < min_phase:
                alt.pop(i if i > 0 else i + 1)
                changed = True
                break
        if changed:
            continue
        for i in range(len(alt) - 1):
            if alt[i][1] == alt[i + 1][1]:
                alt.pop(i + 1)
                changed = True
                break

    cutoff = ls.index[-1] - pd.DateOffset(months=end_buffer)
    return ([(d, k) for d, k in alt if d <= cutoff],
            [(d, k) for d, k in alt if d > cutoff])


def phases(s: pd.Series, tp: list) -> list[dict]:
    """Completed phases between consecutive dated turns. A bull starts at a trough."""
    out = []
    for (a, ka), (b, _kb) in zip(tp, tp[1:]):
        out.append({
            "phase": "bull" if ka == "T" else "bear",
            "start": a, "end": b,
            "months": _months(a, b),
            "change": s[b] / s[a] - 1.0,
            "from": float(s[a]), "to": float(s[b]),
        })
    return out


def cycle_lengths(tp: list, kind: str = "T") -> list[int]:
    """Months between consecutive turns of one kind -- a full cycle."""
    pts = [d for d, k in tp if k == kind]
    return [_months(a, b) for a, b in zip(pts, pts[1:])]


def overlay(s: pd.Series, tp: list, running: dict | None = None) -> list[dict]:
    """Every completed bull indexed to 100 at its own trough, plus the running one.

    Indexing is the only way to compare runs 70 years apart: the 1930s traded
    at a fifth of today's real level, so on a shared price axis every modern
    run would sit above every old one and the SHAPE -- which is the question --
    would be invisible.
    """
    runs = []
    for p in phases(s, tp):
        if p["phase"] != "bull":
            continue
        seg = s[(s.index >= p["start"]) & (s.index <= p["end"])]
        runs.append({
            "label": f"{p['start']:%b %Y}", "start": p["start"], "end": p["end"],
            "months": p["months"], "change": p["change"], "running": False,
            "x": [_months(p["start"], d) for d in seg.index],
            "y": list((seg / seg.iloc[0] * 100.0).values),
        })
    if running:
        seg = s[s.index >= running["start"]]
        if len(seg) > 1:
            runs.append({
                "label": f"{running['start']:%b %Y} (running)",
                "start": running["start"], "end": seg.index[-1],
                "months": _months(running["start"], seg.index[-1]),
                "change": float(seg.iloc[-1] / seg.iloc[0] - 1.0), "running": True,
                "x": [_months(running["start"], d) for d in seg.index],
                "y": list((seg / seg.iloc[0] * 100.0).values),
            })
    return runs


def context(s: pd.Series, tp: list, prov: list) -> dict | None:
    """Where the running phase stands against every completed one like it.

    `still_running_at_age` is the headline and it is a COUNT, not a rate: with
    thirteen past bulls, "1 of 13 was still going at this age" says more than
    any percentage fitted to it, and says it without implying a distribution
    nobody has the sample to claim.
    """
    if not tp:
        return None
    last_d, last_k = tp[-1]
    kind = "bull" if last_k == "T" else "bear"
    age = _months(last_d, s.index[-1])
    now = float(s.iloc[-1])
    start = float(s[last_d])

    seg = s[s.index >= last_d]
    best_at = seg.idxmax() if kind == "bull" else seg.idxmin()

    peers = [p for p in phases(s, tp) if p["phase"] == kind]
    durations = [p["months"] for p in peers]
    changes = [p["change"] for p in peers]
    change = now / start - 1.0

    survivors = []
    for p in peers:
        if p["months"] < age:
            continue
        at_age = p["start"] + pd.DateOffset(months=age)
        if at_age not in s.index:
            continue
        survivors.append({
            "label": f"{p['start']:%b %Y}", "months": p["months"],
            "extra_months": p["months"] - age,
            "extra_change": p["to"] / float(s[at_age]) - 1.0,
        })

    return {
        "kind": kind, "start": last_d, "age_months": age,
        "start_level": start, "level": now, "change": change,
        "best_level": float(seg[best_at]), "best_at": best_at,
        "off_best": now / float(seg[best_at]) - 1.0,
        "provisional": [{"date": d, "kind": k} for d, k in prov],
        "n_peers": len(peers),
        "peer_median_months": int(np.median(durations)) if durations else None,
        "peer_median_change": float(np.median(changes)) if changes else None,
        "rank_duration": sorted(durations + [age], reverse=True).index(age) + 1,
        "rank_change": sorted(changes + [change], reverse=True).index(change) + 1,
        "still_running_at_age": survivors,
        "series_end": s.index[-1],
    }


def summary(seed: dict, key: str = DEFAULT_SERIES, real: bool = True,
            min_phase: int = MIN_PHASE_MONTHS) -> dict:
    """Everything the page draws, from one pass over one series."""
    s, units = price(seed, key, real)
    tp, prov = turning_points(s, min_phase=min_phase)
    ctx = context(s, tp, prov)
    return {
        "series": s, "units": units, "key": key, "real": real,
        "source": seed.get("source", "file"),
        "min_phase": min_phase,
        "turns": tp, "provisional": prov,
        "phases": phases(s, tp),
        "trough_to_trough": cycle_lengths(tp, "T"),
        "peak_to_peak": cycle_lengths(tp, "P"),
        "context": ctx,
        "overlay": overlay(s, tp, ctx if ctx and ctx["kind"] == "bull" else None),
        "first": s.index[0], "last": s.index[-1],
    }
