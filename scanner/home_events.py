"""Exchange filings for the home events feed (spec section 6).

T3a added `redact_error`. T3b adds `Feed`, `ParseError`, `ParseResult`,
`dedupe_key` and `to_event_row`. T3c adds `filter_items`, `classify_response`,
`FetchResult` and `Cooldown`. Later tasks add the feed table (FEEDS),
the parsers, and the fetch and run logic to this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

from scanner.company_reference import fill_from_name

# Query strings: everything from "?" up to whitespace or a quote/bracket.
_QUERY_RE = re.compile(r"(https?://[^\s'\"<>?]+)\?[^\s'\"<>]*")
# "Bearer <token>" pairs.
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+\S+")
# key=value pairs whose key names a credential.
_SECRET_KV_RE = re.compile(r"(?i)\b(token|secret|password|passwd|apikey|api_key|auth|key)=\S+")
# Long opaque runs (30+ url-safe characters with at least one digit or upper-case letter).
_TOKEN_LIKE_RE = re.compile(r"\b(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{30,}\b|\b(?=[A-Za-z0-9_\-]*[A-Z])[A-Za-z0-9_\-]{30,}\b")


def redact_error(text: str) -> str:
    """Strip query strings and token-like substrings from error text.

    Used before any text goes into a run message, so a feed URL or a token
    never reaches `collector_runs.message`.
    """
    if not text:
        return ""
    out = _QUERY_RE.sub(r"\1", text)
    out = _BEARER_RE.sub(r"\1 <redacted>", out)
    out = _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    out = _TOKEN_LIKE_RE.sub("<redacted>", out)
    return out


class ParseError(Exception):
    """The body is not usable XML for this feed. Feed-level: the whole feed is lost."""


@dataclass(frozen=True)
class Feed:
    """One exchange feed in the registry (spec 4.0). The FEEDS tuple is added in T4e."""

    feed_code: str  # "nse:<Name>"
    url: str
    event_type: str
    feed_tier: str
    default_enabled: bool
    flagged: bool  # tier or event type still to confirm (4.0)


@dataclass(frozen=True)
class ParseResult:
    """What a feed parser returns: the usable items and the count it dropped."""

    items: list[dict]
    dropped: int  # items missing a required field or with an unparseable date


def _squash(text: str) -> str:
    """Collapse runs of whitespace. Feed text carries trailing spaces and newlines."""
    return " ".join(text.split())


def dedupe_key(
    feed_code: str,
    source_id: str | None,
    source_url: str,
    title: str,
    description: str,
    published_at: datetime,
) -> str:
    """Key one feed item so a refetch of the same item gives the same key (spec 4.2).

    With a feed id the key is "<feed_code>:<source_id>". Without one it is
    "<feed_code>:" plus a SHA-256 of the JSON array [link, title, description,
    UTC publish time], with title and description whitespace-squashed. The JSON
    encoding keeps a "|" inside the text from making two items collide.
    `published_at` must be timezone-aware: a naive value would be read as
    machine-local time.
    """
    sid = (source_id or "").strip()
    if sid:
        return f"{feed_code}:{sid}"
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    utc_iso = published_at.astimezone(timezone.utc).isoformat()
    payload = json.dumps(
        [source_url, _squash(title), _squash(description), utc_iso],
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{feed_code}:{digest}"


def to_event_row(feed: Feed, item: dict) -> dict:
    """Map one parsed item (isin already filled by filter_items) to a `home_events` row.

    `exchange` comes from the "nse:" prefix of `feed_code`. BSE is deferred (Z2),
    so any other prefix is refused here rather than failing the API's CHECK.
    `published_at` is ISO 8601 with its UTC offset, as the API requires (4.6).
    The item needs `title` and `description`, which the dedupe key reads.
    """
    prefix, sep, _ = feed.feed_code.partition(":")
    if not sep or prefix != "nse":
        raise ValueError(f"unsupported feed_code: {feed.feed_code!r}")
    published_at = item["published_at"]
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    source_id = item.get("source_id")
    return {
        "dedupe_key": dedupe_key(
            feed.feed_code,
            source_id,
            item["source_url"],
            item["title"],
            item["description"],
            published_at,
        ),
        "exchange": prefix.upper(),
        "feed_code": feed.feed_code,
        "source_id": source_id,
        "source_url": item["source_url"],
        "isin": item["isin"],
        "symbol": item["symbol"],
        "company": item.get("company"),
        "event_type": feed.event_type,
        "feed_tier": feed.feed_tier,
        "headline": item["headline"],
        "published_at": published_at.isoformat(),
    }


def filter_items(
    items: list[dict],
    universe: dict[str, str],
) -> tuple[list[dict], dict[str, int]]:
    """Keep items whose symbol is in the universe, and fill a missing ISIN from it (spec 4.3).

    `universe` maps symbol to ISIN. For events it is `company_reference.load_index_for_source(conn, "nse_csv").universe`.
    Returns (kept, counts). Kept items are copies, so the caller's dicts are not
    changed. An ISIN the feed supplied is kept as it is. `counts` always has the
    key "universe": the number of items rejected because their symbol is not in
    the universe.
    """
    kept: list[dict] = []
    counts = {"universe": 0}
    for item in items:
        isin = universe.get(item.get("symbol"))
        if isin is None:
            counts["universe"] += 1
            continue
        filled = dict(item)
        if not filled.get("isin"):
            filled["isin"] = isin
        kept.append(filled)
    return kept, counts


def classify_response(status: int | None, content_type: str, body: bytes) -> str:
    """Classify one feed response as "ok", "blocked", "retry" or "fail" (spec 5.2).

    `status` is None for a timeout or a connection error. The checks run in the
    order of the 5.2 table, so a 200 that returns an HTML page is "blocked", not
    "ok". Any status the table does not list (3xx, 401, 404, other 4xx, and a 2xx
    other than 200) is "fail".
    """
    if status is None:
        return "retry"
    if status in (403, 429):
        return "blocked"
    if status == 408 or 500 <= status <= 599:
        return "retry"
    if status == 200:
        if "html" in (content_type or "").lower():
            return "blocked"
        head = body.lstrip()[:16].lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            return "blocked"
        if not body.strip():
            return "fail"
        return "ok"
    return "fail"


@dataclass(frozen=True)
class FetchResult:
    """What `fetch_feed` returns for one feed (spec 5.2, 6).

    `outcome` is "ok", "blocked", "transient" (a retry that failed again) or
    "fatal" (a non-transient failure, or a ParseError). `detail` is redacted
    with `redact_error` and never holds a URL with a query string.
    """

    outcome: str
    items: list[dict]
    dropped: int
    detail: str


class Cooldown(Protocol):
    """The shared NSE pause (spec 5.1, 5.2). S2 supplies the real one; tests inject a fake."""

    def active(self, exchange: str, now: datetime) -> bool: ...

    def block(self, exchange: str, now: datetime, reason: str) -> None: ...

    def reset(self, exchange: str) -> None: ...


def _request_once(feed: Feed, session: Any, cfg: dict) -> tuple[int | None, str, bytes]:
    """Make one GET to the feed. Returns (status, content_type, body).

    Any exception from the session (timeout, connection error) gives status None
    and an empty body, so the caller classifies it as "retry".
    """
    try:
        response = session.get(feed.url, timeout=cfg["request_timeout_s"])
    except Exception:
        return None, "", b""
    return response.status_code, response.headers.get("Content-Type", ""), response.content


def _settle(
    feed: Feed,
    status: int | None,
    content_type: str,
    body: bytes,
    parse_fn: Callable[[str, bytes], ParseResult],
) -> FetchResult | None:
    """Turn one classified response into a FetchResult, or None when it should be retried."""
    outcome = classify_response(status, content_type, body)
    if outcome == "retry":
        return None
    if outcome == "ok":
        try:
            parsed = parse_fn(feed.feed_code, body)
        except ParseError as exc:
            return FetchResult(outcome="fatal", items=[], dropped=0, detail=redact_error(str(exc)))
        return FetchResult(outcome="ok", items=parsed.items, dropped=parsed.dropped, detail="")
    if outcome == "blocked":
        return FetchResult(outcome="blocked", items=[], dropped=0, detail="blocked")
    # "fail": a non-listed status, or an empty 200
    detail = "empty body" if status == 200 else f"status {status}"
    return FetchResult(outcome="fatal", items=[], dropped=0, detail=detail)


def _transient(status: int | None) -> FetchResult:
    """A retry that failed again, or a retry that was not allowed."""
    detail = "timeout" if status is None else f"status {status}"
    return FetchResult(outcome="transient", items=[], dropped=0, detail=redact_error(detail))


def fetch_feed(
    feed: Feed,
    *,
    session: Any,
    cfg: dict,
    parse_fn: Callable[[str, bytes], ParseResult],
    sleep: Callable[[float], None],
    rng: Any,
    clock: Callable[[], datetime],
    deadline_at: datetime,
) -> FetchResult:
    """Fetch and parse one feed, with a polite gap and at most one retry (spec 5.2, 5.4).

    The gap before the first request is drawn from [gap_min_s, gap_max_s]; the
    retry adds no gap. The retry runs only when it would finish before
    `deadline_at` (backoff_s plus request_timeout_s from now).
    """
    sleep(rng.uniform(cfg["gap_min_s"], cfg["gap_max_s"]))
    status, content_type, body = _request_once(feed, session, cfg)
    result = _settle(feed, status, content_type, body, parse_fn)
    if result is not None:
        return result

    try:
        retry_fits = clock() + timedelta(seconds=cfg["backoff_s"] + cfg["request_timeout_s"]) <= deadline_at
    except OverflowError:
        # The retry would end past the datetime range, so it cannot end before deadline_at.
        retry_fits = False
    if not retry_fits:
        return _transient(status)

    sleep(cfg["backoff_s"])
    status, content_type, body = _request_once(feed, session, cfg)
    result = _settle(feed, status, content_type, body, parse_fn)
    if result is not None:
        return result
    return _transient(status)


# Run parameters and their defaults (spec 7). `enabled_feeds` defaults to the
# feeds whose default_enabled is true, so it is not in this table.
RUN_DEFAULTS: dict[str, float] = {
    "gap_min_s": 5,
    "gap_max_s": 8,
    "request_timeout_s": 20,
    "post_timeout_s": 15,
    "backoff_s": 30,
    "run_deadline_s": 240,
}
EXCHANGE = "nse"
ROTATION_S = 300  # the start feed moves every 5 minutes (spec 5.1 step 3)


class _ConfigError(Exception):
    """A run parameter is invalid. `key` is named in the run message (spec 5.1 step 1)."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _run_config(params: dict, feeds: tuple[Feed, ...]) -> tuple[dict, tuple[Feed, ...]]:
    """Merge `params` over the spec 7 defaults and validate them.

    Returns (cfg, enabled): `cfg` holds the numeric values fetch_feed reads, and
    `enabled` is the feeds to run in registry order. Raises _ConfigError on the
    first bad key.
    """
    cfg: dict[str, float] = {}
    for key, default in RUN_DEFAULTS.items():
        value = params.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _ConfigError(key)
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite or value <= 0:
            raise _ConfigError(key)
        cfg[key] = value
    if cfg["gap_min_s"] > cfg["gap_max_s"]:
        raise _ConfigError("gap_min_s")

    known = {feed.feed_code for feed in feeds}
    wanted = params.get("enabled_feeds")
    if wanted is None:
        enabled = tuple(feed for feed in feeds if feed.default_enabled)
    else:
        if not isinstance(wanted, (list, tuple)):
            raise _ConfigError("enabled_feeds")
        if any(not isinstance(code, str) or code not in known for code in wanted):
            raise _ConfigError("enabled_feeds")
        chosen = set(wanted)
        enabled = tuple(feed for feed in feeds if feed.feed_code in chosen)
    if not enabled:
        # Nothing to run. Refusing here also keeps the rotation from dividing by zero.
        raise _ConfigError("enabled_feeds")
    return cfg, enabled


