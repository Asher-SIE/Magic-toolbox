"""行朗读标题句点加工、字符解释兜底与分句标点配置化测试

processer 依赖 llama_cpp/appscript，任何环境可跑：
复用 test_processer_unload 的同一套桩模块（避免多份桩在同进程互相覆盖）；
setting 在依赖缺失环境（如 Windows）按需以 mock 导入。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests.test_processer_unload  # noqa: F401,E402  导入即完成桩替换
import processer  # noqa: E402
from processer import TextBrowser, TextProcessor, insert_heading_dot, unicode_char_name  # noqa: E402

try:
    import setting
except Exception:
    # 依赖缺失环境（无 ioreg 的机器）以桩UUID导入
    _test_home = tempfile.TemporaryDirectory()
    with mock.patch("os.path.expanduser", return_value=_test_home.name), mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, '"IOPlatformUUID" = "TEST-UUID"\n', ""),
        ):
        import setting


# 原硬编码的分句标点（与 setting.DEFAULT_SENTENCE_PUNCTUATIONS 一致，供桩环境对照）
LEGACY_PUNCTS = [',', '，', '.', '。', '!', '！', '?', '？', ';', '；', ':', '：', '"', '-']


def patch_module_attr(module, name, value):
    """临时替换模块属性并在测试结束后还原（桩/真实 setting 模块均可）"""
    had = hasattr(module, name)
    old = getattr(module, name, None)
    setattr(module, name, value)
    def restore():
        if had:
            setattr(module, name, old)
        else:
            try:
                delattr(module, name)
            except AttributeError:
                pass
    return restore


class InsertHeadingDotTests(unittest.TestCase):
    """markdown标题行（# 数字）井号右侧插入句点"""

    def test_hash_space_digit(self):
        self.assertEqual(insert_heading_dot("# 1 绪论"), "#. 1 绪论")

    def test_double_hash_no_space_digit(self):
        self.assertEqual(insert_heading_dot("##2.3 概述"), "##.2.3 概述")

    def test_triple_hash_space_digit(self):
        self.assertEqual(insert_heading_dot("### 12 方法"), "###. 12 方法")

    def test_max_six_hashes(self):
        self.assertEqual(insert_heading_dot("###### 4 附录"), "######. 4 附录")

    def test_seven_hashes_unchanged(self):
        # 超过markdown标题层级不处理
        self.assertEqual(insert_heading_dot("####### 1 越级"), "####### 1 越级")

    def test_non_digit_heading_unchanged(self):
        self.assertEqual(insert_heading_dot("# 简介"), "# 简介")

    def test_plain_line_unchanged(self):
        self.assertEqual(insert_heading_dot("正文第一行，无标题"), "正文第一行，无标题")

    def test_empty_line_unchanged(self):
        # 行浏览空行时返回换行符，交由符号库解释为“换行”
        self.assertEqual(insert_heading_dot("\n"), "\n")
        self.assertEqual(insert_heading_dot(""), "")

    def test_input_not_mutated(self):
        source = "# 1 绪论"
        insert_heading_dot(source)
        self.assertEqual(source, "# 1 绪论")


class UnicodeCharNameTests(unittest.TestCase):
    """未收录符号的 unicodedata 兜底描述"""

    def test_middle_dot(self):
        self.assertEqual(unicode_char_name('·'), 'middle dot')

    def test_multiplication_sign(self):
        self.assertEqual(unicode_char_name('×'), 'multiplication sign')

    def test_control_char_returns_none(self):
        # 控制符无 unicodedata 名称返回None；生产中常规控制符（空格/换行/制表）由符号库覆盖
        self.assertIsNone(unicode_char_name('\n'))
        self.assertIsNone(unicode_char_name('\t'))

    def test_no_name_returns_none(self):
        self.assertIsNone(unicode_char_name('\uFFFE'))

    def test_invalid_input_returns_none(self):
        self.assertIsNone(unicode_char_name(''))
        self.assertIsNone(unicode_char_name('ab'))


