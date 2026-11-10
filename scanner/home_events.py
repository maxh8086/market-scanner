"""Exchange filings for the home events feed (spec section 6).

T3a added `redact_error`. T3b adds `Feed`, `ParseError`, `ParseResult`,
`dedupe_key` and `to_event_row`. T3c adds `filter_items`, `classify_response`,
`FetchResult` and `Cooldown`. Later tasks add the feed table (FEEDS),
the parsers, and the fetch and run logic to this module.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

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


def dedupe_key(
    feed_code: str,
    source_id: str | None,
    source_url: str,
    published_at: datetime,
) -> str:
    """Key one feed item so a refetch of the same item gives the same key (spec 4.2).

    With a feed id the key is "<feed_code>:<source_id>". Without one it is
    "<feed_code>:" plus a SHA-256 of the link and the UTC publish time.
    `published_at` must be timezone-aware: a naive value would be read as
    machine-local time.
    """
    if source_id:
        return f"{feed_code}:{source_id}"
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    utc_iso = published_at.astimezone(timezone.utc).isoformat()
    digest = hashlib.sha256(f"{source_url}|{utc_iso}".encode()).hexdigest()
    return f"{feed_code}:{digest}"


def to_event_row(feed: Feed, item: dict) -> dict:
    """Map one parsed item (isin already filled by filter_items) to a `home_events` row.

    `exchange` comes from the "nse:" prefix of `feed_code`. BSE is deferred (Z2),
    so any other prefix is refused here rather than failing the API's CHECK.
    `published_at` is ISO 8601 with its UTC offset, as the API requires (4.6).
    """
    prefix, sep, _ = feed.feed_code.partition(":")
    if not sep or prefix != "nse":
        raise ValueError(f"unsupported feed_code: {feed.feed_code!r}")
    published_at = item["published_at"]
    if published_at.tzinfo is None:
        raise ValueError("published_at must be timezone-aware")
    source_id = item.get("source_id")
    return {
        "dedupe_key": dedupe_key(feed.feed_code, source_id, item["source_url"], published_at),
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

    `universe` maps symbol to ISIN (loaded once per run by `load_universe`).
    Returns (kept, counts). Kept items are copies, so the caller's dicts are not
    changed. An ISIN the feed supplied is kept as it is. `counts` always has the
    key "universe": the number of items rejected because their symbol is not in
    the universe.
    """
    kept: list[dict] = []
    counts = {"universe": 0}
    for item in items:
        isin = universe.get(item["symbol"])
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
