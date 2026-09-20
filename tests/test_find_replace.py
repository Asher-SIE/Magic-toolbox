"""查找/替换纯逻辑回归测试（unescape_replace_text / search_next_match / search_prev_match）。

dialogs.py 依赖 wx，本模块在无 wx 的环境自动跳过，
在 macOS 开发机上随 pytest 正常运行。
"""

import re

import pytest

wx = pytest.importorskip("wx")

from dialogs import unescape_replace_text, search_next_match, search_prev_match


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


def test_next_match_advance_and_wrap():
    pat = re.compile('foo')
    text = 'foo bar foo'
    assert search_next_match(pat, text, 0).span() == (0, 3)
    # 插入点在第一个匹配末尾，应命中第二个
    assert search_next_match(pat, text, 3).span() == (8, 11)
    # 插入点在文本末尾，绕回开头
    assert search_next_match(pat, text, 11).span() == (0, 3)
    assert search_next_match(re.compile('zzz'), text, 0) is None


def test_next_match_zero_width_advances_and_rewraps():
    pat = re.compile(r'\b')
    text = 'a'
    # 停在插入点上的零宽匹配应跳过前进
    assert search_next_match(pat, text, 0).span() == (1, 1)
    # 绕回后开头的零宽匹配可再次选中，不能永远停在末尾
    assert search_next_match(pat, text, 1).span() == (0, 0)


def test_prev_match_uses_selection_boundary():
    # 回归：快速查找 prev 分支曾误用未定义的 start_pos 导致崩溃，
    # 且有选区时应以选区起点为界，否则停在当前匹配上无法上移
    pat = re.compile('foo')
    text = 'foo bar foo'
    # 当前选中第二个 foo（8..11），上一个应为第一个（0..3）
    assert search_prev_match(pat, text, 11, 8, 11).span() == (0, 3)
    # 当前选中第一个 foo，界限之前无匹配，绕回最后一个
    assert search_prev_match(pat, text, 3, 0, 3).span() == (8, 11)
    # 无选区时以插入点为界
    assert search_prev_match(pat, text, 10, 10, 10).span() == (8, 11)
    assert search_prev_match(pat, text, 8, 8, 8).span() == (0, 3)
    # 选区反向（终点在起点之前）时取较小端
    assert search_prev_match(pat, text, 11, 11, 8).span() == (0, 3)
    assert search_prev_match(re.compile('zzz'), text, 5, 5, 5) is None
