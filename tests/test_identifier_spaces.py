"""翻译前标识符预处理（insert_identifier_spaces）的拆分规则测试

processer 依赖 appscript/llama_cpp，桩替换后导入（与 test_arabic_to_chinese 同一策略，
导入后还原，避免污染其他测试模块）。

运行方式::

    python -m unittest tests.test_identifier_spaces -v
"""
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# processer 顶层依赖 appscript/llama_cpp（macOS 专属）：仅导入期间临时注入，
# 导入后立即移除，避免占位桩污染后续模块
_injected = []
for _name, _attrs in (("appscript", {}), ("llama_cpp", {"Llama": object})):
    if _name not in sys.modules:
        _stub = types.ModuleType(_name)
        for _attr, _value in _attrs.items():
            setattr(_stub, _attr, _value)
        sys.modules[_name] = _stub
        _injected.append(_name)

_setting_injected = False
if "setting" not in sys.modules:
    _test_home = tempfile.TemporaryDirectory()
    try:
        with mock.patch("os.path.expanduser", return_value=_test_home.name), mock.patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, '"IOPlatformUUID" = "TEST-UUID"\n', ""),
            ):
            import setting  # noqa: F401
    except Exception:
        _fake_setting = types.ModuleType("setting")
        _fake_setting._ = lambda key, *args, **kwargs: key
        sys.modules["setting"] = _fake_setting
        _setting_injected = True

import processer

# 仅当本模块抢跑注入了桩时才还原（processer 由本模块首次加载，交还后续模块
# 用自己的完整桩重新加载）；桩已存在说明 processer 归属其他模块管理，不动
if _injected:
    for _name in _injected:
        del sys.modules[_name]
    sys.modules.pop("processer", None)
if _setting_injected:
    del sys.modules["setting"]


def split(text: str) -> str:
    return processer.insert_identifier_spaces(text)


class CamelCaseTests(unittest.TestCase):
    """驼峰边界拆分"""

    def test_lower_to_upper(self):
        self.assertEqual(split("myVariableName"), "my Variable Name")
        self.assertEqual(split("getText"), "get Text")

    def test_pascal_case(self):
        self.assertEqual(split("VoiceOverHandler"), "Voice Over Handler")

    def test_acronym_kept_intact(self):
        # 连续大写视为一个缩写词，不逐字母拆散
        self.assertEqual(split("HTTPServer"), "HTTP Server")
        self.assertEqual(split("parseHTTPResponse"), "parse HTTP Response")

    def test_letter_to_digit(self):
        self.assertEqual(split("iPhone13"), "iPhone 13")
        self.assertEqual(split("Windows11"), "Windows 11")

    def test_digit_to_upper(self):
        self.assertEqual(split("MP3Player"), "MP 3 Player")

    def test_digit_to_lower_not_split(self):
        # 数字后跟小写不拆，避免 v2ray 这类混合名被拆坏
        self.assertEqual(split("v2ray"), "v2ray")
        self.assertEqual(split("mp3file"), "mp3file")

    def test_single_lower_prefix_brand_kept(self):
        # 单字母小写前缀的品牌词不拆
        self.assertEqual(split("iPhone"), "iPhone")
        self.assertEqual(split("eBay"), "eBay")

    def test_plain_words_unchanged(self):
        self.assertEqual(split("hello world"), "hello world")
        self.assertEqual(split("HTTP"), "HTTP")


class SeparatorTests(unittest.TestCase):
    """连字符与下划线分隔拆分"""

    def test_hyphen(self):
        self.assertEqual(split("well-known"), "well known")
        self.assertEqual(split("state-of-the-art"), "state of the art")

    def test_underscore(self):
        self.assertEqual(split("user_name"), "user name")
        self.assertEqual(split("get_last_phrase"), "get last phrase")

    def test_separator_needs_alnum_both_sides(self):
        # 两侧非字母数字时不替换（负号、列表破折号等不受影响）
        self.assertEqual(split("-5"), "-5")
        self.assertEqual(split("a - b"), "a - b")
        self.assertEqual(split("--dash--"), "--dash--")


class SafetyTests(unittest.TestCase):
    """非目标文本不受影响"""

    def test_chinese_unchanged(self):
        self.assertEqual(split("你好世界"), "你好世界")
        self.assertEqual(split("第2章"), "第2章")

    def test_empty_and_none_text(self):
        self.assertEqual(split(""), "")
        self.assertIsNone(split(None))

    def test_mixed_sentence(self):
        self.assertEqual(
            split("调用 getText 方法解析 HTTPResponse"),
            "调用 get Text 方法解析 HTTP Response"
        )


if __name__ == "__main__":
    unittest.main()
