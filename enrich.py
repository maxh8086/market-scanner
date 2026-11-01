"""Enrichment stages for an ATH scan: fundamentals, filing values, LLM, report.

Deliberately a separate script from `ath_scan.py`. The scan itself must stay a
few minutes so it can run daily at 4 PM; these stages fetch hundreds of PDFs and
may run a local model for hours. Splitting them means a slow stage never delays
the scan, and a stage that dies halfway can be re-run without redoing the rest.

Every stage is idempotent and resumable: work already in the document store is
skipped, so re-running after an interruption costs only what is left.

    python enrich.py --fundamentals          # screener: mcap, PE, ROCE, pledge
    python enrich.py --filings               # order/expansion/guidance PDFs
    python enrich.py --llm                   # local model over stored text
    python enrich.py --report                # join it all into a csv
    python enrich.py --report --timesfm      # ... and run TimesFM as well
    python enrich.py --all                   # in the right order
    python enrich.py --stats                 # what is in the store

Stage order matters only in that `--report` needs the others to have run;
`--llm` reads text that `--filings` stored, and will say so if it is missing.

`--report` also computes the forward-looking columns -- three quarters of
revenue, the same forward year implied by the order book, management's own
guidance set against price action, each stock's volatility regime, and one
market-wide order-intensity read. These are derived from the local caches, so
they cost no network calls, and they are merged in *after* the ranking so a
forecast can never reorder the sheet. `--no-forecast` omits them.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

from scanner.constituents import load_constituents
from scanner import (docstore, factors, forecast, fundamentals, graph, history,
                     intensity, llm, orderval, revenue, significance,
                     volatility)

OUTPUT_DIR = Path("output")
LOGS_DIR = Path("logs")

# Filing kinds, as stored on each document.
KIND_ORDER = "orderbook"
KIND_EXPANSION = "expansion"
KIND_GUIDANCE = "guidance"

# Guidance candidates fetched per symbol. Investor presentations are the largest
# PDFs NSE serves, and the newest one carries the current target, so a small cap
# costs almost nothing in signal and a great deal less in bandwidth.
GUIDANCE_PER_SYMBOL = 3

# A filing PDF larger than this is a prospectus or an annual report attached to
# the wrong category, not a two-page order announcement. attFileSize lets it be
# skipped before the download rather than after.
MAX_PDF_BYTES = 8 * 1024 * 1024


def _die(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def latest_scan(path: str | None) -> Path:
    """The scan CSV to enrich: the one named, or the most recent in output/."""
    if path:
        p = Path(path)
        if not p.exists():
            _die(f"scan file not found: {p}")
        return p
    candidates = sorted(OUTPUT_DIR.glob("ath_scan_*.csv"))
    if not candidates:
        _die("no scan CSV in output/ -- run ath_scan.py first, or pass --scan")
    return candidates[-1]


def load_scan(path: Path) -> pd.DataFrame:
    # keep_default_na=False so a symbol like 'NA' survives, and so the
    # INSUFFICIENT_HISTORY trend label is not re-coerced on the way back in.
    df = pd.read_csv(path, keep_default_na=False)
    if "symbol" not in df.columns:
        _die(f"{path.name} has no 'symbol' column")
    # `isin` is checked in `stage_filings`, not here. Only that stage needs it --
    # announcements are keyed by ISIN -- and demanding it up front made a scan CSV
    # written before the column existed unreportable, which is a worse failure
    # than the one it was guarding against.
    if "isin" not in df.columns and not df.empty:
        df = _fill_isin(df, path)
    return df


def _fill_isin(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Recover a missing `isin` column from the local constituents CSV.

    `ath_scan.py` emits it now, but scans written before it did are still worth
    enriching, and the mapping is sitting in a file on disk -- the same file the
    scan itself resolved instruments from. Re-deriving it here is a local lookup,
    so refusing to run and asking for a whole scan re-run would be a network
    round trip and an intraday quote fetch spent on a column already in hand.

    Symbols absent from the CSV -- a --symbols run for a ticker outside the
    index -- get an empty ISIN, which is what the scan would have written.
    """
    try:
        cons = load_constituents()
        lookup = {str(r["Symbol"]).strip().upper(): str(r["ISIN Code"]).strip()
                  for _, r in cons.iterrows()}
    except Exception as e:  # noqa: BLE001
        print(f"  Warning: no 'isin' column in {path.name} and the "
              f"constituents CSV could not be read ({e})")
        return df
    df = df.copy()
    df["isin"] = [lookup.get(str(s).strip().upper(), "")
                  for s in df["symbol"]]
    found = int((df["isin"] != "").sum())
    print(f"  {path.name} predates the 'isin' column; filled {found}/{len(df)} "
          f"from the constituents CSV")
    return df


# --------------------------------------------------------------------------
# Stage: fundamentals
# --------------------------------------------------------------------------

def stage_fundamentals(db, df: pd.DataFrame, force: bool = False,
                       limit: int | None = None) -> None:
    symbols = [s for s in df["symbol"].tolist() if s]
    if limit:
        symbols = symbols[:limit]
    print(f"\n=== Fundamentals: {len(symbols)} symbols "
          f"(cached < {fundamentals.MAX_AGE_DAYS} day old are skipped) ===")

    results = fundamentals.fetch_many(db, symbols, force=force)
    ok = sum(1 for f in results.values() if f.ok)
    print(f"  {ok}/{len(symbols)} have a market cap")

    failures = {s: f.error for s, f in results.items() if f.error}
    if failures:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log = LOGS_DIR / "fundamentals_errors.csv"
        pd.DataFrame(sorted(failures.items()),
                     columns=["symbol", "error"]).to_csv(log, index=False)
        print(f"  {len(failures)} failed -- see {log}")
        for symbol, err in list(failures.items())[:3]:
            print(f"    {symbol}: {err}")


# --------------------------------------------------------------------------
# Stage: filings
# --------------------------------------------------------------------------

