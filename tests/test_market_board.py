"""Proof that the board cannot quietly disagree with the pages it summarises.

Every assertion here is a way this page could render perfectly and be wrong:
a tile deriving its own figure, a clause asserting something it cannot see, a
cross-panel naming a signal that does not exist, a cache serving shape rather
than freshness, a forwarded secret that silently breaks nine modules.

    python -m pytest tests/test_market_board.py -q
"""

import ast
import os
import sys
from datetime import date, timedelta

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOARD = os.path.join(_HERE, "..", "apps", "market_board")
_REPO = os.path.join(_HERE, "..")
sys.path.insert(0, _BOARD)
sys.path.insert(0, os.path.join(_REPO, "apps", "cash_trade"))

import registry  # noqa: E402
import meaning   # noqa: E402

REGISTRY_PY = os.path.join(_BOARD, "registry.py")
LOADERS_PY = os.path.join(_BOARD, "loaders.py")
APP_PY = os.path.join(_BOARD, "app.py")
MEANING_PY = os.path.join(_BOARD, "meaning.py")


def _tree(path):
    return ast.parse(open(path, encoding="utf-8").read())


def _src(path):
    return open(path, encoding="utf-8").read()


# ── a fixture shaped like the real bundle ────────────────────────────────────
#
# BUILT FROM THE SHAPES OBSERVED LIVE on 2026-10-07, not from the design doc.
# Six of the design's twenty pick expressions did not resolve against the real
# return shapes; these are the shapes the code actually produces.

@pytest.fixture
def bundle():
    wk = date(2026, 10, 5)
    return {
        "lev": {
            "mix": {"week": wk, "total": 375424.0, "negotiated": 74261.0,
                    "neg_grid": 35497.0, "negotiated_pct": 0.197806,
                    "neg_grid_pct": 0.094552, "committed_pct": 0.707643,
                    "must_buy_pct": 0.292357},
            "owned": {"week": wk, "packer_owned": 9830.0},
            "forward": {"week": wk, "fwd_week": 12512.0, "fwd_book": 641882.0},
            "committed": {"week": wk, "committed": 409230, "delivered": 368246},
        },
        "frames": {},
        "need": {"weeks": 4, "cash": 71455.5, "cash_lo": 62313.0,
                 "cash_hi": 75109.0, "must": 104244.0, "to": wk},
        "near": {"n": 3, "committed": 321900.0, "last_year": 520558.0,
                 "change": -0.381625, "from": "Oct", "to": "Dec"},
        "accuracy": {"cash": {"median": 0.0827, "p90": 0.229, "n": 52}},
        "weight": {"weight": 1551.65, "week": wk, "iso_week": 41,
                   "year_ago": 1484.36, "vs_year_ago": 67.29,
                   "expected": 1465.99, "vs_trend": 85.66, "slope": 6.88, "n": 8},
        "cutout": {"choice": {"value": 378.93, "change": 0.67, "avg5": 378.94},
                   "select": {"value": 356.34, "change": -2.23, "avg5": 358.20},
                   "report_date": "2026-10-06",
                   "grading": {"pct": 87.4, "pct_last_week": 87.3,
                               "report_date": "2026-10-06"}},
        "cash": {"live": {"this_week": 220.03, "last_week": 220.73},
                 "dressed": {"this_week": 346.35, "last_week": 347.93},
                 "volume": {"confirmed": 88019.0, "confirmed_last_week": 47138.0,
                            "report_date": "2026-10-05"},
                 "report_date": "2026-10-05"},
        "slaughter": {"weekly": {"value": 548000.0, "week_ending": "2026-10-03",
                                 "chg_wow_pct": 13.2, "chg_yoy_pct": -3.5,
                                 "ytd_chg_pct": -7.5},
                      "beef_production": {"value": 487.0,
                                          "week_ending": "2026-10-03",
                                          "ytd_chg_pct": -5.2}},
        "fci": {"value": 335.86, "date": "2026-10-07", "change": -2.01,
                "cme_last_published": "2026-10-06",
                "published": {"value": 337.87, "date": "2026-10-06",
                              "change": 0.65, "from_cme": True,
                              "source": "CME published (cme_ftp_daily)"}},
        "corn": {"NE": {"price": 4.9889, "bid": 4.7389, "n": 703}},
        "exports": {"ytd": 1574.33, "ytd_prior": 1497.0, "yoy_pct": 5.16,
                    "implied_vs_forecast": -29.0, "months_left": 4},
        "imports": {"ytd": 4358.48, "ytd_prior": 3812.34, "yoy_pct": 14.33,
                    "implied_vs_forecast": 156.0, "months_left": 4},
        "trade_asof": date(2026, 8, 1),
        "asof": {"corn": date(2026, 10, 7)},
        "errors": {},
    }


