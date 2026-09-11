"""
Read-only analytics for Mexican feeder cattle imports.

Import-safe by design -- no `requests`, no HTTP, no ingest. Same split as
herd.py: the Streamlit process should never pull the ingest's network stack in.
Ingest lives in the cme-feeder-cattle-index repo as border_reports.py (AMS
narrative + trade status) and census_imports.py (Census head counts), and the
daily job pushes both to JSA.CME_FEEDER_CATTLE.

TWO SOURCES, NEITHER SUFFICIENT ALONE.

  AMS daily      (border_receipts)  head counts by crossing point, current to
                                    yesterday. ESTIMATES, rounded to the
                                    nearest hundred head.
  AMS weekly     (border_volumes)   exact weekly volumes with AMS's own YTD and
                                    prior-year YTD. A week behind the daily.
  AMS narrative  (border_reports)   trade status, which crossings are open,
                                    market tone -- what no number carries.
  Census         (census_cattle_    the official customs count, seven years of
                 imports)           history, about six weeks late. January
                                    publishes in early March.

So AMS answers "what is crossing now" and Census answers "how does that compare
to a normal year". In September 2026 Census showed zero imports for the entire
year while AMS showed Douglas, AZ reopening on 24 August and 5,200 head crossing
since -- not a contradiction, just the six-week lag. The two tie out where they
overlap: AMS's 2024 and 2025 daily totals land within ~3% of Census.

A CORRECTION WORTH KEEPING. The first version of this module asserted AMS
"carries NO numbers ... all seven International Livestock reports return zero
structured data fields", and the page showed crossing DAYS as a proxy. That was
wrong. MARS reports are split into SECTIONS addressed as PATH segments
(/reports/3486/Report%20Volume); ask for a report without one and you get its
header -- narrative and dates, nothing numeric -- which is indistinguishable
from a report that has no data. Passing `section` as a query parameter is
accepted and silently ignored. The section list was in the response's
`reportSections` key the whole time.

WHY 320 KG MATTERS. Census's weight bands top out at "320 kg or more", and
320 kg is 705 lb -- the very bottom of the CME index's 700-899 lb window. Nearly
all Mexican cattle cross BELOW index weight and reach it only after months on US
feed, so an import cut moves the index with a lag, through supply, and never by
appearing in the index's own composition.
"""
import re

import snowflake_db as db

# ── AMS narrative parsing ────────────────────────────────────────────────────

# "No cattle crossed today." AMS began publishing on zero-crossing days in
# 2026; before that a published report always meant cattle crossed. Counting
# reports rather than crossings therefore understates the 2026 collapse (12
# reports, 7 crossings) while looking perfectly reasonable.
NO_CROSSING = re.compile(r"no cattle (crossed|were crossed|crossing)", re.I)

# Crossings are named inconsistently: case varies (DOUGLAS, AZ), several appear
# in one report ("DOUGLAS AND NOGALES, AZ"), and a preceding sentence can run
# into the name ("... OTHERWISE NOTED. NOGALES, AZ"). Matching city names from a
# known list and requiring the state nearby is what makes the counts add up.
KNOWN_PORTS = ["SANTA TERESA, NM", "ST TERESA, NM", "COLUMBUS, NM",
               "DOUGLAS, AZ", "NOGALES, AZ", "PRESIDIO, TX", "EAGLE PASS, TX",
               "LAREDO, TX", "DEL RIO, TX", "SAN LUIS, AZ", "CALEXICO, CA"]
# AMS's own typo for Santa Teresa. Without folding it, 2024 splits 136/56
# across two names for one crossing.
PORT_ALIASES = {"ST TERESA, NM": "SANTA TERESA, NM"}

REOPEN = re.compile(r"RE-?OPENED|IS NOW OPEN", re.I)
SUSPEND = re.compile(r"SUSPEND|CLOSED|REMAIN(?:S)? CLOSED", re.I)


def _clean(v) -> str:
    return " ".join(str(v or "").split())


def ports_in(text: str):
    """Every known crossing named anywhere in a narrative, normalized."""
    t = _clean(text).upper()
    found = set()
    for p in KNOWN_PORTS:
        city, state = p.split(", ")
        for m in re.finditer(r"\b" + re.escape(city) + r"\b", t):
            if state in t[m.end():m.end() + 30]:
                found.add(PORT_ALIASES.get(p, p))
                break
    return found


