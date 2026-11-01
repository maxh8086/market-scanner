"""Moving-average trend indicators.

Pure functions over a close series -- no I/O, no broker dependency, same
discipline as `scanner.ath`. The caller supplies closes oldest-first and is
responsible for appending today's live price as the final element, because
`history.py` deliberately never caches today's forming candle.
"""

from __future__ import annotations

from typing import Optional, Sequence

EMA_PERIOD = 50
SMA_PERIOD = 200

# Trend labels, in the order a filter would care about.
TREND_UPTREND = "UPTREND"          # above both -- the demerger/expansion pre-filter
TREND_ABOVE_50 = "ABOVE_50_ONLY"   # short-term recovery, long-term still broken
TREND_ABOVE_200 = "ABOVE_200_ONLY"  # long-term intact, short-term pullback
TREND_BELOW_BOTH = "BELOW_BOTH"
# Not enough history (recent IPO). Deliberately NOT "n/a": that string is in
# pandas' default na_values, so a CSV round-trip would silently turn the label
# back into NaN and lose the distinction from a genuinely absent value.
TREND_UNKNOWN = "INSUFFICIENT_HISTORY"


def sma(closes: Sequence[float], period: int = SMA_PERIOD) -> Optional[float]:
    """Simple moving average of the last `period` closes, or None if short."""
    if period <= 0 or len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


def ema(closes: Sequence[float], period: int = EMA_PERIOD) -> Optional[float]:
    """Exponential moving average, SMA-seeded and iterated to the last close.

    Seeded on the *oldest* `period` closes and walked forward over the whole
    series, so with several years of candles the result has fully converged and
    does not depend on where the series happens to start.
    """
    if period <= 0 or len(closes) < period:
        return None
    alpha = 2.0 / (period + 1)
    value = sum(closes[:period]) / period
    for close in closes[period:]:
        value = close * alpha + value * (1 - alpha)
    return value


def classify_trend(
    price: float, ema_value: Optional[float], sma_value: Optional[float]
) -> str:
    """Label a price against its two moving averages.

    Returns TREND_UNKNOWN when either average is missing: a stock listed 190
    days ago has no honest 200 DMA, and reporting BELOW_BOTH for it
    would be a fabricated bearish signal rather than missing data.
    """
    if ema_value is None or sma_value is None:
        return TREND_UNKNOWN
    above_ema = price > ema_value
    above_sma = price > sma_value
    if above_ema and above_sma:
        return TREND_UPTREND
    if above_ema:
        return TREND_ABOVE_50
    if above_sma:
        return TREND_ABOVE_200
    return TREND_BELOW_BOTH


def compute_trend(closes: Sequence[float], price: float) -> dict:
    """Bundle both averages and the trend label for one symbol.

    `closes` is oldest-first and must already include `price` as its last
    element if you want the averages to include today.
    """
    ema_value = ema(closes, EMA_PERIOD)
    sma_value = sma(closes, SMA_PERIOD)
    return {
        "ema50": round(ema_value, 2) if ema_value is not None else None,
        "sma200": round(sma_value, 2) if sma_value is not None else None,
        "above_ema50": None if ema_value is None else price > ema_value,
        "above_sma200": None if sma_value is None else price > sma_value,
        "trend": classify_trend(price, ema_value, sma_value),
    }