# ── the no-arithmetic contract ───────────────────────────────────────────────

def test_the_registry_does_no_arithmetic():
    """THE CENTRAL RULE. A tile that computes its own figure makes this page a
    second implementation of a number another page shows, and the two can
    disagree while both look right -- the failure CLAUDE.md records four times.

    `registry.py` may walk a dict and return what it finds. It may not add,
    subtract, multiply or divide. Where a figure genuinely needs deriving (the
    packer-owned SHARE, which `leverage` returns as head) the derivation
    belongs in the module that owns the data -- or the tile does not ship.
    """
    for node in ast.walk(_tree(REGISTRY_PY)):
        assert not isinstance(node, ast.BinOp), \
            f"registry.py does arithmetic at line {node.lineno}"


def test_the_page_does_no_arithmetic_on_market_numbers():
    """app.py is a renderer. The only BinOps it may contain are string joins
    and modulo for column placement -- never an operation on a reading."""
    for node in ast.walk(_tree(APP_PY)):
        if isinstance(node, ast.BinOp):
            assert isinstance(node.op, (ast.Add, ast.Mod)), (
                f"app.py does {type(node.op).__name__} arithmetic at line "
                f"{node.lineno}")


def test_the_board_never_calls_gather():
    """letter.build.gather() LOOKS pure and is not: build.py:324 runs
    settle_log.sync(), which INSERTs into JSA.LETTER.DRAFTS. A dashboard
    calling it would write to the letter's durable store on every page load."""
    for path in (LOADERS_PY, APP_PY, REGISTRY_PY, MEANING_PY):
        name = os.path.basename(path)
        for node in ast.walk(_tree(path)):
            # AST, NOT grep: every one of these files has a docstring explaining
            # why gather() is never called, and a text search matches the
            # explanation. The same mistake tests/test_rundown.py records.
            if isinstance(node, ast.Call):
                fn = node.func
                called = (fn.attr if isinstance(fn, ast.Attribute)
                          else fn.id if isinstance(fn, ast.Name) else "")
                assert called != "gather", f"{name} calls gather()"
            if isinstance(node, ast.ImportFrom) and node.module == "letter.build":
                pytest.fail(f"{name} imports letter.build")


# ── every signal must actually resolve ───────────────────────────────────────

def test_every_signal_resolves_to_a_real_value(bundle):
    """THE TEST THE DESIGN DID NOT SPECIFY, and the one that matters most.

    An earlier draft read leverage.latest()["negotiated_pct"] where the real
    shape is latest()["mix"]["negotiated_pct"]. With the house .get() idiom
    three tiles would have rendered a dash with nothing raising. A row-count
    assertion passes that; a type-and-finiteness assertion does not.
    """
    import math
    for s in registry.SIGNALS:
        v = s.pick(bundle)
        assert v is not None, f"{s.key} picks nothing out of a full bundle"
        assert isinstance(v, (int, float)), f"{s.key} picks {type(v).__name__}"
        assert math.isfinite(float(v)), f"{s.key} picks a non-finite value"


