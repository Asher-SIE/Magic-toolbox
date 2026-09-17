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
        LocalVLMEngine,
        OCREngine,
        OCRError,
        VLM_IMAGE_MAX_PIXELS,
        available_engines,
        create_engine,
        downscale_target_dimensions,
        engine_display,
        extract_clipboard_image,
        next_engine_key,
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
        # 生产内部机策略（DEBUG_BUILD=False）：内部机只有 Apple OCR
        with mock.patch.object(ocr_engine.setting, "DEBUG_BUILD", False):
            for is_internal in (True, False):
                engines = available_engines(is_internal)
                self.assertIn("apple", [engine.key for engine in engines])

    def test_internal_visibility_filter(self):
        with mock.patch.object(ocr_engine.setting, "DEBUG_BUILD", False), \
                mock.patch.dict(ocr_engine.OCR_ENGINES, {"thirdparty": InternalOnlyEngine}):
            self.assertEqual(
                [engine.key for engine in available_engines(True)], ["apple"])
            self.assertEqual(
                [engine.key for engine in available_engines(False)],
                ["apple", "vlm", "thirdparty"])

    def test_debug_build_opens_all_engines_for_internal(self):
        # 开发内部版本（DEBUG_BUILD=True）：放开内部机限制，开放全部已注册引擎
        with mock.patch.object(ocr_engine.setting, "DEBUG_BUILD", True), \
                mock.patch.dict(ocr_engine.OCR_ENGINES, {"thirdparty": InternalOnlyEngine}):
            self.assertEqual(
                [engine.key for engine in available_engines(True)],
                ["apple", "vlm", "thirdparty"])

    def test_create_engine_returns_instance(self):
        self.assertIsInstance(create_engine("apple"), AppleOCREngine)
        self.assertIsInstance(create_engine("vlm"), LocalVLMEngine)

    def test_create_engine_injects_config(self):
        engine = create_engine("vlm", model_path="a.gguf", mmproj_path="b.gguf")
        self.assertEqual(engine.model_path, "a.gguf")
        self.assertEqual(engine.mmproj_path, "b.gguf")

    def test_create_unknown_engine_raises(self):
        with self.assertRaisesRegex(OCRError, "未知的 OCR 引擎"):
            create_engine("thirdparty")

    def test_engine_display_uses_localized_name(self):
        self.assertEqual(engine_display("apple"), ocr_engine.setting._("ocr_engine_apple"))
        self.assertEqual(engine_display("missing"), "missing")


class NextEngineKeyTests(unittest.TestCase):
    def test_cycles_forward_and_backward(self):
        keys = ["apple", "vlm"]
        self.assertEqual(next_engine_key(keys, "apple", 1), "vlm")
        self.assertEqual(next_engine_key(keys, "vlm", 1), "apple")
        self.assertEqual(next_engine_key(keys, "apple", -1), "vlm")
        self.assertEqual(next_engine_key(keys, "vlm", -1), "apple")

    def test_single_engine_loops_to_itself(self):
        self.assertEqual(next_engine_key(["apple"], "apple", 1), "apple")
        self.assertEqual(next_engine_key(["apple"], "apple", -1), "apple")

    def test_empty_list_returns_current(self):
        self.assertEqual(next_engine_key([], "apple", 1), "apple")

    def test_unknown_current_falls_back_to_first(self):
        self.assertEqual(next_engine_key(["apple", "vlm"], "missing", 1), "vlm")


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


class LocalVLMEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = LocalVLMEngine(model_path="model.gguf", mmproj_path="mmproj.gguf")

    def test_visibility_follows_translation_llm_policy(self):
        # 与本地翻译 LLM 定位一致：公开版开放，生产内部机关闭（DEBUG_BUILD 由列表层统一放开）
        self.assertTrue(self.engine.is_available_for(False))
        self.assertFalse(self.engine.is_available_for(True))

    def test_describe_prompt_targets_captioning_not_ocr(self):
        # 本地视觉模型定位为图像描述引擎：提示词要求约 100 字描述，且不再包含 OCR 逐行输出指令
        self.assertIn("100", LocalVLMEngine.DESCRIBE_PROMPT)
        self.assertIn("描述", LocalVLMEngine.DESCRIBE_PROMPT)
        self.assertNotIn("OCR", LocalVLMEngine.DESCRIBE_PROMPT)
        # 100 字中文约 200 token，上限留冗余但不给 OCR 级别的 2048
        self.assertEqual(LocalVLMEngine.MAX_OUTPUT_TOKENS, 512)
        self.assertFalse(hasattr(LocalVLMEngine, "OCR_PROMPT"))

    def test_unconfigured_recognize_raises(self):
        engine = LocalVLMEngine()
        with self.assertRaises(OCRError):
            engine.recognize(__file__)

    def test_configure_updates_paths_and_unloads_model(self):
        self.engine._llm = mock.Mock()
        self.assertTrue(self.engine.is_loaded())

        self.engine.configure(model_path="other.gguf", mmproj_path="other-mmproj.gguf")

        self.assertEqual(self.engine.model_path, "other.gguf")
        self.assertFalse(self.engine.is_loaded())
        self.assertTrue(self.engine.needs_load())

    def test_configure_same_paths_keeps_model(self):
        self.engine._llm = mock.Mock()
        self.engine.configure(model_path="model.gguf", mmproj_path="mmproj.gguf")
        self.assertTrue(self.engine.is_loaded())

    def test_needs_load_states(self):
        engine = LocalVLMEngine()
        self.assertFalse(engine.needs_load())  # 未配置谈不上加载
        self.engine._llm = mock.Mock()
        self.assertFalse(self.engine.needs_load())  # 已加载

    def test_recognize_without_llama_bindings_raises(self):
        # llama-cpp-python 缺失/版本过旧时给出明确升级提示
        with mock.patch.object(ocr_engine, "Llama", None), \
                mock.patch.object(ocr_engine, "_LLAMA_VL_HANDLER", None):
            with self.assertRaisesRegex(OCRError, "llama-cpp-python"):
                self.engine.recognize(__file__)

    def test_load_model_missing_file_raises(self):
        with mock.patch.object(ocr_engine, "Llama", mock.Mock()), \
                mock.patch.object(ocr_engine, "_LLAMA_VL_HANDLER", mock.Mock()):
            with self.assertRaisesRegex(OCRError, "不存在"):
                self.engine.load_model()


