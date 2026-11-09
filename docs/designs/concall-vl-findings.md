# Concall PDF: VL extraction findings and gaps

Status: parked. Not stored in MongoDB. Source: PDF with SHA-256 prefix 89de8e0bd8f8, file 41662844-4d70-4805-b985-2dfc885dbe0e.pdf in C:\Users\vaibh\OneDrive\Desktop\concall.

## Method

- Scanned pages: Qwen2.5-VL 7B via Ollama (`ts-qwen2-5vl-7b-65536:latest`), one page per request, page images at 2400 px. Earlier pages 2-5 used `ts-qwen3-vl-8b-65536:latest`.
- Sideways pages (6, 7 table) rotated -90 degrees before sending.

## Accepted

- Pages 2-5 (prose auditor report): transcription checked against the images. Printed text matches. Signatures and stamps are `[illegible]`, which is correct.

## Not accepted

- Page 6 (standalone and consolidated results, 30.06.26). The rotated run values mostly match the scan, but row labels come back as a separate block, so each value is mapped to its row only by order. A stray row "14" appears. Not checked cell by cell. No values are accepted from this run.
- Page 7 (EPS, shareholding, notes). The Qwen2.5-VL run has merged labels and misaligned shareholding rows. The manual draft needs two fixes: year-ended date 21.03.26 should be 31.03.26; "Lower Parcel" should be "Lower Parel (W)". No values are accepted yet.

## Findings

- Prose pages transcribe accurately with the VL model.
- Financial tables do not transcribe reliably with the VL model: merged rows, separated labels, repeated values, and on one attempt a degenerate digit run.
- Sideways tables need rotation before the model can read them.
- Repetition checks by repeated line count miss single very long lines. A per-line length check is also needed.
- No arithmetic check was run on the extracted tables.

## Gaps

1. No automated arithmetic validation: totals must equal the sum of their lines, and profit before tax minus tax must equal profit after tax.
2. No fixed row schema or per-row column-count check.
3. No second model or OCR cross-check on the tables.
4. No hand-checked ground-truth set, so no measured error rate.
5. No provenance on records: model, prompt version, page image hash, run time, review status.
6. docs/designs/concall-pipeline.md still names Postgres `concall_events`. The plan doc does not yet record the MongoDB decision.
7. concall.docx is a sample of the expected output, not an input (see concall-summary-template.md).
8. Routing: builder runs used Haiku directly and a VL model outside the tokenfrugal gateway. docs/haiku-fallback-log.md in the tokenfrugal repo has not been updated for these runs.