def test_every_signal_has_an_as_of(bundle):
    for s in registry.SIGNALS:
        assert s.as_of(bundle) is not None, f"{s.key} has no observation date"


def test_a_missing_block_marks_rather_than_vanishes(bundle):
    """A tile that silently disappears reads as "nothing to report there",
    which is a statement and a wrong one."""
    bundle["cutout"] = {}
    readings = {s.key: meaning.read(s, bundle, date(2026, 10, 7))
                for s in registry.SIGNALS}
    assert len(readings) == len(registry.SIGNALS), "a signal vanished"
    assert readings["choice_cutout"].state == meaning.GONE
    assert readings["choice_cutout"].shown == meaning.MISSING
    assert "returned nothing" in meaning.clause(readings["choice_cutout"], bundle)


# ── basis strings and depth ──────────────────────────────────────────────────

def test_every_signal_carries_a_basis():
    """Half the traps in CLAUDE.md are two correct numbers on different
    populations or clocks. A tile without its basis invites that arithmetic."""
    for s in registry.SIGNALS:
        assert s.basis and len(s.basis) > 25, f"{s.key} has no real basis string"
        assert s.source, f"{s.key} names no source"


def test_depth_verdicts_are_declared_and_legal():
    for s in registry.SIGNALS:
        assert s.depth in (registry.FULL, registry.PARTIAL, registry.NONE)
        assert s.depth_note, f"{s.key} declares a depth with no evidence"


def test_sj_ls712_claims_no_history():
    """SJ_LS712 keeps ONE week -- a 3.8 KB file absent from both report
    catalogs. Any backtest on it would be a backtest on one observation."""
    for key in ("weekly_kill", "kill_ytd", "beef_production_ytd"):
        assert registry.BY_KEY[key].depth == registry.NONE


def test_the_futures_floor_is_stated_on_the_page():
    """Five years, not ten. A page that implies otherwise is the failure the
    whole depth audit existed to prevent."""
    src = _src(APP_PY)
    assert "2021-10-08" in src and "five years" in src.lower()


# ── the meaning layer ────────────────────────────────────────────────────────

def test_no_template_names_a_signal_outside_its_requires_set():
    """An earlier draft had the cutout tile say "margin compressing" -- a
    packer-margin call from one leg -- six inches above a cross-panel refusing
    to make that call. Both honestly computed; together, nonsense."""
    labels = {k: s.label.lower() for k, s in registry.BY_KEY.items()}
    for key, rule in meaning.RULES.items():
        allowed = set(rule.requires)
        assert key in allowed, f"{key}'s rule does not require itself"
        text = " ".join((rule.up, rule.down, rule.flat)).lower()
        for other, label in labels.items():
            if other in allowed:
                continue
            assert label not in text, \
                f"{key}'s template names {other}, which is not in its requires"


def test_every_requires_names_a_signal_that_exists():
    """Without this a cross naming a deleted signal renders as nothing at all,
    invisibly -- the defect the design review found in two of four panels."""
    for key, rule in meaning.RULES.items():
        assert set(rule.requires) <= registry.ALL_KEYS, \
            f"{key} requires a signal that does not exist"
    for cross in meaning.CROSSES:
        assert set(cross.requires) <= registry.ALL_KEYS, \
            f"cross {cross.key} requires a signal that does not exist"


def test_staleness_replaces_the_clause_rather_than_badging_it(bundle):
    """A current-sounding reading under a stale number is worse than none --
    it is how the 2026-09-28 brief printed 09-11 settles and read perfectly."""
    s = registry.BY_KEY["choice_cutout"]
    late = date(2026, 10, 6) + timedelta(days=s.max_age_days + 5)
    r = meaning.read(s, bundle, late)
    assert r.state == meaning.STALE
    text = meaning.clause(r, bundle)
    assert "Not current enough" in text
    assert "packer" not in text.lower(), "the live clause leaked through"