def title_port(p: str) -> str:
    """'DOUGLAS, AZ' -> 'Douglas, AZ'."""
    city, _, state = p.partition(", ")
    return f"{city.title()}, {state}"


# ── AMS: status and crossing activity ────────────────────────────────────────

def current_status(conn):
    """
    Latest trade-status note from AMS, with the date so the page can say how old
    it is. Absence is NOT backfilled from an older week: a week with no note is
    a week AMS did not flag anything, and showing last month's suspension notice
    as though it were current would be worse than showing nothing.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, report_begin, report_end, special_notes "
        "FROM border_reports WHERE kind = 'status' "
        "ORDER BY report_date DESC").fetchall()
    if not rows:
        return None
    rd, begin, end, notes = rows[0]
    return {
        "date": db.iso(rd),
        "begin": db.iso(begin) if begin else None,
        "end": db.iso(end) if end else None,
        "notes": _clean(notes) or None,
        "weeks_with_notes": sum(1 for r in rows if r[3]),
        "weeks_total": len(rows),
    }


def crossing_days(conn):
    """
    {year: {"reports", "crossings", "zero"}}.

    "crossings" is the number to show -- see NO_CROSSING above for why it is not
    the report count.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary'").fetchall()
    out = {}
    for rd, narr in rows:
        y = str(db.iso(rd))[:4]
        d = out.setdefault(y, {"reports": 0, "crossings": 0, "zero": 0})
        d["reports"] += 1
        t = _clean(narr)
        if t and NO_CROSSING.search(t):
            d["zero"] += 1
        else:
            d["crossings"] += 1
    return dict(sorted(out.items()))


def ports_by_year(conn):
    """
    {port: {year: crossing days}}, busiest first -- which crossings are open.

    The clearest single picture of the suspension: five crossings active through
    2024, one in 2026. Zero-crossing days are excluded, so a port publishing
    "no cattle crossed" does not count as open.
    """
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary'").fetchall()
    out = {}
    for rd, narr in rows:
        t = _clean(narr)
        if not t or NO_CROSSING.search(t):
            continue
        y = str(db.iso(rd))[:4]
        for p in ports_in(t):
            out.setdefault(p, {})
            out[p][y] = out[p].get(y, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -sum(kv[1].values())))


def crossing_dates(conn):
    """Every date cattle actually crossed, ascending."""
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' ORDER BY report_date").fetchall()
    return [str(db.iso(rd)) for rd, narr in rows
            if _clean(narr) and not NO_CROSSING.search(_clean(narr))]


def reopening(conn, gap_days=45):
    """
    The most recent reopening: first crossing after a gap of `gap_days`+.

    Derived from the DATES rather than from an announcement, so it does not
    depend on AMS having worded a notice a particular way. The matching
    announcement text is returned alongside as corroboration when one exists,
    which is how the 2026-08-24 reopening was confirmed two ways.
    """
    dates = crossing_dates(conn)
    if len(dates) < 2:
        return None
    from datetime import date as _d

    def parse(s):
        return _d.fromisoformat(str(s)[:10])

    reopen_at, prev_at = None, None
    for a, b in zip(dates, dates[1:]):
        if (parse(b) - parse(a)).days >= gap_days:
            reopen_at, prev_at = b, a
    if not reopen_at:
        return None

    note = None
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' ORDER BY report_date").fetchall()
    for rd, narr in rows:
        if str(db.iso(rd))[:10] == reopen_at:
            t = _clean(narr)
            m = re.search(r"\*{2,}(.+?)\*{2,}", t)
            if m and REOPEN.search(m.group(1)):
                note = m.group(1).strip()
            break
    return {"date": reopen_at, "previous_crossing": prev_at,
            "gap_days": (parse(reopen_at) - parse(prev_at)).days,
            "note": note,
            "days_since": (_d.today() - parse(reopen_at)).days}


EXPORT_WORD = re.compile(r"\bEXPORT", re.I)
IMPORT_WORD = re.compile(r"\bIMPORT|\bBORDER\b|\bCROSS", re.I)
# AMS wraps each announcement in asterisks; one note can carry several.
SEGMENT = re.compile(r"\*{2,}\s*(.+?)\s*\*{2,}", re.S)


