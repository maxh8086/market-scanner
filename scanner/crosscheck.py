"""Price cross-check: compare scan output against independent sources.

Compares a scan's LTP and ATH against NSE Bhavcopy (public daily prices) and
other sources via a fallback chain. Useful for detecting Upstox data anomalies.

Bhavcopy prices are UNADJUSTED. Corporate actions (splits, bonuses) can cause
divergences between our historical comparison window and a source's (e.g. a
52-week high from before a bonus). These are flagged as warnings, not failures.
"""
from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple, Optional

import pandas as pd
import requests


class PriceSnapshot(NamedTuple):
    """One day's OHLC for a symbol."""
    date: date
    open: float
    high: float
    low: float
    close: float
    last: float | None = None   # last traded price; NSE's `close` is a 30-min VWAP


class PriceSource(ABC):
    """Protocol for price data sources (e.g. NSE Bhavcopy, Upstox)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly name of this source (e.g. "NSE Bhavcopy")."""

    def last_on(self, symbol: str, on_date: date) -> float | None:
        """Last traded price on a date, if the source distinguishes it from close."""
        return None

    @abstractmethod
    def close_on(self, symbol: str, on_date: date) -> float | None:
        """Return the close price for a symbol on a specific date, or None."""

    @abstractmethod
    def high_between(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> float | None:
        """Return the highest high for a symbol in [from_date, to_date], or None."""


class ComparisonResult(NamedTuple):
    """One symbol's cross-check against a source."""

    symbol: str
    scan_ltp: float
    source_close: float | None
    diff_pct: float | None  # (scan_ltp - source_close) / source_close * 100
    verdict: str  # "OK", "DIVERGED", or "NO_DATA"
    source_name: str


class AthCheckResult(NamedTuple):
    """ATH cross-check result for one symbol."""

    symbol: str
    scan_ath_high: float
    scan_ath_date: date
    source_high: float | None
    source_high_date: date | None
    verdict: str  # "OK", "DIVERGED" (scan ATH < source high), or "NO_DATA"
    source_name: str


class NseBhavcopy(PriceSource):
    """NSE Bhavcopy CSV source.

    Bhavcopy is NSE's public daily security-wise bhavcopy file (equity series).
    This implementation caches downloads locally. Prices are unadjusted (corporate
    actions like splits/bonuses can create gaps).

    URL pattern: https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
    """

    # Minimal User-Agent to avoid bot detection while being respectful
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    BASE_URL = "https://nsearchives.nseindia.com/products/content"
    TIMEOUT_SECS = 30

    def __init__(self, cache_dir: Path | str = "data/bhavcopy"):
        """Initialize with optional local cache directory."""
        self.cache_dir = Path(cache_dir)
        self._cache: dict[date, dict[str, PriceSnapshot]] = {}

    @property
    def name(self) -> str:
        return "NSE Bhavcopy"

    def close_on(self, symbol: str, on_date: date) -> float | None:
        """Return close price for a symbol on a given date."""
        snapshot = self._get_snapshot(symbol, on_date)
        return snapshot.close if snapshot else None

    def last_on(self, symbol: str, on_date: date) -> float | None:
        snapshot = self._get_snapshot(symbol, on_date)
        return snapshot.last if snapshot else None

    def high_between(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> float | None:
        """Return the highest high in [from_date, to_date]."""
        if from_date > to_date:
            return None

        if (to_date - from_date).days > self.MAX_SPAN_DAYS:
            from_date = to_date - timedelta(days=self.MAX_SPAN_DAYS)

        snaps: list[PriceSnapshot] = []
        current = from_date
        while current <= to_date:
            snapshot = self._get_snapshot(symbol, current)
            if snapshot:
                snaps.append(snapshot)
            current += timedelta(days=1)

        # Bhavcopy is raw, not split/bonus adjusted, while the scan's history is.
        # A day-to-day close ratio outside 0.6-1.6 is far beyond any circuit limit,
        # so it is a corporate action: only highs after the last such break are
        # comparable with an adjusted series.
        start = 0
        for i in range(1, len(snaps)):
            ratio = snaps[i - 1].close / snaps[i].close if snaps[i].close else 1.0
            if ratio > 1.6 or ratio < 0.6:
                start = i
        highs = [x.high for x in snaps[start:]]

        return max(highs) if highs else None

    # Longest window high_between will walk. Bhavcopy is one file per day, so a
    # range is a request per weekday: unbounded, an all-time-high query would be
    # thousands of requests per symbol. It cannot answer that question.
    MAX_SPAN_DAYS = 90

    def _get_snapshot(self, symbol: str, on_date: date) -> PriceSnapshot | None:
        """One symbol's OHLC on one day, from the day's whole-market file."""
        return self._day(on_date).get(symbol)

    def _day(self, on_date: date) -> dict[str, PriceSnapshot]:
        """Every EQ symbol's OHLC on a date: memory, then disk, then NSE once.

        A date that cannot be fetched (weekend, holiday, outage) is remembered as
        empty for the life of this object, so a missing day costs one request
        rather than one per symbol.
        """
        if on_date in self._cache:
            return self._cache[on_date]
        day: dict[str, PriceSnapshot] = {}
        if on_date.weekday() < 5:            # NSE publishes nothing on weekends
            day = self._load_day_file(on_date)
            if not day:
                day = self._fetch_day(on_date)
        self._cache[on_date] = day
        return day

    def _load_day_file(self, on_date: date) -> dict[str, PriceSnapshot]:
        """Load a day's cached file whole; empty if absent or unreadable."""
        cache_file = self.cache_dir / f"bhavcopy_{on_date.strftime('%Y%m%d')}.csv"
        if not cache_file.exists():
            return {}
        try:
            return self._parse_cache_csv(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}     # malformed: fall through to a re-fetch

    def _save_to_cache_file(self, on_date: date, day_data: dict[str, PriceSnapshot]) -> None:
        """Save a day's bhavcopy to the cache directory."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / f"bhavcopy_{on_date.strftime('%Y%m%d')}.csv"

        # Write as CSV: symbol,date,open,high,low,close
        with open(cache_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE", "LAST"])
            for symbol, snapshot in sorted(day_data.items()):
                writer.writerow(
                    [
                        symbol,
                        snapshot.date.isoformat(),
                        snapshot.open,
                        snapshot.high,
                        snapshot.low,
                        snapshot.close,
                        "" if snapshot.last is None else snapshot.last,
                    ]
                )

    def _fetch_day(self, on_date: date) -> dict[str, PriceSnapshot]:
        """Fetch one day's bhavcopy from NSE, cache it to disk, return all symbols."""
        url = f"{self.BASE_URL}/sec_bhavdata_full_{on_date.strftime('%d%m%Y')}.csv"
        try:
            resp = requests.get(url, timeout=self.TIMEOUT_SECS,
                                headers={"User-Agent": self.USER_AGENT})
            resp.raise_for_status()
            day_data = self._parse_bhavcopy_csv(resp.text)
        except Exception:
            return {}
        if day_data:
            self._save_to_cache_file(on_date, day_data)
        return day_data

    def _parse_cache_csv(self, csv_text: str) -> dict[str, PriceSnapshot]:
        """Parse our own cache format: SYMBOL,DATE,OPEN,HIGH,LOW,CLOSE."""
        result: dict[str, PriceSnapshot] = {}
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            return result

        for row in reader:
            try:
                symbol = row.get("SYMBOL", "").strip().upper()
                if not symbol:
                    continue

                snap_date = pd.to_datetime(row.get("DATE", "")).date()
                open_price = float(row.get("OPEN", 0))
                high_price = float(row.get("HIGH", 0))
                low_price = float(row.get("LOW", 0))
                close_price = float(row.get("CLOSE", 0))
                last_raw = (row.get("LAST") or "").strip()
                last_price = float(last_raw) if last_raw else None

                result[symbol] = PriceSnapshot(
                    date=snap_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    last=last_price,
                )
            except (ValueError, TypeError):
                continue

        return result

    def _parse_bhavcopy_csv(self, csv_text: str) -> dict[str, PriceSnapshot]:
        """Parse NSE sec_bhavdata_full (EQ and BE series) into symbol -> snapshot.

        The real file pads every header and value with spaces ("SYMBOL, SERIES,
        ..." / "20MICRONS, EQ, ...") and names its columns OPEN_PRICE, HIGH_PRICE,
        LOW_PRICE, CLOSE_PRICE and DATE1 ("28-Sep-2026"). The short names OPEN,
        HIGH, LOW, CLOSE and TIMESTAMP (the older archive layout) are accepted too.
        """
        result: dict[str, PriceSnapshot] = {}
        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)
        if not header:
            return result
        col = {name.strip().upper(): i for i, name in enumerate(header)}

        def idx(*names: str) -> int | None:
            for n in names:
                if n in col:
                    return col[n]
            return None

        i_sym, i_ser = idx("SYMBOL"), idx("SERIES")
        i_open, i_high = idx("OPEN_PRICE", "OPEN"), idx("HIGH_PRICE", "HIGH")
        i_low, i_close = idx("LOW_PRICE", "LOW"), idx("CLOSE_PRICE", "CLOSE")
        i_date = idx("DATE1", "TIMESTAMP", "DATE")
        i_last = idx("LAST_PRICE", "LAST")
        if None in (i_sym, i_ser, i_open, i_high, i_low, i_close, i_date):
            return result

        for row in reader:
            try:
                if row[i_ser].strip() not in ("EQ", "BE"):   # BE = trade-for-trade, same securities
                    continue
                symbol = row[i_sym].strip().upper()
                if not symbol:
                    continue
                if row[i_ser].strip() == "BE" and symbol in result:
                    continue          # EQ, when a symbol has both, is authoritative
                date_str = row[i_date].strip()
                if "-" not in date_str:
                    continue
                result[symbol] = PriceSnapshot(
                    date=pd.to_datetime(date_str).date(),
                    open=float(row[i_open]), high=float(row[i_high]),
                    low=float(row[i_low]), close=float(row[i_close]),
                    last=float(row[i_last]) if i_last is not None else None,
                )
            except (ValueError, TypeError, IndexError):
                continue
        return result


class FallbackChain(PriceSource):
    """Try multiple price sources in order, recording which answered each query."""

    def __init__(self, sources: list[PriceSource]):
        """Initialize with an ordered list of sources."""
        if not sources:
            raise ValueError("FallbackChain requires at least one source")
        self.sources = sources
        self._provenance: dict[tuple[str, date], str] = {}  # (symbol, date) -> source name

    @property
    def name(self) -> str:
        return f"Chain({', '.join(s.name for s in self.sources)})"

    def get_provenance(self, symbol: str, on_date: date) -> str | None:
        """Return which source answered this query (if any)."""
        return self._provenance.get((symbol, on_date))

    def close_on(self, symbol: str, on_date: date) -> float | None:
        """Try each source in order; record which one answered."""
        for source in self.sources:
            result = source.close_on(symbol, on_date)
            if result is not None:
                self._provenance[(symbol, on_date)] = source.name
                return result
        return None

    def high_between(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> float | None:
        """Try each source in order; record which one answered."""
        for source in self.sources:
            result = source.high_between(symbol, from_date, to_date)
            if result is not None:
                # Use from_date as proxy for the range query
                self._provenance[(symbol, from_date)] = source.name
                return result
        return None


def compare(
    scan_df: pd.DataFrame,
    source: PriceSource,
    on_date: date,
    tol_pct: float = 0.5,
) -> pd.DataFrame:
    """Compare scan's LTP against a price source.

    Args:
        scan_df: DataFrame with columns including 'symbol' and 'ltp'.
        source: PriceSource to compare against.
        on_date: The date of the scan (source should have close on this date).
        tol_pct: Tolerance in percent for OK verdict (default 0.5%).

    Returns:
        DataFrame with columns: symbol, scan_ltp, source_close, diff_pct, verdict.
        Verdict is "OK" (within tolerance), "DIVERGED" (outside tolerance), or
        "NO_DATA" (source has no price for that symbol).
    """
    results: list[ComparisonResult] = []

    for _, row in scan_df.iterrows():
        symbol = str(row["symbol"]).strip().upper()
        scan_ltp = float(row["ltp"])

        source_close = source.close_on(symbol, on_date)
        source_last = source.last_on(symbol, on_date)

        if source_close is None:
            results.append(
                ComparisonResult(
                    symbol=symbol,
                    scan_ltp=scan_ltp,
                    source_close=None,
                    diff_pct=None,
                    verdict="NO_DATA",
                    source_name=source.name,
                )
            )
        else:
            # NSE's close is a 30-minute VWAP, not the last trade, and a quote
            # taken after the bell can legitimately return either. Diverged only
            # if the scan matches neither.
            diff_pct = (scan_ltp - source_close) / source_close * 100
            if source_last:
                diff_last = (scan_ltp - source_last) / source_last * 100
                if abs(diff_last) < abs(diff_pct):
                    diff_pct = diff_last
            verdict = "OK" if abs(diff_pct) <= tol_pct else "DIVERGED"
            results.append(
                ComparisonResult(
                    symbol=symbol,
                    scan_ltp=scan_ltp,
                    source_close=source_close,
                    diff_pct=diff_pct,
                    verdict=verdict,
                    source_name=source.name,
                )
            )

    return pd.DataFrame(
        [
            {
                "symbol": r.symbol,
                "scan_ltp": r.scan_ltp,
                "source_close": r.source_close,
                "diff_pct": r.diff_pct,
                "verdict": r.verdict,
            }
            for r in results
        ]
    )


def check_ath(
    scan_df: pd.DataFrame,
    source: PriceSource,
    tol_pct: float = 0.5,
    on_date: date | None = None,
    lookback_days: int = 45,
) -> pd.DataFrame:
    """Verify scan's ATH high against source's max high in the history window.

    The scan's ath_high should be >= any high the source reports up to the
    scan date. If ath_date is within our source window, ath_high should also
    equal the source's max high within tolerance.

    Args:
        scan_df: DataFrame with columns 'symbol', 'ath_high', 'ath_date'.
        source: PriceSource to query for historical highs.
        tol_pct: Tolerance in percent.

    Returns:
        DataFrame with columns: symbol, scan_ath_high, scan_ath_date,
        source_high, source_high_date, verdict.
        Verdict is "OK" (ATH high matches), "DIVERGED" (scan ATH < source high),
        or "NO_DATA" (source has no data for the window).
    """
    results: list[AthCheckResult] = []

    for _, row in scan_df.iterrows():
        symbol = str(row["symbol"]).strip().upper()
        scan_ath_high = float(row["ath_high"])
        scan_ath_date = pd.to_datetime(row["ath_date"]).date()

        # Bounded window: a daily-file source cannot answer "highest ever". This
        # is a lower-bound check -- the scan's ATH must not sit below a high the
        # independent source saw in the last `lookback_days` (catches a missed
        # spike or an unadjusted series), not a proof that the ATH is the ATH.
        window_end = on_date or scan_ath_date
        source_high = source.high_between(
            symbol, window_end - timedelta(days=lookback_days), window_end)

        if source_high is None:
            results.append(
                AthCheckResult(
                    symbol=symbol,
                    scan_ath_high=scan_ath_high,
                    scan_ath_date=scan_ath_date,
                    source_high=None,
                    source_high_date=None,
                    verdict="NO_DATA",
                    source_name=source.name,
                )
            )
        else:
            # Scan ATH should be >= source high (or within tolerance below)
            # If scan is lower, that's a divergence (real case: unadjusted vs adjusted)
            if scan_ath_high >= source_high - (source_high * tol_pct / 100):
                verdict = "OK"
            else:
                verdict = "DIVERGED"

            results.append(
                AthCheckResult(
                    symbol=symbol,
                    scan_ath_high=scan_ath_high,
                    scan_ath_date=scan_ath_date,
                    source_high=source_high,
                    source_high_date=None,  # We don't track the exact date from high_between
                    verdict=verdict,
                    source_name=source.name,
                )
            )

    return pd.DataFrame(
        [
            {
                "symbol": r.symbol,
                "scan_ath_high": r.scan_ath_high,
                "scan_ath_date": r.scan_ath_date,
                "source_high": r.source_high,
                "verdict": r.verdict,
            }
            for r in results
        ]
    )


def summarize_comparison(result_df: pd.DataFrame) -> dict:
    """Summarize comparison results: counts by verdict and worst offenders."""
    verdicts = result_df["verdict"].value_counts().to_dict()
    ok_count = verdicts.get("OK", 0)
    diverged_count = verdicts.get("DIVERGED", 0)
    no_data_count = verdicts.get("NO_DATA", 0)

    # Top 5 diverged (by absolute diff_pct) - only if those columns exist
    worst = []
    if "diff_pct" in result_df.columns:
        diverged_rows = result_df[result_df["verdict"] == "DIVERGED"].copy()
        if not diverged_rows.empty:
            diverged_rows["abs_diff"] = diverged_rows["diff_pct"].abs()
            cols = ["symbol"]
            if "scan_ltp" in diverged_rows.columns:
                cols.append("scan_ltp")
            if "source_close" in diverged_rows.columns:
                cols.append("source_close")
            cols.append("diff_pct")
            worst = (
                diverged_rows.nlargest(5, "abs_diff")[cols]
                .to_dict("records")
            )

    return {
        "ok": int(ok_count),
        "diverged": int(diverged_count),
        "no_data": int(no_data_count),
        "total": len(result_df),
        "worst_divergences": worst,
    }
