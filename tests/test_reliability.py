"""Offline regressions; never open user settings or start mining services."""
import json
import sys
import tempfile
import unittest
import zipfile
import os
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import reliability_io
from release_candidate import sanitize_config, redact_text
from update_release_center import UpdateReleaseCenter
import release_candidate as release
from diagnostics_center import DiagnosticsSupportCenter
from workspace_manager import WorkspaceManager
from pool_profiles import PoolProfileStore


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
        config.RECOVERY_STATUS.update(recovered=False, reason="", preserved=False, write_blocked=False, fields=[])

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
        with patch.object(reliability_io.os, "replace", side_effect=OSError("disk unavailable")):
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

    def test_ranges_and_nested_device_types_are_recovered_with_evidence(self):
        self.file.write_text(json.dumps({"tray_poll_seconds": -1, "regtest_lab_rpc_port": 999999,
                                        "asic_known_devices": [{}], "core_refresh_seconds": 0}))
        result = config.load_config()
        self.assertEqual(result["tray_poll_seconds"], 10)
        self.assertEqual(result["regtest_lab_rpc_port"], 19443)
        self.assertEqual(result["asic_known_devices"], [])
        self.assertTrue(config.recovery_status()["preserved"])
        config.load_config()
        self.assertTrue(config.recovery_status()["recovered"])
        checks = []
        center = DiagnosticsSupportCenter(self.root, "2.0.3", app_data_dir=self.root / "data")
        center._configuration_checks(checks, result)
        self.assertTrue(any(row["code"] == "config.startup_recovery" for row in checks))

    def test_local_pool_restore_cannot_reintroduce_invalid_settings(self):
        self.file.write_text(json.dumps({"pool_url_ephemeral_local_test": True,
                                        "pool_restore_after_local_test": {"mining_processes": [], "pool_backup_urls": None}}))
        result = config.load_config()
        self.assertEqual(result["pool_restore_after_local_test"], {})
        self.assertTrue(config.recovery_status()["preserved"])


