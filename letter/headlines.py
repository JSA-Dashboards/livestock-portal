"""
Candidate headlines for the morning brief's Headlines section.

NOTHING HERE REACHES THE LETTER. These are suggestions shown beside the
Headlines box on the authoring page, for Ross to pick from and rewrite. Every
other figure in the brief is a USDA or CME number that is either right or
marked [[?]]; a headline is editorial, and there is no [[?]] for "a feed
surfaced something misleading and it went out over JSA's name". So the split is
deliberate: fetched here, written by hand there.

It also keeps the copyright question simple. Facts are not copyrightable and can
be restated freely; someone else's headline text is theirs. Showing a title on a
private, passphrase-gated page as a pointer to go read the story is a different
act from reprinting it in a PDF sent to paying clients.

Two kinds of source:

  RSS        Beef Magazine responds to an ordinary request. Drovers and AgWeb
             both return 403 to anything that is not a browser, Meatingplace is
             subscriber-only, and Reuters' agriculture feed is dead -- so the
             list is deliberately short rather than padded with feeds that fail
             silently.

  USDA prose The narratives already fetched for the numbers. AMS writes a
             paragraph on every daily cash report describing how the trade went,
             and the border reports carry USDA's own commentary. Authoritative,
             free, cattle-specific, and no third party's copy.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from . import mailbox, sources

# Feeds that actually answer. Verified 2026-09-23; the ones that do not are
# named in the module docstring so nobody re-adds them hopefully.
RSS_FEEDS = [
    ("Beef Magazine", "https://www.beefmagazine.com/rss.xml"),
]

# A browser-ish agent: several ag publishers reject the requests default.
_UA = {"User-Agent": "Mozilla/5.0 (compatible; JSA-letter/1.0)"}

# Cattle words. The feeds are general-agriculture, so without this the list
# fills with corn agronomy and the panel stops being worth reading.
_RELEVANT = re.compile(
    r"\b(cattle|beef|feeder|fed|packer|cow|heifer|steer|calf|calves|slaughter|"
    r"carcass|cutout|boxed|herd|feedlot|feedyard|cme|usda|export|import|tariff|"
    r"mexico|canada|screwworm|foot.and.mouth|drought)\b", re.I)


def _clean(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


# A morning brief wants this morning's news. Beyond two days an item is not a
# headline, it is background -- "CSU names livestock complex" and "July/August
# edition available" are both real feed items from this week.
MAX_AGE_HOURS = 48


def fetch_rss(name: str, url: str, limit: int = 12, max_age_h: int = MAX_AGE_HOURS) -> list:
    """Recent items from one feed, filtered to cattle-relevant titles."""
    out = []
    try:
        r = sources._session().get(url, timeout=15, headers=_UA)
        if r.status_code != 200:
            return [{"source": name, "error": f"HTTP {r.status_code}"}]
        body = r.text
    except Exception as e:
        return [{"source": name, "error": f"{type(e).__name__}"}]

    for block in re.findall(r"<item[^>]*>(.*?)</item>", body, re.S | re.I)[:60]:
        title = _clean((re.search(r"<title[^>]*>(.*?)</title>", block, re.S) or [None, ""])[1])
        if not title or not _RELEVANT.search(title):
            continue
        link = _clean((re.search(r"<link[^>]*>(.*?)</link>", block, re.S) or [None, ""])[1])
        raw_date = _clean((re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S) or [None, ""])[1])
        when = None
        if raw_date:
            try:
                when = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                when = None
        age = (round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)
               if when and when.tzinfo else None)
        # An item with no parseable date is kept: unknown is not the same as old.
        if age is not None and age > max_age_h:
            continue
        out.append({"source": name, "title": title, "link": link,
                    "when": when.isoformat() if when else None, "age_h": age})
        if len(out) >= limit:
            break
    return out


def fetch_usda_narratives(as_of: date = None) -> list:
    """
    AMS's own written commentary on the cash trade, plus the border narrative.

    The AMS paragraph is the single most useful line in this panel most
    mornings: it is USDA describing the trade in prose, published daily, and not
    anyone's copyrighted reporting.
    """
    out = []

    # National daily negotiated summary (LM_CT115) carries a `trend` paragraph.
    try:
        r = sources._session().get(f"{sources.LMR_BASE}/2662/",
                                   params={"lastReports": 1, "allSections": "true"}, timeout=30)
        r.raise_for_status()
        payload = r.json()
        for sec in (payload if isinstance(payload, list) else [payload]):
            if sec.get("reportSection") != "Summary":
                continue
            for row in sec.get("results", [])[:1]:
                trend = _clean(row.get("trend"))
                if trend:
                    out.append({"source": "USDA AMS cash trade",
                                "title": trend,
                                "when": row.get("published_date"),
                                "link": ""})
            break
    except Exception as e:
        out.append({"source": "USDA AMS cash trade", "error": f"{type(e).__name__}"})

    # Border commentary, from the same Snowflake table the imports page reads.
    try:
        db = sources._load_fci_db()
        conn = db.get_conn()
        try:
            df = db.read_sql_lower(
                "SELECT report_date, narrative FROM border_reports "
                "WHERE kind = 'commentary' ORDER BY report_date DESC", conn)
        finally:
            conn.close()
        if not df.empty:
            row = df.iloc[0]
            text = _clean(str(row.get("narrative") or ""))
            if text:
                out.append({"source": "USDA border report",
                            "title": text, "when": str(row.get("report_date")), "link": ""})
    except Exception:
        # Snowflake being unavailable is not worth a panel-wide error; the AMS
        # narrative and the feed still stand on their own.
        pass

    return out


def candidates(as_of: date = None, limit_per_feed: int = 12,
               max_age_h: int = MAX_AGE_HOURS, include_mailbox: bool = True) -> dict:
    """
    {"items": [...], "errors": [...], "needs_sign_in": bool} -- everything to
    offer, plus what failed and why.

    Sources are independent: a dead feed, an unconfigured mailbox and a
    Snowflake outage each cost their own line and nothing else.
    """
    items, errors, needs_sign_in = [], [], False

    for row in fetch_usda_narratives(as_of):
        (errors if row.get("error") else items).append(row)

    for name, url in RSS_FEEDS:
        for row in fetch_rss(name, url, limit_per_feed, max_age_h):
            (errors if row.get("error") else items).append(row)

    # The paid digests, read from Ross's own mailbox -- see letter/mailbox.py
    # for why that is the right door rather than the publishers' websites.
    if include_mailbox:
        got = mailbox.fetch_digests(max_age_h=max(max_age_h, 30))
        items.extend(got.get("items", []))
        errors.extend({"source": "", "error": e} for e in got.get("errors", []))
        needs_sign_in = bool(got.get("needs_sign_in"))

    return {"items": items,
            "errors": [(f"{e['source']}: {e['error']}" if e.get("source") else e["error"])
                       for e in errors],
            "needs_sign_in": needs_sign_in}
