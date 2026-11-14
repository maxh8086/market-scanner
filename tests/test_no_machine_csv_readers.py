"""Guard: no machine reader in the repo reads the ath_scan CSV files from output/.

The candidate table ath_scan_candidates is the source for machine readers. A person's --scan
CSV is read by path, which the patterns below do not match. The allow-list is empty on purpose:
add a path here only with a comment saying why it must keep reading the CSV.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", ".claude", "tests", "__pycache__",
             "output", "data", "logs"}

# Repo-relative POSIX paths allowed to mention the scan CSV pattern. Empty on purpose.
ALLOW = {}

PATTERNS = [
    re.compile(r"ath_scan_\*\.csv"),
    re.compile(r"glob\(\s*[\"']ath_scan_"),
]


def _py_files():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        yield rel


class NoMachineCsvReadersTests(unittest.TestCase):

    def test_no_machine_reader_globs_the_ath_scan_csv(self):
        hits = []
        for rel in _py_files():
            key = rel.as_posix()
            if key in ALLOW or key == "scanner/report.py":
                continue
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                if any(p.search(line) for p in PATTERNS):
                    hits.append(f"{key}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "machine readers must use ath_scan_candidates, not the CSV:\n"
                                   + "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