def _rotation(enabled: tuple[Feed, ...], now: datetime) -> list[Feed]:
    """Feeds in visit order: start at the rotation index, then walk and wrap (spec 5.1 step 3)."""
    start = int(now.timestamp() // ROTATION_S) % len(enabled)
    return [enabled[(start + offset) % len(enabled)] for offset in range(len(enabled))]


def _run_result(
    status: str,
    *,
    fetched: int = 0,
    new: int = 0,
    times: list[datetime] | None = None,
    message: str = "",
) -> dict:
    """Build the spec 5.1 result. `from` and `to` are the earliest and latest kept published_at, as ISO 8601."""
    times = times or []
    return {
        "status": status,
        "fetched": fetched,
        "new": new,
        "from": min(times).isoformat() if times else None,
        "to": max(times).isoformat() if times else None,
        "message": message,
    }


def run_cycle(
    params: dict,
    now: datetime,
    *,
    feeds: tuple[Feed, ...],
    parse_fn: Callable[[str, bytes], ParseResult],
    universe: dict[str, str],
    session: Any,
    post: Callable[[list[dict]], dict],
    sleep: Callable[[float], None],
    rng: Any,
    clock: Callable[[], datetime],
    cooldown: Cooldown,
    by_name: dict[str, tuple[str, str]] | None = None,
) -> dict:
    """Run one NSE filings cycle (spec 5.1 to 5.4) and return the run result.

    Order: validate params, read the cooldown, set the deadline, then visit the
    enabled feeds from the rotation start. The random gap before each request is
    drawn inside `fetch_feed`, so this function does not sleep itself. Cooldown
    calls take `clock()` (the current time), not `now` (the run start).
    `by_name` (name_key to (symbol, ISIN), from company_reference.build_index) fills
    the symbol of items that carry only a company name; None skips that step.
    """
    try:
        cfg, enabled = _run_config(params, feeds)
    except _ConfigError as exc:
        return _run_result("failed", message=f"config:{exc.key}")
    if cooldown.active(EXCHANGE, clock()):
        return _run_result("skipped", message="exchange_cooldown")

    try:
        deadline_at = clock() + timedelta(seconds=cfg["run_deadline_s"])
    except OverflowError:
        return _run_result("failed", message="config:run_deadline_s")
    order = _rotation(enabled, now)
    try:
        per_feed_budget = timedelta(seconds=cfg["gap_max_s"] + cfg["request_timeout_s"])
        # The feed loop computes clock() + per_feed_budget, so it must fit the datetime range now.
        clock() + per_feed_budget
    except OverflowError:
        return _run_result("failed", message="config:gap_max_s")

    fetched = new = invalid = dropped = universe_rejected = feeds_ok = 0
    transient: list[str] = []
    fatal: list[str] = []
    kept_times: list[datetime] = []
    blocked_code: str | None = None
    post_failed = False
    invalid_stop = False
    mid_run_cooldown = False
    deadline_left: int | None = None

    for index, feed in enumerate(order):
        if clock() + per_feed_budget > deadline_at:
            deadline_left = len(order) - index
            break
        if cooldown.active(EXCHANGE, clock()):
            mid_run_cooldown = True
            break

        outcome = fetch_feed(
            feed,
            session=session,
            cfg=cfg,
            parse_fn=parse_fn,
            sleep=sleep,
            rng=rng,
            clock=clock,
            deadline_at=deadline_at,
        )
        if outcome.outcome == "blocked":
            blocked_code = feed.feed_code
            cooldown.block(EXCHANGE, clock(), f"blocked:{feed.feed_code}")
            break
        if outcome.outcome == "transient":
            transient.append(feed.feed_code)
            continue
        if outcome.outcome == "fatal":
            fatal.append(feed.feed_code)
            continue

        feeds_ok += 1
        fetched += len(outcome.items)
        dropped += outcome.dropped
        items = outcome.items if by_name is None else fill_from_name(outcome.items, by_name)
        kept, counts = filter_items(items, universe)
        universe_rejected += counts["universe"]
        rows = [to_event_row(feed, item) for item in kept]
        seen: set[str] = set()
        unique: list[dict] = []
        for row in rows:
            key = row["dedupe_key"]
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        rows = unique
        try:
            response = post(rows)
        except Exception:
            post_failed = True
            break
        new += int(response.get("inserted", 0))
        feed_invalid = int(response.get("invalid", 0))
        invalid += feed_invalid
        kept_times.extend(item["published_at"] for item in kept)
        if feed_invalid > 0:
            invalid_stop = True
            break

    if blocked_code is not None:
        return _run_result(
            "failed", fetched=fetched, new=new, times=kept_times,
            message=f"blocked:{blocked_code}",
        )
    if post_failed:
        return _run_result("failed", fetched=fetched, new=new, times=kept_times, message="api_error")

    # One reset per run, only when the exchange looked healthy throughout (spec 5.1 step 5).
    if feeds_ok and not mid_run_cooldown:
        cooldown.reset(EXCHANGE)
    if mid_run_cooldown and feeds_ok == 0:
        return _run_result("skipped", message="exchange_cooldown")
    if invalid_stop:
        return _run_result(
            "failed", fetched=fetched, new=new, times=kept_times, message=f"invalid:{invalid}",
        )

    parts = [f"failed:{code}" for code in transient] + [f"fatal:{code}" for code in fatal]
    if deadline_left is not None:
        if feeds_ok == 0:
            parts.insert(0, "deadline: 0 feeds fetched")
        else:
            parts.append(f"deadline: {deadline_left} feeds not fetched")
    if mid_run_cooldown:
        parts.append("exchange_cooldown")
    parts.append(f"rejected parse={dropped} universe={universe_rejected}")
    parts.append(f"invalid={invalid}")
    status = "failed" if fatal or feeds_ok == 0 else "ok"
    return _run_result(
        status, fetched=fetched, new=new, times=kept_times, message="; ".join(parts),
    )


def post_events(rows: list[dict], *, base_url: str, token: str, http, timeout_s: int) -> dict:
    """Post `home_events` rows to the API in batches of 500 and sum the counts (spec 6).

    Each batch is one POST to `<base_url>/internal/events/batch` with a bearer
    token. Any status outside 200 to 299 raises RuntimeError at once. The message
    holds the status code only, never the token, the body or the URL. Earlier
    batches stay posted, since the server's inserts are idempotent.
    """
    batch_size = 500
    url = base_url.rstrip("/") + "/internal/events/batch"
    totals = {"inserted": 0, "duplicates": 0, "invalid": 0}
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        resp = http.post(
            url,
            json={"rows": batch},
            headers={"Authorization": "Bearer " + token},
            timeout=timeout_s,
        )
        if not 200 <= resp.status_code <= 299:
            raise RuntimeError("events batch POST failed with HTTP %d" % resp.status_code)
        body = resp.json()
        totals["inserted"] += body["inserted"]
        totals["duplicates"] += body["duplicates"]
        totals["invalid"] += body["invalid"]
    return totals


# The NSE feed table (spec 4.0). Nothing calls FEEDS yet; run wiring is a later task.
_NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/"

FEEDS: tuple[Feed, ...] = (
    Feed("nse:Financial_Results", _NSE_RSS + "Financial_Results.xml", "results", "high_priority", True, False),
    Feed("nse:Integrated_Filing_Financials", _NSE_RSS + "Integrated_Filing_Financials.xml", "results", "high_priority", True, False),
    Feed("nse:Sast_Regulation29", _NSE_RSS + "Sast_Regulation29.xml", "insider_trade", "high_priority", True, False),
    Feed("nse:Sast_Regulation31", _NSE_RSS + "Sast_Regulation31.xml", "insider_trade", "high_priority", True, False),
    Feed("nse:Corporate_action", _NSE_RSS + "Corporate_action.xml", "corporate_action", "catalyst", True, False),
    Feed("nse:Corporate_Governance", _NSE_RSS + "Corporate_Governance.xml", "governance", "high_priority", True, False),
    Feed("nse:Related_Party_Trans", _NSE_RSS + "Related_Party_Trans.xml", "related_party", "high_priority", True, True),
    Feed("nse:Shareholding_Pattern", _NSE_RSS + "Shareholding_Pattern.xml", "shareholding", "catalyst", True, True),
)


_IST = ZoneInfo("Asia/Kolkata")
# NSE pubDate text, e.g. "03-Nov-2026 10:29:23": India local time, with no offset in the text.
_PUB_DATE_FORMAT = "%d-%b-%Y %H:%M:%S"
# nse:Sast_Regulation29 pubDate has no seconds, e.g. "03-Nov-2026 12:54" (spec 4.0).
_PUB_DATE_FORMAT_MINUTES = "%d-%b-%Y %H:%M"
_HEADLINE_MAX = 500


def _child_text(node: ET.Element, tag: str) -> str:
    """Text of the child `tag`, or "" when the child is missing or empty."""
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text


def _rss_item(
    node: ET.Element,
    date_format: str,
    date_fixup: Callable[[str], str] | None = None,
    company_from_title: Callable[[str], str] | None = None,
) -> dict | None:
    """Map one RSS <item> to a parsed item dict, or None when it must be dropped.

    title, link and pubDate must be non-empty after strip. description must be
    present but may be empty. The link is squashed and must start with http://
    or https:// (any case). The pubDate text goes through date_fixup when given,
    then strptime with date_format; a value that does not parse drops the item.
    company is company_from_title(squashed title) when given, else the squashed title.
    """
    if node.find("description") is None:
        return None
    title = _child_text(node, "title").strip()
    link = _squash(_child_text(node, "link"))
    pub_text = _child_text(node, "pubDate").strip()
    if not title or not link or not pub_text:
        return None
    if not link.lower().startswith(("http://", "https://")):
        return None
    try:
        if date_fixup is not None:
            pub_text = date_fixup(pub_text)
        published_at = datetime.strptime(pub_text, date_format).replace(tzinfo=_IST)
    except ValueError:
        return None
    description = _child_text(node, "description").strip()
    squashed_title = _squash(title)
    company = company_from_title(squashed_title) if company_from_title is not None else squashed_title
    return {
        "source_id": None,
        "source_url": link,
        "symbol": None,
        "isin": None,
        "company": company,
        "title": title,
        "description": description,
        "headline": (_squash(description) or squashed_title)[:_HEADLINE_MAX],
        "published_at": published_at,
    }


def _parse_rss_feed(
    body: bytes,
    date_format: str,
    date_fixup: Callable[[str], str] | None = None,
    company_from_title: Callable[[str], str] | None = None,
) -> ParseResult:
    """Parse an NSE RSS feed body into items (spec 4.0, 6). Shared by every RSS feed.

    Raises ParseError when the body is not XML, or when its root is not an rss
    element with a channel child (an HTML page served with status 200 is one).
    Items that miss a required field or have a bad link or pubDate are dropped
    and counted in `dropped`. date_format, date_fixup and company_from_title are
    passed to _rss_item for every item.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ParseError(str(exc)) from exc
    channel = root.find("channel") if root.tag == "rss" else None
    if channel is None:
        raise ParseError("feed is not an rss document with a channel")
    items: list[dict] = []
    dropped = 0
    for node in channel.findall("item"):
        item = _rss_item(node, date_format, date_fixup, company_from_title)
        if item is None:
            dropped += 1
        else:
            items.append(item)
    return ParseResult(items=items, dropped=dropped)


def _parse_financial_results(body: bytes) -> ParseResult:
    """Parse the nse:Financial_Results RSS feed (spec 4.0, 4.3, 6).

    symbol and isin are None because name resolution (spec 4.3) is not built
    yet. filter_items therefore rejects every item as "universe", which is
    intended until that work lands.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT)


