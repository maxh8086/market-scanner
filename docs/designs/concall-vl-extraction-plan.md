# Concall PDF extraction with the VL model (plan)

Status: plan, approved in principle (VL extraction for concall PDFs). No code written yet.
Date: 2026-11-09.
Related: `docs/designs/concall-pipeline.md`, `docs/designs/concall-summary-template.md`.

## Scope

Input: the 10 PDFs in `C:\Users\vaibh\OneDrive\Desktop\concall`. `concall.docx` is not an input. It is a sample of the expected summary output, used only as a tone and layout reference (recorded 2026-11-09).
Output: page-level text with page numbers, stored in MongoDB (decided by the owner, 2026-11-09; `fundamentals-tables.md` already keeps concall text in Mongo). This overrides the Postgres `concall_events` table named in `concall-pipeline.md`; that doc must be updated to match.

Decisions (2026-11-09, owner):
- Storage: MongoDB.
- Scanned pages (41662844 pages 2–7): local VL model via Ollama, tag `ts-qwen3-vl-8b-65536:latest` (present in Ollama). Called directly through Ollama `/api/chat`, not through tokenfrugal, because the owner chose this model.

Out of scope for this step: the LLM summary itself (the template in `concall-summary-template.md`), annual reports, fundamentals.

## Steps

1. **Inspect (read-only).** For each PDF: page count, whether a text layer exists, and file hash. Output a table: file, pages, text layer yes/no, scanned yes/no. Nothing is written to the database in this step.
2. **Text-layer PDFs.** Extract text per page with the existing PDF tooling. No VL model needed. Keep page numbers.
3. **Scanned PDFs.** Render each page to an image and send it to the VL model through `tokenfrugal.dispatch_task` (builder or thinker role). The model name is chosen by tokenfrugal, not written here. The prompt asks only for text as shown, page by page. No summarising, no interpreting.
4. **Citation rule.** Every extracted block carries `file`, `page`, and `block_index`. A block with no page is rejected.
5. **Verification.** Compare a sample of 3 pages per scanned PDF against the image by hand, and record the character-error result. Any file that fails the sample is flagged and not loaded.
6. **Write.** Upsert into `concall_events` keyed by file hash (or `(symbol, seq_id)` per `concall-pipeline.md`), so a rerun does not duplicate. Blocked until the storage conflict above is settled.
7. **Report.** One summary: files processed, pages, scanned vs text, sample results, and files flagged.

## Acceptance

- Every block returned from the VL model has a page number that matches the image it came from.
- Sampled pages match the image; any mismatch is reported, not hidden.
- Rerunning the step writes no new rows for unchanged files.

## Must not change

- The screener.in path, fundamentals tables, and migration 027 (not applied).
- The collector schedule.

## Step 1 result (inspection, 2026-11-09, read-only)

10 PDFs checked. Two pairs are byte-identical duplicates (SHA-256 match), so 8 unique PDFs remain. `concall.docx` is a sample of the expected output, not an input.

| File | Pages | Text on first 5 pages | Note |
|---|---|---|---|
| 0983e81a-...pdf (and " (1)" copy) | 12 | 5 of 5 | duplicate |
| 132540-20261008-0Ju1v8qzem.pdf | 23 | 5 of 5 | |
| 2b021530-...pdf | 22 | 5 of 5 | |
| 2dcc16c8-...pdf | 3 | 3 of 3 | |
| 41662844-...pdf | 7 | 1 of 5 | likely scanned; VL candidate |
| 63bc1a88-...pdf (and " (1)" copy) | 65 | 5 of 5 | duplicate |
| 7dc14216-...pdf | 29 | 5 of 5 | |
| cde0da46-...pdf | 17 | 5 of 5 | |

Only 41662844 looks scanned from the first pages. The rest have a text layer, so VL is not needed for them unless a later page is blank. Step 2 (text extraction) should check every page, not just the first five.

## Open points

- `concall.docx`: sample of expected output, not an input. Used for tone and layout only. Its wording is third-party text and must not be copied. See `concall-summary-template.md`.
- Which PDFs are transcripts and which are presentations (affects the summary step, not extraction).