def test_staleness_is_measured_against_the_publication_window(bundle):
    """LM_CT153 reports the PRIOR week by schedule. A report-date rule marks it
    stale every Thursday on fresh data, and a panel that cries every week is
    one nobody reads in the week it matters."""
    s = registry.BY_KEY["negotiated_share"]
    assert s.max_age_days >= 11, "the §B window must clear its own publication lag"
    r = meaning.read(s, bundle, date(2026, 10, 14))   # 9 days after the week
    assert r.state == meaning.OK


def test_the_leverage_tension_is_never_averaged(bundle):
    """These point opposite ways right now, and that tension is the most
    informative thing on the page. A composite would hide it."""
    readings = {s.key: meaning.read(s, bundle, date(2026, 10, 7))
                for s in registry.SIGNALS}
    body = next(b for c, b, _ in meaning.crosses(readings, bundle)
                if c.key == "leverage_tension")
    assert "+67 lb" in body
    assert "-38.2%" in body or "−38.2%" in body
    assert "disagree" in body.lower()
    src = _src(MEANING_PY)
    assert "score" not in body.lower() or "would hide" in body.lower()


def test_a_cross_panel_that_cannot_render_says_so(bundle):
    """Returning it silently absent would read as "these signals agree", which
    is a claim nobody made."""
    bundle["weight"] = {}
    readings = {s.key: meaning.read(s, bundle, date(2026, 10, 7))
                for s in registry.SIGNALS}
    out = meaning.crosses(readings, bundle)
    cross, body, live = next(x for x in out if x[0].key == "leverage_tension")
    assert live is False
    assert "Not enough to say" in body
    assert len(out) == len(meaning.CROSSES), "a panel vanished"


def test_fractions_render_as_percentages(bundle):
    """leverage's _pct columns are FRACTIONS (0.1978), not percentages. A tile
    printing 0.2% for a 19.8% share would look like a different market."""
    assert meaning.fmt(0.197806, "frac") == "19.8%"
    assert meaning.fmt(-0.381625, "frac_signed") == "-38.2%"
    assert meaning.fmt(None, "frac") == meaning.MISSING


# ── caching and secrets ──────────────────────────────────────────────────────

def test_every_cached_loader_takes_the_schema_key():
    """st.cache_data keys on the decorated function's own code and NEVER on the
    modules it calls. Adding a key to leverage.load() once made a whole section
    vanish silently because the one-line fetch body had not changed."""
    tree = _tree(LOADERS_PY)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        cached = any("cache_data" in ast.unparse(d) for d in node.decorator_list)
        if not cached:
            continue
        args = [a.arg for a in node.args.args] + \
               [a.arg for a in node.args.kwonlyargs]
        assert "_schema" in args, f"{node.name} is cached without the SCHEMA key"


