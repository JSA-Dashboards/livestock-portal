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

Three kinds of source:

  RSS        Beef Magazine responds to an ordinary request. Drovers and AgWeb
             both return 403 to anything that is not a browser, Meatingplace is
             subscriber-only, and Reuters' agriculture feed is dead -- so the
             list is deliberately short rather than padded with feeds that fail
             silently.

  USDA prose The narratives already fetched for the numbers. AMS writes a
             paragraph on every daily cash report describing how the trade went,
             and the border reports carry USDA's own commentary. Authoritative,
             free, cattle-specific, and no third party's copy.

  Packers    A Google News search for the four beef packers and for plant
             disruption generally, over RSS. ADDED 2026-09-23 BECAUSE OF A MISS:
             an ICE operation in Kansas had meatpacking plants delaying shifts,
             it ran on KMUW and across the Kansas public stations, and this
             panel never saw it.

             The lesson is about the SHAPE of the source, not the length of the
             feed list. What stops a plant for a shift gets reported where the
             plant is -- a local newsroom -- and no fixed list of trade feeds
             subscribed to those newsrooms or ever will. Only a query finds a
             story like that.

             Being a query is also its weakness, and it is a different weakness
             from the rest of this module: a feed either answers or it 404s,
             while a search that returns nothing looks exactly like a quiet news
             day. Read it as recall, never as coverage.