def _candidate_filings(df: pd.DataFrame, today: date, refresh: bool = False
                       ) -> tuple[list[dict], dict[str, int]]:
    """Every order/expansion/guidance filing belonging to a scanned symbol.

    Reuses the classifiers' own selection functions, so the filings fetched are
    exactly the filings the scan's factor columns counted.

    Returns the candidates and a funnel of the counts at each narrowing step, so
    an empty result can say *where* it emptied. Built here rather than recomputed
    by the caller because every number in it is already on hand, and a second
    pass would either re-hit the network or drift from what this function did.
    """
    lookback = max(factors.ORDERBOOK_LOOKBACK_MONTHS,
                   factors.EXPANSION_LOOKBACK_MONTHS,
                   factors.GUIDANCE_LOOKBACK_MONTHS)
    from_date = factors._subtract_months(today, lookback)
    ann = factors.fetch_announcements(from_date, today,
                                      session=requests.Session(),
                                      refresh=refresh)
    funnel = {"announcements": len(ann), "scanned_isins": 0, "matched": 0,
              "with_pdf": 0, "with_seq_id": 0, "unique": 0}
    if not ann:
        return [], funnel

    by_isin = {}
    for _, row in df.iterrows():
        if row.get("isin"):
            by_isin[row["isin"]] = row["symbol"]
    funnel["scanned_isins"] = len(by_isin)

    def _guidance(ann_rows, isin, today):
        return factors.select_guidance_filings(ann_rows, isin, today,
                                               limit=GUIDANCE_PER_SYMBOL)

    out: list[dict] = []
    for isin, symbol in by_isin.items():
        for kind, select in ((KIND_ORDER, factors.select_orderbook_filings),
                             (KIND_EXPANSION, factors.select_expansion_filings),
                             (KIND_GUIDANCE, _guidance)):
            for row in select(ann, isin, today):
                funnel["matched"] += 1
                url = (row.get("attchmntFile") or "").strip()
                if not url.lower().endswith(".pdf"):
                    continue
                funnel["with_pdf"] += 1
                if str(row.get("seqId") or "").strip():
                    funnel["with_seq_id"] += 1
                out.append({
                    "seq_id": str(row.get("seqId") or ""),
                    "symbol": symbol,
                    "isin": isin,
                    "kind": kind,
                    "desc": row.get("desc", ""),
                    "an_date": row["an_date"].isoformat(),
                    "url": url,
                    "size": row.get("attFileSize"),
                })
    # A filing can match several categories (an order that funds an expansion, a
    # presentation that announces both). Keep one document per seq_id; the first
    # kind wins, and `kind` is only a routing hint for which prompt to use.
    # The loop order above is therefore the priority order, and guidance is last
    # on purpose: it is matched by document *type* rather than by content, so it
    # is the broadest match and must not claim a filing a narrower rule wanted.
    seen: set[str] = set()
    unique = []
    for f in out:
        if not f["seq_id"] or f["seq_id"] in seen:
            continue
        seen.add(f["seq_id"])
        unique.append(f)
    funnel["unique"] = len(unique)
    return unique, funnel


def _format_funnel(funnel: dict[str, int]) -> str:
    """The narrowing steps in order, so the first zero names the cause."""
    return " -> ".join(
        f"{label} {funnel[key]}"
        for key, label in (("announcements", "announcements in window"),
                           ("scanned_isins", "scanned ISINs"),
                           ("matched", "classifier matches"),
                           ("with_pdf", "with a .pdf URL"),
                           ("with_seq_id", "with a seq_id"),
                           ("unique", "unique filings")))


def stage_filings(db, df: pd.DataFrame, limit: int | None = None,
                  refetch: bool = False, refresh_factors: bool = False) -> None:
    # load_scan fills this from the constituents CSV when the scan predates the
    # column, so reaching here means even that lookup failed.
    if "isin" not in df.columns or not (df["isin"].astype(str) != "").any():
        _die("no usable 'isin' for any row, and NSE announcements are keyed by "
             "ISIN rather than by symbol.\n"
             "  Re-run ath_scan.py, or check data/ind_niftytotalmarket_list.csv "
             "is present and readable.\n"
             "  --report still works without it.")
    today = date.today()
    candidates, funnel = _candidate_filings(df, today, refresh=refresh_factors)
    if not candidates:
        print("\n=== Filings: nothing to fetch ===")
        # Deliberately does not guess a cause. The previous wording asserted one
        # ("no filing carried a PDF URL") and was wrong -- 162,387 of them did,
        # and the real break was a blank `seq_id` -- which sent the reader after
        # the cache instead of the code. It also named `--refresh-factors`, which
        # is an `ath_scan.py` flag and does nothing here, so following the advice
        # printed could not help. Report the funnel and let it show its own zero.
        print(f"  {_format_funnel(funnel)}")
        print("  Nothing to fetch means one of those counts is zero; the first "
              "zero from the left is the cause.")
        if funnel["with_pdf"] and not funnel["with_seq_id"]:
            # The one cause with a known cure, so name it specifically rather
            # than leaving the reader to infer it from the funnel.
            print("  Filings were matched but none carry a seq_id, which is how "
                  "they are de-duplicated. The cache was written by a build that "
                  "read NSE's field under the wrong name; re-run with "
                  "--refresh-factors to repair those rows.")
        return

    todo = [c for c in candidates
            if refetch or not docstore.has_filing_text(db, c["seq_id"])]
    if limit:
        todo = todo[:limit]

    print(f"\n=== Filings: {len(candidates)} matched, {len(todo)} to fetch ===")
    session = requests.Session()
    # Warm the cookie jar: nsearchives rejects a cold client.
    try:
        session.get("https://www.nseindia.com", headers=orderval.UA, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"  Warning: NSE warm-up failed ({e}); downloads may 403")

    fetched = skipped = failed = 0
    for i, c in enumerate(todo, 1):
        size = c.get("size")
        if isinstance(size, (int, float)) and size and size > MAX_PDF_BYTES:
            docstore.put_filing(db, dict(c, raw_text="",
                                         error=f"skipped: {int(size)} bytes"))
            skipped += 1
            continue
        try:
            text, nbytes = orderval.fetch_filing_text(session, c["url"])
        except Exception as e:  # noqa: BLE001 - one bad PDF must not stop 400
            docstore.put_filing(db, dict(c, raw_text="",
                                         error=f"{type(e).__name__}: {e}"))
            failed += 1
        else:
            parsed = orderval.parse_order_value(text)
            docstore.put_filing(db, dict(
                c, raw_text=text, bytes=nbytes, error="",
                regex_rupees=parsed.rupees,
                regex_confidence=parsed.confidence,
                regex_raw=parsed.raw,
                regex_currency=parsed.currency,
            ))
            fetched += 1
        import time
        time.sleep(orderval.REQUEST_SLEEP)
        if i % 25 == 0:
            print(f"  {i}/{len(todo)} ({fetched} ok, {failed} failed)")

    print(f"  fetched {fetched}, skipped {skipped} (too large), failed {failed}")
    _report_parse_yield(db)


