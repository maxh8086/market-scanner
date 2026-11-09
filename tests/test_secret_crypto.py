"""Offline tests for the app-secret encryption layer (S1). No database, no network."""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scanner import secret_crypto as sc


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(sc.KEY_BYTES)
        self.aad = sc.aad_for("app_secret", "UPSTOX_ANALYTICS_ACCESS_TOKEN", "app", 1)

    def test_round_trip(self):
        nonce, ct = sc.encrypt(self.key, "value-123", self.aad)
        self.assertEqual(sc.decrypt(self.key, nonce, ct, self.aad), "value-123")

    def test_ciphertext_hides_plaintext(self):
        _, ct = sc.encrypt(self.key, "value-123", self.aad)
        self.assertNotIn(b"value-123", ct)

    def test_nonce_is_fresh_per_write(self):
        n1, c1 = sc.encrypt(self.key, "same", self.aad)
        n2, c2 = sc.encrypt(self.key, "same", self.aad)
        self.assertEqual(len(n1), sc.NONCE_BYTES)
        self.assertNotEqual(n1, n2)
        self.assertNotEqual(c1, c2)

    def test_wrong_key_fails(self):
        nonce, ct = sc.encrypt(self.key, "v", self.aad)
        with self.assertRaises(sc.DecryptError):
            sc.decrypt(os.urandom(sc.KEY_BYTES), nonce, ct, self.aad)

    def test_wrong_associated_data_fails(self):
        nonce, ct = sc.encrypt(self.key, "v", self.aad)
        other = sc.aad_for("app_secret", "KITE_API_KEY", "app", 1)
        with self.assertRaises(sc.DecryptError):
            sc.decrypt(self.key, nonce, ct, other)

    def test_tampered_ciphertext_fails(self):
        nonce, ct = sc.encrypt(self.key, "v", self.aad)
        bad = bytearray(ct)
        bad[0] ^= 0x01
        with self.assertRaises(sc.DecryptError):
            sc.decrypt(self.key, nonce, bytes(bad), self.aad)

    def test_decrypt_error_does_not_echo_key_or_ciphertext(self):
        nonce, ct = sc.encrypt(self.key, "v", self.aad)
        try:
            sc.decrypt(os.urandom(sc.KEY_BYTES), nonce, ct, self.aad)
        except sc.DecryptError as e:
            msg = str(e)
            self.assertNotIn(ct.hex()[:16], msg)
            self.assertEqual(msg, "decryption failed")


class MasterKeyFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_fails_closed(self):
        with self.assertRaises(sc.MasterKeyError):
            sc.load_master_key(self.dir / "absent.key")

    def test_malformed_base64_fails(self):
        p = self.dir / "bad.key"
        p.write_text("not base64 !!\n", encoding="ascii")
        with self.assertRaises(sc.MasterKeyError) as cm:
            sc.load_master_key(p)
        self.assertNotIn("not base64 !!", str(cm.exception))

    def test_wrong_length_fails(self):
        p = self.dir / "short.key"
        p.write_text(base64.b64encode(os.urandom(16)).decode() + "\n", encoding="ascii")
        with self.assertRaises(sc.MasterKeyError):
            sc.load_master_key(p)

    def test_valid_file_loads(self):
        raw = os.urandom(sc.KEY_BYTES)
        p = self.dir / "ok.key"
        p.write_text(base64.b64encode(raw).decode() + "\n", encoding="ascii")
        self.assertEqual(sc.load_master_key(p), raw)

    def test_write_new_key_file_creates_32_byte_key(self):
        p = self.dir / "sub" / "new.key"
        sc.write_new_key_file(p)
        self.assertEqual(len(sc.load_master_key(p)), sc.KEY_BYTES)

    def test_write_new_key_file_refuses_overwrite(self):
        p = self.dir / "exists.key"
        sc.write_new_key_file(p)
        before = p.read_bytes()
        with self.assertRaises(sc.MasterKeyError):
            sc.write_new_key_file(p)
        self.assertEqual(p.read_bytes(), before)

    @unittest.skipIf(os.name == "nt", "POSIX file modes are not enforced on Windows")
    def test_key_file_is_owner_only(self):
        p = self.dir / "mode.key"
        sc.write_new_key_file(p)
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_unset_env_var_fails_closed(self):
        env = {k: v for k, v in os.environ.items() if k != sc.KEY_FILE_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(sc.MasterKeyError):
                sc.load_master_key()

    def test_env_var_selects_key_path(self):
        p = self.dir / "env.key"
        sc.write_new_key_file(p)
        with mock.patch.dict(os.environ, {sc.KEY_FILE_ENV: str(p)}):
            self.assertEqual(len(sc.load_master_key()), sc.KEY_BYTES)


class UIStartupTests(unittest.TestCase):
    """The UI app refuses to start without a valid master key."""

    def test_startup_check_fails_without_key(self):
        from ui.app import main as ui_main
        with tempfile.TemporaryDirectory() as d:
            env = {sc.KEY_FILE_ENV: str(Path(d) / "missing.key")}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(sc.MasterKeyError):
                    ui_main.check_master_key()


if __name__ == "__main__":
    unittest.main()