def note_segments(notes: str):
    """
    [(text, direction)] -- one entry per announcement inside a status note.

    THIS IS NOT PEDANTRY, AND ONE LABEL PER NOTE IS THE WRONG SHAPE. AMS report
    3629 covers BOTH directions and a single note routinely carries both. In
    September 2026 the standing note read

        *** EXPORTS TO MEXICO REMAIN SUSPENDED UNTIL FURTHER NOTICE. ***

    while Douglas, AZ was actively crossing cattle INTO the United States, and
    an earlier note carried the Douglas reopening and the export suspension side
    by side. A page that renders "the latest note" as "the border" would have
    declared imports closed for three weeks after they reopened -- confidently,
    and citing a genuine USDA source. So each announcement is classified
    separately and the page asks for the direction it actually means.

    Direction is decided on the plain words IMPORT / EXPORT / BORDER / CROSS.
    An earlier version required "IMPORTS FROM|INTO" and matched 2 notes out of
    26, silently leaving "IMPORTS ARE SUSPENDED UNTIL FURTHER NOTICE" as
    unknown.
    """
    t = _clean(notes)
    if not t:
        return []
    segs = [s.strip() for s in SEGMENT.findall(t) if s.strip()]
    if not segs:                       # unasterisked note, e.g. "Correction to horses"
        segs = [t]
    out = []
    for s in segs:
        has_ex, has_im = bool(EXPORT_WORD.search(s)), bool(IMPORT_WORD.search(s))
        if has_im and not has_ex:
            d = "import"
        elif has_ex and not has_im:
            d = "export"
        elif has_ex and has_im:
            d = "both"
        else:
            d = "unknown"             # holiday schedules, corrections
        out.append((s, d))
    return out


def import_notes(notes: str):
    """Only the announcements that bear on IMPORTS. See note_segments()."""
    return [s for s, d in note_segments(notes) if d in ("import", "both")]


def status_history(conn, limit=None):
    """
    [(week_end, [import-relevant announcement, ...])] newest first.

    The suspension timeline in AMS's own words, which is richer than the
    crossing dates alone: it names New World Screwworm as the cause, and records
    a reopening on 7 July 2025 that closed again shortly after -- a detail no
    volume series shows, because the reopening barely produced volume.
    """
    rows = conn.cursor().execute(
        "SELECT report_end, report_date, special_notes FROM border_reports "
        "WHERE kind = 'status' AND special_notes IS NOT NULL "
        "ORDER BY report_date DESC").fetchall()
    out = []
    for end, rd, notes in rows:
        segs = import_notes(notes)
        if segs:
            out.append((str(db.iso(end or rd)), segs))
        if limit and len(out) >= limit:
            break
    return out


def import_status(conn, stale_days=10):
    """
    Is the IMPORT border open, judged only on import-side evidence.

    Derived from crossing activity in the 3486 summary rather than from any
    announcement in 3629 -- see note_direction() for why mixing the two is a
    trap. Returns the evidence, not just a verdict, so the page can show what
    the call rests on.

    "open" means cattle have actually crossed recently. A run of published
    zero-crossing days leaves the port open but idle, which is a different
    thing and is reported as such.
    """
    from datetime import date as _d

    dates = crossing_dates(conn)
    rows = conn.cursor().execute(
        "SELECT MAX(report_date) FROM border_reports WHERE kind = 'commentary'"
    ).fetchone()
    latest_report = str(db.iso(rows[0])) if rows and rows[0] else None
    if not dates:
        return {"state": "closed", "last_crossing": None,
                "latest_report": latest_report, "reopening": reopening(conn)}

    last = dates[-1]
    days = (_d.today() - _d.fromisoformat(str(last)[:10])).days
    # Idle vs closed: the port is still publishing, just with nothing crossing.
    if days <= stale_days:
        state = "open"
    elif latest_report and (_d.today() -
                            _d.fromisoformat(str(latest_report)[:10])).days <= stale_days:
        state = "idle"
    else:
        state = "closed"
    # ports_by_year is already ordered busiest-first, so keep that order.
    current_year = str(_d.today().year)
    active = [title_port(p) for p, d in ports_by_year(conn).items()
              if d.get(current_year)]
    return {"state": state, "last_crossing": str(last),
            "days_since_crossing": days, "latest_report": latest_report,
            "active_ports": active, "reopening": reopening(conn)}


