"""
What a Mexican feeder calf is worth INSIDE Mexico, against the US border quote.

The page has always been able to price a calf the moment it reaches the US
side -- AMS 3486 gives $/cwt F.O.B. at Douglas and Santa Teresa, and the
Border Prices section differences that against the CME index. This is the
other half: the same animal before it crosses.

    JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES   Tamaulipas auction, MXN/kg
    JSA.CME_FEEDER_CATTLE.FX_USDMXN           ECB reference rate, per sale day
    JSA.CME_FEEDER_CATTLE.BORDER_PRICES       AMS 3486, $/cwt F.O.B.

`scripts/mx_auction.py` writes the first two from the droplet. This module only
reads.

**IT DOES NOT IMPORT `requests`, AND THAT IS DELIBERATE.** CLAUDE.md records the
rule for this page: `border.py` has no HTTP path so the Streamlit process cannot
acquire one, and the ingest lives elsewhere. The conversion below is therefore a
second copy of `mx_auction.usd_per_cwt` rather than an import of it --
`mx_auction` needs `requests` for the scrape. `tests/test_mx_prices.py` runs the
two against each other over a grid so the copy cannot drift; that test may
import the scraper because a test is not the page.

THE COMPARISON IS HONEST ONLY IF THE READER IS TOLD WHAT IT IS NOT, and the
panel says all three out loud:

* **TAMAULIPAS IS NOT WHERE THESE CATTLE COME FROM.** Douglas and Santa Teresa
  take Sonora and Chihuahua cattle. Neither state has an auction on
  mexicoganadero.com, and the only figures for them anywhere are association
  spokesmen quoted in the Mexican press. Tamaulipas is a northern border state
  publishing real feeder bands by weight, which makes it the closest honest
  comparator and not the right one. A reader who takes the gap below as "the
  export premium at Douglas" has been misled by a number that is correctly
  computed.
* **THE TWO SIDES ARE RARELY QUOTED THE SAME DAY.** Tamaulipas sells roughly
  weekly; AMS quotes only on days enough head sell to establish a trend. So
  `compare()` pairs each sale with the NEAREST priced border date and returns
  `gap_days` for the panel to print. Pretending to a same-day spread would be
  the letter-vs-dashboard failure recorded in CLAUDE.md, arriving by a new
  route.
* **IT IS A LEVEL, NOT A MARGIN.** Nothing here nets out freight, the test, the
  crossing fee, shrink or the buyer's margin. A calf worth 60% of the Douglas
  price is not 40% profit.

WEIGHT IS MATCHED ON THE MIDPOINT, which is the one judgement call in here. The
two ladders do not align -- Tamaulipas bands in kg (151-180, 181-200, ...) and
AMS in lb (400-500, 500-600, ...) -- so a band is assigned to the US bracket
containing its own midpoint in pounds. Two Mexican bands can therefore land in
one US bracket, and they are kept as separate rows rather than averaged: with no
head counts an average would weight a thin band equally with a heavy one and
report a single figure that no lot ever traded at.

ONLY THE `CN` LADDER IS COMPARED. The site also prints wide `CNH` lots
(100-180, 181-260, 251-330 kg) which overlap the narrow ones and run far
cheaper -- BECERRO CNH 251-330 at 58.33 MXN/kg against CN 251-280 at 81.89 on
the 2026-09-30 sale. Mixing the two ladders would double-count a weight and
drag every comparison down by a grade difference the US quote does not share.
`CNH_PREFIXES` names them; `bands()` returns them flagged so the data table can
still show them, and `compare()` leaves them out.

SEX IS MATCHED TOO. BECERRO is a bull calf and pairs with AMS `Steers`;
BECERRA is a heifer calf and pairs with `Spayed Heifers`. Pairing a Mexican
heifer against a US steer quote would read as a discount that is really a sex
difference.
"""

from __future__ import annotations

from datetime import date

# Matches scripts/mx_auction.LB_PER_KG exactly; a test pins that it still does.
LB_PER_KG = 2.2046226218

MX_TABLE = "JSA.CME_FEEDER_CATTLE.MX_AUCTION_PRICES"
FX_TABLE = "JSA.CME_FEEDER_CATTLE.FX_USDMXN"
US_TABLE = "border_prices"

PER_KG = "MXN/kg"

#: The auction this page compares against. Yucatan and Durango come free in the
#: same scrape and are kept in the table for context, but neither bands by
#: weight, so neither can be matched to an AMS bracket at all.
AUCTION = "TAMAULIPAS"

