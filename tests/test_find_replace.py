"""查找/替换纯逻辑回归测试（unescape_replace_text）。

dialogs.py 依赖 wx，本模块在无 wx 的环境自动跳过，
在 macOS 开发机上随 pytest 正常运行。
"""

import pytest

wx = pytest.importorskip("wx")

from dialogs import unescape_replace_text


def test_basic_escapes():
    assert unescape_replace_text('\\n') == '\n'
    assert unescape_replace_text('\\t') == '\t'
    assert unescape_replace_text('\\r') == '\r'
    assert unescape_replace_text('\\\\') == '\\'


def test_double_backslash_not_consumed():
    # 回归：旧实现按顺序 replace，"\\n" 会被错误解析成"反斜杠+换行"
    assert unescape_replace_text('\\\\n') == '\\n'
    assert unescape_replace_text('\\\\t') == '\\t'
    assert unescape_replace_text('\\\\r') == '\\r'


def test_unknown_escape_and_lone_backslash_kept():
    assert unescape_replace_text('\\q') == '\\q'
    assert unescape_replace_text('a\\') == 'a\\'


def test_plain_text_unchanged():
    assert unescape_replace_text('') == ''
    assert unescape_replace_text('hello world') == 'hello world'
    # 混合场景：替换为"字面反斜杠 + 换行"
    assert unescape_replace_text('C:\\\\end\\n') == 'C:\\end\n'
