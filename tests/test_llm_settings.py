"""Offline tests for the LC3 write routes in ui/app/llm_settings.py (prefix /api/llm).

The database and key encryption are fakes. scanner.pg.db.connect returns an in-memory
connection that records statements, scanner.app_secrets.put is a mock, and the master key
is a random 32-byte value made per test. No real database, .env file or secret file is read.

Run from the worktree root:
    .venv/Scripts/python.exe -m unittest tests.test_llm_settings -q
"""
import os
import unittest
from unittest import mock

UI_HEADER = "X-Market-Scanner-UI"
# Assumed configured UI origin. The implementation must accept exactly this value.
UI_ORIGIN = "http://localhost:8080"
FOREIGN_ORIGIN = "https://attacker.example.test"
PLAIN_KEY = "test-llm-key-PLAINTEXT-7741"  # fake value, never a real key
REFUSED = (401, 403)


class _FakeResult:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConn:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return _FakeResult()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class LlmSettingsRouteTests(unittest.TestCase):

    def _harness(self):
        # Importing the new router is the first step, so a missing module fails here.
        import ui.app.llm_settings  # noqa: F401
        from ui.app.main import app
        from fastapi.testclient import TestClient

        self.conn = _FakeConn()
        patches = [
            mock.patch("scanner.pg.db.connect", return_value=self.conn),
            mock.patch("scanner.app_secrets.put"),
            mock.patch("scanner.secret_crypto.load_master_key", return_value=os.urandom(32)),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.put = mocks[1]
        return TestClient(app)

    @staticmethod
    def _key_body(provider_id="openai", api_key=PLAIN_KEY):
        return {"provider_id": provider_id, "api_key": api_key}

    @staticmethod
    def _good_headers():
        return {UI_HEADER: "1", "Origin": UI_ORIGIN}

    def test_key_write_without_header_refused(self):
        client = self._harness()
        r = client.post("/api/llm/keys", json=self._key_body(),
                        headers={"Origin": UI_ORIGIN})
        self.assertIn(r.status_code, REFUSED)
        self.assertEqual(self.conn.statements, [])
        self.put.assert_not_called()

    def test_key_write_foreign_origin_refused(self):
        client = self._harness()
        r = client.post("/api/llm/keys", json=self._key_body(),
                        headers={UI_HEADER: "1", "Origin": FOREIGN_ORIGIN})
        self.assertIn(r.status_code, REFUSED)
        self.assertEqual(self.conn.statements, [])
        self.put.assert_not_called()

    def test_key_response_has_no_plaintext(self):
        client = self._harness()
        r = client.post("/api/llm/keys", json=self._key_body(), headers=self._good_headers())
        # Positive control: the value reached the encryption path, so the test is not
        # passing only because the request was dropped.
        self.assertIn(r.status_code, (200, 201))
        self.assertIn(PLAIN_KEY, repr(self.put.call_args))
        self.assertNotIn(PLAIN_KEY, r.text)
        self.assertNotIn(PLAIN_KEY, str(dict(r.headers)))
        for _sql, params in self.conn.statements:
            self.assertNotIn(PLAIN_KEY, repr(params))

    def test_key_name_rule(self):
        client = self._harness()
        bad = ["", "OpenAI", "1openai", "_openai", "open-ai", "open.ai", "open ai",
               "open/../x", "a" * 42]
        good = ["a", "openai", "ollama_local", "openrouter2", "a" * 41]
        for pid in bad:
            with self.subTest(provider_id=pid):
                self.put.reset_mock()
                r = client.post("/api/llm/keys", json=self._key_body(provider_id=pid),
                                headers=self._good_headers())
                self.assertIn(r.status_code, (400, 422))
                self.put.assert_not_called()
        for pid in good:
            with self.subTest(provider_id=pid):
                self.put.reset_mock()
                r = client.post("/api/llm/keys", json=self._key_body(provider_id=pid),
                                headers=self._good_headers())
                self.assertIn(r.status_code, (200, 201))
                self.assertIn(f"'llm_key_{pid}'", repr(self.put.call_args))

    def test_provider_add_requires_header(self):
        client = self._harness()
        body = {"provider_id": "openrouter", "display_name": "OpenRouter",
                "class": "openai_compat", "origin": "https://openrouter.ai",
                "list_endpoint": "/api/v1/models"}
        r = client.post("/api/llm/providers", json=body, headers={"Origin": UI_ORIGIN})
        self.assertIn(r.status_code, REFUSED)
        self.assertEqual(self.conn.statements, [])
        # Positive control: the same request with the header gets past the guard.
        r2 = client.post("/api/llm/providers", json=body, headers=self._good_headers())
        self.assertNotIn(r2.status_code, REFUSED)
        self.assertNotEqual(r2.status_code, 404)


if __name__ == "__main__":
    unittest.main()
