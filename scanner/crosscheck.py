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


class PriceSource(ABC):
    """Protocol for price data sources (e.g. NSE Bhavcopy, Upstox)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Friendly name of this source (e.g. "NSE Bhavcopy")."""

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

    def high_between(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
    ) -> float | None:
        """Return the highest high in [from_date, to_date]."""
        if from_date > to_date:
            return None

        highs: list[float] = []
        current = from_date
        while current <= to_date:
            snapshot = self._get_snapshot(symbol, current)
            if snapshot:
                highs.append(snapshot.high)
            current += timedelta(days=1)

        return max(highs) if highs else None

    def _get_snapshot(self, symbol: str, on_date: date) -> PriceSnapshot | None:
        """Fetch and cache one day's OHLC for a symbol."""
        # Check in-memory cache first
        if on_date in self._cache:
            return self._cache[on_date].get(symbol)

        # Try to load from disk
        snapshot = self._load_from_cache_file(symbol, on_date)
        if snapshot:
            if on_date not in self._cache:
                self._cache[on_date] = {}
            self._cache[on_date][symbol] = snapshot
            return snapshot

        # Try to fetch from NSE
        snapshot = self._fetch_from_nse(symbol, on_date)
        if snapshot:
            if on_date not in self._cache:
                self._cache[on_date] = {}
            self._cache[on_date][symbol] = snapshot
            self._save_to_cache_file(on_date, self._cache[on_date])
            return snapshot

        return None

    def _load_from_cache_file(self, symbol: str, on_date: date) -> PriceSnapshot | None:
        """Load a day's bhavcopy from the cache directory."""
        cache_file = self.cache_dir / f"bhavcopy_{on_date.strftime('%Y%m%d')}.csv"
        if not cache_file.exists():
            return None

        try:
            # Try to parse as cached format first (SYMBOL,DATE,OPEN,HIGH,LOW,CLOSE)
            data = self._parse_cache_csv(cache_file.read_text(encoding="utf-8"))
            return data.get(symbol)
        except Exception:
            # Malformed or missing file; will re-fetch
            return None

    def _save_to_cache_file(self, on_date: date, day_data: dict[str, PriceSnapshot]) -> None:
        """Save a day's bhavcopy to the cache directory."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / f"bhavcopy_{on_date.strftime('%Y%m%d')}.csv"

        # Write as CSV: symbol,date,open,high,low,close
        with open(cache_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["SYMBOL", "DATE", "OPEN", "HIGH", "LOW", "CLOSE"])
            for symbol, snapshot in sorted(day_data.items()):
                writer.writerow(
                    [
                        symbol,
                        snapshot.date.isoformat(),
                        snapshot.open,
                        snapshot.high,
                        snapshot.low,
                        snapshot.close,
                    ]
                )

    def _fetch_from_nse(self, symbol: str, on_date: date) -> PriceSnapshot | None:
        """Fetch one day's bhavcopy from NSE and cache all symbols in it."""
        url = f"{self.BASE_URL}/sec_bhavdata_full_{on_date.strftime('%d%m%Y')}.csv"

        try:
            resp = requests.get(
                url,
                timeout=self.TIMEOUT_SECS,
                headers={"User-Agent": self.USER_AGENT},
            )
            resp.raise_for_status()
        except requests.RequestException:
            return None

        try:
            day_data = self._parse_bhavcopy_csv(resp.text)
        except Exception:
            return None

        # Cache all symbols from this day
        if day_data:
            self._cache[on_date] = day_data
            self._save_to_cache_file(on_date, day_data)

        return day_data.get(symbol)

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

                result[symbol] = PriceSnapshot(
                    date=snap_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                )
            except (ValueError, TypeError):
                continue

        return result

    def _parse_bhavcopy_csv(self, csv_text: str) -> dict[str, PriceSnapshot]:
        """Parse NSE Bhavcopy CSV (EQ series only) into symbol -> snapshot."""
        result: dict[str, PriceSnapshot] = {}

        # NSE Bhavcopy format: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, ...
        # We only want EQ series (equity spot market).
        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            return result

        for row in reader:
            if not row or row.get("SERIES") != "EQ":
                continue

            try:
                symbol = row.get("SYMBOL", "").strip().upper()
                if not symbol:
                    continue

                open_price = float(row.get("OPEN", 0))
                high_price = float(row.get("HIGH", 0))
                low_price = float(row.get("LOW", 0))
                close_price = float(row.get("CLOSE", 0))

                # Extract date from TIMESTAMP or DATE field (format varies)
                date_str = row.get("TIMESTAMP") or row.get("DATE", "")
                if "-" in date_str:
                    # Format: DD-MMM-YYYY or YYYY-MM-DD
                    try:
                        snap_date = pd.to_datetime(date_str).date()
                    except Exception:
                        continue
                else:
                    continue

                result[symbol] = PriceSnapshot(
                    date=snap_date,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                )
            except (ValueError, TypeError):
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
            diff_pct = (scan_ltp - source_close) / source_close * 100
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

        # Query source for the highest high from listing to scan date
        # (we don't know the actual listing date, so use a far-past date)
        far_past = date(1990, 1, 1)
        source_high = source.high_between(symbol, far_past, scan_ath_date)

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
