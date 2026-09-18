"""extract_urls 提取与 VoiceOverHandler.get_last_spoken_text 即时读取逻辑测试

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
from processer import VoiceOverHandler, extract_urls  # noqa: E402

if _setting_injected:
    del sys.modules["setting"]


class ExtractUrlsTests(unittest.TestCase):
    def test_plain_https_url(self):
        self.assertEqual(extract_urls("https://example.com/a?b=1"), ["https://example.com/a?b=1"])

    def test_url_with_chinese_context(self):
        # 中文紧贴URL无空格时按非URL字符截断
        self.assertEqual(extract_urls("详情见https://example.com/path，谢谢"), ["https://example.com/path"])

    def test_www_url_adds_scheme(self):
        self.assertEqual(extract_urls("访问www.example.com查看"), ["https://www.example.com"])

    def test_bare_domain_adds_scheme(self):
        # 无协议头大小写裸域名
        self.assertEqual(extract_urls("搜索GOOGLE.COM就有了"), ["https://GOOGLE.COM"])
        self.assertEqual(extract_urls("打开 example.com。"), ["https://example.com"])

    def test_bare_domain_with_path_and_port(self):
        self.assertEqual(
            extract_urls("访问example.com/path?q=1查看"),
            ["https://example.com/path?q=1"])
        self.assertEqual(
            extract_urls("本地服务 example.com:8080/x 已启动"),
            ["https://example.com:8080/x"])

    def test_scheme_url_with_dotless_host(self):
        # localhost 无点主机仅带协议头分支可匹配，两分支并存防回归
        self.assertEqual(extract_urls("http://localhost:8080/x"), ["http://localhost:8080/x"])

    def test_trailing_punctuation_stripped(self):
        self.assertEqual(extract_urls("打开 https://example.com。"), ["https://example.com"])
        self.assertEqual(extract_urls("(https://example.com/foo)"), ["https://example.com/foo"])
        self.assertEqual(extract_urls("链接是 https://example.com，点击打开"), ["https://example.com"])

    def test_port_query_fragment_kept(self):
        self.assertEqual(
            extract_urls("https://example.com:8080/a?x=1&y=2#f"),
            ["https://example.com:8080/a?x=1&y=2#f"])

    def test_multiple_urls_in_order(self):
        self.assertEqual(
            extract_urls("见 https://a.com 和 b.cn，或 www.c.org/xyz"),
            ["https://a.com", "https://b.cn", "https://www.c.org/xyz"])

    def test_duplicate_urls_deduped(self):
        # 裸域名与带协议头的同一地址归并
        self.assertEqual(extract_urls("google.com 和 https://google.com"), ["https://google.com"])

    def test_no_url_returns_empty(self):
        self.assertEqual(extract_urls("这里没有链接，只有文字"), [])
        self.assertEqual(extract_urls(""), [])
        self.assertEqual(extract_urls(None), [])

    def test_number_and_version_not_url(self):
        # 版本号/小数（末段非字母）不误判
        self.assertEqual(extract_urls("升级到版本 15.6.1 试试"), [])


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
