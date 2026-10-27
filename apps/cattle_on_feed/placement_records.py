"""
Record-low placement months, and whether they mean what they look like.

Asked for by Ross on 2026-10-27, after he noticed placements had been the
lowest on record for their calendar month three reports running and wanted it
set against the 2014-15 rebuild.

WHAT THIS COMPUTES AND WHAT IT REFUSES TO. It reports WHAT moved -- how long
the run is, how it ranks, and what the herd and the heifer mix were doing at
the time. It does NOT say whether the cause is heifer retention. That split is
the one the 6 State market summary already runs on, and this page has a
standing rule against a caption that supplies a plausible wrong cause.

THE RECORD RULE IS THE WHOLE CORRECTNESS, and getting it wrong is how the
first pass at this analysis reached the opposite conclusion.

Placements are strongly seasonal -- October is always large, July always
small -- so "lowest ever" on the raw series is a statement about the calendar.
A record has to be conditioned on the calendar month. But then a month cannot
set a record the first time it appears, and a short history manufactures them:

    minimum prior years required     3-month runs found
                 0                   5   (1997, 1998, 2001, 2015, 2026)
                 5                   3   (2001, 2015, 2026)
                10                   2   (2015, 2026)
                20                   1   (2026)

**Sep-Nov 2001 is an artefact of a five-year-old series, and it reverses the
answer.** It cleared the bar with exactly five prior years, and it is not a
low-placement episode at all: its lowest "record" month is 1,908,000 head,
7.4% ABOVE the highest of the 2026 run, and its 12-month total ranks 302nd of
359 windows. Admit it and the record looks like something that happens in
ordinary years; exclude it and the only genuine precedent is 2015, which was a
retention cycle. MIN_PRIOR_YEARS is 10 for that reason and the page prints it.

THREE FRAMINGS, BECAUSE THEY DISAGREE AND THE DISAGREEMENT IS THE POINT:

  * calendar-month records -- what Ross noticed, and what USDA's own monthly
    comparison invites. Fragile: the August 2026 margin is 12,000 head and the
    largest revision on record is 20,000.
  * the 12-month rolling total -- seasonality-free and revision-proof. 2026 is
    the lowest of 359 windows; 2015 is 5th.
  * placements per 100 Jan-1 beef cows -- the one that separates "fewer cattle
    are being placed" from "there are fewer cattle". 2026 is mid-pack here
    while 2015 is 25th of 359, which is the single most useful number on the
    panel and the least likely to be reached for.
"""
from __future__ import annotations

import pandas as pd

# Bump when compare() changes the SHAPE of what it returns -- st.cache_data
# keys on the calling function and never on this module. Passed at the call
# site, because a default is not part of the key.
SCHEMA = 1

# See the module docstring. Ten admits 2015 and 2026 and excludes the 2001
# artefact; it is a judgement, which is why the panel states it rather than
# hiding it in here.
MIN_PRIOR_YEARS = 10

# A run shorter than this is not worth a headline -- single record months are
# ordinary (52 of 370 on the raw rule).
MIN_RUN = 2


def _ordered(placements: pd.DataFrame) -> pd.DataFrame:
    return placements.sort_values(["year", "month"]).reset_index(drop=True)


def flag_records(placements: pd.DataFrame,
                 min_prior: int = MIN_PRIOR_YEARS) -> pd.DataFrame:
    """`placements` plus a `record` column and `n_prior`.

    A record is judged AT THE TIME -- below every prior year's same month, not
    below the whole series including years that had not happened yet.
    """
    p = _ordered(placements)
    rec, prior_n = [], []
    for r in p.itertuples():
        prior = p[(p.month == r.month) & (p.year < r.year)]
        prior_n.append(len(prior))
        rec.append(len(prior) >= min_prior and r.Value < prior.Value.min())
    p["n_prior"] = prior_n
    p["record"] = rec
    return p


def runs(flagged: pd.DataFrame, min_run: int = MIN_RUN) -> list:
    """[{start, end, months, values}] for each consecutive stretch of records."""
    out, cur = [], []
    for r in flagged.itertuples():
        if r.record:
            cur.append(r)
        else:
            if len(cur) >= min_run:
                out.append(cur)
            cur = []
    if len(cur) >= min_run:
        out.append(cur)
    return [{"start": (c[0].year, c[0].month), "end": (c[-1].year, c[-1].month),
             "months": len(c), "values": [c_.Value for c_ in c]} for c in out]


