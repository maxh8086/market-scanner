import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_PY = (ROOT / "ui/app/api.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "ui/app/static/app.js").read_text(encoding="utf-8")


def js_column_keys(js):
    start = js.find("const RESULT_COLUMNS = [")
    if start == -1:
        raise AssertionError("RESULT_COLUMNS missing")
    end = js.find("];", start)
    return re.findall(r'key: "(\w+)"', js[start:end])


def api_sort_keys(py):
    start = py.find("RESULT_SORT_COLUMNS = {")
    if start == -1:
        raise AssertionError("RESULT_SORT_COLUMNS missing")
    end = py.find("}", start)
    return re.findall(r'"(\w+)": "', py[start:end])


class ResultsSortContractTests(unittest.TestCase):
    def test_every_results_column_is_sortable_by_the_api(self):
        js_keys = js_column_keys(APP_JS)
        api_keys = api_sort_keys(API_PY)
        self.assertEqual(len(js_keys), 7, "results table should have seven columns")
        for key in js_keys:
            with self.subTest(column=key):
                self.assertIn(key, api_keys, f"API must accept sort={key}")

    def test_api_sorts_nulls_last_with_symbol_tiebreak(self):
        self.assertIn("NULLS LAST", API_PY)
        self.assertIn("ss.symbol ASC", API_PY)

    def test_frontend_sends_sort_and_order(self):
        self.assertIn("&sort=${resultsSort.key}&order=${resultsSort.order}", APP_JS)

    def test_headers_are_clickable_with_aria_sort(self):
        body = APP_JS[APP_JS.find("function resultsHeaderHtml"):]
        self.assertIn("onclick=\"setResultsSort(", body)
        self.assertIn("aria-sort", body)


if __name__ == "__main__":
    unittest.main()