class GetCharExplanationTests(unittest.TestCase):
    """字符解释：符号库优先，未收录符号兜底，多字文本原样返回"""

    def setUp(self):
        self.setting = processer.setting
        self._restore_lang = patch_module_attr(self.setting, 'current_lang', 'zh')
        self._restore_dict = patch_module_attr(self.setting, 'chars_dict', {
            'zh': {'，': '全角逗号', ' ': '空格'},
            'en': {'#': 'Number'},
        })
        self.addCleanup(self._restore_lang)
        self.addCleanup(self._restore_dict)
        self.browser = TextBrowser()

    def test_dict_hit(self):
        self.assertEqual(self.browser.get_char_explanation('，'), '全角逗号')

    def test_fallback_for_unlisted_symbol(self):
        # 控制字典中不存在'·'，走 unicodedata 兜底，保证旁白有输出
        self.assertEqual(self.browser.get_char_explanation('·'), 'middle dot')

    def test_alnum_char_unchanged(self):
        self.assertEqual(self.browser.get_char_explanation('a'), 'a')
        self.assertEqual(self.browser.get_char_explanation('中'), '中')

    def test_multi_char_passthrough(self):
        # 整行文本不做符号解释
        self.assertEqual(self.browser.get_char_explanation('abc'), 'abc')

    def test_en_lang_fallback(self):
        self.setting.current_lang = 'en'
        self.assertEqual(self.browser.get_char_explanation('$'), 'dollar sign')
        self.assertEqual(self.browser.get_char_explanation('#'), 'Number')


class SentencePunctConfigTests(unittest.TestCase):
    """分句标点从硬编码改为实时读取配置"""

    def setUp(self):
        self.setting = processer.setting
        # 桩环境无这两个属性，统一补齐并在结束后还原
        self.addCleanup(patch_module_attr(self.setting, 'sentence_punctuations', list(LEGACY_PUNCTS)))
        self.addCleanup(patch_module_attr(self.setting, 'DEFAULT_SENTENCE_PUNCTUATIONS', list(LEGACY_PUNCTS)))

    def test_custom_puncts_take_effect(self):
        self.setting.sentence_punctuations = ['|']
        processor = TextProcessor('a,b|c')
        self.assertEqual(processor.replace_punctuation_with_newline(), 'a,b\nc')

    def test_legacy_default_behavior(self):
        processor = TextProcessor('你好，世界。Hello')
        self.assertEqual(processor.replace_punctuation_with_newline(), '你好\n世界\nHello')

    def test_multi_char_entries_ignored(self):
        # 防御：translate表仅接受单字符键，多字符项应被忽略而非报错
        self.setting.sentence_punctuations = ['。', 'ab']
        processor = TextProcessor('一。二')
        self.assertEqual(processor.replace_punctuation_with_newline(), '一\n二')


class SettingSentencePunctFileTests(unittest.TestCase):
    """分句标点配置文件的读写、清洗与回退"""

    def setUp(self):
        fd, self._config_file = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(self._config_file)
        self._restore_path = patch_module_attr(setting, 'config_path', self._config_file)
        self.addCleanup(self._restore_path)

    def test_normalize_filters_and_dedupes(self):
        self.assertEqual(setting._normalize_sentence_punctuations(['.', '!!', '.', '，', '', '  ']), ['.', '，'])

    def test_normalize_invalid_type_falls_back(self):
        self.assertEqual(setting._normalize_sentence_punctuations('abc'), setting.DEFAULT_SENTENCE_PUNCTUATIONS)

    def test_normalize_empty_falls_back(self):
        self.assertEqual(setting._normalize_sentence_punctuations([]), setting.DEFAULT_SENTENCE_PUNCTUATIONS)

    def test_save_and_load_roundtrip(self):
        setting.save_config('English', 'Chinese', sentence_punctuations=['.', '？', '!!'])
        with open(self._config_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(saved['sentence_punctuations'], ['.', '？'])

        config = setting.load_config()
        self.assertEqual(config['sentence_punctuations'], ['.', '？'])
        self.assertEqual(setting.sentence_punctuations, ['.', '？'])

    def test_save_without_param_preserves_current(self):
        setting.save_config('English', 'Chinese', sentence_punctuations=['|'])
        setting.save_config('Chinese', 'English')
        with open(self._config_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(saved['sentence_punctuations'], ['|'])

    def test_load_without_config_file_defaults(self):
        config = setting.load_config()
        self.assertEqual(config['sentence_punctuations'], setting.DEFAULT_SENTENCE_PUNCTUATIONS)
        self.assertEqual(setting.sentence_punctuations, setting.DEFAULT_SENTENCE_PUNCTUATIONS)


class LocaleSentencePunctTests(unittest.TestCase):
    """新增设置面板文案在 zh_CN 与 en 语言包中可命中"""

    def test_both_locales_resolved(self):
        import gettext
        locale_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'locales')
        for lang in ('zh_CN', 'en'):
            trans = gettext.translation('messages', localedir=locale_dir, languages=[lang])
            text = trans.gettext('sentence_punct_group')
            self.assertTrue(text and text != 'sentence_punct_group', f'{lang} 缺少 sentence_punct_group 文案')
            hint = trans.gettext('sentence_punct_hint')
            self.assertTrue(hint and hint != 'sentence_punct_hint', f'{lang} 缺少 sentence_punct_hint 文案')


if __name__ == '__main__':
    unittest.main()
