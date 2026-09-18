import os
import subprocess
import tempfile
import unittest
from unittest import mock

_test_home = tempfile.TemporaryDirectory()
with mock.patch("os.path.expanduser", return_value=_test_home.name), mock.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, '"IOPlatformUUID" = "TEST-UUID"\n', ""),
    ):
    import setting


class DebugBuildConfigTests(unittest.TestCase):
    """验证 DEBUG_BUILD 标志从 debug_config.json 读取的各种状态"""

    def setUp(self):
        self._app_dir = os.path.join(_test_home.name, "Library", "Application Support", "MagicToolbox")
        os.makedirs(self._app_dir, exist_ok=True)
        self._config_path = os.path.join(self._app_dir, "debug_config.json")
        self.addCleanup(self._remove_config)

    def _remove_config(self):
        if os.path.exists(self._config_path):
            os.remove(self._config_path)

    def _write(self, content):
        with open(self._config_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _load(self):
        with mock.patch.object(setting, "app_data_dir", self._app_dir):
            return setting._load_debug_build()

    def test_missing_file_defaults_false(self):
        self.assertFalse(self._load())

    def test_true_enables_debug(self):
        self._write('{"debug_build": true}')
        self.assertTrue(self._load())

    def test_false_keeps_disabled(self):
        self._write('{"debug_build": false}')
        self.assertFalse(self._load())

    def test_missing_key_defaults_false(self):
        self._write('{"other": true}')
        self.assertFalse(self._load())

    def test_broken_json_defaults_false(self):
        self._write("{broken json")
        self.assertFalse(self._load())

    def test_internal_locked_without_debug(self):
        with mock.patch.object(setting, "is_internal_device", return_value=True), \
                mock.patch.object(setting, "DEBUG_BUILD", False):
            self.assertTrue(setting.is_internal_locked())

    def test_internal_unlocked_with_debug(self):
        with mock.patch.object(setting, "is_internal_device", return_value=True), \
                mock.patch.object(setting, "DEBUG_BUILD", True):
            self.assertFalse(setting.is_internal_locked())

    def test_external_never_locked(self):
        with mock.patch.object(setting, "is_internal_device", return_value=False), \
                mock.patch.object(setting, "DEBUG_BUILD", False):
            self.assertFalse(setting.is_internal_locked())


if __name__ == "__main__":
    unittest.main()
