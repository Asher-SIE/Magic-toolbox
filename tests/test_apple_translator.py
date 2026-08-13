import json
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


if __name__ == "__main__":
    unittest.main()