#: Feeder calves. Everything else the sale prints -- VACA (cows), TORO (bulls),
#: TORETE, NOVILLONAS, VAQUILLAS -- is a different animal on a different market
#: and has no border quote to sit beside.
FEEDER_PREFIXES = ("BECERRO", "BECERRA")

#: The wide overlapping ladder, excluded from the comparison. See the docstring.
CNH_PREFIXES = ("BECERRO CNH", "BECERRA CNH")

#: Mexican sex -> the AMS class that quotes the same animal.
US_CLASS_BY_SEX = {"M": "Steers", "F": "Spayed Heifers"}

#: AMS publishes 1-2 and 2-3; the page headlines 1-2, so the comparison does.
US_GRADE = "1-2"

#: How far apart a sale and a border quote may be and still be shown as a pair.
#: Beyond this the panel prints the sale with no comparison rather than a
#: spread across a fortnight of market movement.
MAX_GAP_DAYS = 21

#: Bumped whenever load() changes the SHAPE of what it returns. It is passed
#: into the cached fetch purely as part of the key -- st.cache_data keys on the
#: decorated function's own code and never on the modules it calls, the trap
#: recorded in CLAUDE.md for leverage.SCHEMA and am_cutout.SCHEMA. Without it a
#: new key renders "—" and nothing raises.
#:
#: 2 (2026-10-07): bands() now sorts steers and the CN ladder first. The SHAPE
#: did not change, only the ORDER -- which is precisely a change the cache
#: cannot see, so the deployed page would have gone on serving the old
#: heifers-first ordering from a cached dict with nothing raising. Bump this
#: for an ordering or content change, not only for a new key.
SCHEMA = 2


def usd_per_cwt(mxn_per_kg, mxn_per_usd):
    """MXN/kg -> USD/cwt, the unit AMS 3486 quotes the border in.

    Kilos to pounds, pesos to dollars, per-pound to per-hundredweight. None
    propagates rather than defaulting, so a missing rate leaves the cell empty
    instead of silently pricing a calf at an implied 1.0 peso.

    Byte-for-byte the same arithmetic as scripts/mx_auction.usd_per_cwt; see
    this module's docstring for why it is copied rather than imported.
    """
    if mxn_per_kg is None or not mxn_per_usd:
        return None
    return float(mxn_per_kg) / LB_PER_KG / float(mxn_per_usd) * 100.0


def kg_to_lb(kg):
    return None if kg is None else float(kg) * LB_PER_KG


def band_midpoint_lb(low_kg, high_kg):
    """Midpoint of a Mexican band, in pounds, or None if it is open-ended.

    An open band ("menor a 150kg") has no midpoint that means anything, and
    inventing one by treating the missing end as zero would place a 150 kg calf
    at 75 kg and match it to a bracket four rungs down.
    """
    if low_kg is None or high_kg is None:
        return None
    return kg_to_lb((float(low_kg) + float(high_kg)) / 2.0)


def match_us_band(mid_lb, us_bands):
    """The US bracket containing `mid_lb`, or None.

    `us_bands` is [(low_lb, high_lb, avg_price)]. None rather than a nearest
    match on purpose: a 828 lb Mexican band has no counterpart when AMS stops
    at 800, and snapping it to 700-800 would compare a heavier calf to a
    lighter quote and report the weight slide as a price gap.
    """
    if mid_lb is None:
        return None
    for low, high, price in us_bands:
        if low is None or high is None:
            continue
        if float(low) <= mid_lb <= float(high):
            return (float(low), float(high), price)
    return None


def is_feeder(clasificacion: str) -> bool:
    c = (clasificacion or "").upper()
    return any(c.startswith(p) for p in FEEDER_PREFIXES)


def is_cnh(clasificacion: str) -> bool:
    c = (clasificacion or "").upper()
    return any(c.startswith(p) for p in CNH_PREFIXES)


# ── reads ───────────────────────────────────────────────────────────────────

def sale_dates(conn, auction=AUCTION):
    """Every sale date held, newest first. The site keeps two sales and no
    archive, so this list only ever grows forwards from the first run."""
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT DISTINCT SALE_DATE FROM {MX_TABLE} "
        f"WHERE AUCTION = %s ORDER BY SALE_DATE DESC", (auction,)
    ).fetchall()
    return [r[0] for r in rows]


