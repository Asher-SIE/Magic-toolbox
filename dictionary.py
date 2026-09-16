"""本地 gzip 词典，供所有翻译模式共用的查询层。

从 processer.py 的 Translator 中迁出，使"先查词库、无匹配再翻译"
不依赖 LLM 翻译器实例（苹果翻译模式下同样可用）。
"""

from __future__ import annotations

import gzip
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class Dictionary:
    """本地 gzip 词典（resources/dict.txt），启动时全量载入内存。"""

    def __init__(self, dict_path: str | None = None):
        if dict_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            dict_path = os.path.join(current_dir, "resources", "dict.txt")
        self._dict_path = dict_path
        self._dictionary: dict = {}
        self._load_dictionary()

    def _load_dictionary(self):
        """本地词典加载（完全原始代码，一字未改，包括故意的文件格式实现）"""
        self._dictionary.clear()
        try:
            with gzip.open(self._dict_path, 'rt', encoding='utf-8') as file:
                for line_num, line in enumerate(file, 1):
                    # 去除首尾空白字符跳过空行
                    line = line.strip()
                    if not line:
                        continue

                    # 分割字段取前两个
                    parts = line.split('\t', 2)
                    if len(parts) >= 2:
                        english, chinese = parts[0], parts[1]
                        # 统一转为小写
                        self._dictionary[english.lower()] = chinese
                    else:
                        # 格式错误警告
                        logger.warning(f"词典第{line_num}行格式不正确（需至少两个字段），已跳过")

            # 加载完成日志
            logger.info(f"本地 gzip 词典加载完成，共加载 {len(self._dictionary)} 条有效记录（路径：{self._dict_path}）")
        except FileNotFoundError:
            # 文件不存在异常
            logger.error(f"词典加载失败：找不到 gzip 文件 {self._dict_path}")
        except gzip.BadGzipFile:
            logger.error(f"词典加载失败：{self._dict_path} 不是有效的 gzip 压缩文件")
        except Exception as e:
            logger.error(f"加载 gzip 词典时发生错误: {str(e)}")

    def lookup(self, word: str) -> Optional[str]:
        """本地词典查询（完全原始代码，一字未改）"""
        if not isinstance(word, str) or not word.strip():
            logger.debug("词典查询：输入无效")
            return None

        # 统一转为小写
        lower_word = word.strip().lower()
        if lower_word in self._dictionary:
            logger.debug(f"词典命中：{word} → {self._dictionary[lower_word]}")
            return self._dictionary[lower_word]
        else:
            logger.debug(f"词典未命中：{word}")
            return None

    def __len__(self) -> int:
        return len(self._dictionary)