class PersistentStateTests(unittest.TestCase):
    def test_stopped_native_monitor_generation_cannot_restart_itself(self):
        # Import the native bridge without leaking its standalone protocol setup
        # into this test process's streams, environment or module registry.
        with patch.dict(os.environ), patch.dict(sys.modules), patch.object(sys, "stdout", sys.stderr):
            import windows_native_bridge as bridge
        entered, release_snapshot = threading.Event(), threading.Event()
        emitted = []

        class Backend:
            cfg = {"tray_enabled": True, "tray_poll_seconds": 10}
            calls = 0

            def _tray_status_snapshot(self):
                self.calls += 1
                if self.calls == 1:
                    entered.set()
                    release_snapshot.wait(5)
                return {}

        manager = bridge.NativeHostTrayManager(Backend())
        manager.supported = True
        with patch.object(bridge, "_host_event", side_effect=lambda *a, **kw: emitted.append(threading.get_ident())):
            try:
                manager.start()
                self.assertTrue(entered.wait(2))
                old_thread, old_stop = manager._thread, manager._stop
                manager.stop()
                manager.start()
                self.assertIsNot(manager._stop, old_stop)
                self.assertTrue(old_stop.is_set())
                release_snapshot.set()
                old_thread.join(2)
                self.assertFalse(old_thread.is_alive())
                self.assertNotIn(old_thread.ident, emitted)
            finally:
                release_snapshot.set()
                manager.stop()

    def test_workspace_wrong_types_and_usage_do_not_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            path.write_text(json.dumps({"last_view": {}, "recent_views": None, "pinned_views": 2,
                                        "command_usage": {"test": "bad"}, "sidebar_compact": "false"}))
            manager = WorkspaceManager(path)
            self.assertEqual(manager.snapshot()["last_view"], "dashboard")
            self.assertFalse(manager.snapshot()["sidebar_compact"])
            manager.record_command("test")
            self.assertEqual(manager.snapshot()["command_usage"]["test"], 1)
            self.assertEqual(len(list(path.parent.glob("workspace.corrupt-*.json"))), 1)

    def test_profile_storage_preserves_invalid_root_before_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text('{"profiles": null}')
            store = PoolProfileStore(path)
            self.assertEqual(store.list(), [])
            store._save()
            self.assertEqual(len(list(path.parent.glob("profiles.corrupt-*.json"))), 1)

    def test_session_marker_corruption_and_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "runtime-session.json"
            marker.write_text('{"clean_shutdown":"false"}')
            with patch.object(release, "SESSION_MARKER", marker), patch.object(release, "APP_DATA_DIR", root):
                manager = release.ReleaseCandidateManager(root, "2.0.3", config.DEFAULTS)
                self.assertTrue(manager.state()["previous_unclean_shutdown"])
                manager.mark_clean_shutdown()
                self.assertIs(json.loads(marker.read_text())["clean_shutdown"], True)
                next_manager = release.ReleaseCandidateManager(root, "2.0.3", config.DEFAULTS)
                self.assertFalse(next_manager.state()["previous_unclean_shutdown"])


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

    def test_actual_bundle_entries_are_sanitized_and_outputs_are_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = {**config.DEFAULTS, "rows": [[{"api_key": "SENTINEL"}]], "pool_worker": "SENTINEL"}
            log = '{"rpc_password": "SENTINEL with spaces"}'
            (root / "startup-error.log").write_text(log)
            (root / "settings.corrupt-private.json").write_text("SENTINEL")
            (root / "analytics.sqlite3").write_text("SENTINEL")
            with patch.object(release, "SESSION_MARKER", root / "session.json"), \
                 patch.object(release, "APP_DATA_DIR", root), patch.object(release, "SUPPORT_DIR", root / "support"), \
                 patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}):
                manager = release.ReleaseCandidateManager(root, "2.0.3", cfg)
                manager._state["checks"] = [{"password": "SENTINEL", "detail": log}]
                center = DiagnosticsSupportCenter(root, "2.0.3", app_data_dir=root / "data")
                center._state.update(checked=True, checks=[{"api_key": "SENTINEL", "detail": log}])
                outputs = [manager.create_support_bundle(cfg, logs=[{"time": "", "message": log}]),
                           manager.create_support_bundle(cfg),
                           center.create_support_bundle({"cfg": cfg, "release_report": log, "logs": [{"message": log}]})]
                self.assertEqual(len({item["path"] for item in outputs}), 3)
                for result in outputs:
                    with zipfile.ZipFile(result["path"]) as archive:
                        self.assertIsNone(archive.testzip())
                        for name in archive.namelist():
                            data = archive.read(name).decode("utf-8")
                            self.assertNotIn("SENTINEL", data, name)
                            self.assertNotIn("corrupt", name)
                            self.assertNotIn("sqlite", name)
                            if name.endswith(".json"):
                                json.loads(data)

    def test_bundle_failure_leaves_no_partial_or_temporary_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(release, "SESSION_MARKER", root / "session.json"), \
                 patch.object(release, "APP_DATA_DIR", root), patch.object(release, "SUPPORT_DIR", root / "support"):
                manager = release.ReleaseCandidateManager(root, "2.0.3", config.DEFAULTS)
                with patch.object(release.zipfile.ZipFile, "writestr", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        manager.create_support_bundle(config.DEFAULTS)
                self.assertEqual(list((root / "support").iterdir()), [])
                self.assertEqual(manager.state()["support_bundle"], "")

    def test_native_diagnostics_does_not_require_legacy_gui_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
                         "WebView2Loader.dll", "_runtime/python.exe", "_runtime/bms_native_bridge.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            center = DiagnosticsSupportCenter(root, "2.0.3", app_data_dir=root / "data")
            checks = []
            with patch.dict(os.environ, {"BMS_NATIVE_HOST": "1", "BMS_GUI_BACKEND": "microsoft-edge-webview2-direct"}):
                with patch("diagnostics_center.importlib.import_module", side_effect=AssertionError("Legacy import")):
                    center._runtime_checks(checks, "quick")
            self.assertTrue(any(row["code"] == "runtime.webview2_native" and row["status"] == "pass" for row in checks))


class ReleaseVerificationTests(unittest.TestCase):
    def test_native_runtime_inventory_cannot_bypass_source_binding(self):
        from update_release_center import verify_release_folder
        import hashlib
        from purple_dragon_security import PRODUCT_NAME, SECURITY_SCHEME, publisher_key_id
        from branding import PUBLISHER_NAME
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {"product": PRODUCT_NAME, "security_scheme": SECURITY_SCHEME,
                        "publisher_key_id": publisher_key_id(), "publisher_name": PUBLISHER_NAME,
                        "version": "2.0.3", "files": {}, "signature": "fixture"}
            (root / "purple_dragon_manifest.json").write_text(json.dumps(manifest))
            (root / "release_info.json").write_text(json.dumps({"product": PRODUCT_NAME, "version": "2.0.3"}))
            runtime = root / "_runtime"
            runtime.mkdir()
            binary = runtime / "python.exe"
            binary.write_bytes(b"fixture-runtime")
            with patch("update_release_center._verify_rsa_pkcs1_v15_sha256", return_value=True):
                missing = verify_release_folder(root)
                self.assertFalse(missing["trusted"])
                self.assertTrue(any("runtime inventory" in error for error in missing["errors"]))
                inventory = {"schema": 1, "product": PRODUCT_NAME, "version": "2.0.3",
                             "publisher_key_id": publisher_key_id(), "source_manifest_sha256": "wrong-source",
                             "files": {"_runtime/python.exe": hashlib.sha256(binary.read_bytes()).hexdigest()}, "signature": "fixture"}
                (root / "purple_dragon_runtime.json").write_text(json.dumps(inventory))
                self.assertFalse(verify_release_folder(root)["trusted"])
                inventory["source_manifest_sha256"] = hashlib.sha256((root / "purple_dragon_manifest.json").read_bytes()).hexdigest()
                (root / "purple_dragon_runtime.json").write_text(json.dumps(inventory))
                self.assertTrue(verify_release_folder(root)["trusted"])
                binary.write_bytes(b"tampered-runtime")
                self.assertFalse(verify_release_folder(root)["trusted"])
            # A forged signature must fail even when the inventory digest matches.
            self.assertFalse(verify_release_folder(root)["trusted"])

    def test_unreadable_package_returns_blocked_inspection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "candidate.zip"
            package.touch()
            center = UpdateReleaseCenter(root, "2.0.2", app_data_dir=root / "state")
            with patch("update_release_center._sha256_file", side_effect=PermissionError("private path")):
                center.inspect(str(package))
            self.assertFalse(center._last_inspection["ok"])
            self.assertNotIn("private path", center._last_inspection["detail"])

    def test_changed_folder_is_rejected_and_partial_staging_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "candidate"
            folder.mkdir()
            (folder / "purple_dragon_manifest.json").write_text('{}')
            center = UpdateReleaseCenter(root, "2.0.2", app_data_dir=root / "state")
            center._last_inspection = {"ok": True, "source": str(folder), "trust": {"trusted": True, "version": "2.0.3"},
                                       "manifest_sha256": "previously verified manifest digest"}
            with patch("update_release_center.verify_release_folder", return_value={"trusted": False}):
                with self.assertRaises(OSError):
                    center.stage_last_inspection()
            self.assertEqual(list(center.staging_dir.iterdir()), [])
            self.assertFalse(center.rollback_file.exists())

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
