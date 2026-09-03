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
    from apple_translator import AppleTranslationError, AppleTranslator


class AppleTranslatorTests(unittest.TestCase):
    def setUp(self):
        self.translator = AppleTranslator(tool_path=__file__, timeout=12)

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_translate_uses_json_stdin_and_maps_languages(self, run, _supports):
        run.return_value = subprocess.CompletedProcess(
            [__file__], 0, json.dumps({"ok": True, "translatedText": "你好"}), ""
        )

        result = self.translator.translate("Hello 世界", "English", "Chinese")

        self.assertEqual(result, "你好")
        kwargs = run.call_args.kwargs
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
    def test_prepare_uses_same_protocol(self, run, _supports):
        run.return_value = subprocess.CompletedProcess(
            [__file__], 0, json.dumps({"ok": True}), ""
        )
        self.assertTrue(self.translator.prepare_translation("Japanese", "English"))
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["action"], "prepare")
        self.assertEqual(payload["sourceLanguage"], "ja")
        self.assertEqual(payload["targetLanguage"], "en")

    @mock.patch("apple_translator.setting.supports_apple_translation", return_value=True)
    @mock.patch("apple_translator.subprocess.run")
    def test_native_error_is_reported(self, run, _supports):
        run.return_value = subprocess.CompletedProcess(
            [__file__], 0, json.dumps({"ok": False, "error": "unsupported language"}), ""
        )
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
        self.assertIn("macOS 15", self.translator.get_status_message())

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
