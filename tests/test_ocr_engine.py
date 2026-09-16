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
    import ocr_engine
    from ocr_engine import (
        AppleOCREngine,
        OCREngine,
        OCRError,
        available_engines,
        create_engine,
        extract_clipboard_image,
    )


class InternalOnlyEngine(OCREngine):
    """模拟未来只在公开版开放的第三方引擎，用于验证注册表的可见性过滤"""

    key = "thirdparty"
    display_key = "ocr_engine_thirdparty"

    def is_available_for(self, is_internal):
        return not is_internal

    def is_available(self):
        return True

    def get_status_message(self):
        return ""

    def recognize(self, image_path):
        return ""


class OCREngineRegistryTests(unittest.TestCase):
    def test_apple_engine_available_for_internal_and_public(self):
        for is_internal in (True, False):
            engines = available_engines(is_internal)
            self.assertEqual([engine.key for engine in engines], ["apple"])

    def test_create_engine_returns_instance(self):
        self.assertIsInstance(create_engine("apple"), AppleOCREngine)

    def test_create_unknown_engine_raises(self):
        with self.assertRaisesRegex(OCRError, "未知的 OCR 引擎"):
            create_engine("thirdparty")

    def test_internal_visibility_filter(self):
        with mock.patch.dict(ocr_engine.OCR_ENGINES, {"thirdparty": InternalOnlyEngine}):
            self.assertEqual(
                [engine.key for engine in available_engines(True)], ["apple"])
            self.assertEqual(
                [engine.key for engine in available_engines(False)], ["apple", "thirdparty"])


class AppleOCREngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AppleOCREngine()

    def _patch_engine_ready(self):
        """使 is_available 恒为 True，跨平台聚焦文件校验路径"""
        return mock.patch.multiple(
            ocr_engine,
            IS_MACOS=True,
            VNImageRequestHandler=mock.Mock(),
            setting=mock.Mock(supports_apple_translation=mock.Mock(return_value=True)),
        )

    def test_empty_path_raises(self):
        with self._patch_engine_ready():
            with self.assertRaises(OCRError):
                self.engine.recognize("")

    def test_missing_file_raises(self):
        missing = os.path.join(_test_home.name, "missing.png")
        with self._patch_engine_ready():
            with self.assertRaisesRegex(OCRError, "图片文件不存在"):
                self.engine.recognize(missing)

    def test_unavailable_without_vision_binding(self):
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                mock.patch.object(ocr_engine, "VNImageRequestHandler", None):
            self.assertFalse(self.engine.is_available())
            self.assertIn("Vision", self.engine.get_status_message())
            with self.assertRaises(OCRError):
                self.engine.recognize(__file__)

    def test_unavailable_below_macos_26(self):
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                mock.patch.object(ocr_engine, "VNImageRequestHandler", mock.Mock()), \
                mock.patch.object(ocr_engine.setting, "supports_apple_translation", return_value=False):
            self.assertFalse(self.engine.is_available())
            self.assertIn("macOS 26", self.engine.get_status_message())

    def test_collect_lines_joins_top_candidates(self):
        first, second, empty = mock.Mock(), mock.Mock(), mock.Mock()
        first.string.return_value = "你好"
        second.string.return_value = "世界"
        empty.topCandidates_.return_value = []
        observation_a, observation_b = mock.Mock(), mock.Mock()
        observation_a.topCandidates_.return_value = [first]
        observation_b.topCandidates_.return_value = [second, empty]

        request = mock.Mock()
        request.results.return_value = [observation_a, observation_b]

        self.assertEqual(AppleOCREngine._collect_lines(request), "你好\n世界")


class ExtractClipboardImageTests(unittest.TestCase):
    @staticmethod
    def _make_url(path, is_file=True):
        url = mock.Mock()
        url.isFileURL.return_value = is_file
        url.path.return_value = path
        return url

    def _install_pasteboard(self, urls=None, data=None):
        pasteboard = mock.Mock()
        pasteboard.readObjectsForClasses_options_.return_value = urls or []
        pasteboard.dataForType_.side_effect = lambda utype: (data or {}).get(utype)
        return mock.patch.object(
            ocr_engine, "NSPasteboard",
            **{"generalPasteboard.return_value": pasteboard},
        )

    @unittest.skipIf(ocr_engine.IS_MACOS, "仅在非 macOS 平台验证降级路径")
    def test_returns_none_without_macos(self):
        self.assertIsNone(extract_clipboard_image())

    def test_file_url_image_returned_as_is(self):
        url = self._make_url("/tmp/photos/pic.png")
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(urls=[url]), \
                mock.patch("ocr_engine.os.path.isfile", return_value=True):
            self.assertEqual(extract_clipboard_image(), ("/tmp/photos/pic.png", False))

    def test_heic_file_accepted(self):
        url = self._make_url("/tmp/photos/pic.heic")
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(urls=[url]), \
                mock.patch("ocr_engine.os.path.isfile", return_value=True):
            self.assertEqual(extract_clipboard_image(), ("/tmp/photos/pic.heic", False))

    def test_non_image_file_falls_through(self):
        url = self._make_url("/tmp/docs/report.txt")
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(urls=[url]):
            self.assertIsNone(extract_clipboard_image())

    def test_web_url_ignored(self):
        url = self._make_url("https://example.com/pic.png", is_file=False)
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(urls=[url]):
            self.assertIsNone(extract_clipboard_image())

    def test_bitmap_data_written_to_temp_file(self):
        png_bytes = b"\x89PNG-fake-bytes"
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(data={"public.png": png_bytes}):
            result = extract_clipboard_image()
        self.assertIsNotNone(result)
        path, is_temp = result
        self.assertTrue(is_temp)
        self.assertTrue(path.endswith(".png"))
        try:
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), png_bytes)
        finally:
            os.remove(path)

    def test_empty_clipboard_returns_none(self):
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard():
            self.assertIsNone(extract_clipboard_image())


if __name__ == "__main__":
    unittest.main()