def recent_commentary(conn, limit=15):
    """Latest port-level market notes, newest first, with a crossed flag."""
    rows = conn.cursor().execute(
        "SELECT report_date, narrative FROM border_reports "
        "WHERE kind = 'commentary' AND narrative IS NOT NULL "
        "ORDER BY report_date DESC").fetchall()
    out = []
    for rd, narr in rows[:limit]:
        t = _clean(narr)
        # A leading "*** ... ***" block is an AMS announcement, not market
        # commentary; split it out so the table's text column stays readable.
        note = None
        m = re.match(r"\*{2,}(.+?)\*{2,}\s*(.*)$", t)
        if m:
            note, t = m.group(1).strip(), m.group(2).strip()
        port, _, rest = t.partition(" - ")
        out.append({
            "date": str(db.iso(rd)),
            "port": title_port(port.strip().upper()) if rest else None,
            "text": rest.strip() if rest else t,
            "note": note,
            "crossed": not NO_CROSSING.search(t or ""),
        })
    return out


# ── Census: classification and volumes ──────────────────────────────────────

def classify_commodity(commodity: str, descr: str) -> str:
    """
    feeder / slaughter / breeding / dairy / other, from the description.

    THE EXCLUSION CLAUSE. Every commercial line reads

        CATTLE, LIVE, MALE, WEIGHING 200 KG OR MORE BUT LESS THAN 320 KG EACH,
        OTHER THAN PUREBRED BREEDING AND/OR DAIRY

    so a substring test for "breeding" labels the whole feeder volume as
    breeding stock, and switching to "dairy" labels it dairy. Either mistake
    mislabelled 115,636 of June 2024's 116,696 head and still rendered a
    plausible table. Everything after "OTHER THAN" says what the line is NOT, so
    it is split off and only the positive part is matched -- which also handles
    any exclusion Census adds later.

    Keyed on the description, not the code: HS10 numbers get renumbered, the
    wording does not. Read-time classification means a wrong call is a one-line
    fix rather than a re-pull.
    """
    positive, _, _excl = (descr or "").upper().partition("OTHER THAN")
    if "IMMEDIATE SLAUGHTER" in positive:
        return "slaughter"
    if "DAIRY" in positive:
        return "dairy"
    if "PUREBRED" in positive or "FOR BREEDING" in positive:
        return "breeding"
    if "WEIGHING" in positive and "KG" in positive:
        return "feeder"
    return "other"


# Ordered light to heavy so a composition chart stacks sensibly.
BANDS = ["<90 kg (<198 lb)", "90-200 kg (198-441 lb)",
         "200-320 kg (441-705 lb)", "320+ kg (705+ lb)", "unspecified"]


def weight_band(descr: str) -> str:
    """The HS weight band, in pounds as well as kilos. See the 320 kg note above."""
    d, _, _x = (descr or "").upper().partition("OTHER THAN")
    if "LESS THAN 90" in d:
        return BANDS[0]
    if "90 KG OR MORE" in d and "LESS THAN 200" in d:
        return BANDS[1]
    if "200 KG OR MORE" in d and "LESS THAN 320" in d:
        return BANDS[2]
    if "320 KG OR MORE" in d:
        return BANDS[3]
    return BANDS[4]


# ── AMS head counts (the timely series) ─────────────────────────────────────
#
# These come from MARS report SECTIONS, which are PATH segments
# (/reports/3486/Report%20Volume). Requesting a report without one returns only
# its header -- narrative and dates, nothing numeric -- which is why an earlier
# version of this page concluded AMS published no numbers at all and showed
# crossing DAYS as a proxy. It publishes head counts daily.
#
# Two series, different in kind, never to be mixed:
#   border_receipts  DAILY, field named receipts_current_EST, rounded to the
#                    nearest 50-100 head. Current to yesterday.
#   border_volumes   WEEKLY ACTUALS with AMS's own YTD and prior-year YTD
#                    already computed. Exact, but a week behind.
# Through 2026-09-04 the daily estimates summed to 2,600 against an actual
# 2,557 -- a 1.7% rounding gap. Small, but the page labels which it is showing.

