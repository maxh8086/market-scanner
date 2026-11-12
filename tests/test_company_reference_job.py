"""Tests for the company_reference monthly job (task MT1, design section 4.4 and rules M-08, M-09, M-11).

Offline: HTTP is mocked with unittest.mock.patch, and the database connection is a MagicMock.
Assumed API, not yet written: scanner/index_sources.py exposes INDEX_SOURCES, an ordered mapping
from each index name to its candidate URLs (primary host filename variants first, then the
fallback host). The tests read names and candidates from there and never hard-code the names.
"""
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import requests

from scanner import company_reference as cr
from scanner import company_reference_job as job

REPO_ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 13)
CSV_BYTES = b"Symbol,Series,ISIN\nABC,EQ,INE000000000\n"
HTML_BYTES = b"<!DOCTYPE html><html><body>Access denied</body></html>"
GOOD_INDEX = "GOOD TEST INDEX"
BAD_INDEX = "BAD TEST INDEX"


def _response(status: int, content: bytes = b"") -> mock.MagicMock:
    resp = mock.MagicMock(name=f"response_{status}")
    resp.status_code = status
    resp.content = content
    resp.text = content.decode("utf-8", errors="replace")
    resp.headers = {"Content-Type": "text/html" if content.startswith(b"<") else "text/csv"}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def _url_of(call) -> str:
    return call.args[0] if call.args else call.kwargs["url"]


class CompanyReferenceJobTests(unittest.TestCase):
    def test_seven_index_names_defined_once(self):
        from scanner import index_sources

        names = list(index_sources.INDEX_SOURCES)
        self.assertEqual(len(names), 7, "scanner/index_sources.py must define exactly seven indices")
        self.assertEqual(len(set(names)), 7, "index names must be unique")
        self.assertEqual(set(job.SCAN_INDEXES), set(names), "the job must scan the same seven indices")

        for path in (
            REPO_ROOT / "scanner" / "company_reference_job.py",
            REPO_ROOT / "scripts" / "fetch_index_constituents.py",
        ):
            text = path.read_text(encoding="utf-8")
            for name in names:
                self.assertNotIn(
                    f'"{name}"',
                    text,
                    f"{name!r} is spelled out in {path.name}; import it from scanner.index_sources",
                )

    def test_html_200_is_not_accepted(self):
        name = GOOD_INDEX
        urls = ("https://primary.example/a.csv", "https://fallback.example/a.csv")
        with mock.patch.dict(job.SCAN_INDEXES, {name: urls}, clear=True), mock.patch(
            "scanner.company_reference_job.requests.get",
            return_value=_response(200, HTML_BYTES),
        ) as get:
            with self.assertRaises(RuntimeError):
                job.fetch_index_bytes(name)
        # Both candidates were requested; the HTML 200 from each was refused, not returned.
        self.assertEqual(get.call_count, 2)

    def test_first_filename_404_tries_next_variant(self):
        from scanner import index_sources

        name = next(iter(index_sources.INDEX_SOURCES))
        first, second = list(index_sources.INDEX_SOURCES[name])[:2]

        def respond(url, *args, **kwargs):
            if url == first:
                return _response(404)
            return _response(200, CSV_BYTES)

        with mock.patch(
            "scanner.company_reference_job.requests.get", side_effect=respond
        ) as get:
            raw = job.fetch_index_bytes(name)

        self.assertEqual(raw, CSV_BYTES)
        self.assertEqual(_url_of(get.call_args_list[0]), first)
        self.assertEqual(_url_of(get.call_args_list[1]), second)

    def test_failed_index_keeps_last_good_rows(self):
        conn, _refresh, replace, _counts = self._refresh_with_failed_index()

        replaced = [c.args[1] for c in replace.call_args_list]
        self.assertEqual(replaced, [GOOD_INDEX], "only the index that downloaded is replaced")
        self.assertNotIn(BAD_INDEX, replaced, "the failed index must keep its last good rows")
        for call in conn.execute.call_args_list:
            self.assertNotIn(BAD_INDEX, str(call), "no SQL may touch the failed index's rows")

    def test_master_refresh_commits_when_one_index_fails(self):
        conn, refresh, _replace, counts = self._refresh_with_failed_index()

        refresh.assert_called_once()
        sources = refresh.call_args.args[1]
        self.assertEqual(set(sources), {cr.SOURCE_CSV, cr.SOURCE_MASTER})
        self.assertTrue({cr.SOURCE_CSV, cr.SOURCE_MASTER} <= set(counts))
        conn.transaction.assert_called_once()
        self.assertEqual(
            conn.transaction.return_value.__exit__.call_args.args,
            (None, None, None),
            "the transaction must commit, not roll back",
        )

    def _refresh_with_failed_index(self):
        conn = mock.MagicMock(name="conn")
        indexes = {
            GOOD_INDEX: ("https://primary.example/g.csv", "https://fallback.example/g.csv"),
            BAD_INDEX: ("https://primary.example/b.csv", "https://fallback.example/b.csv"),
        }
        with mock.patch.dict(job.SCAN_INDEXES, indexes, clear=True), mock.patch.object(
            job, "parse_csv_bytes", return_value=["csv-row"]
        ), mock.patch.object(cr, "master_rows", return_value=["master-row"]), mock.patch.object(
            job,
            "parse_index_bytes",
            side_effect=lambda raw, name, as_of: [{"index_name": name}],
        ), mock.patch.object(
            cr, "refresh", return_value={cr.SOURCE_CSV: 1, cr.SOURCE_MASTER: 1}
        ) as refresh, mock.patch.object(
            cr, "replace_index_constituents", return_value=1
        ) as replace:
            counts = job.run_refresh(
                conn,
                today=TODAY,
                fetch_csv=lambda: b"",
                fetch_master=lambda: b"",
                fetch_indexes=lambda: {GOOD_INDEX: CSV_BYTES},  # BAD_INDEX failed to download
            )
        return conn, refresh, replace, counts


if __name__ == "__main__":
    unittest.main()