class DownscaleTargetDimensionsTests(unittest.TestCase):
    def test_small_image_passthrough(self):
        # 几十万像素的小图不降采样：再缩只会丢细节，内存上没有收益
        self.assertIsNone(downscale_target_dimensions(800, 600))

    def test_at_cap_passthrough(self):
        self.assertIsNone(downscale_target_dimensions(1024, 1024))

    def test_oversized_image_scaled_within_cap(self):
        # 2560×1440 等比缩到面积上限内，保持 16:9 纵横比
        width, height = downscale_target_dimensions(2560, 1440)
        self.assertLessEqual(width * height, VLM_IMAGE_MAX_PIXELS)
        self.assertAlmostEqual(width / height, 2560 / 1440, delta=0.01)

    def test_square_image_halves(self):
        # 2000² 缩放系数恰为 0.512，落回 1024×1024（面积等于上限）
        self.assertEqual(downscale_target_dimensions(2000, 2000), (1024, 1024))

    def test_invalid_dimensions_passthrough(self):
        self.assertIsNone(downscale_target_dimensions(0, 100))
        self.assertIsNone(downscale_target_dimensions(-5, 100))


class LocalVLMDownscaleTests(unittest.TestCase):
    def setUp(self):
        self.engine = LocalVLMEngine(model_path="model.gguf", mmproj_path="mmproj.gguf")

    def test_oversized_image_uses_scaled_temp(self):
        with mock.patch.object(ocr_engine, "_probe_image_size", return_value=(2560, 1440)), \
                mock.patch.object(ocr_engine, "_write_downscaled_image", return_value="/tmp/scaled.png") as writer:
            path, is_temp = self.engine._downscale_if_needed("/tmp/big.png")
        self.assertEqual((path, is_temp), ("/tmp/scaled.png", True))
        writer.assert_called_once_with("/tmp/big.png", (1365, 768))

    def test_small_image_not_scaled(self):
        with mock.patch.object(ocr_engine, "_probe_image_size", return_value=(800, 600)), \
                mock.patch.object(ocr_engine, "_write_downscaled_image") as writer:
            path, is_temp = self.engine._downscale_if_needed("/tmp/small.png")
        self.assertEqual((path, is_temp), ("/tmp/small.png", False))
        writer.assert_not_called()

    def test_probe_failure_falls_back_to_original(self):
        with mock.patch.object(ocr_engine, "_probe_image_size", return_value=None), \
                mock.patch.object(ocr_engine, "_write_downscaled_image") as writer:
            path, is_temp = self.engine._downscale_if_needed("/tmp/odd.png")
        self.assertEqual((path, is_temp), ("/tmp/odd.png", False))
        writer.assert_not_called()

    def test_write_failure_falls_back_to_original(self):
        # 降采样失败不阻断识别：回退原图
        with mock.patch.object(ocr_engine, "_probe_image_size", return_value=(2560, 1440)), \
                mock.patch.object(ocr_engine, "_write_downscaled_image", return_value=None):
            path, is_temp = self.engine._downscale_if_needed("/tmp/big.png")
        self.assertEqual((path, is_temp), ("/tmp/big.png", False))

    def test_recognize_removes_scaled_temp_file(self):
        engine = self.engine
        engine._llm = mock.Mock()
        engine._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": " 一张测试图片 "}}]}
        fd, temp_path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, "wb") as f:
            f.write(b"fake-image-bytes")
        try:
            with mock.patch.object(engine, "_downscale_if_needed", return_value=(temp_path, True)):
                self.assertEqual(engine.recognize(__file__), "一张测试图片")
            self.assertFalse(os.path.exists(temp_path))  # 降采样临时文件用毕即删
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_recognize_keeps_original_file(self):
        engine = self.engine
        engine._llm = mock.Mock()
        engine._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "描述"}}]}
        fd, image_path = tempfile.mkstemp(suffix=".png")
        with os.fdopen(fd, "wb") as f:
            f.write(b"fake-image-bytes")
        try:
            with mock.patch.object(engine, "_downscale_if_needed", return_value=(image_path, False)):
                engine.recognize(__file__)
            self.assertTrue(os.path.exists(image_path))  # 原图不由引擎删除
        finally:
            if os.path.exists(image_path):
                os.remove(image_path)


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

    def test_first_file_url_returned_without_validation(self):
        # 不做多余校验：文件 URL（无论类型）直接交给当前引擎，错误由引擎播报
        url = self._make_url("/tmp/docs/report.txt")
        with mock.patch.object(ocr_engine, "IS_MACOS", True), \
                self._install_pasteboard(urls=[url]):
            self.assertEqual(extract_clipboard_image(), ("/tmp/docs/report.txt", False))

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