def daily_receipts(conn, since=None):
    """
    [(date, head, week_to_date)] -- AMS's own grand-total row per day.

    NEVER sums the per-crossing rows to get this. They are hierarchical rollups
    (all-points / per-state / per-crossing), so summing triple-counts, and the
    parts do not always reconcile: over 463 days the named crossings disagreed
    with AMS's published total on 19 of them. is_total flags the authoritative
    row at ingest so no reader has to re-derive that rule.
    """
    sql = ("SELECT report_date, receipts_est, receipts_wtd_est "
           "FROM border_receipts WHERE is_total = 1")
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " ORDER BY report_date"
    return [(str(db.iso(d)), v or 0, w or 0)
            for d, v, w in conn.cursor().execute(sql).fetchall()]


def receipts_by_year(conn):
    """{year: {"head", "days"}} from the daily estimate series."""
    out = {}
    for d, v, _w in daily_receipts(conn):
        y = str(d)[:4]
        r = out.setdefault(y, {"head": 0, "days": 0})
        r["head"] += v
        r["days"] += 1
    return dict(sorted(out.items()))


def receipts_by_crossing(conn, since=None):
    """
    [(crossing, state, head)] detail, busiest first.

    Detail only: these can disagree with the published total, so the page must
    present them as a breakdown rather than as something that adds up.
    """
    sql = ("SELECT crossing_point, crossing_state, SUM(receipts_est) "
           "FROM border_receipts WHERE is_total = 0 "
           "AND crossing_point <> 'All Crossing Points'")
    if since:
        sql += f" AND report_date >= '{since}'"
    sql += " GROUP BY crossing_point, crossing_state"
    rows = conn.cursor().execute(sql).fetchall()
    return sorted([(p, s, v or 0) for p, s, v in rows], key=lambda t: -t[2])


def ytd_actuals(conn, commodity="Feeder Cattle"):
    """
    AMS's OWN year-to-date, not one this page computes.

    Worth using rather than summing the daily series: AMS defines the cut-off,
    so a partial current year cannot be mismeasured against a full prior one --
    the trap that had the index's 2026 YTD reading the wrong sign before the
    weekday alignment went in. Returns the latest week carrying a YTD figure.
    """
    rows = conn.cursor().execute(
        "SELECT report_begin, report_end, current_volume, current_ytd, "
        "       prior_volume, prior_ytd, current_year, prior_year "
        "FROM border_volumes WHERE category = 'Import' "
        f"AND commodity = '{commodity}' AND origin = 'Mexico' "
        "ORDER BY report_begin DESC").fetchall()
    for b, e, cv, cy, pv, py, yr, pyr in rows:
        if cy is None:
            continue          # weeks during the shutdown carry no YTD at all
        return {
            "week_begin": str(db.iso(b)), "week_end": str(db.iso(e)),
            "week": cv, "ytd": cy, "prior_week": pv, "prior_ytd": py,
            "year": yr, "prior_year": pyr,
            "pct": ((cy / py - 1) * 100) if py else None,
        }
    return None


def since_reopening(conn):
    """
    Head crossed since the border reopened, from the daily series.

    Deliberately the daily estimates rather than AMS's weekly actuals: the
    actuals lag a week, and "how many since it reopened" is a question about
    right now. The caller is told it is an estimate.
    """
    r = reopening(conn)
    if not r or not r.get("date"):
        return None
    rows = daily_receipts(conn, since=r["date"])
    if not rows:
        return None
    crossed = [(d, v) for d, v, _w in rows if v > 0]
    return {
        "from": r["date"],
        "head": sum(v for _d, v, _w in rows),
        "days": len(rows),
        "days_with_cattle": len(crossed),
        "best_day": max(crossed, key=lambda t: t[1]) if crossed else None,
        "latest": rows[-1][0],
    }


def _national(conn):
    return conn.cursor().execute(
        "SELECT period, commodity, descr, head, value_usd "
        "FROM census_cattle_imports WHERE port_code = '' "
        "ORDER BY period").fetchall()


def monthly_head(conn, kinds=("feeder",)):
    """([(period, head)], data_through_period)."""
    agg = {}
    for period, commodity, descr, head, _v in _national(conn):
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        agg[str(period)] = agg.get(str(period), 0) + (head or 0)
    series = sorted(agg.items())
    return series, (series[-1][0] if series else None)


