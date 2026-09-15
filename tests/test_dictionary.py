import gzip
import os
import tempfile
import unittest

from dictionary import Dictionary


class DictionaryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dict_path = os.path.join(self._tmp.name, "dict.txt")
        content = (
            "apple\t苹果\n"
            "Apple\t苹果(公司)\n"
            "hello world\t你好，世界\n"
            "\n"
            "bad-line-no-tab\n"
            "窗\twindow\n"
        )
        with gzip.open(self.dict_path, "wt", encoding="utf-8") as fh:
            fh.write(content)

    def test_lookup_is_case_insensitive_and_strips_spaces(self):
        dictionary = Dictionary(dict_path=self.dict_path)
        # 同 key 后写覆盖：apple 被 Apple 覆盖
        self.assertEqual(dictionary.lookup("APPLE"), "苹果(公司)")
        self.assertEqual(dictionary.lookup("  apple  "), "苹果(公司)")
        self.assertEqual(dictionary.lookup("hello world"), "你好，世界")
        self.assertEqual(dictionary.lookup("窗"), "window")

    def test_lookup_miss_returns_none(self):
        dictionary = Dictionary(dict_path=self.dict_path)
        self.assertIsNone(dictionary.lookup("unknown"))
        self.assertIsNone(dictionary.lookup(""))
        self.assertIsNone(dictionary.lookup("   "))
        self.assertIsNone(dictionary.lookup(None))

    def test_malformed_lines_are_skipped(self):
        dictionary = Dictionary(dict_path=self.dict_path)
        self.assertIsNone(dictionary.lookup("bad-line-no-tab"))
        self.assertEqual(len(dictionary), 3)

    def test_missing_file_does_not_raise(self):
        dictionary = Dictionary(dict_path=os.path.join(self._tmp.name, "missing.txt"))
        self.assertEqual(len(dictionary), 0)
        self.assertIsNone(dictionary.lookup("apple"))


if __name__ == "__main__":
    unittest.main()