def stage_reparse(db) -> None:
    """Re-run the order-value regex over stored text, downloading nothing.

    `scanner/orderval.py` keeps parsing pure and separate from fetching so that
    a better regex can be re-applied to `docstore` text for free. That was true
    of the code and impossible from the CLI: the only way to get a corrected
    parse onto stored rows was `--filings --refetch`, which re-downloads every
    PDF at a one-second courtesy sleep -- sixteen minutes and ~1 GB of NSE's
    bandwidth to re-run a regex that takes three seconds.

    Prints the before/after tier counts, because a parser change that moves
    nothing is the interesting outcome and the easiest one to assume away.
    """
    docs = [d for d in docstore.all_filings(db) if d.get("raw_text")]
    print(f"\n=== Reparse: {len(docs)} stored documents, no downloads ===")
    if not docs:
        print("  nothing stored yet; run --filings first")
        return

    before: dict[str, int] = {}
    after: dict[str, int] = {}
    changed = 0
    for d in docs:
        old = d.get("regex_confidence") or "?"
        before[old] = before.get(old, 0) + 1
        parsed = orderval.parse_order_value(d["raw_text"])
        after[parsed.confidence] = after.get(parsed.confidence, 0) + 1
        if (parsed.confidence != d.get("regex_confidence")
                or parsed.rupees != d.get("regex_rupees")):
            changed += 1
            docstore.put_filing(db, dict(
                d, regex_rupees=parsed.rupees,
                regex_confidence=parsed.confidence,
                regex_raw=parsed.raw, regex_currency=parsed.currency))

    print(f"  {changed} of {len(docs)} documents changed")
    tiers = sorted(set(before) | set(after),
                   key=lambda k: -(after.get(k, 0) + before.get(k, 0)))
    print(f"    {'tier':<18} {'before':>7} {'after':>7} {'delta':>7}")
    for tier in tiers:
        b, a = before.get(tier, 0), after.get(tier, 0)
        print(f"    {tier:<18} {b:>7} {a:>7} {a - b:>+7}")
    _report_parse_yield(db)


def _report_parse_yield(db) -> None:
    """What the regex actually got, by confidence tier -- the honest scoreboard."""
    docs = [d for d in docstore.all_filings(db) if d.get("raw_text")]
    if not docs:
        return
    tiers: dict[str, int] = {}
    for d in docs:
        tiers[d.get("regex_confidence", "?")] = tiers.get(
            d.get("regex_confidence", "?"), 0) + 1
    trusted = sum(v for k, v in tiers.items()
                  if k in (orderval.CONF_ANCHOR_SCALED, orderval.CONF_ANCHOR_BARE))
    print(f"  parse yield over {len(docs)} documents with text:")
    for tier, n in sorted(tiers.items(), key=lambda kv: -kv[1]):
        print(f"    {tier:<16} {n:>4}  ({n / len(docs) * 100:.0f}%)")
    print(f"    trustworthy      {trusted:>4}  "
          f"({trusted / len(docs) * 100:.0f}%)")

    no_text = [d for d in docstore.all_filings(db)
               if not d.get("raw_text") and not d.get("error")]
    if no_text:
        print(f"  {len(no_text)} PDFs yielded no text layer (scanned?) -- "
              f"these are the only ones OCR would help. {llm.OCR_FALLBACK_NOTE}")


# --------------------------------------------------------------------------
# Stage: LLM
# --------------------------------------------------------------------------