def annual_head(conn, kinds=("feeder",)):
    """{year: head} full-year totals, plus the data-through period."""
    series, through = monthly_head(conn, kinds)
    out = {}
    for period, head in series:
        y = int(str(period)[:4])
        out[y] = out.get(y, 0) + head
    return out, through


def ytd_compare(conn, kinds=("feeder",)):
    """
    {year: {...}} year-to-date on MONTHS PRESENT IN BOTH YEARS only.

    A partial current year must never be measured against a full prior year --
    the same trap that had the index's 2026 YTD reading the wrong sign before
    the weekday alignment went in.
    """
    series, through = monthly_head(conn, kinds)
    by = {}
    for period, head in series:
        y, m = str(period).split("-")
        by.setdefault(int(y), {})[int(m)] = head
    out = {}
    for y in sorted(by):
        prev = by.get(y - 1, {})
        shared = sorted(set(by[y]) & set(prev))
        cur = sum(by[y][m] for m in shared)
        prv = sum(prev[m] for m in shared)
        out[y] = {"total": sum(by[y].values()), "months": sorted(by[y]),
                  "shared_months": shared, "ytd": cur, "prior_ytd": prv,
                  "pct": (cur / prv - 1) * 100 if prv else None}
    return out, through


def band_shares(conn, year=None, kinds=("feeder",)):
    """[(band, head, share_pct)] for one year, light to heavy."""
    rows = _national(conn)
    years = sorted({int(str(p)[:4]) for p, *_ in rows})
    if not years:
        return [], None
    if year is None:
        # The newest year that actually carried volume -- the newest year on
        # file is all zeros during a suspension, which would render an empty
        # chart rather than the last real composition.
        for y in reversed(years):
            if any((h or 0) for p, c, d, h, _v in rows if str(p)[:4] == str(y)):
                year = y
                break
        else:
            year = years[-1]
    agg = {}
    for period, commodity, descr, head, _v in rows:
        if str(period)[:4] != str(year):
            continue
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        b = weight_band(descr)
        agg[b] = agg.get(b, 0) + (head or 0)
    total = sum(agg.values())
    out = [(b, agg.get(b, 0), (agg.get(b, 0) / total * 100) if total else 0)
           for b in BANDS if agg.get(b)]
    return out, year


def kind_totals(conn, year=None):
    """{kind: head} for one year -- the audit view behind the feeder headline."""
    rows = _national(conn)
    years = sorted({int(str(p)[:4]) for p, *_ in rows})
    if not years:
        return {}, None
    year = year if year is not None else years[-1]
    agg = {}
    for period, commodity, descr, head, _v in rows:
        if str(period)[:4] != str(year):
            continue
        k = classify_commodity(commodity, descr)
        agg[k] = agg.get(k, 0) + (head or 0)
    return agg, year


def value_per_head(conn, kinds=("feeder",)):
    """
    [(period, $/head)] -- the customs value per animal.

    Not a market price: it is the declared entry value, and it moves with both
    the cattle market and the mix of weights crossing. Useful as a level check
    on the head counts, not as a quote.
    """
    agg = {}
    for period, commodity, descr, head, value in _national(conn):
        if kinds and classify_commodity(commodity, descr) not in kinds:
            continue
        d = agg.setdefault(str(period), [0, 0])
        d[0] += (head or 0)
        d[1] += (value or 0)
    return [(p, v / h) for p, (h, v) in sorted(agg.items()) if h]


def data_freshness(conn):
    """What each source is current to -- shown so the lag is never implicit."""
    cur = conn.cursor()
    ams = cur.execute("SELECT MAX(report_date) FROM border_reports "
                      "WHERE kind = 'commentary'").fetchone()
    census_rows = cur.execute(
        "SELECT period, SUM(head) FROM census_cattle_imports "
        "WHERE port_code = '' GROUP BY period ORDER BY period").fetchall()
    last_nonzero = None
    for p, h in census_rows:
        if (h or 0) > 0:
            last_nonzero = str(p)
    return {
        "ams_through": str(db.iso(ams[0])) if ams and ams[0] else None,
        "census_through": str(census_rows[-1][0]) if census_rows else None,
        "census_last_volume": last_nonzero,
    }