def bands(conn, sale_date, auction=AUCTION):
    """Feeder bands for one sale.

    [{clasificacion, sex, low_kg, high_kg, low, high, avg, unit, cnh}] with
    `low`/`high` in POUNDS. Rows priced per head rather than per kilo are
    returned with avg None: the scraper records the unit it saw, and a per-head
    price divided by a weight the sale did not state is a number nobody quoted.
    """
    cur = conn.cursor()
    rows = cur.execute(
        f"SELECT CLASIFICACION, SEX, WEIGHT_LOW_KG, WEIGHT_HIGH_KG, "
        f"       PRICE_MIN, PRICE_MAX, PRICE_AVG, UNIT "
        f"FROM {MX_TABLE} WHERE AUCTION = %s AND SALE_DATE = %s ",
        (auction, sale_date)
    ).fetchall()
    out = []
    for cls, sex, lo_kg, hi_kg, lo, hi, avg, unit in rows:
        if not is_feeder(cls):
            continue
        out.append({
            "clasificacion": cls,
            "sex": sex,
            "low_kg": float(lo_kg) if lo_kg is not None else None,
            "high_kg": float(hi_kg) if hi_kg is not None else None,
            "low_lb": kg_to_lb(lo_kg),
            "high_lb": kg_to_lb(hi_kg),
            "mid_lb": band_midpoint_lb(lo_kg, hi_kg),
            "price_min": float(lo) if lo is not None else None,
            "price_max": float(hi) if hi is not None else None,
            "price_avg": float(avg) if avg is not None and unit == PER_KG else None,
            "unit": unit,
            "cnh": is_cnh(cls),
        })

    # THE ROWS THAT CARRY A COMPARISON COME FIRST, and that is not cosmetic.
    # Sorted by the SQL's `SEX, WEIGHT_LOW_KG`, F sorts before M -- so the first
    # ten rows were heifers, every one of them showing a dash in the AMS
    # columns because AMS stopped quoting Spayed Heifers in May 2025. The whole
    # point of the table sat below the fold under a block of em-dashes, which
    # reads as a broken join rather than as the US feed's state. Spotted on the
    # deployed page, not in a test, because no test looks at row order.
    #
    # Steers before heifers, the clean CN ladder before the wide CNH lots, then
    # ascending weight -- so the table opens on the ladder a reader can compare
    # straight down and the uncomparable rows collect at the bottom.
    out.sort(key=lambda r: (0 if r["sex"] == "M" else 1,
                            1 if r["cnh"] else 0,
                            r["low_kg"] if r["low_kg"] is not None else -1.0))
    return out


def fx_on(conn, when):
    """(rate_date, mxn_per_usd) for `when`, falling back to the newest rate
    BEFORE it.

    Strictly before, never after. A sale is priced at the rate that stood when
    it traded; reaching forward to a later rate would restate a past sale every
    time the peso moved, which is the decay failure `FORECAST_MAX_ANALOGUES`
    exists to stop on the cash forecast tab.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT RATE_DATE, MXN_PER_USD FROM {FX_TABLE} "
        f"WHERE RATE_DATE <= %s ORDER BY RATE_DATE DESC LIMIT 1", (when,)
    ).fetchone()
    if not r:
        return None, None
    return r[0], float(r[1])


def us_last_quoted(conn, us_class, grade=US_GRADE):
    """The newest date AMS priced `us_class` at all, ignoring any gap limit.

    EXISTS SO A BLANK COLUMN CAN EXPLAIN ITSELF. AMS has not quoted Spayed
    Heifers since 2025-05-12 -- 2026 carries 23 priced days and every one of
    them is Steers -- so every Mexican heifer band correctly matches nothing.
    Without this the panel would show a column of dashes that looks exactly
    like a broken join, and the honest answer ("the US side stopped quoting
    this class eighteen months ago") is one query away.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT MAX(report_date) FROM {US_TABLE} "
        f"WHERE avg_price IS NOT NULL AND class_desc = %s AND muscle_grade = %s",
        (us_class, grade)
    ).fetchone()
    return r[0] if r else None


