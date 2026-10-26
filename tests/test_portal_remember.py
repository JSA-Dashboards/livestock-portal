"""
Remembering the portal unlock across a page load.

Ross, 2026-10-26: "after i login to my dashboard view- it makes me enter the
password every time i click a different dashboard tab. i only want to enter the
password one time per session."

WHAT WAS ACTUALLY HAPPENING, reproduced under Streamlit 1.64 rather than
guessed at: `st.session_state` lives and dies with one Streamlit session, and a
session dies on any FULL page load -- a refresh, a new tab, a pasted deep link,
the Community Cloud iframe re-navigating. Clicking a top-nav link keeps the
session and the gate stayed open; a full navigation to the same URL came back
gated. The local portal runs Streamlit 1.63, which puts navigation in the
SIDEBAR, so none of this was visible without building a 1.64 harness.

So the unlock is also remembered in a signed cookie. THE TOKEN IS THE WHOLE
SECURITY OF THAT, and it is what these tests are for: the browser holds it, so
if it could be forged or its expiry extended the gate would open for anyone who
thought to try.

The passphrase is the HMAC key, which is why rotating it invalidates every
token at once -- the one revocation story this gate has.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import portal_auth  # noqa: E402

SECRET = "a-test-passphrase-not-anybodys"


# -- the token ---------------------------------------------------------------

def test_a_valid_token_round_trips():
    assert portal_auth.token_is_valid(portal_auth.issue_token(SECRET), SECRET)


def test_the_token_never_contains_the_passphrase():
    """It is handed to the browser. The passphrase must not travel with it."""
    assert SECRET not in portal_auth.issue_token(SECRET)


def test_a_different_passphrase_does_not_verify():
    """
    Rotating the passphrase has to invalidate every outstanding token -- that
    is the only revocation this gate has. It is also what stops the client
    app's token opening the staff app.
    """
    token = portal_auth.issue_token(SECRET)
    assert not portal_auth.token_is_valid(token, "the-rotated-one")


def test_the_expiry_cannot_be_extended():
    """
    The expiry is INSIDE the signature. A browser that edits its own cookie to
    push the date out must not be believed -- verified in a real browser too,
    where the forged cookie came back gated with zero tiles.
    """
    token = portal_auth.issue_token(SECRET)
    _, _, sig = token.partition(".")
    forged = f"{int(time.time()) + 99_999_999}.{sig}"
    assert not portal_auth.token_is_valid(forged, SECRET)


def test_an_expired_token_is_refused():
    assert not portal_auth.token_is_valid(portal_auth.issue_token(SECRET, days=-1), SECRET)


@pytest.mark.parametrize("junk", ["", "nonsense", ".", "abc.def", "123", "123.", ".deadbeef"])
def test_malformed_tokens_are_refused(junk):
    assert not portal_auth.token_is_valid(junk, SECRET)


def test_no_secret_verifies_nothing():
    """Fail closed. A deployment with no passphrase has nothing to check a
    token against, so no token may pass."""
    assert not portal_auth.token_is_valid(portal_auth.issue_token(SECRET), "")


# -- the wiring --------------------------------------------------------------

def test_the_cookie_is_checked_after_session_state_and_needs_a_secret():
    """
    Order matters in two directions. The session-state fast path must come
    first so an unlocked session never re-reads cookies; and the cookie branch
    must require a configured secret, so the "not configured" branch below it
    still shuts the gate on a misconfigured deployment.
    """
    import ast
    src = (ROOT / "portal_auth.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "require_passphrase")
    body = ast.unparse(fn)
    assert body.index("is_unlocked(secret_name)") < body.index("token_is_valid"), \
        "session state must be checked before the cookie"
    assert body.index("token_is_valid") < body.index("if not secret:"), \
        "the cookie check must precede the not-configured branch"
    assert "if secret and REMEMBER_DAYS" in body, \
        "the cookie branch must require a configured secret"


def test_the_passphrase_is_never_written_to_the_browser():
    """
    `_remember_in_browser` emits JavaScript. The one thing it must never put in
    that script is the secret it was verified against.
    """
    import ast
    src = (ROOT / "portal_auth.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_remember_in_browser")

    # IDENTIFIERS, not substrings. `secret_name` is the secret's NAME and is
    # fine to handle -- a substring check flags it and would push someone into
    # renaming a correct parameter to satisfy the test.
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "secret" not in names, \
        "_remember_in_browser binds `secret` -- it takes a token, never the passphrase"
    calls = {n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "configured_passphrase" not in calls, \
        "_remember_in_browser must not read the passphrase at all"
    assert {"secret_name", "token"} <= {a.arg for a in fn.args.args}


def test_the_cookie_is_not_marked_secure_unconditionally():
    """
    A Secure cookie is silently DROPPED on http://localhost, so hard-coding the
    flag would make this work on the deployed app and do nothing in local
    testing -- the exact shape of bug this repo keeps recording. It is set from
    location.protocol instead.
    """
    src = (ROOT / "portal_auth.py").read_text(encoding="utf-8")
    assert "location.protocol==='https:'" in src.replace(" ", "")
    assert ";Secure;" not in src and "SameSite=Lax;Secure" not in src


def test_remember_days_can_turn_the_cookie_off():
    """REMEMBER_DAYS = 0 reverts to session-only, which is the fallback if the
    cookie ever misbehaves on a deployment."""
    src = (ROOT / "portal_auth.py").read_text(encoding="utf-8")
    assert "if REMEMBER_DAYS:" in src
    assert "if secret and REMEMBER_DAYS" in src
    assert isinstance(portal_auth.REMEMBER_DAYS, int)


def test_reading_cookies_cannot_raise():
    """
    st.context.cookies throws without a live request context -- a bare script
    run, a test, a thread. The gate must not die on that; it should simply find
    no token and ask for the passphrase.
    """
    assert portal_auth._cookie("anything") == ""