def stage_llm(db, cfg: llm.LLMConfig, limit: int | None = None,
              only_gaps: bool = True, rerun: bool = False, workers: int = 1) -> None:
    reachable, detail = llm.health(cfg)
    if not reachable:
        _die(f"LLM backend unreachable at {cfg.base_url} ({detail}).\n"
             f"  Start your OpenAI-compatible LLM server, then pass its URL:\n"
             f"    --llm-url <server URL> --llm-model qwen3-4b --llm-api openai\n"
             f"  (start.ps1 passes LLM_URL for you). Any OpenAI-compatible or Ollama server works.")
    print(f"\n=== LLM: {cfg.model} at {cfg.base_url} ({detail}) ===")

    docs = [d for d in docstore.all_filings(db) if d.get("raw_text")]
    if only_gaps:
        # Only where the regex has no trustworthy answer. This is the whole
        # point of tiering: not spending minutes of CPU on a filing whose
        # mandated field was already read correctly for free.
        #
        # Capacity and guidance are always run, never skipped. The regex reads
        # one thing -- an order value from a mandated template field -- and
        # having read it says nothing about whether the same document also
        # contains a capacity figure or a revenue target. Only order filings
        # have an alternative source to defer to.
        docs = [d for d in docs
                if d.get("kind") in (KIND_EXPANSION, KIND_GUIDANCE)
                or d.get("regex_confidence") not in (
                    orderval.CONF_ANCHOR_SCALED, orderval.CONF_ANCHOR_BARE)]
    if not rerun:
        docs = [d for d in docs if not docstore.get_extraction(
            db, d["seq_id"], _kind_for(d))]
    if limit:
        docs = docs[:limit]

    if not docs:
        print("  nothing to extract (all done, or --filings has not run)")
        return

    print(f"  {len(docs)} documents to extract"
          f"{' (regex gaps and expansions only)' if only_gaps else ''}")
    ok = bad = 0
    workers = max(1, workers)
    started = time.time()

    # Try to reach Neo4j for push_filing, but don't fail the stage if unreachable
    g = None
    try:
        g = graph.Graph(graph.connect())
        if not g.wait_ready(seconds=5):
            g = None
    except SystemExit:  # graph.connect() raises SystemExit when NEO4J_AUTH is unset
        g = None
    except Exception:  # noqa: BLE001
        g = None

    def _extract(d):
        return d, llm.extract(cfg, d["raw_text"], _kind_for(d),
                              source_key=d["seq_id"], symbol=d.get("symbol"))

    # Requests run concurrently (vLLM batches them); results are stored from this
    # thread only, because TinyDB is not safe for concurrent writers.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_extract, d) for d in docs]
        for i, fut in enumerate(as_completed(futures), 1):
            d, result = fut.result()
            extraction_doc = {
                "symbol": d.get("symbol", ""),
                "data": result.data,
                "raw": result.raw,
                "error": result.error,
                "seconds": result.seconds,
                "model": result.model,
                "prompt_version": result.prompt_version,
            }
            docstore.put_extraction(db, d["seq_id"], _kind_for(d), extraction_doc)

            # Push to Neo4j immediately after storing (if reachable)
            if g:
                g.push_filing(d, extraction_doc)

            if result.ok:
                ok += 1
            else:
                bad += 1
            if i % 5 == 0 or i == len(docs):
                rate = (time.time() - started) / i
                left = (len(docs) - i) * rate / 60
                print(f"  {i}/{len(docs)}  {ok} ok, {bad} failed  "
                      f"({rate:.1f}s/doc, ~{left:.0f} min left)", flush=True)

    if g:
        g.close()

    _report_cross_check(db)


_PROMPT_FOR_KIND = {
    KIND_EXPANSION: llm.KIND_CAPACITY,
    KIND_GUIDANCE: llm.KIND_GUIDANCE,
}


def _kind_for(doc) -> str:
    return _PROMPT_FOR_KIND.get(doc.get("kind"), llm.KIND_ORDER)


def _report_cross_check(db) -> None:
    """Where the model and the regex disagree -- the rows worth a human glance."""
    verdicts: dict[str, int] = {}
    disagreements = []
    for ex in docstore.extractions_by_kind(db, llm.KIND_ORDER):
        doc = docstore.get_filing(db, ex["seq_id"])
        if not doc:
            continue
        llm_value = _num((ex.get("data") or {}).get("order_value_inr"))
        verdict = llm.cross_check(doc.get("regex_rupees"), llm_value)
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        if verdict == llm.DISAGREE:
            disagreements.append((doc.get("symbol"), doc.get("regex_rupees"),
                                  llm_value))
    if not verdicts:
        return
    print("  regex vs model:")
    for k, v in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        print(f"    {k:<12} {v}")
    for symbol, r, l in disagreements[:5]:
        print(f"    disagree: {symbol} regex={r} llm={l}")


# --------------------------------------------------------------------------
# Forward-looking columns
#
# Everything below is a highlight, never a filter and never part of the ranking.
# `significance` ranks on filed numbers only; a forecast that could reorder the
# sheet would let a model's guess outrank a company's disclosure, which is the
# one thing this project has consistently refused to allow.
#
# All of it reads the local caches and makes no network call, so a forecast can
# never delay or fail the stages that fetch real data.
# --------------------------------------------------------------------------

def _guidance_for_symbol(db, symbol: str) -> revenue.Guidance:
    """The newest management revenue target the model found for this symbol.

    Newest rather than largest, the opposite of `_best_order_for_symbol`: an
    order value is a fact that stays true, but a target is superseded the moment
    management issues a new one, and reporting last year's raised guidance after
    this year's cut would be worse than reporting nothing.
    """
    best: tuple[str, revenue.Guidance] | None = None
    for doc in docstore.filings_for(db, symbol):
        if doc.get("kind") != KIND_GUIDANCE:
            continue
        ex = docstore.get_extraction(db, doc["seq_id"], llm.KIND_GUIDANCE)
        data = (ex or {}).get("data") or {}
        if not data.get("has_guidance"):
            continue
        # A broker's forecast quoted inside a company's own presentation is not
        # guidance, and the prompt is asked to make exactly this distinction.
        if not data.get("is_management_statement"):
            continue
        direction = str(data.get("direction") or revenue.GUIDANCE_NONE).upper()
        when = str(doc.get("an_date", ""))
        g = revenue.Guidance(
            direction=direction,
            target_inr=_num(data.get("target_inr")),
            growth_pct=_num(data.get("growth_pct")),
            period=str(data.get("period") or ""),
            source_date=when,
            verbatim=str(data.get("verbatim") or ""),
        )
        if not g.ok:
            continue
        if best is None or when > best[0]:
            best = (when, g)
    return best[1] if best else revenue.Guidance()


def _orders_for_symbol(db, symbol: str) -> list[dict]:
    """Every credible order win for a symbol, in crore, with its period.

    Values are converted to crore here because the revenue series comes from
    screener in crore and `order_backed` divides one by the other. Mixing the
    two units would make every book-to-bill ratio out by a factor of ten million
    -- an error large enough to be obvious, which is the only reason it is safe
    to do the conversion at a boundary rather than to carry units in the types.
    """
    out = []
    for doc in docstore.filings_for(db, symbol):
        if doc.get("kind") != KIND_ORDER:
            continue
        value = _num(doc.get("regex_rupees"))
        trusted = doc.get("regex_confidence") in (orderval.CONF_ANCHOR_SCALED,
                                                  orderval.CONF_ANCHOR_BARE)
        ex = docstore.get_extraction(db, doc["seq_id"], llm.KIND_ORDER)
        data = (ex or {}).get("data") or {}
        if not (trusted and value and value > 0):
            value = _num(data.get("order_value_inr"))
        months = _num(data.get("execution_months")) or 0
        if not (value and value > 0):
            continue
        out.append({"value": float(value) / significance.CRORE,
                    "execution_months": months})
    return out


