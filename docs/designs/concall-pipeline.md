# Concall data in application code

Status: draft, awaiting approval. No code changed yet.

## Problem

The database holds 78,164 concall and investor-presentation announcements, all with PDF links in `attchmnt_file`. None of those PDFs is downloaded or read. The intimation XML that NSE publishes for analyst and investor meetings (XBRL subject "Analyst/Investor Meet – XBRL") is not parsed anywhere.

## Goal

Application code, not the LLM prompt, does three things:

1. Fetch concall and presentation attachments and cache the files.
2. Parse intimation XML into typed fields and store them.
3. Extract PDF text with a page cap and store it beside the event row.

The LLM receives only the extracted passages used for guidance, never whole documents.

## Non-goals

- No change to the order-value factor.
- No LLM call for the XML fields.
- No OCR. Scanned PDFs are flagged `needs_ocr`, not guessed.

## Design

**Storage.** New table `concall_events` keyed by `(symbol, seq_id)`: meeting date, meeting type, host names, presentation-included flag, source URL, fetch status, extracted text (capped), page count, `needs_ocr` flag. Migration under `db/migrations/`.

**XML parser.** Pure function, element names as listed in the sample intimation (`DateOfMeetingOrCallOrConferenceOrEventForIntimation`, `TypeOfMeetingForWhichIntimationIsGiven`, `WhetherIntimationOfMeetingIncludesPresentation`, and others). Unknown elements are ignored and counted, not stored.

**PDF text.** Reuse `scanner/orderval.py` `extract_pdf_text` and `fetch_filing_text`. Raise `MAX_PAGES` for this feed only, via a parameter, not by editing the constant. Transcripts can run longer than the 8-page order filings.

**Fetch.** Collector step, after announcements. Scoped to watchlist symbols, last 12 months (same window as `GUIDANCE_LOOKBACK_MONTHS`). Requests paced like the existing NSE fetches. Failures recorded per row and retried on the next run, not silently dropped.

**Guidance.** `scanner/factors.py` keeps selecting candidates as it does now. The guidance step reads `concall_events.text` for those candidates.

## Acceptance

- Parser test on the saved sample XML (`sample_analyst_meet.xml`): every expected field present, correct types.
- Test that a scanned PDF sets `needs_ocr` and stores no text.
- A live run for NEOGEN over the 12-month window, row counts reported against the 14 XBRL rows in the CSV.

## Summary step (added 2026-11-08)

After the fetch and parse steps, a summary step writes the concall overview, summary, Q&A, and annual report summary into `concall_summaries`. It uses the local LLM through tokenfrugal, with the prompt, schema, and checks in `docs/designs/concall-summary-template.md`. The UI reads only from the database.

## Open questions

1. Do you want transcripts and presentations both, or transcripts only?
2. Page cap for transcripts: 40 pages, or no cap?
3. Should the guidance step use the stored text immediately, or stay on the current path until the stored text is checked?
