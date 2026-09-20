"""Translator 模型卸载/推理互斥与卸载后重载逻辑测试

processer 依赖 llama_cpp/appscript，这里以桩模块替换后导入，任何环境可跑。
"""
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

_test_dir = tempfile.TemporaryDirectory()

# 桩替换 processer 顶层依赖：假 Llama 的 create_completion 可阻塞，模拟真实推理耗时
_fake_appscript = types.ModuleType("appscript")


class _FakeLlama:
    def __init__(self, model_path=None, **kwargs):
        assert model_path and os.path.exists(model_path)
        self.reset_count = 0
        self.hold_seconds = 0.0
        self.started = threading.Event()
        self.release = threading.Event()

    def create_completion(self, **kwargs):
        self.started.set()
        if self.hold_seconds:
            self.release.wait(timeout=self.hold_seconds + 5)
        return {"choices": [{"text": "fake translation"}]}

    def reset(self):
        self.reset_count += 1


_fake_llama_cpp = types.ModuleType("llama_cpp")
_fake_llama_cpp.Llama = _FakeLlama

# llama_cpp/appscript 强制桩替换（仅 processer 消费，保证无依赖环境可跑）；
# setting 仅在导入 processer 期间临时注入桩（其余测试需要真实 setting），导入后还原
sys.modules.setdefault("appscript", _fake_appscript)
sys.modules.setdefault("llama_cpp", _fake_llama_cpp)
_setting_injected = False
if "setting" not in sys.modules:
    try:
        import setting  # noqa: F401
    except Exception:
        _fake_setting = types.ModuleType("setting")
        _fake_setting.chars_dict = {"zh": {}, "en": {}}
        _fake_setting.current_lang = "zh"
        sys.modules["setting"] = _fake_setting
        _setting_injected = True
import processer  # noqa: E402
from processer import Translator  # noqa: E402

if _setting_injected:
    del sys.modules["setting"]


def _make_model_file():
    path = os.path.join(_test_dir.name, "fake_model.gguf")
    with open(path, "wb") as f:
        f.write(b"fake")
    return path


class TranslatorUnloadTests(unittest.TestCase):
    def setUp(self):
        self.translator = Translator(log_level=40)
        self.model_file = _make_model_file()
        self.assertTrue(self.translator.load_model(self.model_file))

    def tearDown(self):
        self.translator.unload_model()

    def test_unload_releases_model(self):
        self.translator.unload_model()
        self.assertFalse(self.translator.model_available)
        self.assertIsNone(self.translator._model)

    def test_unload_waits_for_running_inference(self):
        # 推理进行中卸载：必须等待推理完成，期间模型引用不释放、翻译正常返回
        model = self.translator._model
        model.hold_seconds = 3.0
        done = {}
        thread = threading.Thread(
            target=lambda: done.update(
                result=self.translator.translate_with_streaming("hello", "English", "Chinese")),
            daemon=True,
        )
        thread.start()
        self.assertTrue(model.started.wait(timeout=5))

        unload_finished = threading.Event()
        unload_thread = threading.Thread(
            target=lambda: (self.translator.unload_model(), unload_finished.set()),
            daemon=True,
        )
        unload_thread.start()
        time.sleep(0.3)
        self.assertFalse(unload_finished.is_set())  # 推理中卸载被阻塞

        model.release.set()
        thread.join(timeout=5)
        self.assertTrue(unload_finished.wait(timeout=5))
        self.assertEqual(done.get("result"), "fake translation")
        self.assertFalse(self.translator.model_available)
        self.assertIsNone(self.translator._model)

    def test_translate_after_unload_raises_not_crash(self):
        self.translator.unload_model()
        with self.assertRaisesRegex(RuntimeError, "不可用"):
            self.translator.translate("hello", "English", "Chinese")

    def test_reload_after_unload_restores_translation(self):
        # 模拟 _do_translate 的懒加载路径：卸载后按配置路径重载即可恢复翻译
        self.translator.unload_model()
        self.assertTrue(self.translator.load_model(self.model_file))
        self.assertEqual(
            self.translator.translate_with_streaming("hello", "English", "Chinese"),
            "fake translation")

    def test_load_invalid_path_fails_safely_after_unload(self):
        self.translator.unload_model()
        self.assertFalse(self.translator.load_model(self.model_file + ".missing"))
        self.assertFalse(self.translator.model_available)


if __name__ == "__main__":
    unittest.main()