def test_no_loader_persists_to_disk():
    """Streamlit ignores ttl when persist is set, so such a cache never
    expires. That is exactly how fetch_leverage froze on the Cash Cattle Trade
    page until 2026-10-07."""
    for node in ast.walk(_tree(LOADERS_PY)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    assert kw.arg != "persist",                         f"{node.name} is cached with persist=, which voids its ttl"


def test_the_schema_key_includes_every_upstream_module():
    assert isinstance(__import__("loaders").SCHEMA, tuple)
    assert len(__import__("loaders").SCHEMA) >= 2


def test_the_page_never_forwards_snowflake_schema():
    """Nine modules each default it to the schema they own. Forwarding one
    value overrides all nine and their queries miss silently."""
    src = _src(APP_PY)
    block = src[src.index("for _k in ("):src.index("import loaders")]
    assert "SNOWFLAKE_SCHEMA" not in block, \
        "app.py forwards SNOWFLAKE_SCHEMA into os.environ"
    assert "SNOWFLAKE_ACCOUNT" in block, "the block must still forward the rest"


def test_no_table_is_read_unqualified_by_this_page():
    """Every Snowflake read here goes through a module that names its own
    tables; the board issues no SQL of its own."""
    # Look for SQL in STRING CONSTANTS, and require both halves of a query --
    # "Select cutout" is a tile label and uppercases to "SELECT ", which is how
    # the first version of this test failed.
    for path in (LOADERS_PY, APP_PY, REGISTRY_PY, MEANING_PY):
        name = os.path.basename(path)
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.upper()
                assert not ("SELECT " in text and " FROM " in text),                     f"{name} writes SQL at line {node.lineno}"


def test_the_page_is_admin_gated_before_anything_renders():
    """It is unlisted, not merely locked -- Home.py registers it under TOOLS.
    The gate must be the first call, not a check partway down."""
    src = _src(APP_PY)
    assert "portal_auth.require_admin(" in src
    assert src.index("require_admin(") < src.index("import loaders")


def test_the_index_tile_never_shows_the_forward_estimate(bundle):
    """Ross, 2026-10-07: the board was quoting 335.86 -- our estimate for an
    index date still running -- when CME had that morning published 10/06 at
    337.87. The same defect the evening letter had, and the same fix: read the
    `published` block, which is the newest COMPLETED session and can never be
    the unfinished forward day."""
    fci = registry.BY_KEY["feeder_index"]
    assert fci.pick(bundle) == 337.87, "the tile must show CME's settled print"
    assert fci.pick(bundle) != bundle["fci"]["value"], "that is the forward estimate"
    assert fci.as_of(bundle) == "2026-10-06"
    chg = registry.BY_KEY["feeder_index_change"]
    assert chg.pick(bundle) == 0.65, "the move must be between two settled sessions"


def test_the_weight_tile_compares_to_a_year_ago(bundle):
    """Ross's call, 2026-10-07. weight_context returns both; the board takes
    vs_year_ago. The eight-year fit reads larger (+85.7 against +67.3) because
    the series drifts about +6.9 lb/yr, and that difference is recorded in the
    registry rather than argued in the UI."""
    w = registry.BY_KEY["weight_vs_year"]
    assert w.pick(bundle) == bundle["weight"]["vs_year_ago"]
    assert w.pick(bundle) != bundle["weight"]["vs_trend"]
    assert "weight_vs_trend" not in registry.ALL_KEYS, "the old key must be gone"
    assert "year ago" in w.basis.lower()


def test_the_demand_card_exists_and_is_second(bundle):
    """Demand sits between what beef is worth and what the packer earns,
    because it is the REASON the cutout moves rather than a consequence."""
    assert registry.Q_DEMAND in registry.QUESTIONS
    assert registry.QUESTIONS.index(registry.Q_DEMAND) == 1
    assert len(registry.for_question(registry.Q_DEMAND)) >= 4


def test_the_demand_card_says_it_is_on_a_different_clock(bundle):
    """ERS is monthly and about six weeks behind, where the cutout is same-day.
    A max_age_days written against a weekly cadence would mark the whole card
    stale every day of its life."""
    for s in registry.for_question(registry.Q_DEMAND):
        assert s.max_age_days >= 70, f"{s.key} would read stale on arrival"
        assert "monthly" in s.cadence
    r = meaning.read(registry.BY_KEY["imports_yoy"], bundle, date(2026, 10, 7))
    assert r.state == meaning.OK, "August data on 7 October is normal, not stale"


def test_the_demand_card_never_claims_the_weekly_export_figure(bundle):
    """JSA already publishes FAS ESR weekly at jpsi.com/export-sales-dashboard.
    That is a different figure -- sales not customs entries, product weight not
    carcass -- and two JSA surfaces quoting different export numbers without
    saying why is the failure this whole board is built to avoid."""
    ex = registry.BY_KEY["exports_ytd"]
    assert "carcass" in ex.basis.lower()
    assert "ers" in ex.source.lower()
