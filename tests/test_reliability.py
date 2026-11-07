"""Offline regressions; never open user settings or start mining services."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from release_candidate import sanitize_config, redact_text
from update_release_center import UpdateReleaseCenter


class ConfigRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.file = self.root / "settings.json"
        self.patches = [patch.object(config, "CONFIG_DIR", self.root),
                        patch.object(config, "CONFIG_FILE", self.file)]
        for item in self.patches:
            item.start()
        self.status = dict(config.RECOVERY_STATUS)
        config.RECOVERY_STATUS.update(recovered=False, reason="", preserved=False)

    def tearDown(self):
        config.RECOVERY_STATUS.update(self.status)
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_corrupt_input_is_preserved_before_defaults_are_saved(self):
        for bad in ('{"partial":', '[]', '{"benchmark_processes": NaN}', '{"value": 1e999}', '\udcff'):
            with self.subTest(bad=repr(bad)):
                self.file.write_bytes(bad.encode("utf-8", errors="surrogateescape"))
                original = self.file.read_bytes()
                result = config.load_config()
                self.assertEqual(result["benchmark_processes"], 2)
                self.assertTrue(config.RECOVERY_STATUS["preserved"])
                self.assertIn(original, [p.read_bytes() for p in self.root.glob("settings.corrupt-*.json")])
                config.save_config(result)
                self.assertIsInstance(json.loads(self.file.read_text()), dict)

    def test_wrong_types_and_defaults_are_isolated(self):
        self.file.write_text(json.dumps({"tray_enabled": "false", "pool_backup_urls": None,
                                        "mining_processes": [], "ui_theme": {}}))
        result = config.load_config()
        self.assertIs(result["tray_enabled"], True)
        self.assertEqual(result["mining_processes"], 2)
        result["pool_backup_urls"].append("private")
        self.assertEqual(config.DEFAULTS["pool_backup_urls"], [])

    def test_failed_replace_keeps_original_and_cleans_temporary_file(self):
        self.file.write_text('{"benchmark_processes": 4}')
        original = self.file.read_bytes()
        with patch.object(config.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                config.save_config(config.DEFAULTS)
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_failed_preservation_prevents_overwrite(self):
        self.file.write_text('{broken')
        with patch.object(Path, "replace", side_effect=PermissionError):
            result = config.load_config()
        with self.assertRaises(OSError):
            config.save_config(result)
        self.assertEqual(self.file.read_text(), '{broken')

    def test_secrets_and_nonfinite_values_are_not_written(self):
        config.save_config({"rpc_password": "secret", "pool_password": "secret", "benchmark_processes": 3})
        self.assertNotIn("secret", self.file.read_text())
        original = self.file.read_bytes()
        with self.assertRaises(ValueError):
            config.save_config({"number": float("nan")})
        self.assertEqual(original, self.file.read_bytes())


class SupportPrivacyTests(unittest.TestCase):
    def test_nested_lists_and_key_variants(self):
        value = {"items": [[{"rpc_password": "SENTINEL", "privateKey": "SENTINEL",
                              "api-key": "SENTINEL", "pool_worker": "SENTINEL"}]],
                 "access_token": "SENTINEL"}
        self.assertNotIn("SENTINEL", json.dumps(sanitize_config(value)))

    def test_log_credentials_and_multiline_keys(self):
        for value in ('{"rpc_password": "SENTINEL with spaces"}',
                      'https://user:SENTINEL@localhost:8332/',
                      'Authorization: Bearer SENTINEL',
                      '-----BEGIN PRIVATE KEY-----\nSENTINEL\n-----END PRIVATE KEY-----'):
            self.assertNotIn("SENTINEL", redact_text(value))


class ReleaseVerificationTests(unittest.TestCase):
    def test_checksum_cannot_be_silently_ignored_for_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            center = UpdateReleaseCenter(root, "2.0.2", app_data_dir=root / "state")
            center.inspect(str(root), "a" * 64)
            self.assertFalse(center._last_inspection["ok"])
            self.assertIn("requires a package file", center._last_inspection["detail"])

    def test_malformed_checksum_blocks_before_package_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "candidate.zip"
            package.write_bytes(b"not a zip")
            center = UpdateReleaseCenter(root, "2.0.2", app_data_dir=root / "state")
            center.inspect(str(package), "oops")
            self.assertFalse(center._last_inspection["ok"])
            self.assertIn("64 hexadecimal", center._last_inspection["detail"])


if __name__ == "__main__":
    unittest.main()