def us_bands_near(conn, when, us_class, grade=US_GRADE, max_gap=MAX_GAP_DAYS):
    """(quote_date, [(low_lb, high_lb, avg)], gap_days) nearest to `when`.

    Nearest in EITHER direction, because a sale can fall between two quoted
    border days and the closer one is the better comparator whichever side it
    sits. Returns (None, [], None) when nothing is within `max_gap`.
    """
    cur = conn.cursor()
    r = cur.execute(
        f"SELECT report_date, ABS(DATEDIFF('day', report_date, %s)) g "
        f"FROM {US_TABLE} WHERE avg_price IS NOT NULL AND class_desc = %s "
        f"  AND muscle_grade = %s "
        f"ORDER BY g ASC, report_date DESC LIMIT 1", (when, us_class, grade)
    ).fetchone()
    if not r or r[1] is None or int(r[1]) > max_gap:
        return None, [], None
    on, gap = r[0], int(r[1])
    rows = cur.execute(
        f"SELECT weight_low, weight_high, avg_price FROM {US_TABLE} "
        f"WHERE report_date = %s AND class_desc = %s AND muscle_grade = %s "
        f"  AND avg_price IS NOT NULL ORDER BY weight_low", (on, us_class, grade)
    ).fetchall()
    return on, [(r[0], r[1], float(r[2])) for r in rows], gap


# ── the comparison ──────────────────────────────────────────────────────────

def compare(conn, sale_date=None, auction=AUCTION):
    """Everything the panel draws, for one sale. None if no sale is held.

    Every row that carries a US counterpart gets `usd`, `us_price`, `pct` and
    `diff`; a row with no counterpart keeps `usd` and leaves the rest None, so
    the table still prices it in dollars and simply shows no spread.
    """
    dates = sale_dates(conn, auction)
    if not dates:
        return None
    on = sale_date or dates[0]

    rate_date, rate = fx_on(conn, on)
    rows = bands(conn, on, auction)

    us_cache = {}
    for sex, us_class in US_CLASS_BY_SEX.items():
        us_cache[sex] = us_bands_near(conn, on, us_class)

    out = []
    for b in rows:
        b = dict(b)
        b["usd"] = usd_per_cwt(b["price_avg"], rate)
        us_date, us_list, gap = us_cache.get(b["sex"], (None, [], None))
        b["us_class"] = US_CLASS_BY_SEX.get(b["sex"])
        b["us_date"] = us_date
        b["gap_days"] = gap
        match = None if b["cnh"] else match_us_band(b["mid_lb"], us_list)
        if match and b["usd"] is not None:
            b["us_low_lb"], b["us_high_lb"], b["us_price"] = match
            b["pct"] = b["usd"] / match[2] * 100.0 if match[2] else None
            b["diff"] = b["usd"] - match[2]
        else:
            b["us_low_lb"] = b["us_high_lb"] = b["us_price"] = None
            b["pct"] = b["diff"] = None
        out.append(b)

    return {
        "auction": auction,
        "sale_date": on,
        "sale_dates": dates,
        "fx_date": rate_date,
        "fx": rate,
        "rows": out,
        "us_dates": {s: us_cache[s][0] for s in us_cache},
        "gaps": {s: us_cache[s][2] for s in us_cache},
        # Only populated for a sex whose quote is missing, so the panel can say
        # WHY rather than printing a column of dashes. See us_last_quoted().
        "us_last": {s: us_last_quoted(conn, US_CLASS_BY_SEX[s])
                    for s in US_CLASS_BY_SEX if us_cache[s][0] is None},
    }


def headline(cmp_, sex="M"):
    """The single best-matched pair, for the tiles, or None.

    Picks the HEAVIEST matched band rather than the first, because the page's
    own border headline is 700-800 lb and the heaviest Mexican band that
    matches anything is the one that lands there. A reader comparing the two
    panels should see the same bracket in both.
    """
    best = None
    for r in cmp_["rows"] if cmp_ else []:
        if r["sex"] != sex or r["pct"] is None or r["mid_lb"] is None:
            continue
        if best is None or r["mid_lb"] > best["mid_lb"]:
            best = r
    return best


def spread_history(conn, sex="M", auction=AUCTION):
    """[(sale_date, pct, usd, us_price)] for the heaviest matched band, oldest
    first -- the series the panel charts once there is more than one sale.

    It accrues from the first run and cannot be backfilled: mexicoganadero.com
    keeps the current sale and one previous, with no archive and no date
    parameter. Same shape as JSA.BOXED_BEEF.CUTOUT_AM and for the same reason.
    """
    out = []
    for d in reversed(sale_dates(conn, auction)):
        c = compare(conn, d, auction)
        h = headline(c, sex)
        if h:
            out.append((d, h["pct"], h["usd"], h["us_price"]))
    return out
