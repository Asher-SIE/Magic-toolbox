"""extract_url 提取与 VoiceOverHandler.get_last_spoken_text 即时读取逻辑测试

processer 依赖 llama_cpp/appscript，这里以桩模块替换后导入，任何环境可跑。
"""
import sys
import types
import unittest

# 桩替换 processer 顶层依赖（仅 processer 消费，保证无依赖环境可跑）；
# setting 仅在导入 processer 期间临时注入桩（其余测试需要真实 setting），导入后还原
_fake_appscript = types.ModuleType("appscript")
_vo_content = {"text": None}


class _FakeVoiceOver:
    """last_phrase.content() 可预设/可抛异常的 VoiceOver 桩应用"""

    def __init__(self, _appId):
        pass

    @property
    def last_phrase(self):
        text = _vo_content["text"]
        if isinstance(text, Exception):
            raise text
        return types.SimpleNamespace(content=lambda: text)


_fake_appscript.app = _FakeVoiceOver

_fake_llama_cpp = types.ModuleType("llama_cpp")
_fake_llama_cpp.Llama = object

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
from processer import VoiceOverHandler, extract_url  # noqa: E402

if _setting_injected:
    del sys.modules["setting"]


class ExtractUrlTests(unittest.TestCase):
    def test_plain_https_url(self):
        self.assertEqual(extract_url("https://example.com/a?b=1"), "https://example.com/a?b=1")

    def test_url_with_chinese_context(self):
        # 中文紧贴URL无空格时按非URL字符截断
        self.assertEqual(extract_url("详情见https://example.com/path，谢谢"), "https://example.com/path")

    def test_www_url_adds_scheme(self):
        self.assertEqual(extract_url("访问www.example.com查看"), "https://www.example.com")

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(extract_url("打开 https://example.com。"), "https://example.com")
        self.assertEqual(extract_url("(https://example.com/foo)"), "https://example.com/foo")
        self.assertEqual(extract_url("链接是 https://example.com，点击打开"), "https://example.com")

    def test_port_query_fragment_kept(self):
        self.assertEqual(
            extract_url("https://example.com:8080/a?x=1&y=2#f"),
            "https://example.com:8080/a?x=1&y=2#f")

    def test_first_url_wins(self):
        self.assertEqual(
            extract_url("见 https://a.com 和 https://b.com"),
            "https://a.com")

    def test_no_url_returns_none(self):
        self.assertIsNone(extract_url("这里没有链接，只有文字"))
        self.assertIsNone(extract_url(""))
        self.assertIsNone(extract_url(None))


class GetLastSpokenTextTests(unittest.TestCase):
    def setUp(self):
        _vo_content["text"] = None

    def tearDown(self):
        _vo_content["text"] = None

    def test_returns_current_content(self):
        handler = VoiceOverHandler(log_level=40)
        _vo_content["text"] = "https://example.com"
        self.assertEqual(handler.get_last_spoken_text(), "https://example.com")

    def test_repeated_read_not_deduped(self):
        # 与轮询用的 get_last_phrase 不同：重复读取同一内容不应被去重拦截
        handler = VoiceOverHandler(log_level=40)
        _vo_content["text"] = "同一句话"
        self.assertEqual(handler.get_last_spoken_text(), "同一句话")
        self.assertEqual(handler.get_last_spoken_text(), "同一句话")

    def test_empty_content_returns_none(self):
        handler = VoiceOverHandler(log_level=40)
        _vo_content["text"] = ""
        self.assertIsNone(handler.get_last_spoken_text())

    def test_exception_returns_none(self):
        handler = VoiceOverHandler(log_level=40)
        _vo_content["text"] = RuntimeError("VoiceOver not running")
        self.assertIsNone(handler.get_last_spoken_text())


if __name__ == "__main__":
    unittest.main()
