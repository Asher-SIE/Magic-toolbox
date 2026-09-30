"""数字转中文（arabic_to_chinese）的转换规则测试

运算符号 +-*/= 直出汉字；分数与负数需转义符 | 显式声明。
processer 依赖 appscript/llama_cpp，桩替换后导入，任何环境可跑。

运行方式::

    python -m unittest tests.test_arabic_to_chinese -v
"""
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

# processer 顶层依赖 appscript/llama_cpp（macOS 专属）：仅导入期间临时注入，
# 导入后立即移除，避免占位桩污染后续模块（test_processer_unload 等自带完整桩）
_injected = []
for _name, _attrs in (("appscript", {}), ("llama_cpp", {"Llama": object})):
    if _name not in sys.modules:
        _stub = types.ModuleType(_name)
        for _attr, _value in _attrs.items():
            setattr(_stub, _attr, _value)
        sys.modules[_name] = _stub
        _injected.append(_name)

# setting 与其他测试共享真实模块：mock 掉 macOS 专属的 ioreg/expanduser 后导入，
# 失败（极端环境）再临时注入最小桩
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


def convert(text: str) -> str:
    return processer.TextProcessor(text).arabic_to_chinese()


class OperatorTests(unittest.TestCase):
    """运算符号直读：键入 +-*/= 输出加减乘除等于"""

    def test_operators_read_as_chinese(self):
        self.assertEqual(convert("1+1=2"), "一加一等于二")
        self.assertEqual(convert("3-2"), "三减二")
        self.assertEqual(convert("2*3"), "二乘三")
        # "除以"而非"除"：中文里"三除九"是9÷3，语义相反
        self.assertEqual(convert("1/2"), "一除以二")

    def test_fullwidth_pipe_normalized(self):
        # 中文输入法易输出全角竖线，两种写法都应触发分数转换
        self.assertEqual(convert("3\uff5c/9"), "九分之三")
        self.assertEqual(convert("3|/9"), "九分之三")

    def test_letter_mapping_removed(self):
        # 旧版字母 a/s/m/d 误转运算符的行为已删除，普通字母丢弃
        self.assertEqual(convert("a1"), "一")
        self.assertEqual(convert("m"), "")


class EscapeTests(unittest.TestCase):
    """转义符 |：分数与负数需显式声明"""

    def test_fraction_with_escape(self):
        self.assertEqual(convert("1|/2"), "二分之一")
        self.assertEqual(convert("3|/4"), "四分之三")

    def test_negative_fraction(self):
        self.assertEqual(convert("|-1|/2"), "负二分之一")

    def test_negative_integer(self):
        self.assertEqual(convert("|-5"), "负五")

    def test_negative_decimal(self):
        self.assertEqual(convert("|-3.14"), "负三点一四")
        self.assertEqual(convert("|-.14"), "负零点一四")
        self.assertEqual(convert("|-0.14"), "负零点一四")

    def test_negative_percent(self):
        self.assertEqual(convert("|-50%"), "负百分之五十")

    def test_bare_minus_means_subtract(self):
        # 未加转义符的 - 按减号直读，不再隐式判负
        self.assertEqual(convert("-5"), "减五")

    def test_isolated_pipe_dropped(self):
        # | 后不跟 / 或 - 时丢弃，不影响数字转换
        self.assertEqual(convert("|5"), "五")


class NumberTests(unittest.TestCase):
    """基础数字转换保持原有行为"""

    def test_integer(self):
        self.assertEqual(convert("123"), "一百二十三")
        self.assertEqual(convert("12345"), "一万二千三百四十五")

    def test_decimal(self):
        self.assertEqual(convert("3.14"), "三点一四")
        self.assertEqual(convert(".5"), "零点五")

    def test_percent(self):
        self.assertEqual(convert("50%"), "百分之五十")


if __name__ == "__main__":
    unittest.main()
