from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import glossary
from scanner.glossary import entry_for, load_glossary

SAMPLE_ENTRY = {
    "key": "ath_distance_pct",
    "visibility": ["excel", "ui", "prompt"],
    "label": "Distance from ATH",
    "tooltip": "How far the price is below its all-time high.",
    "explanation": "Computed as (close / ATH - 1) * 100 on the latest session.",
    "derivation_kind": "formula",
    "formula": "(close / ath - 1) * 100",
    "provisional": False,
    "wording_status": "draft",
}


class GlossaryLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, data, name: str = "glossary.json") -> Path:
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def _entry(self, **changes) -> dict:
        entry = copy.deepcopy(SAMPLE_ENTRY)
        for field, value in changes.items():
            if value is None:
                entry.pop(field, None)
            else:
                entry[field] = value
        return entry

    def _assert_rejects(self, entry: dict, key_name: str = "ath_distance_pct") -> None:
        path = self._write({key_name: entry})
        with self.assertRaises(ValueError) as ctx:
            load_glossary(path)
        self.assertIn(key_name, str(ctx.exception))

    def test_repo_glossary_file_loads(self) -> None:
        self.assertEqual(load_glossary(glossary.GLOSSARY_PATH), {})

    def test_empty_file_loads(self) -> None:
        self.assertEqual(load_glossary(self._write({})), {})

    def test_valid_sample_entry_passes(self) -> None:
        result = load_glossary(self._write({"ath_distance_pct": SAMPLE_ENTRY}))
        self.assertEqual(result, {"ath_distance_pct": SAMPLE_ENTRY})

    def test_producer_entry_passes(self) -> None:
        entry = self._entry(
            derivation_kind="producer",
            formula=None,
            producer="scanner.ath.compute_ath",
            provisional=True,
            wording_status="approved",
        )
        result = load_glossary(self._write({"ath_distance_pct": entry}))
        self.assertIn("ath_distance_pct", result)

    def test_backend_only_entry_without_text_passes(self) -> None:
        entry = self._entry(
            key="above_sma200", visibility=["backend"], tooltip=None, explanation=None
        )
        result = load_glossary(self._write({"above_sma200": entry}))
        self.assertIn("above_sma200", result)

    def test_non_object_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_glossary(self._write([SAMPLE_ENTRY]))

    def test_formula_kind_without_formula_raises(self) -> None:
        self._assert_rejects(self._entry(formula=None))

    def test_formula_kind_with_blank_formula_raises(self) -> None:
        self._assert_rejects(self._entry(formula="   "))

    def test_producer_kind_without_producer_raises(self) -> None:
        self._assert_rejects(
            self._entry(derivation_kind="producer", formula=None, producer=None)
        )

    def test_invalid_derivation_kind_raises(self) -> None:
        self._assert_rejects(self._entry(derivation_kind="guess"))

    def test_tooltip_on_backend_only_raises(self) -> None:
        self._assert_rejects(self._entry(visibility=["backend"]))

    def test_explanation_on_backend_only_raises(self) -> None:
        self._assert_rejects(
            self._entry(visibility=["backend"], tooltip=None)
        )

    def test_invalid_wording_status_raises(self) -> None:
        self._assert_rejects(self._entry(wording_status="final"))

    def test_non_boolean_provisional_raises(self) -> None:
        self._assert_rejects(self._entry(provisional="yes"))

    def test_missing_required_field_raises(self) -> None:
        self._assert_rejects(self._entry(wording_status=None))

    def test_invalid_visibility_raises(self) -> None:
        self._assert_rejects(self._entry(visibility=["screen"]))

    def test_error_names_the_offending_key(self) -> None:
        good = copy.deepcopy(SAMPLE_ENTRY)
        bad = self._entry(wording_status="final")
        bad["key"] = "bad_key"
        path = self._write({"ath_distance_pct": good, "bad_key": bad})
        with self.assertRaises(ValueError) as ctx:
            load_glossary(path)
        self.assertIn("bad_key", str(ctx.exception))
        self.assertNotIn("ath_distance_pct", str(ctx.exception))

    def test_key_field_differing_from_dict_key_raises(self) -> None:
        path = self._write({"ath_distance_pct": self._entry(key="other_key")})
        with self.assertRaises(ValueError) as ctx:
            load_glossary(path)
        self.assertIn("ath_distance_pct", str(ctx.exception))
        self.assertIn("other_key", str(ctx.exception))


class EntryForTests(unittest.TestCase):
    def test_entry_for_unknown_key_returns_none(self) -> None:
        self.assertIsNone(entry_for("no_such_column"))

    def test_entry_for_returns_loaded_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "glossary.json"
            path.write_text(
                json.dumps({"ath_distance_pct": SAMPLE_ENTRY}), encoding="utf-8"
            )
            with mock.patch.object(glossary, "GLOSSARY_PATH", path):
                self.assertEqual(entry_for("ath_distance_pct"), SAMPLE_ENTRY)
                self.assertIsNone(entry_for("missing"))


if __name__ == "__main__":
    unittest.main()
