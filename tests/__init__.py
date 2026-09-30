"""Unit tests run against local stand-ins, never against the shared databases.

Set before any scanner module is imported, so a shell that has the infra secrets loaded
cannot make a test write into the real Postgres or MongoDB.
"""
import os

os.environ["MARKETDATA_BACKEND"] = "sqlite"   # candles, announcements, corporate actions
os.environ["DOCSTORE_BACKEND"] = "tinydb"     # filings, fundamentals, extractions, conclusions
os.environ.pop("RUN_ID", None)                # no metrics rows from tests
