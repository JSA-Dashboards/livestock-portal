"""
Build the Tuesday or Friday letter.

    python -m letter.build                      # today's Tuesday letter
    python -m letter.build --friday             # the Friday letter
    python -m letter.build --date 2026-09-22
    python -m letter.build --no-fetch           # re-render after editing commentary
    python -m letter.build --html-only          # skip the PDF step
    python -m letter.build --friday --cof-guess on_feed=101.8,placed=96.8,marketed=96.1

The two letters share the futures opening, the technicals and most of the
rundown. Friday drops the five-bullet weekly cash block, expands the rundown
with the completed week and both YTD rates, and adds regional cash, CFTC, and --
on the one Friday a month that follows a USDA release -- Cattle on Feed.

The normal cycle is two runs. The first fetches the data and writes
out/commentary_<date>.md with the figures quoted underneath each heading; you
write your read into that file; the second run picks it up and produces the PDF.
--no-fetch makes the second run instant and, more to the point, guarantees the
numbers in the PDF are the ones you were looking at while writing.

EVERY SOURCE IS ISOLATED. One agency being down degrades that section to a
marked [[?]] and the letter still builds -- there is no run in which a USDA
outage leaves you with nothing at 4pm. The exit code is non-zero when anything
is missing, so a scheduled run can tell "built, needs attention" from "clean".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

from . import (archive, cof, commentary, config, render, settle_log, sources,
               technicals, topdf)

# snowflake_db passes a raw DBAPI connection to pd.read_sql, which pandas
# warns about on every query. That is the shared module's choice, not this
# one's; silenced for this process rather than edited there.
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out"


# -- Secrets ------------------------------------------------------------------

def load_env() -> None:
    """
    Environment first, then .env, then .streamlit/secrets.toml.

    The dashboards read secrets through st.secrets, which does not exist here,
    so the same values are picked up from the file directly. Nothing is printed:
    these are credentials.
    """
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    secrets = REPO / ".streamlit" / "secrets.toml"
    if secrets.exists():
        try:
            import tomllib
            data = tomllib.loads(secrets.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        for k, v in data.items():
            if isinstance(v, (str, int, float)):
                os.environ.setdefault(k, str(v))

    # THE PASSPHRASE NAMING TRAP, bridged here rather than duplicated.
    #
    # CLAUDE.md records that the key passphrase lives ONLY in
    # SNOWFLAKE_PRIVATE_KEY_PASSPHRASE, and that the Python connector does not
    # read it -- snowflake_db._load_private_key() looks for
    # SNOWFLAKE_PRIVATE_KEY_PWD. Without this line the connection falls through
    # to password auth and dies on KeyError: 'SNOWFLAKE_PASSWORD', which names
    # neither the real cause nor the fix.
    #
    # Mapped in memory, never written to .env: the passphrase stays in the one
    # place it already lives.
    if not os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"):
        phrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        if phrase:
            os.environ["SNOWFLAKE_PRIVATE_KEY_PWD"] = phrase


def _try(label: str, fn, errors: list):
    """Run one fetch; record the failure and carry on rather than aborting."""
    try:
        return fn()
    except Exception as e:
        errors.append(f"{label}: {type(e).__name__}: {e}")
        if os.environ.get("LETTER_DEBUG"):
            traceback.print_exc()
        return None


# -- Assembly -----------------------------------------------------------------

def gather(issue: date, errors: list, kind: str = "tuesday", cof_guesses: dict = None) -> dict:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not api_key:
        errors.append("MASSIVE_API_KEY not set -- futures and technicals unavailable")

    ctx: dict = {
        "issue_date": issue,
        "kind": kind,
        "change_basis": config.CHANGE_BASIS,
        "live_cattle": [],
        "feeder_cattle": [],
        "tech_lc": None,
        "tech_fc": None,
        "cash": {},
        "cutout": {},
        "slaughter": {},
        "daily_slaughter": {},
        "carcass_weights": {},
        "fci": {},
        "douglas": {},
        "cftc": {},
        "regional_cash": {},
        "cof": {},
        "outside": [],
        "calendar": [],
        "regional_cash": {},
    }

    if api_key:
        # The morning brief must not read today's in-progress bar as a settle:
        # it goes out at 07:30, before CME livestock opens, and quotes the prior
        # session. The evening letter is written after the close and wants
        # today's. See sources.fetch_futures(completed_only=...).
        settled_only = (kind == "am")
        ctx["live_cattle"] = _try("live cattle futures", lambda: sources.fetch_futures(
            config.LIVE_CATTLE_CODE, api_key, issue, config.N_CONTRACTS,
            completed_only=settled_only), errors) or []
        ctx["feeder_cattle"] = _try("feeder cattle futures", lambda: sources.fetch_futures(
            config.FEEDER_CATTLE_CODE, api_key, issue, config.N_CONTRACTS,
            completed_only=settled_only), errors) or []

        # Technicals run on the front contract of each -- the one the letter names.
        if ctx["live_cattle"]:
            ctx["tech_lc"] = _try("live cattle technicals", lambda: technicals.build(
                ctx["live_cattle"][0]["ticker"], api_key, config.MA_WINDOWS), errors)
        if ctx["feeder_cattle"]:
            ctx["tech_fc"] = _try("feeder technicals", lambda: technicals.build(
                ctx["feeder_cattle"][0]["ticker"], api_key, config.MA_WINDOWS), errors)

    ctx["cash"] = _try("cash trade (LM_CT150/CT154)", sources.fetch_cash_trade, errors) or {}
    ctx["cutout"] = _try("boxed beef (LM_XB403/LSWFEDCC)", sources.fetch_cutout, errors) or {}
    ctx["slaughter"] = _try("weekly slaughter (SJ_LS712)", sources.fetch_slaughter, errors) or {}
    ctx["daily_slaughter"] = _try("daily slaughter (AMS 3208)",
                                  sources.fetch_daily_slaughter, errors) or {}
    ctx["carcass_weights"] = _try("carcass weights (AMS 3658)",
                                  sources.fetch_carcass_weights, errors) or {}
    if ctx["carcass_weights"].get("error"):
        errors.append(f"carcass weights (AMS 3658): {ctx['carcass_weights']['error']}")

    if config.INCLUDE_FEEDER_INDEX:
        ctx["fci"] = _try("feeder cattle index (Snowflake)", sources.fetch_feeder_index, errors) or {}
    ctx["douglas"] = _try("Douglas imports (Snowflake)",
                          lambda: sources.fetch_douglas_ytd(issue.year), errors) or {}

    if kind == "am":
        # The morning brief's own sources. Cattle futures do not open until
        # 08:30 CT, so grain and equities are the only real overnight signal.
        if api_key:
            ctx["outside"] = _try("outside markets", lambda: sources.fetch_outside_markets(
                api_key, issue), errors) or []
        ctx["calendar"] = _try("USDA release calendar",
                               lambda: sources.fetch_report_calendar(issue), errors) or []
        # WEEK TO DATE, not yesterday. AMS publishes its daily summary around
        # 11am so today's has not printed, and Monday is routinely untested --
        # a Tuesday brief built from Monday alone reads "no established test"
        # while the week has in fact traded.
        ctx["regional_cash"] = _try("cash week-to-date (AMS daily)",
                                    lambda: sources.fetch_regional_cash_wtd(issue), errors) or {}

    if kind == "friday":
        ctx["cftc"] = _try("CFTC managed money", sources.fetch_cftc, errors) or {}
        # Regional cash is a single trading day, and on a Friday letter that day
        # is the Friday itself -- the week's last established test.
        ctx["regional_cash"] = _try("regional cash (AMS daily)",
                                    lambda: sources.fetch_regional_cash(issue), errors) or {}
        ctx["cof"] = _try("Cattle on Feed", lambda: cof.fetch(issue, cof_guesses), errors) or {}
    return ctx


def backfill_week_base(ctx: dict, out_dir: Path, issue: date) -> list:
    """
    Recover the week-over-week change from the PREVIOUS letter when the futures
    history has no bar for the prior Friday.

    This is how Ross computes it by hand: the prior Friday's settles are printed
    in the Friday letter, and every build already stores them in
    out/data_<kind>_<date>.json. Chaining to that is exact -- it is the same
    number the client read last time -- where reaching back to an earlier
    session in a gapped series is merely plausible.

    Verified against 2026-09-22: the 9/18 file carries Oct Live Cattle at
    215.925, and 218.775 - 215.925 = +2.85, which is what the letter printed.

    Returns the contracts it fixed, for reporting.
    """
    prior_friday = issue - timedelta(days=(issue.weekday() - 4) % 7 or 7)

    # OUR OWN LOG FIRST. Every previous build recorded what it fetched, so once
    # a letter has been built on a Friday this needs nothing from Massive's
    # history -- which is the whole point, that history having had a week-long
    # hole since 2026-09-14.
    fixed = []
    logged = settle_log.settles_on(prior_friday)
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = logged.get(c.get("ticker"))
            if base is None:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"settle log ({base})"
            fixed.append(f"{c.get('month')} {base}")

    prior_ctx = None
    for kind in ("friday", "tuesday"):
        p = out_dir / f"data_{kind}_{prior_friday}.json"
        if p.exists():
            try:
                prior_ctx = json.loads(p.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                continue
    if not prior_ctx:
        return fixed

    for key in ("live_cattle", "feeder_cattle"):
        # ONLY trust a stored settle that really is the prior Friday's. A letter
        # rebuilt later, or built when the history already had the gap, carries a
        # settle_date from some other session -- using it would compute a change
        # against the wrong day and look perfectly reasonable doing it.
        was = {c.get("month"): c.get("settle") for c in (prior_ctx.get(key) or [])
               if str(c.get("settle_date", ""))[:10] == prior_friday.isoformat()}
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = was.get(c.get("month"))
            if base is None:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"data_{prior_friday} ({base})"
            fixed.append(f"{c.get('month')} {base}")
    return fixed


# -- Prior-Friday settles, entered by hand ------------------------------------
#
# The week-over-week change needs one number per contract: the prior Friday's
# settle. Normally that comes from the futures history, or failing that from the
# previous letter's stored settles (backfill_week_base above). When neither is
# available -- Massive's history has had no bars for 2026-09-14..09-18 for over
# a week -- these let you type the six numbers off your own last letter rather
# than lose the whole block.
#
# KEYED BY TICKER, NOT MONTH. "Oct" is both LEV6 and GFV6; keying by month would
# quietly apply the Live Cattle base to the Feeder contract.


def prior_friday_of(issue: date) -> date:
    """The Friday the week-over-week change measures from."""
    return issue - timedelta(days=(issue.weekday() - 4) % 7 or 7)


def week_base_path(out_dir, issue, day: str = None) -> Path:
    """
    Keyed by the PRIOR FRIDAY, not by the letter.

    That Friday's settle is a property of the week: Monday's letter and
    Thursday's letter both measure from it. Keying by day meant typing the same
    six numbers again on every letter of the week. `day` is accepted and ignored
    so existing callers keep working.
    """
    return Path(out_dir) / f"weekbase_{prior_friday_of(issue)}.json"


def load_week_base(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def save_week_base(path: Path, bases: dict) -> None:
    clean = {k: float(v) for k, v in (bases or {}).items() if v}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(clean, indent=2), encoding="utf-8")


def apply_week_base(ctx: dict, bases: dict) -> list:
    """
    Fill missing weekly changes from hand-entered prior-Friday settles.

    Only touches contracts that are actually missing a base, so a real bar or a
    chained value always wins over a typed one. Returns what it filled.
    """
    if not bases:
        return []
    fixed = []
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            if not c.get("week_base_missing"):
                continue
            base = bases.get(c.get("ticker"))
            if not base:
                continue
            c["change_week"] = round(float(c["settle"]) - float(base), 4)
            c["week_base_missing"] = False
            c["week_base_source"] = f"entered by hand ({base})"
            fixed.append(f"{c.get('month')} {base}")
    return fixed


def missing_week_bases(ctx: dict) -> list:
    """(ticker, label) for every contract still without a prior-Friday settle."""
    out = []
    for key, product in (("live_cattle", "Live Cattle"), ("feeder_cattle", "Feeder Cattle")):
        for c in ctx.get(key) or []:
            if c.get("week_base_missing"):
                out.append((c["ticker"], f"{product} {c.get('month')}"))
    return out


def hints(ctx: dict, kind: str = "tuesday") -> dict:
    """
    What to quote under each commentary heading in the editable file.

    These are the figures you would otherwise be flipping between dashboards to
    read while writing the market read.
    """
    out: dict = {key: [] for key, _ in commentary.sections_for(kind)}
    keys = set(out)

    # Derived from the format's OWN sections rather than hardcoded, so a format
    # that lacks them cannot KeyError. The AM report has only a Morning Note,
    # and assuming "market_action" existed killed the build before it wrote
    # anything -- after a full fetch, which is the expensive half.
    lead = next((k for k in ("morning_note", "key_headlines", "market_action") if k in keys), None)
    tail = next((k for k in ("cash_recap", "fundamental", "morning_note") if k in keys), None)

    def add(slot, text):
        """Append only to a slot this format actually has."""
        if slot in keys:
            out[slot].append(text)

    basis = "week to date" if ctx["change_basis"] == "week" else "session"
    key = "change_week" if ctx["change_basis"] == "week" else "change_day"
    for label, rows in (("Live Cattle", ctx["live_cattle"]), ("Feeders", ctx["feeder_cattle"])):
        for r in rows:
            add(lead, f"{label} {r['month']}: {r.get(key)} ({basis}) at {r.get('settle')}")

    # Through add() as well: the AM format has no technicals sections at all.
    for slot, tech, label in (("technicals_lc", ctx.get("tech_lc"), "Live Cattle"),
                              ("technicals_fc", ctx.get("tech_fc"), "Feeders")):
        if not tech or tech.get("error"):
            add(slot, f"{label}: no bars available")
            continue
        ma = tech.get("ma", {})
        add(slot, f"{tech.get('month','')} {label} close {tech.get('last_close')}"
                  f" on {tech.get('last_date')}")
        for w in config.MA_WINDOWS:
            add(slot, f"{w}-day MA {ma.get(w)}  (printed automatically)")
        add(slot, f"prior session high/low {tech.get('prior_high')} / {tech.get('prior_low')}")
        add(slot, f"{tech.get('swing_days')}-day swing high/low "
                  f"{tech.get('swing_high')} / {tech.get('swing_low')}")
        add(slot, "support/resistance below are YOUR call -- nothing is printed unless you write it")

    # Figures SJ_LS712 does publish but the Tuesday letter does not print. They
    # are quoted here because they are the completed-week context you would
    # otherwise open the Cattle Weights dashboard to read.
    sl = ctx.get("slaughter") or {}
    wk = sl.get("weekly") or {}
    if wk.get("value") is not None:
        add(tail, 
            f"week ending {wk.get('week_ending')}: {wk['value']:,.0f} head "
            f"vs {wk.get('last_week'):,.0f} LW and {wk.get('year_ago'):,.0f} LY"
            if wk.get("last_week") and wk.get("year_ago")
            else f"week ending {wk.get('week_ending')}: {wk['value']:,.0f} head")
    if wk.get("ytd_chg_pct") is not None:
        add(tail, f"YTD slaughter {wk['ytd_chg_pct']}% YoY")
    bp = sl.get("beef_production") or {}
    if bp.get("ytd_chg_pct") is not None:
        add(tail, f"YTD beef production {bp['ytd_chg_pct']}% YoY")

    if kind == "friday":
        rc = (ctx.get("regional_cash") or {}).get("regions") or {}
        for name, r in rc.items():
            if r.get("undefined"):
                add(tail, f"{name}: no adequate market test (prints as Undefined)")
            else:
                add(tail, 
                    f"{name}: live {r.get('live_low')}-{r.get('live_high')}, "
                    f"dressed {r.get('dressed_low')}-{r.get('dressed_high')}, {r.get('head')} hd")
        cf = ctx.get("cof") or {}
        if cf.get("include"):
            add("cof_note", 
                f"actual {cf.get('actual')} | guesses {cf.get('guesses') or 'none entered'} "
                f"| year-ago {cf.get('year_ago')}")

    d = ctx.get("douglas") or {}
    if d.get("head") is not None:
        add(tail, f"YTD Douglas feeder imports {d['head']:,} head ({d.get('year')})")
    cash = (ctx.get("cash") or {}).get("live", {})
    if cash.get("this_week") is not None and cash.get("last_week") is not None:
        add(tail, 
            f"live cash {cash['this_week']} vs {cash['last_week']} "
            f"({cash['this_week'] - cash['last_week']:+.2f} week on week)")
    return out


def _jsonable(o):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the Tuesday or Friday cattle letter.")
    ap.add_argument("--date", help="issue date, YYYY-MM-DD (default: today)")
    ap.add_argument("--no-fetch", action="store_true",
                    help="re-render from the last fetch -- use after editing commentary")
    ap.add_argument("--html-only", action="store_true", help="skip the PDF step")
    ap.add_argument("--archive", action="store_true",
                    help="copy this letter into the private archive repo, commit and "
                         "push. Use it for the letter you actually sent, not a draft.")
    ap.add_argument("--out", default=str(OUT), help="output directory")
    ap.add_argument("--session", choices=[x.lower() for x in config.SESSIONS],
                    default=config.DEFAULT_SESSION.lower(),
                    help="which of the day's two reports (default: pm)")
    ap.add_argument("--day", choices=[d.lower() for d in config.DAYS], default=None,
                    help="which weekday's letter (default: today, or Monday at a weekend). "
                         "Friday uses the week-in-review format; every other day uses "
                         "the standard one.")
    ap.add_argument("--kind", choices=["tuesday", "friday"], default=None,
                    help=argparse.SUPPRESS)   # kept so older commands still run
    ap.add_argument("--friday", action="store_true", help="shorthand for --day friday")
    ap.add_argument("--week-base", default="",
                    help="prior-Friday settles when the futures history has a hole, "
                         "e.g. LEV6=215.925,GFV6=323.50. Keyed by ticker; persists "
                         "to out/weekbase_<kind>_<date>.json for later re-renders.")
    ap.add_argument("--cof-guess", default="",
                    help="analyst pre-report estimates for the Cattle on Feed table, "
                         "e.g. on_feed=101.8,placed=96.8,marketed=96.1. USDA does not "
                         "publish these and nothing can derive them.")
    args = ap.parse_args(argv)

    # The issue date has to be resolved FIRST: with no --day, the weekday is
    # derived from it.
    issue = date.fromisoformat(args.date) if args.date else date.today()

    # day = what you picked; fmt = which of the two layouts it produces.
    if args.friday:
        day = "friday"
    elif args.day:
        day = args.day
    elif args.kind:
        day = args.kind          # legacy --kind tuesday|friday
    else:
        day = config.day_for_date(issue)
    fmt = config.format_for(day, args.session)
    kind = fmt                   # render/commentary still switch on the format
    session = args.session
    # AM and PM are separate letters on the same day, so every artefact is
    # keyed by both -- a shared name would have the morning letter overwrite
    # the evening one and neither would say so.
    slug = f"{session}_{day}"

    week_base_cli = {}
    for pair in args.week_base.split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            try:
                week_base_cli[k.strip().upper()] = float(v)
            except ValueError:
                pass

    cof_guesses = {}
    for pair in args.cof_guess.split(","):
        if "=" in pair:
            k, _, v = pair.partition("=")
            try:
                cof_guesses[k.strip()] = float(v)
            except ValueError:
                pass

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    data_path = out_dir / f"data_{slug}_{issue}.json"

    load_env()
    errors: list = []

    if args.no_fetch:
        if not data_path.exists():
            print(f"no saved data at {data_path} -- run once without --no-fetch first")
            return 2
        ctx = json.loads(data_path.read_text(encoding="utf-8"))
        ctx["issue_date"] = issue
        ctx["kind"] = kind
        ctx["session"] = session
        print(f"reusing {data_path.name}")
    else:
        print(f"fetching {session.upper()} {day} letter for {issue} ({fmt} format) ...")
        ctx = gather(issue, errors, kind, cof_guesses)
        ctx["session"] = session
        # Chain to the previous letter before caching, so the recovered change
        # is what --no-fetch re-renders from too.
        settle_log.record(ctx)
        recovered = backfill_week_base(ctx, out_dir, issue)
        if recovered:
            print(f"  recovered the weekly change from the previous letter: {', '.join(recovered)}")
        data_path.write_text(json.dumps(ctx, indent=2, default=_jsonable), encoding="utf-8")
        print(f"wrote {data_path.name}")

    # Hand-entered prior-Friday settles: merge anything new from the CLI into
    # the saved file, then apply. Applied on BOTH paths so a --no-fetch
    # re-render keeps the correction.
    wb_path = week_base_path(out_dir, issue, day)
    week_base = load_week_base(wb_path)
    if week_base_cli:
        week_base.update(week_base_cli)
        save_week_base(wb_path, week_base)
    filled = apply_week_base(ctx, week_base)
    if filled:
        print(f"  weekly change from entered prior-Friday settles: {', '.join(filled)}")

    # The commentary file is created once and never overwritten -- it holds your draft.
    cpath = commentary.path_for(out_dir, issue, slug)
    existed = cpath.exists()
    commentary.write_template(cpath, hints(ctx, kind), kind)
    ctx["commentary"] = commentary.read(cpath, kind)

    html = render.build_html(ctx)
    html_path = out_dir / f"{config.title_for(session)} {day.title()} {issue}.html"
    html_path.write_text(html, encoding="utf-8")

    pdf_msg = ""
    pdf_path = None
    if not args.html_only:
        pdf_path = out_dir / f"{config.title_for(session)} {day.title()} {issue}.pdf"
        ok, msg = topdf.html_to_pdf(html_path, pdf_path)
        pdf_msg = f"PDF: {msg}" if ok else f"PDF NOT written -- {msg}"
        if not ok:
            pdf_path = None

    # -- Archive, only when asked ------------------------------------------
    # OPT-IN, because "published" means Ross sent it and only he knows when.
    # Archiving every build would commit a dozen drafts a day and bury the one
    # that went out. See letter/archive.py.
    archive_msg = ""
    if getattr(args, "archive", False):
        result = archive.publish(issue, session, html_path, pdf_path,
                                 kind=kind, title=config.title_for(session))
        if not result["ok"]:
            archive_msg = f"ARCHIVE FAILED -- {result['reason']}"
        elif not result["changed"]:
            archive_msg = "Archive: already held this letter, unchanged."
        else:
            where = "pushed" if result["pushed"] else "committed locally"
            archive_msg = f"Archive: {len(result['files'])} file(s) {where}."
            if result["reason"]:
                archive_msg += f" {result['reason']}"

    # -- Report -------------------------------------------------------------
    missing = html.count(render.MISSING)
    print()
    print(f"HTML: {html_path}")
    if pdf_msg:
        print(pdf_msg)
    if archive_msg:
        print(archive_msg)
    if not existed:
        print(f"\nCommentary file created: {cpath}")
        titles = " / ".join(t for _, t in commentary.sections_for(kind))
        print(f"  Write your {titles} into it,")
        print("  then re-run with --no-fetch to render the final letter.")
    elif commentary.is_empty(ctx["commentary"]):
        print(f"\nCommentary file is still empty: {cpath}")

    if missing:
        print(f"\n{missing} value(s) could not be filled and are marked [[?]] in the letter.")
    for e in errors:
        print(f"  ! {e}")

    inferred = (ctx.get("calendar") or {}).get("inferred") or []
    if inferred:
        print(f"\n  ! WASDE dates are INFERRED from Crop Production's release slot: "
              f"{', '.join(inferred)}.")
        print("    ESMIS returns no upcoming_releases for WASDE. The paired date is right")
        print("    when it appears, but WASDE months with no Crop Production (roughly")
        print("    Dec-Apr) will not show at all.")

    ds = ctx.get("daily_slaughter") or {}
    if ds.get("status") and ds["status"].lower() != "final":
        print(f"\n  ! AMS 3208 is a {ds['status'].upper()} print for {ds.get('report_date')}.")
        print("    The daily and WTD figures will be revised -- re-run for the final.")

    cw = ctx.get("carcass_weights") or {}
    if cw.get("week_ending"):
        print(f"\n  Carcass weights are for the week ending {cw['week_ending']} "
              "(AMS 3658, published Thursdays, ~12 days in arrears).")

    if kind == "friday":
        cftc = ctx.get("cftc") or {}
        if cftc.get("as_of") and not sources.cftc_is_current(cftc, issue):
            print(f"\n  ! CFTC data is as of {cftc['as_of']}, which is NOT this week's Tuesday.")
            print("    CFTC releases Friday 3:30pm ET. Built before then, you get last week's")
            print("    positions with no error. Re-run after 3:30pm ET.")
        cf = ctx.get("cof") or {}
        if cf.get("include"):
            print(f"\n  COF block INCLUDED ({cf.get('title')}, "
                  f"released {cf.get('release_date')}).")
            if not cf.get("guesses"):
                print("    No analyst guesses given -- that column prints as dashes.")
                print("    Pass --cof-guess on_feed=...,placed=...,marketed=... to fill it.")
            print("    NOTE On-Feed and Year-Ago are COMPUTED (100.7 / 98.9 for Sept 2026),")
            print("    not the old Excel sheet's 100.8 / 99. See letter/cof.py.")
        elif cf.get("reason"):
            print(f"\n  COF block omitted: {cf['reason']}")

    # THE 3PM CENTRAL TRAP. LM_XB403 PM publishes around 3pm Central. A letter
    # written before that gets the PREVIOUS session's cutout, with no error --
    # which is why the 9/22 letter's Choice and Select had to be typed by hand.
    cut_date = (ctx.get("cutout") or {}).get("report_date")
    if cut_date and date.fromisoformat(cut_date) < issue:
        print(f"\n  ! Boxed beef is the {cut_date} print, not {issue}'s.")
        print("    LM_XB403 PM releases about 3pm Central. Re-run after that for today's")
        print(f"    cutout; until then the letter correctly labels it as the {cut_date} PM print.")

    # A gapped futures history corrupts the weekly change and the moving
    # averages together, and both look plausible while being wrong.
    fut_gaps, no_base = set(), []
    for label, rows in (("Live Cattle", ctx.get("live_cattle") or []),
                        ("Feeders", ctx.get("feeder_cattle") or [])):
        for r in rows:
            fut_gaps.update(r.get("gaps") or [])
            if r.get("week_base_missing"):
                no_base.append(f"{label} {r.get('month')}")
    for tech in (ctx.get("tech_lc"), ctx.get("tech_fc")):
        if tech:
            fut_gaps.update(tech.get("gaps") or [])
    if no_base:
        print(f"\n  ! No settle on the prior Friday for: {', '.join(no_base)}.")
        print("    The week-over-week change is marked rather than measured from an")
        print("    earlier session, which would print a plausible wrong number.")
    if fut_gaps:
        shown = ", ".join(sorted(fut_gaps)[:8])
        print(f"\n  ! Futures history is missing sessions: {shown}")
        print("    Moving averages over a gapped series are wrong, not approximate, so")
        print("    they are marked too. This is upstream data, not a fetch failure.")

    # Several AMS endpoints serve the LATEST report and take no date filter, so
    # a back-dated rebuild quietly picks up today's numbers rather than the
    # issue's. Harmless on the day; wrong afterwards, and silent either way.
    stale = []
    for label, rd in (("boxed beef", (ctx.get("cutout") or {}).get("report_date")),
                      ("daily slaughter", (ctx.get("daily_slaughter") or {}).get("report_date")),
                      ("cash trade", (ctx.get("cash") or {}).get("report_date"))):
        if rd and abs((date.fromisoformat(rd) - issue).days) > 3:
            stale.append(f"{label} is from {rd}")
    if stale:
        print(f"\n  ! Built for {issue}, but " + "; ".join(stale) + ".")
        print("    These AMS endpoints always serve the newest report and take no date")
        print("    filter, so a back-dated build does not reconstruct that day.")

    if not os.environ.get("USE_SNOWFLAKE"):
        print("\n  ! USE_SNOWFLAKE is not set, so the feeder index and Douglas imports came")
        print("    from the committed SQLite file, which is stale. Set USE_SNOWFLAKE=1 and")
        print("    the Snowflake credentials for the live values.")

    fci = ctx.get("fci") or {}
    if config.INCLUDE_FEEDER_INDEX and fci.get("value") is not None:
        print(f"\n  Feeder index {fci['value']} is JSA's own estimate for {fci.get('date')} "
              "(fci_daily), not CME's published value.")
        if fci.get("cme_last_published"):
            print(f"    Headline date follows CME's publication clock; their last file is "
                  f"{fci['cme_last_published']}. If that stops advancing, suspect the CME")
            print("    ingest rather than this letter.")

    return 1 if (missing or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
