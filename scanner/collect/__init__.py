"""Collector package: fetch and push data to databases.

Sources (one small class per data type):
  - candles_eod: daily candles, end of day only
  - announcements: NSE announcements, as and when reported
  - corporate_actions: NSE corporate actions, as and when reported
  - filings: order/expansion/guidance PDFs, as and when published
  - fundamentals: market cap, ratios, and ownership from screener.in

Scheduling:
  - each source has a mode: 'scheduled' (cron in Asia/Kolkata) or 'manual' (never auto-runs)
  - a "Run now" button always works, inserting a request into collector_requests
  - the collector service claims and executes requests, recording attempts in collector_runs

Public API (imported by scanner/collect/settings.py and the UI):
  - get_settings() -> dict per source with mode, cron, params
  - update_setting(source, mode=None, cron=None, params=None) -> None
  - request_run(source) -> bool (new request queued, or one already existed)
  - list_runs(source=None, limit=50) -> list of collector_runs rows
"""