def _num(value):
    """A model-supplied number, or None for anything that is not one.

    `bool` is excluded explicitly. The model writes its own JSON, so a `true`
    can land in a field that asked for a value, and `isinstance(True, int)` is
    True in Python -- without the guard a boolean becomes 1.0 and is reported as
    a one-crore revenue target or a 1% growth guidance. Nothing downstream would
    notice, because 1.0 is a perfectly plausible number.
    """
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _forecast_rows(db, df: pd.DataFrame, funds: dict, model=None) -> list[dict]:
    """One row of forward-looking columns per symbol."""
    symbols = [s for s in df["symbol"].tolist() if s]
    trends = (dict(zip(df["symbol"], df["trend"])) if "trend" in df.columns
              else {})

    closes = history.cached_closes(symbols, min_rows=volatility.MIN_CLOSES)
    print(f"  price history in cache for {len(closes)}/{len(symbols)} symbols")

    rows = []
    n_revenue = n_flag = 0
    for symbol in symbols:
        row: dict = {"symbol": symbol}

        # --- volatility regime, from closes already cached ------------------
        vstate = volatility.VolState(error="no cached closes")
        if symbol in closes:
            vstate = volatility.vol_state(closes[symbol], model=model)
        if vstate.ok:
            row.update({
                "vol_pct": vstate.current,
                "vol_baseline_pct": vstate.baseline,
                "vol_vs_baseline": vstate.ratio,
                "vol_percentile": vstate.percentile,
                "vol_regime": vstate.regime,
                "vol_forecast_pct": vstate.forecast,
                "breakout_quality": volatility.breakout_quality(
                    vstate, trends.get(symbol)),
            })

        # --- three quarters of revenue, three ways -------------------------
        # No model here, on purpose, even under --timesfm: it was measured to be
        # worse on this particular series. The measurement is recorded on
        # `revenue.forward_revenue`, which is the module that owns the decision.
        f = funds.get(symbol)
        quarters = list(f.quarterly_sales) if f else []
        outlook = revenue.forward_revenue(quarters, model=None)
        if outlook.ok:
            n_revenue += 1
            row.update({
                "rev_backend": outlook.backend,
                "rev_latest_q_cr": _round(outlook.latest_actual),
                "rev_trailing_ttm_cr": _round(outlook.trailing_ttm),
                "rev_forward_ttm_cr": _round(outlook.forward_ttm),
                "rev_ttm_growth_pct": outlook.ttm_growth_pct,
                # The three outcomes at the forward year. Empty when the history
                # was too short to backtest a band -- which is why `rev_note`
                # rides along: a blank scenario column with no explanation looks
                # like a bug, and the point forecast beside it is still good.
                "rev_forward_ttm_bad_cr": _round(outlook.forward_ttm_bad),
                "rev_forward_ttm_good_cr": _round(outlook.forward_ttm_very_good),
                "rev_growth_pct_bad": outlook.growth_pct_bad,
                "rev_growth_pct_very_good": outlook.growth_pct_very_good,
                # How far this rule has typically missed on this company's own
                # past quarters. Read beside the growth figure rather than
                # instead of it: +18% with a 4% typical miss and +18% with a 30%
                # one are very different claims, and nothing else in the row
                # distinguishes them. Populated on far steps where the band is
                # not, which is why it is worth a column of its own.
                "rev_ttm_dev_pct": outlook.ttm_dev_pct,
                "rev_ttm_dev_cr": _round(outlook.ttm_dev_cr),
                "rev_note": outlook.note,
            })
            for q in outlook.quarters:
                row[f"rev_q{q.step}_cr"] = _round(q.value)
                row[f"rev_q{q.step}_qoq_pct"] = q.qoq_pct
                row[f"rev_q{q.step}_yoy_pct"] = q.yoy_pct
                row[f"rev_q{q.step}_bad_cr"] = _round(q.bad)
                row[f"rev_q{q.step}_very_good_cr"] = _round(q.very_good)
                row[f"rev_q{q.step}_dev_pct"] = q.dev_pct

        # --- the same forward year, from contracted work -------------------
        orders = revenue.order_backed(_orders_for_symbol(db, symbol),
                                      outlook.trailing_ttm)
        if orders.ok:
            row.update({
                "order_inflow_cr": _round(orders.total_value),
                "order_annualised_cr": _round(orders.annualised),
                "order_forward_ttm_cr": _round(orders.implied_forward_ttm),
                "order_growth_pct": orders.implied_growth_pct,
                "book_to_bill": orders.book_to_bill,
            })

        rec = revenue.reconcile(outlook, orders)
        row["orders_vs_history"] = rec.verdict
        row["orders_vs_history_gap_pct"] = rec.gap_pct

        # --- and from what management says ---------------------------------
        guidance = _guidance_for_symbol(db, symbol)
        if guidance.ok:
            row.update({
                "guidance_direction": guidance.direction,
                "guidance_period": guidance.period,
                "guidance_forward_ttm_cr": _round(
                    guidance.implied_forward_ttm(outlook.trailing_ttm)),
                "guidance_date": guidance.source_date,
                "guidance_verbatim": guidance.verbatim[:300],
            })

        flag = revenue.confluence_flag(guidance, trends.get(symbol), rec)
        if flag.level:
            n_flag += 1
            row["confluence_flag"] = flag.level
            row["confluence_why"] = flag.summary()

        rows.append(row)

    print(f"  revenue outlook for {n_revenue}/{len(symbols)} symbols "
          f"(needs {revenue.MIN_QUARTERS} quarters of sales)")
    print(f"  guidance confluence flag on {n_flag} symbols")
    return rows