def current_run(flagged: pd.DataFrame) -> int:
    """Records ending at the newest month. 0 if the newest month is not one."""
    n = 0
    for r in reversed(list(flagged.itertuples())):
        if not r.record:
            break
        n += 1
    return n


def run_standing(flagged: pd.DataFrame) -> dict:
    """Where the run ending at the newest month sits against every other run.

    THE RUN IN PROGRESS IS NOT ONE OF ITS OWN PRECEDENTS, which is the only
    subtle thing here: `runs()` returns it like any other, so counting runs of
    the longest length without excluding it reports the current run as having
    matched itself.

    `ties` is therefore how many EARLIER runs reached the same length --
    0 means outright, 1 means "matched once before".
    """
    rs = runs(flagged, min_run=1)
    cur = current_run(flagged)
    longest = max((r["months"] for r in rs), default=0)
    newest = (int(flagged.iloc[-1].year), int(flagged.iloc[-1].month)) if len(flagged) else None
    ties = sum(1 for r in rs
               if r["months"] == longest and not (cur and r["end"] == newest))
    return {"current": cur, "longest": longest, "ties": ties,
            "is_longest": bool(cur) and cur == longest}


def records_in_last(flagged: pd.DataFrame, window: int = 12) -> dict:
    """How many of the last `window` months were records, and the series best.

    This is the framing that survives a revision: one month losing its record
    moves the count by one rather than breaking a run in half.
    """
    f = flagged.copy()
    f["cnt"] = f.record.rolling(window).sum()
    done = f.dropna(subset=["cnt"])
    if done.empty:
        return {}
    now = int(done.cnt.iloc[-1])
    best = int(done.cnt.max())
    return {"window": window, "now": now, "best": best,
            "is_best": now >= best,
            "months": [(int(r.year), int(r.month))
                       for r in f.tail(window).itertuples() if r.record]}


def rolling_total(placements: pd.DataFrame, window: int = 12) -> dict:
    """The trailing `window`-month placement total, and where it ranks.

    Seasonality-free: every window contains each calendar month exactly once,
    so no adjustment and no month-conditioning is needed.
    """
    p = _ordered(placements)
    p["roll"] = p.Value.rolling(window).sum()
    r = p.dropna(subset=["roll"])
    if r.empty:
        return {}
    cur = r.iloc[-1]
    rank = int((r.roll < cur.roll).sum()) + 1
    return {"window": window, "total": float(cur.roll), "rank": rank,
            "of": len(r), "ends": (int(cur.year), int(cur.month)),
            "lowest": [(int(x.year), int(x.month), float(x.roll))
                       for _, x in r.nsmallest(5, "roll").iterrows()]}


def lowest_windows(placements: pd.DataFrame, beef_cows: pd.Series = None,
                   n: int = 10, window: int = 12) -> dict:
    """The `n` lowest rolling `window`-month placement totals, lowest first.

    WINDOWS OVERLAP, AND THAT IS THE THING TO KNOW BEFORE READING THIS AS A
    LEAGUE TABLE. The 12 months ending August and the 12 months ending
    September share eleven of their months, so ONE quiet stretch fills several
    rows -- on the series as it stands the ten lowest windows touch just three
    calendar years. That is not a fault in the ranking, it is what a rolling
    window is, but a reader who takes ten rows for ten episodes has been
    misled. `stretches` counts how many SEPARATE runs of consecutive
    month-ends the rows come from, so the page can say so out loud.

    `per100` rides along per row because the panel's whole point is that the
    total and the per-cow figure disagree; a window can be among the lowest
    totals on file and unremarkable per cow.
    """
    p = _ordered(placements)
    p["roll"] = p.Value.rolling(window).sum()
    r = p.dropna(subset=["roll"]).copy()
    if r.empty:
        return {"rows": [], "stretches": 0, "of": 0, "window": window}
    if beef_cows is not None:
        r["per100"] = r.roll / r.year.map(beef_cows) * 100
    rows = []
    for i, (_, x) in enumerate(r.nsmallest(n, "roll").iterrows(), 1):
        per = x.per100 if beef_cows is not None else None
        rows.append({"rank": i, "year": int(x.year), "month": int(x.month),
                     "total": float(x.roll),
                     "per100": None if per is None or pd.isna(per) else float(per)})
    ends = sorted(d["year"] * 12 + d["month"] for d in rows)
    stretches = 1 + sum(1 for a, b in zip(ends, ends[1:]) if b - a > 1)
    return {"rows": rows, "stretches": stretches, "of": len(r), "window": window}


