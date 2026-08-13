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


class AppleTranslationPlatformTests(unittest.TestCase):
    @staticmethod
    def completed(version):
        return subprocess.CompletedProcess(["sw_vers"], 0, version, "")

    @mock.patch("setting.subprocess.run", return_value=completed.__func__("15.0.1\n"))
    def test_macos_15_is_supported(self, _run):
        self.assertTrue(setting.supports_apple_translation())

    @mock.patch("setting.subprocess.run", return_value=completed.__func__("14.7.6\n"))
    def test_macos_14_is_not_supported(self, _run):
        self.assertFalse(setting.supports_apple_translation())

    @mock.patch("setting.subprocess.run", side_effect=FileNotFoundError)
    def test_non_macos_is_not_supported(self, _run):
        self.assertFalse(setting.supports_apple_translation())


if __name__ == "__main__":
    unittest.main()