def stage_backfill_announcements(months: int) -> None:
    """Extend the cached announcement history back `months` from today.

    The market-intensity series needs two full years to separate an annual
    pattern from a trend, and the scan only ever fetches
    ORDERBOOK_LOOKBACK_MONTHS back because that is all its per-stock factors
    need. This is the one-off that closes the gap.

    `fetch_announcements` slices into calendar months and writes each one to the
    cache as it lands, so an interrupted run leaves every completed month behind
    and re-running it is safe. It does not *skip* months already cached -- its
    cache check is for the whole range, not per month -- so a re-run costs the
    requests again. At one request and a one-second pause per month that is a
    few minutes, which is why this is a flag and not part of every scan.
    """
    today = date.today()
    from_date = factors._subtract_months(today, months)
    print(f"\n=== Backfill announcements: {from_date} to {today} "
          f"({months} months) ===")
    print(f"  {months} requests, ~17k rows each, one second apart. "
          f"Safe to interrupt and re-run.")
    fetched = factors.fetch_announcements(from_date, today,
                                          session=requests.Session())
    print(f"  fetched {len(fetched)} announcement rows")

    # Report against the cache rather than what this call returned: a chunk that
    # failed is missing from `fetched` but months stored by earlier runs are
    # present, and the cache is what the feature actually reads.
    rows = intensity.load_announcements()
    print(f"  cache now holds {len(rows)} announcements")
    months_seen, counts = intensity.monthly_counts(rows, today=today)
    if not months_seen:
        print("  no order wins matched -- check the announcement feed")
        return
    print(f"  {sum(counts)} are order wins, over {len(months_seen)} usable "
          f"months ({months_seen[0]} to {months_seen[-1]})")
    if len(counts) >= intensity.MIN_MONTHS:
        print(f"  enough for a seasonal forecast (needs "
              f"{intensity.MIN_MONTHS}). Run --report to see it.")
    else:
        short = intensity.MIN_MONTHS - len(counts)
        print(f"  {short} month(s) short of the {intensity.MIN_MONTHS} a "
              f"seasonal forecast needs -- re-run with "
              f"--backfill-announcements {months + short + 1}")


