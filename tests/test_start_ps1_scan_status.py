"""Static checks: start.ps1 reads the scan hand-over from ath_scan_candidates, not output/ CSV files."""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
START_PS1 = REPO_ROOT / "start.ps1"


class StartPs1ScanStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = START_PS1.read_text(encoding="utf-8")

    def test_no_scan_csv_lookup(self):
        self.assertNotIn("ath_scan_*.csv", self.text)

    def test_no_import_csv_in_file(self):
        self.assertNotIn("Import-Csv", self.text)

    def test_no_output_directory_listing_for_scan(self):
        self.assertNotIn("Get-ChildItem -LiteralPath 'output' -Filter 'ath_scan", self.text)
        self.assertIsNone(re.search(r"Get-ChildItem\s+-LiteralPath\s+'output'\s+-Filter\s+'ath_scan", self.text))

    def test_reads_latest_scan_from_store_module(self):
        self.assertIn("scanner.ath_scan_store", self.text)
        self.assertIn("'latest'", self.text)

    def test_latest_scan_line_regex(self):
        self.assertIn(r"'^(\d{4}-\d{2}-\d{2}) (\d+)$'", self.text)

    def test_file_is_ascii_only(self):
        self.assertEqual([c for c in self.text if ord(c) > 127], [])


if __name__ == "__main__":
    unittest.main()
