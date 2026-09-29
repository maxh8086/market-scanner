"""Excel / CSV / terminal output for the scan results."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from scanner.ath import bucket_labels

BASE_COLUMNS = [
    "symbol",
    "company",
    "industry",
    "ltp",
    "today_high",
    "ath_high",
    "ath_date",
    "ath_close",
    "distance_pct",
    "bucket",
    "days_since_ath",
    "listed_days",
    "recent_ipo",
]

TREND_COLUMNS = [
    "ema50",
    "sma200",
    "above_ema50",
    "above_sma200",
    "trend",
]

FACTOR_COLUMNS = [
    "bonus_issue",
    "demerger",
    "orderbook_signal",
    "expansion_signal",
    "factors_matched",
]


def _get_output_columns(df: pd.DataFrame) -> list[str]:
    """Return the actual columns to output, adaptive based on what's present in the DataFrame.

    Trend and factor groups are both optional -- `--no-factors` omits one, and a
    DataFrame from an older run may lack either -- so neither is allowed to turn
    a missing column into a KeyError at write time.
    """
    cols = BASE_COLUMNS.copy()
    for group in (TREND_COLUMNS, FACTOR_COLUMNS):
        cols.extend(c for c in group if c in df.columns)
    return cols


def _bucket_order(max_dist: float) -> list[str]:
    return ["NEW_ATH_TODAY"] + bucket_labels(max_dist)


def sort_results(df: pd.DataFrame, max_dist: float = 26.0) -> pd.DataFrame:
    if df.empty:
        return df
    order = _bucket_order(max_dist)
    df = df.copy()
    df["_bucket_order"] = df["bucket"].map(lambda b: order.index(b) if b in order else len(order))
    df = df.sort_values(["_bucket_order", "distance_pct"]).drop(columns="_bucket_order")
    return df.reset_index(drop=True)


def write_outputs(
    df: pd.DataFrame, as_of: str, max_dist: float = 26.0, output_dir: str = "output"
) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bucket_order = _bucket_order(max_dist)

    output_cols = _get_output_columns(df)
    df = sort_results(df, max_dist)[output_cols] if not df.empty else pd.DataFrame(columns=output_cols)

    csv_path = out_dir / f"ath_scan_{as_of}.csv"
    xlsx_path = out_dir / f"ath_scan_{as_of}.xlsx"

    df.to_csv(csv_path, index=False)

    # A workbook open in Excel is locked, and a full scan spends minutes of
    # fetching before it reaches this line -- so a lock must not destroy the
    # run's output. Fall back to a suffixed filename and report where it went.
    try:
        with open(xlsx_path, "a+b"):
            pass
    except PermissionError:
        stamp = datetime.now().strftime("%H%M%S")
        xlsx_path = out_dir / f"ath_scan_{as_of}_{stamp}.xlsx"
        print(
            f"Warning: {out_dir / f'ath_scan_{as_of}.xlsx'} is locked "
            f"(open in Excel?) -- writing {xlsx_path.name} instead."
        )

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for bucket in bucket_order:
            sheet_df = df[df["bucket"] == bucket]
            sheet_name = bucket.replace("%", "pct")
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)

        summary_rows = []
        summary_rows.append(("Total scanned", len(df)))
        summary_rows.append(("", ""))
        summary_rows.append(("By bucket", ""))
        for bucket in bucket_order:
            summary_rows.append((bucket, int((df["bucket"] == bucket).sum())))
        summary_rows.append(("", ""))
        summary_rows.append(("By industry", ""))
        if not df.empty:
            for industry, count in df["industry"].value_counts().items():
                summary_rows.append((industry, int(count)))

        if not df.empty and "trend" in df.columns:
            summary_rows.append(("", ""))
            summary_rows.append(("By trend (50 EMA / 200 SMA)", ""))
            for label, count in df["trend"].value_counts().items():
                summary_rows.append((f"  {label}", int(count)))

        # Add factors_matched distribution if present
        if not df.empty and "factors_matched" in df.columns:
            summary_rows.append(("", ""))
            summary_rows.append(("Factors matched distribution", ""))
            for factor_count in sorted(df["factors_matched"].unique()):
                count = int((df["factors_matched"] == factor_count).sum())
                summary_rows.append((f"  {factor_count} factors", count))

        summary_df = pd.DataFrame(summary_rows, columns=["Metric", "Value"])
        summary_df.to_excel(writer, sheet_name="Summary", index=False)

    return csv_path, xlsx_path


def print_summary(df: pd.DataFrame, as_of: str, intraday: bool, max_dist: float = 26.0) -> None:
    console = Console()
    label = "INTRADAY" if intraday else "FINAL"
    console.print(f"\n[bold]ATH Scan — {as_of} ({label})[/bold]\n")

    table = Table(title="Summary by bucket")
    table.add_column("Bucket")
    table.add_column("Count", justify="right")
    for bucket in _bucket_order(max_dist):
        count = int((df["bucket"] == bucket).sum()) if not df.empty else 0
        table.add_row(bucket, str(count))
    console.print(table)

    if df.empty:
        console.print("\n[yellow]No symbols matched.[/yellow]")
        return

    if "trend" in df.columns:
        trend_table = Table(title="Trend (50 EMA / 200 SMA)")
        trend_table.add_column("Trend")
        trend_table.add_column("Count", justify="right")
        for label, count in df["trend"].value_counts().items():
            trend_table.add_row(str(label), str(int(count)))
        console.print(trend_table)

    top = sort_results(df, max_dist).head(20)
    detail = Table(title="Top matches (first 20)")
    for col in ["symbol", "bucket", "distance_pct", "ltp", "ath_high", "ath_date", "recent_ipo"]:
        detail.add_column(col)
    for _, row in top.iterrows():
        detail.add_row(
            str(row["symbol"]),
            str(row["bucket"]),
            f"{row['distance_pct']:.2f}",
            f"{row['ltp']:.2f}",
            f"{row['ath_high']:.2f}",
            str(row["ath_date"]),
            str(row["recent_ipo"]),
        )
    console.print(detail)


def write_skipped(skipped: list[dict], path: str = "logs/skipped.csv") -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(skipped, columns=["symbol", "company", "reason"])
    df.to_csv(out_path, index=False)
