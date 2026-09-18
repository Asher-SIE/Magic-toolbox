import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_test_home = tempfile.TemporaryDirectory()
with mock.patch("os.path.expanduser", return_value=_test_home.name), mock.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, '"IOPlatformUUID" = "TEST-UUID"\n', ""),
    ):
    from apple_translator import (
        LANGUAGE_DOWNLOAD_HINT,
        STATUS_INSTALLED,
        STATUS_SUPPORTED,
        STATUS_UNSUPPORTED,
        AppleTranslationError,
        AppleTranslator,
    )


class AppleTranslatorTests(unittest.TestCase):
    def setUp(self):
        self.translator = AppleTranslator(tool_path=__file__, timeout=12)

    @staticmethod
    def _completed(stdout):
        return subprocess.CompletedProcess([__file__], 0, stdout, "")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_translate_prechecks_status_then_translates(self, run, _supports):
        run.side_effect = [
            self._completed(json.dumps({"ok": True, "status": STATUS_INSTALLED})),
            self._completed(json.dumps({"ok": True, "translatedText": "你好"})),
        ]

        result = self.translator.translate("Hello 世界", "English", "Chinese")

        self.assertEqual(result, "你好")
        self.assertEqual(run.call_count, 2)
        status_payload = json.loads(run.call_args_list[0].kwargs["input"])
        self.assertEqual(status_payload, {
            "action": "status",
            "sourceLanguage": "en",
            "targetLanguage": "zh-Hans",
        })
        kwargs = run.call_args_list[1].kwargs
        self.assertEqual(kwargs["timeout"], 12)
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload, {
            "action": "translate",
            "sourceLanguage": "en",
            "targetLanguage": "zh-Hans",
            "text": "Hello 世界",
        })

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_get_language_status_caches_result(self, run, _supports):
        run.return_value = self._completed(json.dumps({"ok": True, "status": STATUS_INSTALLED}))

        self.assertEqual(self.translator.get_language_status("English", "Chinese"), STATUS_INSTALLED)
        self.assertEqual(self.translator.get_language_status("English", "Chinese"), STATUS_INSTALLED)

        self.assertEqual(run.call_count, 1)

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_missing_language_pack_fails_fast_via_helper(self, run, _supports):
        """缓存状态为"未安装"时不再短路：语言包可能在启动预检后才装好，
        交给实际调用验证，确实未装时由 Swift 侧快速失败返回 language_not_installed"""
        run.side_effect = [
            self._completed(json.dumps({"ok": True, "status": STATUS_SUPPORTED})),
            self._completed(json.dumps({"ok": False, "code": "language_not_installed"})),
        ]

        with self.assertRaisesRegex(AppleTranslationError, LANGUAGE_DOWNLOAD_HINT):
            self.translator.translate("hello", "English", "Chinese")

        self.assertEqual(run.call_count, 2)
        payload = json.loads(run.call_args_list[1].kwargs["input"])
        self.assertEqual(payload["action"], "translate")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_install_after_cache_recovers_without_restart(self, run, _supports):
        """启动预检缓存"未安装"后用户装好语言包：无需重启应用，重试即翻译成功"""
        self.translator._language_status_cache[("en", "zh-Hans")] = STATUS_SUPPORTED
        run.return_value = self._completed(json.dumps({"ok": True, "translatedText": "你好"}))

        result = self.translator.translate("hello", "English", "Chinese")

        self.assertEqual(result, "你好")
        self.assertEqual(run.call_count, 1)
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["action"], "translate")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_unsupported_pair_blocks_translation(self, run, _supports):
        run.return_value = self._completed(json.dumps({"ok": True, "status": STATUS_UNSUPPORTED}))

        with self.assertRaisesRegex(AppleTranslationError, "不支持"):
            self.translator.translate("hello", "English", "Chinese")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_get_language_hint_messages(self, run, _supports):
        run.return_value = self._completed(json.dumps({"ok": True, "status": STATUS_SUPPORTED}))
        self.assertIn("系统设置", self.translator.get_language_hint("English", "Chinese"))
        self.translator._language_status_cache.clear()

        run.return_value = self._completed(json.dumps({"ok": True, "status": STATUS_UNSUPPORTED}))
        self.assertIn("不支持", self.translator.get_language_hint("English", "Chinese"))
        self.translator._language_status_cache.clear()

        run.return_value = self._completed(json.dumps({"ok": True, "status": STATUS_INSTALLED}))
        self.assertEqual(self.translator.get_language_hint("English", "Chinese"), "")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_native_not_installed_code_maps_to_download_hint(self, run, _supports):
        run.side_effect = [
            self._completed(json.dumps({"ok": True, "status": STATUS_INSTALLED})),
            self._completed(json.dumps({
                "ok": False, "error": "not installed", "code": "language_not_installed",
            })),
        ]

        with self.assertRaisesRegex(AppleTranslationError, "系统设置"):
            self.translator.translate("hello", "English", "Chinese")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_native_error_is_reported(self, run, _supports):
        run.side_effect = [
            self._completed(json.dumps({"ok": True, "status": STATUS_INSTALLED})),
            self._completed(json.dumps({"ok": False, "error": "unsupported language"})),
        ]

        with self.assertRaisesRegex(AppleTranslationError, "unsupported language"):
            self.translator.translate("hello", "English", "Klingon")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run", side_effect=subprocess.TimeoutExpired("tool", 12))
    def test_timeout_is_reported(self, _run, _supports):
        with self.assertRaisesRegex(AppleTranslationError, "超时"):
            self.translator.translate("hello", "English", "Chinese")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=False)
    def test_unsupported_system_is_unavailable(self, _supports):
        self.assertFalse(self.translator.is_available())
        self.assertIn("macOS 26", self.translator.get_status_message())

    def test_empty_text_does_not_launch_helper(self):
        with mock.patch.object(self.translator, "_invoke") as invoke:
            self.assertEqual(self.translator.translate("  ", "English", "Chinese"), "")
            invoke.assert_not_called()


class AppleTranslatorPathResolutionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tool_dir = os.path.join(self._tmp.name, "AppleTranslateTool.app", "Contents", "MacOS")
        os.makedirs(tool_dir)
        self.tool_path = os.path.join(tool_dir, "AppleTranslateTool-bin")
        with open(self.tool_path, "wb") as fh:
            fh.write(b"stub")
        os.chmod(self.tool_path, 0o755)

    def test_resolves_tool_from_candidate_root(self):
        translator = AppleTranslator()
        with mock.patch.object(
            AppleTranslator, "_candidate_roots", return_value=[self._tmp.name]
        ):
            self.assertEqual(translator._resolve_tool_path(), self.tool_path)
            self.assertTrue(translator._check_tool_available())

    def test_frozen_app_includes_bundle_roots(self):
        exe_dir = os.path.join(self._tmp.name, "MacOS")
        os.makedirs(exe_dir)
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "_MEIPASS", self._tmp.name, create=True), \
                mock.patch.object(sys, "executable", os.path.join(exe_dir, "MagicToolbox")):
            roots = AppleTranslator._candidate_roots()
        self.assertIn(self._tmp.name, roots)
        self.assertIn(exe_dir, roots)

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    def test_missing_explicit_tool_path_is_unavailable(self, _supports):
        translator = AppleTranslator(tool_path=os.path.join(self._tmp.name, "missing"))
        self.assertIsNone(translator._resolve_tool_path())
        self.assertFalse(translator.is_available())


if __name__ == "__main__":
    unittest.main()