"""
from __future__ import annotations

import html
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
#
# THE PACKER AND PLANT WORDS ARE LOAD-BEARING, and were missing until
# 2026-09-23. "ICE agents in Kansas cause schools to warn families and
# meatpacking plants to delay shifts" contains not one word of the original
# list: not "packer" -- the word is "meatpacking" -- and no company name. So the
# headline was thrown out as agronomy before anyone asked which feed carried it.
# A story about the packers not killing cattle is a cattle story.
#
# The plant words are PHRASES on purpose, and each one carries a MEAT
# qualifier. A bare "plant" matches planting intentions, plant disease and every
# agronomy item in a general-ag feed. A bare "processing plant" is worse, and it
# was tried: the first run of the packer search returned a post office in Sioux
# Falls, a Norwegian salmon plant and a warehouse fire in Calgary, all of them
# genuine "processing plant" stories and none of them cattle.
#
# "beef plant" and "slaughter plant" need no entry of their own -- "beef" and
# "slaughter" already stand alone above.
_RELEVANT = re.compile(
    r"\b(cattle|beef|feeder|fed|packers?|cow|heifer|steer|calf|calves|slaughter|"
    r"carcass|cutout|boxed|herd|feedlot|feedyard|cme|usda|export|import|tariff|"
    r"mexico|canada|screwworm|foot.and.mouth|drought|"
    r"tyson|jbs|cargill|national beef|greater omaha|"
    r"meat.?packing|packing\s+(?:plants?|facilit(?:y|ies))|"
    r"meat\s+(?:processing|plants?|facilit(?:y|ies)))\b", re.I)


def _clean(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    # AFTER the tags come out, not before: an escaped &lt;b&gt; should survive as
    # visible text rather than become a tag and get stripped. Without this the
    # panel shows "Tyson&#39;s" and a picked headline carries that into the
    # Headlines box and then into the letter.
    text = html.unescape(text)
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


# Google News over RSS: no key, no account, and it indexes the local newsrooms
# that actually cover a plant. The `when:Nd` operator does the recency cut
# server-side; the client-side age check below still runs, because an item with
# no parseable date would otherwise slip the window.
GOOGLE_NEWS = "https://news.google.com/rss/search"

# TWO QUERIES, NOT FOUR. One per packer would be four requests for one panel and
# would still miss the story that names no company -- which is most of them, the
# Kansas one included. So: one query that names the packers, one that describes
# the event.
#
# EVERY TERM IS QUALIFIED. "Tyson" alone is a boxer and a food company with a
# dozen chicken plants; "packing plant" alone is a cardboard factory. The
# qualifier in each query is what keeps this a cattle panel.
PACKER_QUERIES = [
    ("packers", '(Tyson OR JBS OR Cargill OR "National Beef") (beef OR cattle OR plant)'),
    ("plants", '("beef plant" OR "meatpacking plant" OR "packing plant" OR '
               '"processing plant") '
               '(cattle OR beef OR slaughter OR shift OR closure OR raid OR workers)'),
]


def fetch_packer_news(limit: int = 10, max_age_h: int = MAX_AGE_HOURS) -> list:
    """
    Beef packer and plant news from a Google News search.

    Titles arrive as "Headline - Publisher" with the publisher also in its own
    <source> tag, so the suffix is stripped and the publisher becomes the
    attribution -- which is the part worth reading, since half these outlets are
    ones Ross has never heard of and should judge for himself.

    Links are Google's redirect URLs rather than the publisher's. They open
    fine; they are just ugly, and there is no way to ask this feed for the real
    one without following each redirect.
    """
    out, seen = [], set()
    # `when:` takes whole days, and rounding DOWN would cut the window short.
    days = max(1, -(-int(max_age_h) // 24))

    for label, query in PACKER_QUERIES:
        try:
            r = sources._session().get(
                GOOGLE_NEWS, timeout=20, headers=_UA,
                params={"q": f"{query} when:{days}d", "hl": "en-US",
                        "gl": "US", "ceid": "US:en"})
            if r.status_code != 200:
                out.append({"source": f"Google News ({label})",
                            "error": f"HTTP {r.status_code}"})
                continue
            body = r.text
        except Exception as e:
            out.append({"source": f"Google News ({label})", "error": f"{type(e).__name__}"})
            continue

        kept = 0
        for block in re.findall(r"<item>(.*?)</item>", body, re.S | re.I)[:60]:
            title = _clean((re.search(r"<title[^>]*>(.*?)</title>", block, re.S) or [None, ""])[1])
            pub = _clean((re.search(r"<source[^>]*>(.*?)</source>", block, re.S) or [None, ""])[1])
            # Only strip the suffix when it really is the publisher's name --
            # plenty of headlines contain " - " of their own.
            if pub and title.endswith(f" - {pub}"):
                title = title[: -(len(pub) + 3)].strip()
            if not title or not _RELEVANT.search(title):
                continue
            key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
            if key in seen:
                continue

            raw_date = _clean((re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S)
                               or [None, ""])[1])
            when = None
            if raw_date:
                try:
                    when = parsedate_to_datetime(raw_date)
                except (TypeError, ValueError):
                    when = None
            age = (round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)
                   if when and when.tzinfo else None)
            if age is not None and age > max_age_h:
                continue

            seen.add(key)
            link = _clean((re.search(r"<link[^>]*>(.*?)</link>", block, re.S) or [None, ""])[1])
            out.append({"source": pub or "Google News", "title": title, "link": link,
                        "when": when.isoformat() if when else None, "age_h": age})
            kept += 1
            if kept >= limit:
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


def _dedupe(items: list) -> list:
    """
    One row per story.

    Needed once the packer search is in: a plant closure runs on the wire and
    comes back from both queries, from Beef Magazine, and again from whichever
    digest picked it up. Matching is on the title with punctuation and case
    thrown away, so it collapses the same headline reprinted -- not the same
    story rewritten by two newsrooms, which stays as two rows. That is the right
    side to err on: a duplicate costs a glance, a dropped story is the bug this
    whole change is about.

    First occurrence wins, so source order below is priority order.
    """
    seen, out = set(), []
    for item in items:
        key = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def candidates(as_of: date = None, limit_per_feed: int = 12,
               max_age_h: int = MAX_AGE_HOURS, include_mailbox: bool = True,
               include_packers: bool = True) -> dict:
    """
    {"items": [...], "errors": [...], "needs_sign_in": bool} -- everything to
    offer, plus what failed and why.

    Sources are independent: a dead feed, an unconfigured mailbox, a search that
    answers with nothing and a Snowflake outage each cost their own line and
    nothing else.
    """
    items, errors, needs_sign_in = [], [], False

    for row in fetch_usda_narratives(as_of):
        (errors if row.get("error") else items).append(row)

    for name, url in RSS_FEEDS:
        for row in fetch_rss(name, url, limit_per_feed, max_age_h):
            (errors if row.get("error") else items).append(row)

    # Packer and plant news. Sits above the digests because it is the source
    # most likely to be carrying something nobody else has -- see the module
    # docstring for the miss that put it here.
    if include_packers:
        for row in fetch_packer_news(max_age_h=max_age_h):
            (errors if row.get("error") else items).append(row)

    # The paid digests, read from Ross's own mailbox -- see letter/mailbox.py
    # for why that is the right door rather than the publishers' websites.
    if include_mailbox:
        got = mailbox.fetch_digests(max_age_h=max(max_age_h, 72))
        items.extend(got.get("items", []))
        errors.extend({"source": "", "error": e} for e in got.get("errors", []))
        needs_sign_in = bool(got.get("needs_sign_in"))

    return {"items": _dedupe(items),
            "errors": [(f"{e['source']}: {e['error']}" if e.get("source") else e["error"])
                       for e in errors],
            "needs_sign_in": needs_sign_in}
