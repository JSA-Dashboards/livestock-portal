"""
Beef market headlines read out of Ross's own inbox.

Four subscription digests: Meatingplace, eMeat, Global AgriTrends and
Sterling. Adding a fifth is one line in DIGESTS.

WHY THE MAILBOX AND NOT THE SITE. These are paid subscriptions. Fetching their
web pages with a script is the thing their terms are most likely to prohibit,
and it needs a stored password. The digest email does not: it was sent TO Ross
because he subscribed, it is sitting in his mailbox, and reading it is the same
act as opening it. No request ever reaches their servers.

NO PASSWORD PASSES THROUGH THIS CODE. MSAL's device-code flow prints a short
code, Ross signs in through a normal browser, and Graph returns a token that
lives in a local cache file. Same flow basis-tracker/email_client.py already
uses for the ADM and Mendota bid emails.

WHAT IT DOES WITH THEM. Nothing but offer them. The digests feed the candidate
panel on the authoring page, which is a pick list; the letter still prints only
what Ross typed. Reprinting a trade publication's headline text in a PDF sent to
paying clients is a different act from reading it, and this module deliberately
cannot do the second one.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

# Cached beside the code, not in out/ -- that directory gets cleared, and losing
# the token means signing in again for no reason. Gitignored with letter/data/.
TOKEN_CACHE = Path(__file__).resolve().parent / "data" / "graph_token.json"

# Add a digest by adding a line. `match` is passed to Graph's $search, which
# looks at sender, subject and body, so a publication name is enough.
# THREE WAYS TO FIND A DIGEST, in descending order of precision:
#
#   sender      exact From address. Cannot match anything else. Best.
#   sender_name From display name, matched with startswith, for publishers
#               whose address is not visible in the mail client. Prefix rather
#               than equals because these names vary: eMeat sends as both "The
#               EMEAT Daily Bulletin" and "The EMEAT Daily Bulletin - 3 Price
#               Alerts". Still body-free.
#   subject  Graph KQL "subject:..." -- searches the SUBJECT LINE ONLY, never
#            the body. Right when the address is unknown but the subject is
#            distinctive.
#   match    bare $search, which reads sender, subject AND body. A word like
#            "sterling" then also matches a client email about sterling silver,
#            and that message's text surfaces in the panel. Fallback only.
#
# Each entry should move up this list as its first real digest arrives and the
# From address becomes visible.
DIGESTS = [
    # Two a day, Morning Update and Afternoon Update, and the SUBJECT is the
    # lead headline rather than a title for a list of them.
    {"label": "Meatingplace", "sender_name": "Meatingplace Editorial"},
    # The Bulletin only. "The EMEAT Team" is the same publisher's marketing --
    # weekly newsletters and "50% off" promotions -- and does not belong in a
    # market headline panel.
    {"label": "eMeat", "sender_name": "The EMEAT Daily Bulletin"},
    {"label": "Global AgriTrends", "sender": "no-reply@globalagritrends.com"},
    # John Nalivka at Sterling Marketing. The address is exact where "sterling"
    # as a word search was not; it also catches every flavour he sends -- Profit
    # Tracker, Monthly, Red Meat Trade, Pork Industry -- which a subject match
    # on one of them would not. The Profit Tracker carries the packer margin the
    # evening letter quotes by hand.
    {"label": "Sterling", "sender": "jnalivka@fmtc.com"},
]

# Boilerplate that appears as a link in every marketing email.
_CHROME = re.compile(
    r"unsubscribe|view (this |it )?in (your )?browser|privacy polic|terms of|"
    r"contact us|advertise|manage (your )?preferences|forward to a friend|"
    r"update profile|follow us|subscribe|log ?in|sign ?in|click here|read more|"
    r"^\W*$", re.I)


def configured() -> bool:
    return bool(os.environ.get("GRAPH_CLIENT_ID") and os.environ.get("GRAPH_TENANT_ID"))


def _app():
    import msal
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        cache.deserialize(TOKEN_CACHE.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        client_id=os.environ["GRAPH_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}",
        token_cache=cache,
    )
    return app, cache


def _save(cache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(cache.serialize(), encoding="utf-8")


def token(interactive: bool = False):
    """
    A Graph token, or (None, device_flow) when sign-in is needed.

    Silent whenever a cached account exists, so the daily build never blocks.
    `interactive=True` starts the device-code flow and returns the flow dict for
    the caller to show -- this module never prints a code or waits on a human of
    its own accord.
    """
    if not configured():
        return None, {"error": "GRAPH_CLIENT_ID / GRAPH_TENANT_ID not set"}
    app, cache = _app()
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save(cache)
            return result["access_token"], None
    if not interactive:
        return None, {"error": "not signed in"}
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        return None, {"error": f"device flow failed: {flow.get('error_description', flow)}"}
    return None, flow


def complete_sign_in(flow: dict):
    """Block until the user finishes the device-code flow. Caller's choice."""
    app, cache = _app()
    result = app.acquire_token_by_device_flow(flow)
    _save(cache)
    return result.get("access_token")


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def parse_headlines(body: str, content_type: str = "html", limit: int = 15) -> list:
    """
    Pull headline-ish lines out of a digest.

    HEURISTIC, AND IT WILL NEED TUNING against a real message -- every publisher
    lays these out differently. Anchor text is tried first because a digest is
    almost always a list of linked headlines; failing that, the stripped text is
    read line by line. Both paths drop marketing chrome and anything too short
    to be a headline or long enough to be a paragraph.
    """
    out, seen = [], set()

    if content_type == "html":
        candidates = [re.sub(r"\s+", " ", _strip_html(a)).strip()
                      for a in re.findall(r"<a\b[^>]*>(.*?)</a>", body or "", re.S | re.I)]
    else:
        candidates = []

    if not candidates:
        text = body if content_type != "html" else _strip_html(body)
        candidates = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]

    for line in candidates:
        if not (25 <= len(line) <= 160):
            continue
        if _CHROME.search(line):
            continue
        if not re.search(r"[A-Za-z]{3}", line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= limit:
            break
    return out


def fetch_digests(max_age_h: int = 72, per_source: int = 10) -> dict:
    """
    {"items": [...], "errors": [...]} from the configured digests.

    THREE DAYS, NOT ONE. These are not all dailies -- Sterling arrives a few
    times a week, and on 2026-09-23 its newest was Monday afternoon, about 45
    hours old. A 30-hour window silently dropped it. Every item carries its age
    so the panel can show how fresh each one is and let Ross judge.

    Never raises and never blocks on sign-in: an unconfigured or signed-out
    mailbox is one line in the panel, not a failed morning.
    """
    import requests

    items, errors = [], []
    access, problem = token(interactive=False)
    if not access:
        return {"items": [], "errors": [f"mailbox: {problem.get('error')}"], "needs_sign_in": True}

    since = (datetime.now(timezone.utc) - timedelta(hours=max_age_h))
    headers = {"Authorization": f"Bearer {access}",
               "ConsistencyLevel": "eventual"}

    for src in DIGESTS:
        # An exact sender filter where we have the address; full-text search
        # only as a fallback. See the note on DIGESTS -- search reads the body,
        # so it can match mail that has nothing to do with the publication.
        fields = "subject,receivedDateTime,body,from"
        if src.get("sender"):
            query = {"$filter": f"from/emailAddress/address eq '{src['sender']}'",
                     "$orderby": "receivedDateTime desc", "$top": 5, "$select": fields}
        elif src.get("sender_name"):
            query = {"$filter": f"startswith(from/emailAddress/name,'{src['sender_name']}')",
                     "$orderby": "receivedDateTime desc", "$top": 8, "$select": fields}
        elif src.get("subject"):
            # KQL property restriction: subject line only, body untouched.
            query = {"$search": f'subject:"{src["subject"]}"', "$top": 5, "$select": fields}
        else:
            query = {"$search": f'"{src["match"]}"', "$top": 5, "$select": fields}
        try:
            r = requests.get(f"{GRAPH}/me/messages", headers=headers,
                             timeout=30, params=query)
            if r.status_code != 200:
                errors.append(f"{src['label']}: HTTP {r.status_code}")
                continue
            messages = r.json().get("value", [])
        except Exception as e:
            errors.append(f"{src['label']}: {type(e).__name__}")
            continue

        newest = None
        for m in messages:
            try:
                when = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if when < since:
                continue
            if newest is None or when > newest[0]:
                newest = (when, m)
        if not newest:
            errors.append(f"{src['label']}: nothing in the last {max_age_h}h")
            continue

        when, msg = newest
        body = (msg.get("body") or {})
        age = round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)

        # THE SUBJECT COUNTS. Meatingplace puts the lead story in the subject
        # line and the words "Morning Update" in the body, so parsing only the
        # body throws away the best headline in the message.
        lines = []
        subject = re.sub(r"\s+", " ", str(msg.get("subject") or "")).strip()
        if subject and not _CHROME.search(subject) and len(subject) >= 12:
            lines.append(subject)
        for line in parse_headlines(body.get("content", ""),
                                    body.get("contentType", "html"), per_source):
            if line.lower() != subject.lower():
                lines.append(line)

        for line in lines:
            items.append({"source": src["label"], "title": line,
                          "when": when.isoformat(), "age_h": age, "link": ""})

    return {"items": items, "errors": errors}