def per_cow(placements: pd.DataFrame, beef_cows: pd.Series,
            window: int = 12) -> dict:
    """Trailing placements per 100 Jan-1 beef cows, and its rank.

    THE DISCRIMINATOR. A record-low placement total means one of two very
    different things -- fewer cattle are being placed, or there are fewer
    cattle. Dividing by the breeding herd separates them, and it is the only
    measure here on which 2026 and 2015 come apart.

    `beef_cows` is a year-indexed Series of Jan-1 head. It MUST be the SURVEY
    series: "CATTLE, COWS, BEEF - INVENTORY" also carries CENSUS rows, and the
    census years 1997, 2002 and 2017 come back at 1.4M, 1.2M and 4.0M against a
    true ~30M, which reads as a collapse and recovery that never happened.
    """
    p = _ordered(placements)
    p["roll"] = p.Value.rolling(window).sum()
    r = p.dropna(subset=["roll"]).copy()
    r["cows"] = r.year.map(beef_cows)
    r = r.dropna(subset=["cows"])
    if r.empty:
        return {}
    r["per100"] = r.roll / r.cows * 100
    cur = r.iloc[-1]
    rank = int((r.per100 < cur.per100).sum()) + 1
    return {"value": float(cur.per100), "rank": rank, "of": len(r),
            "ends": (int(cur.year), int(cur.month)),
            "by_year": {int(y): float(v) for y, v in
                        r.groupby("year").per100.last().items()}}


def heifer_share(heifers: pd.DataFrame, steers: pd.DataFrame) -> pd.DataFrame:
    """Heifers as a percent of heifers+steers on feed, quarterly.

    Against the ON-FEED total rather than reading a published share, so the
    denominator is explicit -- see the panel's caption about imported steers
    sitting in it.
    """
    m = heifers.merge(steers, on=["year", "month"], suffixes=("_h", "_s"))
    m["pct"] = m.Value_h / (m.Value_h + m.Value_s) * 100
    return m[["year", "month", "pct"]].sort_values(["year", "month"]).reset_index(drop=True)


def share_at(share: pd.DataFrame, year: int) -> dict:
    """That year's mean heifer share and its percentile in the whole series."""
    s = share[share.year == year].pct
    if s.empty:
        return {}
    v = float(s.mean())
    return {"pct": v, "percentile": float((share.pct < v).mean() * 100)}


def compare(placements: pd.DataFrame, beef_cows: pd.Series,
            share: pd.DataFrame, min_prior: int = MIN_PRIOR_YEARS) -> dict:
    """Everything the panel draws, from one pass over the series."""
    flagged = flag_records(placements, min_prior)
    roll = rolling_total(placements)
    rows = []
    for run in runs(flagged, min_run=3):
        y = run["end"][0]
        rows.append({
            "run": run,
            "year": y,
            "share": share_at(share, y),
            "cows_next": _chg(beef_cows, y, y + 1),
            "cows_then": _chg(beef_cows, y + 1, y + 2),
        })
    return {
        "flagged": flagged,
        "current_run": current_run(flagged),
        "standing": run_standing(flagged),
        "last12": records_in_last(flagged),
        "rolling": roll,
        "per_cow": per_cow(placements, beef_cows),
        "lowest_windows": lowest_windows(placements, beef_cows),
        "runs": rows,
        "min_prior": min_prior,
        "first_year": int(_ordered(placements).year.min()),
    }


def _chg(series: pd.Series, a: int, b: int):
    if a in series.index and b in series.index and series[a]:
        return float(series[b] / series[a] - 1) * 100
    return None