def _report_market_intensity(model, stem: str) -> None:
    """The market-level order-flow read: one row for the whole run, not per stock."""
    out = intensity.market_intensity(model=model)
    print("\n  market-wide order-award intensity:")
    if not out.ok:
        print(f"    unavailable: {out.error}")
        return
    print(f"    {out.summary()}")
    print(f"    {intensity.context_note(out)}")
    if out.note:
        print(f"    {out.note}")
    if out.agreement:
        print(f"    baseline vs model: {out.agreement}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"market_intensity_{stem}.csv"
    frame = pd.DataFrame({"month": out.months, "order_filings": out.counts,
                          "kind": "actual"})
    if out.forecast:
        future = _next_months(out.latest_month, len(out.forecast))
        frame = pd.concat([frame, pd.DataFrame({
            "month": future,
            "order_filings": [_round(v) for v in out.forecast],
            "kind": out.backend})], ignore_index=True)
    frame.to_csv(path, index=False)
    print(f"    wrote {path}")


def _next_months(last: str, count: int) -> list[str]:
    y, m = (int(x) for x in last.split("-"))
    out = []
    for _ in range(count):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        out.append(f"{y:04d}-{m:02d}")
    return out


# --------------------------------------------------------------------------
# Stage: report
# --------------------------------------------------------------------------

_TRUSTED_TIERS = (orderval.CONF_ANCHOR_SCALED, orderval.CONF_ANCHOR_BARE)


def _best_order_for_symbol(db, symbol: str) -> tuple[float | None, str, str]:
    """The largest *trustworthy* order value for a symbol, and where it came from.

    Only an anchored regex read or the model's extraction qualifies. A `loose`
    figure is discarded outright rather than ranked, because measuring the output
    over 964 real filings showed what `loose` actually reads:

        PIRAMALFIN  Rs 109,542 cr  post-merger net worth, from an NCLT appeal
        KPIL        Rs  26,000 cr  cumulative order book, not one order
        CIPLA       Rs   2,205 cr  unsecured creditors in a scheme
        JSWINFRA    Rs      97 cr  a GST demand the company is appealing
        ADANIPORTS  Rs     100 cr  gross debt, off an investor deck

    Ten of twenty-four ranked rows came from that tier, and they held the top of
    the ranking -- because the enriched sheet sorts by significance, "largest"
    selected for the misreads: net worth, debt, cumulative books and tax demands
    are all systematically larger than any single order. The defect was
    anti-correlated with correctness, which is the worst property a ranking key
    can have. `_orderbook_series` already gated on these same tiers; this
    function simply never did.

    Largest rather than latest, among what survives the gate: a symbol's biggest
    win in the window is what moves the needle, and the scan's job is to draw
    attention. `order_value_source` still reports the tier, so a model-sourced
    value is never mistaken for a filed one.
    """
    best: tuple[float | None, str, str] = (None, "", "")
    for doc in docstore.filings_for(db, symbol):
        if doc.get("kind") != KIND_ORDER:
            continue
        value, source = _num(doc.get("regex_rupees")), doc.get("regex_confidence", "")
        if not (value and value > 0 and source in _TRUSTED_TIERS):
            value, source = None, ""
        # Fall back to the model only where the regex had nothing trustworthy.
        if value is None:
            ex = docstore.get_extraction(db, doc["seq_id"], llm.KIND_ORDER)
            llm_value = _num((ex or {}).get("data", {}).get("order_value_inr"))
            if llm_value and llm_value > 0:
                value, source = llm_value, "llm"
        if value is not None and (best[0] is None or value > best[0]):
            best = (value, source, doc.get("an_date", ""))
    return best


# Matched against the ORDER window, not the expansion signal's own 6 months --
# see `factors.select_expansion_filings`'s `months` argument for why.
CAPACITY_CONTEXT_MONTHS = factors.ORDERBOOK_LOOKBACK_MONTHS


def _capacity_context(df: pd.DataFrame, today: date) -> dict[str, list[str]]:
    """{symbol: capacity-announcement dates, newest first}.

    The brief asked for "existing orderbook vs potential orderbook if its present
    in advance, if there is no plan, present it as unplanned order book". This is
    the half of that which needs no model: did the company announce a capacity
    expansion in the same window it won the order?

      PLANNED         a capacity announcement on or before the order
      CAPACITY_AFTER  one, but only after the order was announced
      UNPLANNED       none in the window

    `UNPLANNED` says a capacity expansion was **not filed**, which is not the
    same as no plan existing -- a company announces capacity when it chooses to,
    and plenty deliver inside an envelope they already have. It is still worth
    surfacing, because the two readings are both worth a human look: either the
    company had the headroom already, or it has won work whose delivery it has
    not addressed publicly. Which of those it is needs the PDFs, so this column
    points attention rather than concluding. `CAPACITY_AFTER` is the most
    interesting of the three and the reason the direction is reported at all
    instead of a bare yes/no: capacity announced *after* a win is the company
    telling you the order outgrew its plant.

    Read from the announcement METADATA cache, so this touches no network -- the
    text is irrelevant here, only that a filing exists and when. That also fixes
    an asymmetry that would otherwise fabricate: the fetched expansion PDFs look
    back 6 months and the orders 12, so a third of order winners would read
    `UNPLANNED` for no reason except that nothing had looked.
    """
    from_date = factors._subtract_months(today, CAPACITY_CONTEXT_MONTHS)
    ann = factors.cached_announcements(from_date, today)
    if not ann:
        return {}

    out: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        isin, symbol = row.get("isin"), row["symbol"]
        if not isin:
            continue
        hits = factors.select_expansion_filings(
            ann, isin, today, months=CAPACITY_CONTEXT_MONTHS)
        if hits:  # already sorted newest first
            out[symbol] = [h["an_date"].isoformat() for h in hits]
    return out


def _capacity_plan(cap_dates: list[str], order_date: str) -> tuple[str, str]:
    """(label, the capacity date the label is about) for one symbol's order.

    Blank for a symbol with no trustworthy order value: there is no order to call
    planned or otherwise, and an empty cell says that better than a verdict would.
    """
    if not order_date:
        return "", ""
    before = [d for d in cap_dates if d <= order_date]
    if before:
        return "PLANNED", before[0]          # nearest preceding, newest first
    if cap_dates:
        return "CAPACITY_AFTER", cap_dates[-1]   # earliest one after the order
    return "UNPLANNED", ""


def _capacity_for_symbol(db, symbol: str) -> str:
    """'existing -> proposed' from the model's capacity extraction, if any."""
    for doc in docstore.filings_for(db, symbol):
        if doc.get("kind") != KIND_EXPANSION:
            continue
        ex = docstore.get_extraction(db, doc["seq_id"], llm.KIND_CAPACITY)
        data = (ex or {}).get("data") or {}
        existing, proposed = data.get("existing_capacity"), data.get("proposed_capacity")
        if proposed:
            planned = "" if data.get("is_planned", True) else " (exploratory)"
            if existing:
                return f"{existing} -> {proposed}{planned}"
            return f"-> {proposed}{planned}"
    return ""


def stage_report(db, df: pd.DataFrame, scan_path: Path,
                 with_forecast: bool = True, timesfm: bool = False) -> Path:
    print("\n=== Report ===")
    industries = {}
    if "industry" in df.columns:
        industries = dict(zip(df["symbol"], df["industry"]))

    funds = {}
    for symbol in df["symbol"]:
        doc = docstore.get_fundamentals(db, symbol)
        if doc:
            known = set(fundamentals.Fundamentals.__dataclass_fields__)
            funds[symbol] = fundamentals.Fundamentals(
                symbol=symbol,
                **{k: v for k, v in doc.items() if k in known and k != "symbol"})

    ind_pe = fundamentals.industry_pe(funds, industries)

    cap_dates = _capacity_context(df, date.today())

    rows = []
    for symbol in df["symbol"]:
        f = funds.get(symbol)
        order_rupees, source, when = _best_order_for_symbol(db, symbol)
        plan, plan_date = _capacity_plan(cap_dates.get(symbol, []), when)
        s = significance.score(
            order_rupees,
            mcap_cr=f.mcap_cr if f else None,
            quarterly_sales=f.quarterly_sales if f else None,
            annual_sales=f.annual_sales if f else None,
        )
        median_pe = ind_pe.get((industries.get(symbol) or "").strip())
        rows.append({
            "symbol": symbol,
            "mcap_cr": f.mcap_cr if f else None,
            "pe": f.pe if f else None,
            "industry_pe": round(median_pe, 1) if median_pe else None,
            "pe_vs_industry_pct": _round(fundamentals.pe_vs_industry(
                f.pe if f else None, median_pe)),
            "roce": f.roce if f else None,
            "roe": f.roe if f else None,
            "debt_to_equity": f.debt_to_equity if f else None,
            "pledged_pct": f.pledged_pct if f else None,
            "ttm_sales_cr": _round(s.ttm_sales_cr),
            "qoq_growth_pct": _round(s.qoq_growth_pct),
            "yoy_growth_pct": _round(s.yoy_growth_pct),
            "order_value_cr": _round(s.order_cr),
            "order_value_source": source,
            "order_value_date": when,
            "order_pct_of_mcap": _round(s.order_to_mcap_pct),
            "order_pct_of_sales": _round(s.order_to_ttm_sales_pct),
            "order_significance": s.verdict,
            "capacity_change": _capacity_for_symbol(db, symbol),
            "order_capacity_plan": plan,
            "capacity_filing_date": plan_date,
        })

    enriched = df.merge(pd.DataFrame(rows), on="symbol", how="left")
    enriched["_rank"] = enriched["order_significance"].map(significance.rank)
    enriched = enriched.sort_values(
        ["_rank", "order_pct_of_mcap"], ascending=False).drop(columns=["_rank"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = scan_path.stem.replace("ath_scan_", "")

    if with_forecast:
        print("\n  --- forward-looking columns (highlight only, not ranked) ---")
        model = None
        if timesfm:
            model, detail = forecast.load_timesfm()
            print(f"  TimesFM: {detail}")
            if model is None:
                print("  continuing with the baseline forecast only")
        # Merged after the sort, so nothing here can move a row. The ranking is
        # already fixed by `order_significance` above.
        enriched = enriched.merge(
            pd.DataFrame(_forecast_rows(db, df, funds, model=model)),
            on="symbol", how="left")
        _report_market_intensity(model, stem)
    out = OUTPUT_DIR / f"ath_enriched_{stem}.csv"
    enriched.to_csv(out, index=False)
    print(f"  wrote {out} ({len(enriched)} rows, {len(enriched.columns)} columns)")

    counts = enriched["order_significance"].value_counts(dropna=False)
    print("  order significance:")
    for label, n in counts.items():
        print(f"    {label or 'none':<18} {n}")
    return out


def _round(value, places: int = 2):
    return None if value is None else round(value, places)


# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scan", help="scan CSV to enrich (default: newest in output/)")
    p.add_argument("--fundamentals", action="store_true")
    p.add_argument("--filings", action="store_true")
    p.add_argument("--llm", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--all", action="store_true", help="every stage, in order")
    p.add_argument("--stats", action="store_true", help="document store contents")
    p.add_argument("--limit", type=int, help="cap items per stage (trial runs)")
    p.add_argument("--force", action="store_true",
                   help="refetch fundamentals even if cached today")
    p.add_argument("--reparse", action="store_true",
                   help="re-run the order-value regex over already-stored "
                        "filing text, downloading nothing (use after changing "
                        "scanner/orderval.py)")
    p.add_argument("--refetch", action="store_true",
                   help="redownload filing PDFs already stored")
    p.add_argument("--refresh-factors", action="store_true",
                   help="re-fetch NSE announcements, ignoring today's cache "
                        "(repairs cached rows missing seq_id or a PDF URL)")
    p.add_argument("--llm-all", action="store_true",
                   help="run the model on every filing, not just regex gaps")
    p.add_argument("--llm-rerun", action="store_true",
                   help="re-extract documents that already have an extraction")
    p.add_argument("--llm-workers", type=int, default=1,
                   help="concurrent extraction requests (vLLM batches them; use 4 there)")
    p.add_argument("--llm-url", default=llm.LLMConfig.base_url)
    p.add_argument("--llm-model", default=llm.LLMConfig.model)
    p.add_argument("--llm-api", default=llm.LLMConfig.api,
                   choices=["ollama", "openai"])
    p.add_argument("--no-forecast", action="store_true",
                   help="skip the forward-looking columns in --report")
    p.add_argument("--timesfm", action="store_true",
                   help="also run TimesFM alongside the free baseline forecast "
                        "(needs timesfm[torch]; CPU is fine, but slow)")
    p.add_argument("--backfill-announcements", type=int, metavar="MONTHS",
                   nargs="?", const=intensity.BACKFILL_MONTHS,
                   help=f"extend the cached announcement history back MONTHS "
                        f"from today, so the market-wide order-intensity "
                        f"forecast has the {intensity.MIN_MONTHS} months it "
                        f"needs (default {intensity.BACKFILL_MONTHS}). One-off, "
                        f"~1 request and 1 second per month; safe to interrupt "
                        f"and re-run; needs no scan CSV")
    args = p.parse_args()

    db = docstore.open_db()
    try:
        if args.stats:
            s = docstore.stats(db)
            print("Document store:")
            for k, v in s.items():
                if k == "bytes_on_disk":
                    print(f"  {k:<20} {v:,} ({v / 1e6:.1f} MB)")
                else:
                    print(f"  {k:<20} {v}")
            if not any([args.fundamentals, args.filings, args.llm,
                        args.report, args.all, args.reparse]):
                return

        # Before the scan CSV is touched: this stage reads only factors.db and
        # is useful on its own, with no scan in output/ at all.
        if args.backfill_announcements:
            stage_backfill_announcements(args.backfill_announcements)
            if not any([args.fundamentals, args.filings, args.llm,
                        args.report, args.all, args.reparse]):
                return

        if args.reparse:
            stage_reparse(db)
            if not any([args.fundamentals, args.filings, args.llm,
                        args.report, args.all]):
                return

        if not any([args.fundamentals, args.filings, args.llm, args.report,
                    args.all]):
            p.print_help()
            return

        scan_path = latest_scan(args.scan)
        df = load_scan(scan_path)
        if df.empty:
            # A quiet market (or a narrow --symbols list) can leave nothing within range.
            # That is a result, not an error: later stages must not see a stale enriched file
            # as this scan's, so write nothing and let the caller skip them.
            print(f"{scan_path.name} has no stocks within range of their ATH; nothing to enrich.")
            return
        print(f"Enriching {scan_path.name}: {len(df)} rows")

        if args.fundamentals or args.all:
            stage_fundamentals(db, df, force=args.force, limit=args.limit)
        if args.filings or args.all:
            stage_filings(db, df, limit=args.limit, refetch=args.refetch,
                          refresh_factors=args.refresh_factors)
        if args.llm or args.all:
            cfg = llm.LLMConfig(base_url=args.llm_url, model=args.llm_model,
                                api=args.llm_api)
            stage_llm(db, cfg, limit=args.limit, only_gaps=not args.llm_all,
                      rerun=args.llm_rerun, workers=args.llm_workers)
        if args.report or args.all:
            stage_report(db, df, scan_path,
                         with_forecast=not args.no_forecast,
                         timesfm=args.timesfm)
    finally:
        db.close()


if __name__ == "__main__":
    main()
