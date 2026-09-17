"""TextBrowser 长按跳转方向（first_line/last_line）逻辑测试

processer 依赖 llama_cpp/appscript，这里以桩模块替换后导入，任何环境可跑。
"""
import sys
import types
import unittest

# 桩替换 processer 顶层依赖（仅 TextBrowser 纯逻辑，无需真实依赖）；
# Llama 属性必须存在，processer 类定义时的类型标注会求值
_fake_llama_cpp = types.ModuleType("llama_cpp")
_fake_llama_cpp.Llama = type("Llama", (), {})
sys.modules.setdefault("appscript", types.ModuleType("appscript"))
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
from processer import TextBrowser  # noqa: E402

if _setting_injected:
    del sys.modules["setting"]


class TextBrowserJumpTests(unittest.TestCase):
    def setUp(self):
        self.tb = TextBrowser()

    def test_first_line(self):
        self.tb.set_text("第一行\n第二行\n第三行")
        spoken = self.tb.browse("first_line")
        self.assertEqual(spoken, "第一行")
        self.assertEqual(self.tb.focus_pos, 0)
        self.assertEqual(self.tb._current_line, "第一行")

    def test_last_line(self):
        self.tb.set_text("第一行\n第二行\n第三行")
        spoken = self.tb.browse("last_line")
        self.assertEqual(spoken, "第三行")
        self.assertEqual(self.tb.focus_pos, self.tb.current_text.index("第三行"))
        self.assertEqual(self.tb._current_line, "第三行")

    def test_last_line_row_column(self):
        self.tb.set_text("第一行\n第二行\n第三行")
        self.tb.browse("last_line")
        self.assertEqual(self.tb._row_column, (3, 1))

    def test_first_line_after_navigation(self):
        # 行间导航后再跳第一行，焦点必须归零
        self.tb.set_text("第一行\n第二行\n第三行")
        self.tb.browse("next_line")
        self.tb.browse("next_line")
        self.tb.browse("first_line")
        self.assertEqual(self.tb.focus_pos, 0)
        self.assertEqual(self.tb._current_line, "第一行")

    def test_last_line_after_navigation(self):
        # 行间导航后再跳最后一行，不再受 next_line 的边界钳制影响
        self.tb.set_text("第一行\n第二行\n第三行")
        self.tb.browse("prev_line")
        self.tb.browse("last_line")
        self.assertEqual(self.tb.focus_pos, self.tb.current_text.index("第三行"))
        self.assertEqual(self.tb._current_line, "第三行")

    def test_single_line_text(self):
        self.tb.set_text("唯一一行")
        self.assertEqual(self.tb.browse("first_line"), "唯一一行")
        self.assertEqual(self.tb.browse("last_line"), "唯一一行")
        self.assertEqual(self.tb.focus_pos, 0)

    def test_trailing_empty_line(self):
        # 末尾连续空行：最后一行内容为空，朗读文本回退为换行占位
        self.tb.set_text("第一行\n\n")
        self.assertEqual(self.tb.browse("last_line"), "\n")
        self.assertEqual(self.tb._current_line, "\n")

    def test_empty_text_returns_empty(self):
        self.tb.set_text("")
        self.assertEqual(self.tb.browse("first_line"), "")
        self.assertEqual(self.tb.browse("last_line"), "")


if __name__ == "__main__":
    unittest.main()
