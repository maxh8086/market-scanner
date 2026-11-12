"""Migration 054 (LLM provider store): llm_provider and ai_setting in a throwaway schema.

Needs Postgres: setUpClass skips when it is unreachable. A skip is not a pass.
Tests write only to the throwaway schema created by pgschema.create.
"""
import unittest
from pathlib import Path

from scanner.pg import db
import tests.pgschema as pgschema

REPO = Path(__file__).resolve().parent.parent
UP_SQL = REPO / "db" / "migrations" / "054_llm_provider_store.sql"
DOWN_SQL = REPO / "db" / "migrations" / "down" / "054_llm_provider_store.down.sql"

TABLES = ("llm_provider", "ai_setting")
LLM_PROVIDER_COLUMNS = {"provider_id", "display_name", "class", "origin", "list_endpoint",
                        "approved", "key_ref", "key_version", "updated_at"}
AI_SETTING_COLUMNS = {"key", "value", "updated_at"}
EXPECTED_CLASSES = {"openai": "openai_compat", "anthropic": "anthropic_native",
                    "openrouter": "openai_compat", "ollama": "ollama"}
EXPECTED_APPROVED = {"openai": False, "anthropic": False, "openrouter": False, "ollama": True}
EXPECTED_SETTINGS = {"AI_PROVIDER_NAME": "ollama",
                     "AI_MODEL_NAME": "hf.co/unsloth/Qwen3.5-4B-GGUF:Q6_K",
                     "AI_PROVIDER_ROUTE": "native"}


def _columns(table):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s", (table,)).fetchall()
    return {r["column_name"] for r in rows}


def _tables_present():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ANY(%s)",
            (list(TABLES),)).fetchall()
    return {r["table_name"] for r in rows}


class TestMigration054(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = pgschema.create(cls)  # raises SkipTest without Postgres

    def test_054_creates_both_tables(self):
        self.assertEqual(_tables_present(), set(TABLES))
        self.assertEqual(_columns("llm_provider"), LLM_PROVIDER_COLUMNS)
        self.assertEqual(_columns("ai_setting"), AI_SETTING_COLUMNS)

    def test_054_seeds_four_presets(self):
        with db.connect() as conn:
            providers = conn.execute(
                'SELECT provider_id, "class", approved FROM llm_provider').fetchall()
            settings = conn.execute("SELECT key, value FROM ai_setting").fetchall()
        self.assertEqual(len(providers), 4)
        self.assertEqual({r["provider_id"] for r in providers}, set(EXPECTED_CLASSES))
        for r in providers:
            pid = r["provider_id"]
            self.assertEqual(r["class"], EXPECTED_CLASSES[pid], pid)
            self.assertEqual(r["approved"], EXPECTED_APPROVED[pid], pid)
        actual = {r["key"]: r["value"] for r in settings}
        for key, value in EXPECTED_SETTINGS.items():
            self.assertEqual(actual.get(key), value, key)

    def test_054_active_model_insert_does_not_overwrite(self):
        self.own_schema = pgschema.create(self)
        up_sql = UP_SQL.read_text(encoding="utf-8")
        with db.connect() as conn:
            conn.execute("UPDATE ai_setting SET value = 'custom-model:1' "
                         "WHERE key = 'AI_MODEL_NAME'")
            conn.commit()
            conn.execute(up_sql)  # idempotent re-run: IF NOT EXISTS and ON CONFLICT DO NOTHING
            conn.commit()
        with db.connect() as conn:
            value = conn.execute(
                "SELECT value FROM ai_setting WHERE key = 'AI_MODEL_NAME'").fetchone()["value"]
        self.assertEqual(value, "custom-model:1")

    def test_054_down_drops_tables(self):
        # A second throwaway schema, so the class schema above stays intact for other tests.
        self.second_schema = pgschema.create(self)
        self.assertEqual(_tables_present(), set(TABLES), "precondition: up applied")
        down_sql = DOWN_SQL.read_text(encoding="utf-8")
        with db.connect() as conn:
            conn.execute(down_sql)
        self.assertEqual(_tables_present(), set(), "down step left tables behind")


if __name__ == "__main__":
    unittest.main()
