"""TextBrowser 长按跳转方向（first_line/last_line）逻辑测试

processer 依赖 llama_cpp/appscript，任何环境可跑：
复用 test_processer_unload 的同一套桩模块（避免两份桩在同进程互相覆盖）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.test_processer_unload  # noqa: F401,E402  导入即完成桩替换
import processer  # noqa: E402
from processer import TextBrowser  # noqa: E402


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
