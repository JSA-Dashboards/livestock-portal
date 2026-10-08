"""
The SCHEMA cache guard must actually key the cache.

`st.cache_data` keys on the decorated function's own code and arguments and
never on the modules it calls, so a page that adds a key to a shared module's
return value keeps serving the old shape with nothing raising. The portal's
answer is a `SCHEMA` constant on the module, passed into the cached fetch
purely to be part of the key -- recorded in CLAUDE.md for `leverage.SCHEMA`,
`am_cutout.SCHEMA` and the rest.

**THAT GUARD WAS INERT ON EVERY PAGE I ADDED IT TO**, 2026-10-07, in four
functions across three pages. Two independent mistakes, either of which is
enough on its own:

  * `_schema` with a LEADING UNDERSCORE. Streamlit treats an
    underscore-prefixed argument as deliberately unhashable and leaves it
    out of the key entirely -- the documented way to pass a database
    connection into a cached function. So naming it `_schema` asks Streamlit
    to ignore the one thing it was added for.
  * A DEFAULT that the caller never overrides. `st.cache_data` hashes the
    arguments it is CALLED with; a parameter left at its default does not
    vary, so even spelled correctly it would contribute nothing unless the
    call site passes it.

The pre-existing pages had both halves right -- `fetch_am_cutout(schema: int
= am_cutout.SCHEMA)` called as `fetch_am_cutout(am_cutout.SCHEMA)` -- and I
copied the shape without the substance.

The test that was supposed to cover this asserted `"wasde.SCHEMA" in page`,
a string match that the broken form satisfies perfectly. It passed
throughout. This file replaces that with something that reads the code.

Scoped to arguments whose DEFAULT is a `*.SCHEMA` attribute, deliberately:
an underscore prefix is correct and necessary elsewhere, for the unhashable
connection and dataframe arguments several pages pass.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted(ROOT.glob("apps/*/app.py"))

# utf-8-SIG, not utf-8. Two pages in this repo (beef_trimmings and
# cattle_on_feed) begin with a UTF-8 BOM, and `ast.parse` rejects it with
# "invalid non-printable character U+FEFF" -- a parse error that looks like
# a syntax error in the page rather than a codec choice in the reader. The
# same trap CLAUDE.md records for PowerShell-written TOML.
ENCODING = "utf-8-sig"


def _is_cache_data(dec: ast.expr) -> bool:
    """@st.cache_data, with or without arguments."""
    node = dec.func if isinstance(dec, ast.Call) else dec
    return isinstance(node, ast.Attribute) and node.attr in (
        "cache_data", "cache_resource")


def _schema_params(fn: ast.FunctionDef):
    """[(index, name)] for arguments defaulting to something.SCHEMA."""
    args = fn.args.posonlyargs + fn.args.args
    defaults = fn.args.defaults
    first_default = len(args) - len(defaults)
    out = []
    for offset, default in enumerate(defaults):
        if isinstance(default, ast.Attribute) and default.attr == "SCHEMA":
            idx = first_default + offset
            out.append((idx, args[idx].arg))
    return out


def _cached_schema_functions(tree: ast.AST):
    """[(FunctionDef, index, param_name)] for every cached SCHEMA guard."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not any(_is_cache_data(d) for d in node.decorator_list):
            continue
        for idx, name in _schema_params(node):
            found.append((node, idx, name))
    return found


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.parent.name)
def test_schema_arguments_are_not_underscore_prefixed(page):
    """
    Streamlit drops underscore-prefixed arguments from the cache key. Naming
    the guard `_schema` asks it to ignore the one thing it exists for.
    """
    tree = ast.parse(page.read_text(encoding=ENCODING))
    for fn, _, name in _cached_schema_functions(tree):
        assert not name.startswith("_"), (
            f"{page.parent.name}/{fn.name}: argument {name!r} defaults to a "
            f"SCHEMA constant but is underscore-prefixed, so st.cache_data "
            f"leaves it out of the key and the guard does nothing")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.parent.name)
def test_every_call_passes_the_schema_explicitly(page):
    """
    st.cache_data hashes the arguments it is CALLED with. A parameter left
    at its default never varies, so it contributes nothing to the key even
    when it is spelled correctly.
    """
    src = page.read_text(encoding=ENCODING)
    tree = ast.parse(src)
    guards = {fn.name: (idx, name)
              for fn, idx, name in _cached_schema_functions(tree)}
    if not guards:
        pytest.skip("no SCHEMA-keyed cached fetches on this page")

    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in guards]
    # Every guarded function must be called somewhere, or the guard is moot.
    assert calls, f"{page.parent.name}: SCHEMA guards defined but never called"

    for call in calls:
        idx, name = guards[call.func.id]
        passed = len(call.args) > idx or any(
            kw.arg == name for kw in call.keywords)
        assert passed, (
            f"{page.parent.name}: {call.func.id}() is called at line "
            f"{call.lineno} without passing {name!r}. The default is never "
            f"hashed, so the cache would not notice a SCHEMA bump")


def test_the_guard_is_present_wherever_a_shared_module_is_cached():
    """
    The three WASDE pages and the trade page must each key their cached
    fetch on the module constant -- that is what makes a shape change to
    `wasde.py` or `trade_flows.py` reach a running deployment at all.
    """
    expected = {
        "apps/beef_trade/app.py": ("tf.SCHEMA", "wasde.SCHEMA"),
        "apps/cash_trade/app.py": ("wasde.SCHEMA",),
        "apps/beef_weight/app.py": ("wasde.SCHEMA",),
        "apps/fed_cattle_crush/app.py": ("wasde.SCHEMA",),
    }
    for rel, constants in expected.items():
        page = ROOT / rel
        assert page.exists(), rel
        tree = ast.parse(page.read_text(encoding=ENCODING))
        guards = _cached_schema_functions(tree)
        assert guards, f"{rel}: lost its SCHEMA-keyed cached fetch"
        src = page.read_text(encoding=ENCODING)
        for const in constants:
            assert const in src, f"{rel}: no longer references {const}"


def test_this_file_would_have_failed_against_the_broken_form():
    """
    A guard test that cannot fail is the thing it is guarding against. The
    original was `assert "wasde.SCHEMA" in page`, which the broken code
    satisfied. These two check the shape instead, so prove they reject it.
    """
    broken = (
        "import streamlit as st\n"
        "import wasde\n"
        "@st.cache_data(ttl=1)\n"
        "def fetch(_schema: int = wasde.SCHEMA) -> dict:\n"
        "    return {}\n"
        "x = fetch()\n"
    )
    tree = ast.parse(broken)
    guards = _cached_schema_functions(tree)
    assert guards, "the detector failed to see the guard at all"
    fn, idx, name = guards[0]
    assert name == "_schema"
    assert name.startswith("_"), "underscore check would not have fired"

    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "fetch")
    passed = len(call.args) > idx or any(kw.arg == name for kw in call.keywords)
    assert not passed, "the call-site check would not have fired either"

    # And the corrected form passes both.
    fixed = broken.replace("_schema", "schema").replace("fetch()",
                                                        "fetch(wasde.SCHEMA)")
    tree = ast.parse(fixed)
    fn, idx, name = _cached_schema_functions(tree)[0]
    assert not name.startswith("_")
    call = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "fetch")
    assert len(call.args) > idx