def _parse_integrated_filing_financials(body: bytes) -> ParseResult:
    """Parse the nse:Integrated_Filing_Financials RSS feed (spec 4.0, 6).

    Its pubDate uses the NSE format with no fixup, and company is the whole
    squashed title, as for Financial_Results. Errors and drops are as in
    _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT)


def _parse_sast_regulation29(body: bytes) -> ParseResult:
    """Parse the nse:Sast_Regulation29 RSS feed (spec 4.0, 6).

    Its pubDate has no seconds, so it uses the minutes-only format with no
    fixup, and company is the whole squashed title, as for Financial_Results.
    Errors and drops are as in _parse_rss_feed. Repeated items are kept here;
    run_cycle drops repeated dedupe keys before posting (spec 4.2).
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT_MINUTES)


def _parse_sast_regulation31(body: bytes) -> ParseResult:
    """Parse the nse:Sast_Regulation31 RSS feed (spec 4.0, 6).

    Its pubDate has seconds, so it uses the NSE format with no fixup, and company
    is the whole squashed title, as for Financial_Results. Errors and drops are
    as in _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT)


# nse:Corporate_action titles are "<COMPANY> - Ex-Date: DD-Mon-YYYY" (spec 4.0).
_CORPORATE_ACTION_SEPARATOR = " - Ex-Date:"


def _corporate_action_company(squashed_title: str) -> str:
    """Company part of a Corporate_action title: the text before the first ' - Ex-Date:'.

    A title without the separator gives the whole squashed title (spec 4.0).
    """
    return squashed_title.partition(_CORPORATE_ACTION_SEPARATOR)[0].strip()


def _parse_corporate_action(body: bytes) -> ParseResult:
    """Parse the nse:Corporate_action RSS feed (spec 4.0, 6).

    Its pubDate uses the NSE format with no fixup. company is the title part
    before ' - Ex-Date:' (_corporate_action_company). Errors and drops are as in
    _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT, company_from_title=_corporate_action_company)


