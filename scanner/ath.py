"""Pure ATH / distance / bucketing logic — no I/O, no Kite, no pandas.

Kept import-clean so it can be reused directly by other tools (e.g. an
equity-agent platform) without pulling in the scanning/reporting machinery.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

RECENT_IPO_THRESHOLD_DAYS = 365


@dataclass(frozen=True)
class Candle:
    d: date
    high: float
    close: float


@dataclass(frozen=True)
class AthStats:
    ath_high: float
    ath_date: date
    ath_close: float
    ath_close_date: date
    first_date: date
    last_date: date


@dataclass(frozen=True)
class ScanResult:
    ath_high: float
    ath_date: date
    ath_close: float
    distance_pct: float
    bucket: str
    days_since_ath: int
    listed_days: int
    recent_ipo: bool


def compute_ath(candles: Sequence[Candle]) -> AthStats:
    """Compute ATH-by-high, ATH-by-close, and the history's date span."""
    if not candles:
        raise ValueError("compute_ath requires at least one candle")

    ath_candle = max(candles, key=lambda c: c.high)
    ath_close_candle = max(candles, key=lambda c: c.close)
    dates = [c.d for c in candles]

    return AthStats(
        ath_high=ath_candle.high,
        ath_date=ath_candle.d,
        ath_close=ath_close_candle.close,
        ath_close_date=ath_close_candle.d,
        first_date=min(dates),
        last_date=max(dates),
    )


def is_new_ath_today(prior_candles: Sequence[Candle], today_high: float) -> bool:
    """True when today's high is >= the highest high of all earlier days.

    With no earlier days at all (a brand-new listing's first session), this
    is vacuously a new ATH.
    """
    if not prior_candles:
        return True
    prior_high = max(c.high for c in prior_candles)
    return today_high >= prior_high


def distance_pct(ath_high: float, ltp: float) -> float:
    """Percent LTP sits below the ATH high. Clamped at 0 for LTP >= ATH."""
    if ath_high <= 0:
        raise ValueError("ath_high must be positive")
    d = (ath_high - ltp) / ath_high * 100
    return max(d, 0.0)


_BREAKPOINTS = (5, 15)


def _bucket_boundaries(max_dist: float) -> list[tuple[float, str]]:
    """(upper_bound, label) pairs for the 0-5% / 5-15% / 15-max_dist% scheme,
    collapsing breakpoints that fall at or beyond max_dist so a tighter
    --max-dist (e.g. 10) still produces sensible buckets like 0-5%/5-10%."""
    breakpoints = [b for b in _BREAKPOINTS if b < max_dist]
    bounds: list[tuple[float, str]] = []
    lower = 0
    for bp in breakpoints:
        bounds.append((bp, f"{lower:g}-{bp:g}%"))
        lower = bp
    bounds.append((max_dist, f"{lower:g}-{max_dist:g}%"))
    return bounds


def bucket_labels(max_dist: float = 26.0) -> list[str]:
    """Ordered (excluding NEW_ATH_TODAY) bucket labels for this max_dist."""
    return [label for _, label in _bucket_boundaries(max_dist)]


def classify_bucket(dist_pct: float, is_new_ath: bool, max_dist: float = 26.0) -> Optional[str]:
    """Return the bucket label for a given distance, or None if it should
    be dropped (more than max_dist below ATH)."""
    if is_new_ath:
        return "NEW_ATH_TODAY"
    if dist_pct > max_dist:
        return None
    for upper, label in _bucket_boundaries(max_dist):
        if dist_pct <= upper:
            return label
    return None  # unreachable: dist_pct <= max_dist is guaranteed above


def listed_days(first_date: date, as_of: date) -> int:
    return (as_of - first_date).days


def is_recent_ipo(days_listed: int, threshold_days: int = RECENT_IPO_THRESHOLD_DAYS) -> bool:
    return days_listed < threshold_days


def scan_symbol(
    prior_candles: Sequence[Candle],
    today_high: float,
    ltp: float,
    as_of: date,
    max_dist: float = 26.0,
) -> Optional[ScanResult]:
    """Classify one symbol given its history up to (but excluding) today,
    today's high, and the current LTP. Returns None if it should be
    dropped (more than max_dist below ATH).

    `prior_candles` may be empty (brand-new listing).
    """
    new_ath = is_new_ath_today(prior_candles, today_high)

    if prior_candles:
        prior_stats = compute_ath(prior_candles)
        first_date = prior_stats.first_date
        prior_ath_high = prior_stats.ath_high
        prior_ath_date = prior_stats.ath_date
        prior_ath_close = prior_stats.ath_close
    else:
        first_date = as_of
        prior_ath_high = float("-inf")
        prior_ath_date = as_of
        prior_ath_close = float("-inf")

    if new_ath and today_high >= prior_ath_high:
        ath_high = today_high
        ath_date = as_of
    else:
        ath_high = prior_ath_high
        ath_date = prior_ath_date

    # ath_close tracks the highest daily close; today's close isn't known
    # intraday, so it only participates via prior_candles (which the caller
    # may include today's candle in, once the day is final).
    ath_close = prior_ath_close if prior_candles else ltp

    dist = distance_pct(ath_high, ltp)
    bucket = classify_bucket(dist, new_ath, max_dist)
    if bucket is None:
        return None

    days_listed = listed_days(first_date, as_of)

    return ScanResult(
        ath_high=ath_high,
        ath_date=ath_date,
        ath_close=ath_close,
        distance_pct=dist,
        bucket=bucket,
        days_since_ath=(as_of - ath_date).days,
        listed_days=days_listed,
        recent_ipo=is_recent_ipo(days_listed),
    )