def _parse_corporate_governance(body: bytes) -> ParseResult:
    """Parse the nse:Corporate_Governance RSS feed (spec 4.0, 6).

    Its pubDate uses the NSE format with no fixup, and company is the whole
    squashed title, as for Financial_Results. The sample feed has no items
    (spec 4.0), so a channel with no item elements gives an empty result.
    Errors and drops are as in _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT)


# nse:Related_Party_Trans pubDate: some items use "DD-MON-YYYY HH:MM.SS" (a dot before the
# seconds), others "DD-MON-YYYY HH:MM:SS" (spec 4.0, decided 2026-11-11).
def _rpt_date_fixup(text: str) -> str:
    """Replace the dot before the seconds with a colon, so the NSE date format applies (spec 4.0).

    Colon-form pubDate text has no dot and is returned unchanged.
    """
    return text.replace(".", ":")


def _parse_related_party_trans(body: bytes) -> ParseResult:
    """Parse the nse:Related_Party_Trans RSS feed (spec 4.0, 6).

    pubDate uses the NSE format, after _rpt_date_fixup for the dot variant.
    company is the whole squashed title, as for Financial_Results. Errors and
    drops are as in _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT, date_fixup=_rpt_date_fixup)


def _parse_shareholding_pattern(body: bytes) -> ParseResult:
    """Parse the nse:Shareholding_Pattern RSS feed (spec 4.0, 6).

    Its pubDate uses the NSE format with no fixup, and company is the whole
    squashed title, as for Financial_Results. Errors and drops are as in
    _parse_rss_feed.
    """
    return _parse_rss_feed(body, _PUB_DATE_FORMAT)


PARSERS: dict[str, Callable[[bytes], ParseResult]] = {
    "nse:Financial_Results": _parse_financial_results,
    "nse:Integrated_Filing_Financials": _parse_integrated_filing_financials,
    "nse:Sast_Regulation29": _parse_sast_regulation29,
    "nse:Sast_Regulation31": _parse_sast_regulation31,
    "nse:Corporate_action": _parse_corporate_action,
    "nse:Corporate_Governance": _parse_corporate_governance,
    "nse:Related_Party_Trans": _parse_related_party_trans,
    "nse:Shareholding_Pattern": _parse_shareholding_pattern,
}


def parse(feed_code: str, body: bytes) -> ParseResult:
    """Parse one feed body with the parser registered for `feed_code` (spec 6).

    An unknown feed_code raises ValueError. That is a caller error, not a bad
    body, so it is not ParseError.
    """
    parser = PARSERS.get(feed_code)
    if parser is None:
        raise ValueError(f"no parser for feed_code: {feed_code!r}")
    return parser(body)
