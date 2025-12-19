## https://hf-mirror.com/facebook/mbart-large-50-many-to-many-mmt/resolve/main/model.safetensors?download=trueimport re

import appscript
import logging
import os
import re 
import setting
import sys
import threading
import time
import torch
import wx

from transformers import MBartForConditionalGeneration, MBart50TokenizerFast
from typing import Optional, Tuple, Callable


# 多线程管理基类：封装线程启停
class BaseThreadedWorker:
    """
    多线程工作基类，提供统一的线程管理功能
    子类需实现_run_task方法定义具体任务逻辑
    """
    def __init__(self, log_level: int = logging.WARNING, loop_interval: float = 0.1):
        """
        初始化基类
        :param log_level: 日志级别
        :param loop_interval: 任务循环间隔(秒)
        """
        # 日志配置
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(log_level)
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # 线程控制参数
        self._is_running = False 
        self._stop_event = threading.Event()  # 强制唤醒线程
        self._loop_interval = loop_interval  # 循环间隔时间
        self._worker_thread: Optional[threading.Thread] = None  # 线程对象
        self._result_callback: Optional[Callable] = None  # 结果回调函数

    def _run_task(self) -> Optional[any]:
        """
        子类必须实现的任务逻辑方法
        :return: 任务结果，有效结果返回具体值，无效返回None
        """
        raise NotImplementedError("子类必须实现_run_task方法")

    def _thread_loop(self):
        """线程主循环：持续执行任务并处理结果"""
        self._is_running = True
        self._stop_event.clear()  # 重置停止事件
        self.logger.info(f"线程启动，循环间隔: {self._loop_interval}秒")
        
        while self._is_running:
            try:
                # 执行子类实现的任务逻辑
                result = self._run_task()
                
                # 若有有效结果且设置了回调，触发回调
                if result is not None and self._result_callback:
                    if isinstance(result, tuple):
                        self._result_callback(*result)  # 解包元组参数
                    else:
                        self._result_callback(result)  # 单个参数
                        
            except Exception as e:
                self.logger.error(f"任务执行出错: {str(e)}", exc_info=True)
            
            #  event.wait  支持被强制唤醒
            if self._stop_event.wait(self._loop_interval):
                # 如果事件被触发（调用了 stop_worker），直接退出循环
                break
            
        self.logger.info("线程已停止")
        self._is_running = False


    def start_worker(self, callback: Optional[Callable] = None):
        """
        启动工作线程
        :param callback: 处理任务结果的回调函数
        """
        if self._is_running:
            self.logger.warning("线程已在运行中，无需重复启动")
            return
            
        self._result_callback = callback
        # 创建守护线程，主线程退出时自动结束
        self._worker_thread = threading.Thread(
            target=self._thread_loop,
            daemon=False
        )
        self._worker_thread.start()

    def stop_worker(self, timeout: float = 1.0):
        """
        停止工作线程
        :param timeout: 等待线程退出的超时时间(秒)
        """
        if not self._is_running or not self._worker_thread:
            self.logger.warning("线程未在运行，无需停止")
            return
            
        self._is_running = False
        self._stop_event.set()  # 触发事件，强制唤醒等待中的线程
        self._worker_thread.join(timeout=timeout)
        
        if self._worker_thread.is_alive():
            self.logger.warning(f"线程未在{timeout}秒内正常退出")


    def is_running(self) -> bool:
        """判断线程是否正在运行"""
        return self._is_running

    def __del__(self):
        """对象销毁时确保线程已停止"""
        if self._is_running:
            self.stop_worker()


# 翻译类
class MBartTranslator(BaseThreadedWorker):
    def __init__(self, log_level: int = logging.WARNING, loop_interval: float = 1):
        """初始化翻译器：加载模型、分词器、本地词典"""
        super().__init__(log_level=log_level, loop_interval=loop_interval)
        
        self._model = None
        self._tokenizer = None
        self._input_text: Optional[str] = None  # 待翻译文本
        self._dictionary: dict = {}

        #查找模型
        self.model_available = False
        self._current_dir = os.path.dirname(os.path.abspath(__file__))
        self.external_dir = os.path.expanduser("~/Downloads")
        self.model_path = self._find_model_path()
        self._dict_path = os.path.join(self._current_dir, "resources", "dict.txt")

        # 加载词典
        self._load_dictionary()
        #  加载模型
        self._try_load_model_and_tokenizer()


    def _find_model_path(self) -> str:
        """按顺序查找模型目录，返回第一个找到的路径，都找不到则返回默认路径"""
        # 1. 优先查找程序当前目录下的 "model"
        path_in_current = os.path.join(self._current_dir, "model")
        if os.path.isdir(path_in_current):
            self.logger.info(f"在当前目录找到模型: {path_in_current}")
            return path_in_current

        # 2. 如果找不到，查找用户的 "下载" 目录下的 "model"
        path_in_external = os.path.join(self.external_dir, "model")
        if os.path.isdir(path_in_external):
            self.logger.info(f"在下载目录找到模型: {path_in_external}")
            return path_in_external

        # 3. 都找不到，返回一个默认路径
        self.logger.warning("在当前目录和下载目录均未找到 'model' 文件夹。")
        return path_in_current # 返回一个默认路径，让后续加载尝试失败


    def _try_load_model_and_tokenizer(self):
        """加载MBart模型和分词器"""
        try:
            # 加载模型（指定MPS设备，float16精度减少内存占用）
            self._model = MBartForConditionalGeneration.from_pretrained(
                self.model_path,
                torch_dtype=torch.bfloat16,# float16先加个B看看有什么区别
                trust_remote_code=True
            ).to("mps")
            
            # 加载分词器
            self._tokenizer = MBart50TokenizerFast.from_pretrained(
                self.model_path,
                trust_remote_code=True
            )
            self.model_available = True
            self.logger.info("模型加载成功。")

        except Exception as e:
            self.model_available = False
            self.logger.warning(f"模型加载失败，翻译功能不可用。错误：{str(e)}\n请将模型放入下载目录: {self.external_dir}")
            


    def _load_dictionary(self):
        """
        加载本地词典 ）
        """
        self._dictionary.clear()
        try:
            with open(self._dict_path, 'r', encoding='utf-8') as file:
                for line_num, line in enumerate(file, 1):
                    # 去除首尾空白字符，跳过空行
                    line = line.strip()
                    if not line:
                        continue

                    # 分割字段：取前两个
                    parts = line.split('\t', 2)  # 最多分割2次
                    if len(parts) >= 2:
                        english, chinese = parts[0], parts[1]  # 仅保留前两个字段
                        # 统一转为小写，实现不区分大小写查询
                        self._dictionary[english.lower()] = chinese
                    else:
                        # 格式错误（不足两个字段），仅警告不中断
                        self.logger.warning(f"词典第{line_num}行格式不正确（需至少两个字段），已跳过")
            
            self.logger.info(f"本地词典加载完成，共加载 {len(self._dictionary)} 条有效记录（路径：{self._dict_path}）")
        except FileNotFoundError:
            self.logger.error(f"词典加载失败：找不到文件 {self._dict_path}")
        except Exception as e:
            self.logger.error(f"加载词典时发生错误: {str(e)}")


    def _lookup_word(self, word: str) -> Optional[str]:
        """本地词典查询,命中返回解释,未命中None"""
        if not isinstance(word, str) or not word.strip():
            self.logger.debug("词典查询：输入非有效英文单词")
            return None
        
        # 统一转为小写，匹配词典键
        lower_word = word.strip().lower()
        if lower_word in self._dictionary:
            self.logger.debug(f"词典命中：{word} → {self._dictionary[lower_word]}")
            return self._dictionary[lower_word]
        else:
            self.logger.debug(f"词典未命中：{word}（将调用模型翻译）")
            return None


    def set_input_text(self, text: str, langType: str):
        """设置待翻译的文本）"""
        self._input_text = text.strip()
        self._langType = langType


    def _is_chinese_char(self, c):
        """判断单个字符是否为中文字符"""
        return '\u4e00' <= c <= '\u9fff'


    def _is_chinese(self,text):
        """检测文本是否是中文"""
        if not text.strip():
            return False
        return any(self._is_chinese_char(c) for c in text)


    def _detect_english(self, text):
        """只有当文本不包含任何中文字符，且包含英文字母时，才判定为英文"""
        text = text.strip()
        if not text:
            return False
        if any(self._is_chinese(c) for c in text):
            return False
        return bool(re.search(r'[a-zA-Z]+', text))


    def translate(self, original_text):
        """公有方法：对外提供查询接口"""
        original_text = original_text.strip()
        if not original_text:
            raise ValueError("请输入要翻译的内容")

        # 当输入是「单个中文字符」时查询词典
        if self._is_chinese(original_text) and len(original_text) == 1:
            dict_result = self._lookup_word(original_text)
            if dict_result:
                return dict_result

            ## 未命中则整体翻译为英文

        is_english = self._detect_english(original_text)
        # 判断是否为「单个英文单词」（不含空格，仅字母/数字）
        is_single_word = bool(re.match(r'^[a-zA-Z0-9]+$', original_text.strip()))
        if is_english and is_single_word:
            dict_result = self._lookup_word(original_text)
            if dict_result:
                return dict_result  # 词典命中，直接返回结果

        # 词典未命中/非单词翻译
        
        # 构建翻译提示词和语言参数
        prompt_prefix_English = "Translation English to Chinese:###T###"
        prompt_prefix_Chinese = "翻译中文到英语:###T###"

        if self._langType == "EN":
            # 英文→中文
            translate_prompt = f"{prompt_prefix_English}{original_text}"
            src_lang = "en_XX"
            tgt_lang = "zh_CN"
        elif self._langType == "ZH":
            # 中文→英文
            translate_prompt = f"{prompt_prefix_Chinese}{original_text}"
            src_lang = "zh_CN"
            tgt_lang = "en_XX"

        # 分词器编码（将文本转为模型可识别的Tensor
        self._tokenizer.src_lang = src_lang  # 设置源语言
        self._tokenizer.tgt_lang = tgt_lang  # 设置目标语言
        inputs = self._tokenizer(
            translate_prompt,
            return_tensors="pt",
            padding=False,
            truncation=True,
            max_length=1024,
            add_special_tokens=True
        ).to("mps")  # 移动到MPS设备

        # 模型生成翻译结果（禁用梯度计算，减少内存占用
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=1024,  # 生成文本的最大新增token数
                num_beams=3,
                early_stopping=False,
                forced_bos_token_id=self._tokenizer.lang_code_to_id[tgt_lang],  # 强制目标语言
                no_repeat_ngram_size=3,  # 避免重复短语
                repetition_penalty=1.3   # 惩罚重复token
            )

        # 解码并清理结果（移除特殊符号和提示词格式
        translated_text = self._tokenizer.decode(
            outputs[0],
            skip_special_tokens=True,    # 跳过<pad>、</s>等特殊token
            clean_up_tokenization_spaces=True,  # 清理多余空格
            skip_prompt=False
        )

        # 移除提示词残留
        clean_patterns = [
            r"^.*?###T###",
            r"^.*?#.*?T.*?#",
            r"^.*?#.*?T"
        ]
        for pattern in clean_patterns:
            translated_text = re.sub(
                pattern, "", translated_text, flags=re.DOTALL | re.IGNORECASE
            ).strip()

        # 无效结果校验
        if not translated_text or re.match(r'^[\s\.,!?;:\'"]*$', translated_text):
            return f"未生成有效结果\n输入：{original_text}"
        return translated_text


    def _run_task(self) -> Optional[Tuple[str, str]]:
        """多线程任务实现：处理待翻译文本并返回结果"""
        if not self._input_text:
            return None
            
        original_text = self._input_text
        try:
            # 调用整合后的translate方法（自动包含词典查询）
            translated_text = self.translate(original_text)
            # 清空已处理的输入文本
            self._input_text = None
            return (original_text, translated_text)
        except Exception as e:
            self.logger.error(f"翻译过程出错: {str(e)}")
            self._input_text = None
            return None


# VO监听类：继承多线程基类
class VoiceOverHandler(BaseThreadedWorker):
    def __init__(self, log_level: int = logging.WARNING, repeat_threshold: float = 0.05, loop_interval: float = 0.1):
        """
        :param repeat_threshold: 重复内容的时间阈值（秒），超过此值视为新朗读
        :param loop_interval: 监听循环间隔时间（秒）
        """
        super().__init__(log_level=log_level, loop_interval=loop_interval)
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(log_level)
        self._vo_err_count = 0    #初始化错误计数器
        self.vo = appscript.app("VoiceOver")  # 建立与VoiceOver的连接
        
        # 缓存上次的朗读信息（内容+时间戳）
        self._last_content: Optional[str] = None
        self._last_timestamp: float = 0.0  # 时间戳（秒）
        self.repeat_threshold = repeat_threshold  # 阈值（默认0.05秒）

    def get_last_phrase(self) -> Optional[Tuple[str, float]]:
        """
        获取最后朗读的内容及时间戳，返回元组(内容, 时间戳)
        若内容重复且未超过阈值，返回None；否则返回新内容
        """
        try:
            current_content = self.vo.last_phrase.content()
            current_timestamp = time.time()  # 获取当前时间戳（秒，精确到小数）
            
            # 内容为空返回None
            self._vo_err_count = 0
            if not current_content:
                return None
            
            # 判断是否为重复内容
            if current_content == self._last_content:
                # 计算与上次的时间差
                time_diff = current_timestamp - self._last_timestamp
                if time_diff < self.repeat_threshold:
                    self.logger.debug(f"重复内容（时间差{time_diff:.2f}s < 阈值）：{current_content}")
                    return None
            
            # 视为新内容，更新缓存并返回
            self._last_content = current_content
            self._last_timestamp = current_timestamp
            self.logger.info(f"新朗读内容（时间戳：{current_timestamp:.2f}）：{current_content}")
            return (current_content, current_timestamp)
            
        except Exception as e:
            self.logger.error(f"VoiceOver错误：{str(e)}")
            self._vo_err_count += 1
            if self._vo_err_count == 6:
                reboot_VoiceOver()
                self._vo_err_count = 0
            return None


    def speak_text(self, text: str) -> bool:
        #  朗读文本
        try:
            # 调用 VoiceOver output 方法
            self.vo.output(text)
            self.logger.info(f"VoiceOver output 指令触发成功，文本：{text[:50]}...")
            return True

        # 常见错误提示
        except Exception as e:
            error_msg = str(e)
            if "not running" in error_msg.lower():
                self.logger.error("可能原因：VoiceOver 已被关闭，请重新启动（快捷键 Cmd+F5）")
            elif "permission" in error_msg.lower():
                self.logger.error("可能原因：当前用户无 VoiceOver 操作权限，请在「系统设置-隐私与安全性-辅助功能」中授权")
            return False
        
            self.logger.error(f"朗读文本时发生未知异常：{str(e)}", exc_info=True)
            return False


    def _run_task(self) -> Optional[Tuple[str, float]]:
        """多线程任务实现：获取VO内容并返回"""
        return self.get_last_phrase()


#  剪贴板监视器类
class ClipboardMonitor(BaseThreadedWorker):
    """
    监测剪贴板内容变化，并返回 (新内容, 时间戳) 元组。
    """
    def __init__(self, log_level: int = logging.INFO, loop_interval: float = 0.2):
        """
        初始化剪贴板监视器。
        
        :param log_level: 日志级别
        :param loop_interval: 检查剪贴板的时间间隔（秒）
        """
        super().__init__(log_level=log_level, loop_interval=loop_interval)
        self._last_content: Optional[str] = None
        # 使用线程局部存储来保存wx.App实例，避免线程问题
        self._thread_local = threading.local()

    def _get_wx_app(self) -> wx.App:
        """确保每个线程都有一个wx.App实例"""
        if not hasattr(self._thread_local, 'app'):
            # 对于非GUI线程，必须创建一个wx.App实例
            self._thread_local.app = wx.App(False)
        return self._thread_local.app

    def _run_task(self) -> Optional[Tuple[str, float]]:
        """
        检查剪贴板内容是否变化。
        如果变化，则返回 (新内容, 时间戳) 元组，否则返回 None。
        """
        # 确保线程有wx.App实例
        self._get_wx_app()
        
        clipboard = wx.Clipboard.Get()
        if not clipboard.Open():
            self.logger.error("无法打开剪贴板。")
            return None
            
        try:
            # 尝试获取文本数据
            text_data = wx.TextDataObject()
            if clipboard.GetData(text_data):
                current_content = text_data.GetText()
                
                # 检查内容是否有效且与上次不同
                if current_content and current_content != self._last_content:
                    self._last_content = current_content
                    timestamp = time.time()
                    self.logger.debug(f"检测到剪贴板变化: {current_content[:50]}...")
                    return (current_content, timestamp)
                    
        except Exception as e:
            self.logger.error(f"读取剪贴板时出错: {e}", exc_info=True)
        finally:
            clipboard.Close()
            
        # 如果没有变化或获取失败，则返回None
        return None


class TextBrowser:
    def __init__(self):
        self.current_text = ""  # 存储传入的文本
        self.focus_pos = 0  # 浏览焦点的虚拟坐标（字符索引）
        self._total_chars = 0  # 文本总字数
        self._row_column = (0, 0)  #行列坐标
        self._current_line = ""  # 当前行内容


    def set_text(self, text: str) -> None:
        """存储传入的文本"""
        self.current_text = text
        self._total_chars = len(text)
        self.focus_pos = 0  # 重置焦点位置


    def browse(self, direction: str) -> Tuple[str]:
        """
        浏览文本方法
            direction: 浏览方向
                "prev_char": 前一个字, "next_char": 后一个字
                "prev_line": 当前剪贴板上一行, "next_line": 当前剪贴板下一行
                - "explain_char": 返回焦点位置内容
        
        返回:
            Tuple[朗读的文本, 行坐标(从0开始), 列坐标(从0开始), 总字数]
        """
        # 处理当前文本内的字符浏览
        if not self.current_text:
            return
        
        # 前一个字
        if direction == "prev_char":
            self.focus_pos = max(0, self.focus_pos - 1)
            spoken_text = self.current_text[self.focus_pos:self.focus_pos + 1]
        
        # 后一个字
        elif direction == "next_char":
            self.focus_pos = min(self._total_chars - 1, self.focus_pos + 1)
            spoken_text = self.current_text[self.focus_pos:self.focus_pos + 1]
        
        # 上一行
        elif direction == "prev_line":
            lines = self.current_text.split('\n')
            current_line = self._get_current_line(lines)
            target_line = max(0, current_line - 1)
            spoken_text = lines[target_line] if lines else ""
            if not spoken_text:  # 手动处理空行
                spoken_text = '\n'
            self._current_line = spoken_text
            self.focus_pos = self._get_line_start_index(lines, target_line)
        
        # 下一行
        elif direction == "next_line":
            lines = self.current_text.split('\n')
            current_line = self._get_current_line(lines)
            target_line = min(len(lines) - 1, current_line + 1)
            spoken_text = lines[target_line] if lines else ""
            if not spoken_text:  # 手动处理空行
                spoken_text = '\n'
            self._current_line = spoken_text
            self.focus_pos = self._get_line_start_index(lines, target_line)
        
        # 返回焦点位置内容
        elif direction == "explain_char":
            spoken_text = self.current_text[self.focus_pos:self.focus_pos + 1]

        # 粘贴剪贴板当前行
        elif direction == "paste_line":
            spoken_text = self._current_line

        else:
            spoken_text = "null"
        
        # 计算当前焦点的行、列坐标
        lines = self.current_text.split('\n')
        current_line = self._get_current_line(lines)
        line_start = self._get_line_start_index(lines, current_line)
        current_col = self.focus_pos - line_start  # 列坐标 = 焦点索引 - 行起始索引

        self._row_column = (current_line + 1, current_col + 1)
        return self.get_char_explanation(spoken_text)


    # 辅助方法：获取当前焦点所在行
    def _get_current_line(self, lines: list) -> int:
        if not lines:
            return 0
        cumulative = 0
        for i, line in enumerate(lines):
            cumulative += len(line) + 1  # +1 包含换行符
            if self.focus_pos < cumulative:
                return i
        return len(lines) - 1


    # 辅助方法：获取指定行的起始索引
    def _get_line_start_index(self, lines: list, line_num: int) -> int:
        if line_num <= 0:
            return 0
        start = 0
        for i in range(line_num):
            start += len(lines[i]) + 1  # +1 包含换行符
        return start


    def get_char_explanation(self, char: str) -> str:
        #  特定字符解释
        return setting.chars_dict[setting.current_lang].get(char, char)


def reboot_VoiceOver(event):
    os.system('killall -9 VoiceOver')


class TextProcessor:
    def __init__(self, text: str):
        # 外部文本
        self.text = text


    def set_text(self, text: str):
        # 外部文本
        self.text = text


    # 删除文本空白
    def remove_all_whitespace(self) -> str:
        return self.text.translate(str.maketrans('', '', ' \t\n\r\f\v'))


    # 合并多个空格
    def merge_multiple_spaces(self) -> str:
        text = re.sub(r'\n+', '\n', self.text)
        # 合并连续空白
        return re.sub(r'[ \t]+', ' ', text)


    #  分行
    def replace_punctuation_with_newline(self) -> str:
        common_punctuations = [
            ',', '，', '.', '。', '!', '！', '?', '？', ';', '；',
            ':', '：', '"', 
            '-'
        ]
        trans_table = str.maketrans({punc: '\n' for punc in common_punctuations})
        return self.text.translate(trans_table)


    # 阿拉伯数字转中文
    def arabic_to_chinese(self) -> str:
        chinese_nums = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']
        level_units = ['', '万', '亿', '万亿']  # 第0组=个级、第1组=万级、第2组=亿级
        # 四则运算符号映射表
        op_map = {
            'a': ' + ',
            's': ' - ',
            'm': ' × ',
            'd': ' ÷ '
        }

        def four_digit_to_chinese(num_str: str) -> str:
            """直接处理1-4位数字，自动跳过开头零，组内零正常处理"""
            if not num_str or num_str == '0000':
                return ''
            
            result = ''
            zero_flag = False
            digit_units = ['千', '百', '十', '']  # 对应4位的位权（从左到右）
            # 找到第一个非零数字的位置，跳过开头零
            first_non_zero = 0
            while first_non_zero < len(num_str) and num_str[first_non_zero] == '0':
                first_non_zero += 1
            if first_non_zero == len(num_str):
                return ''  # 全零返回空

            # 从第一个非零数字开始处理，按4位位权对应（不足4位时自动匹配）
            for i in range(len(num_str)):
                digit = int(num_str[i])
                unit = digit_units[4 - len(num_str) + i]  # 匹配正确位权
                if digit == 0:
                    zero_flag = True
                else:
                    if zero_flag:
                        result += chinese_nums[0]
                        zero_flag = False
                    # 十位特殊处理：仅10-19（两位数）省略"一"
                    if unit == '十' and digit == 1 and first_non_zero == i:
                        result += unit
                    else:
                        result += chinese_nums[digit] + unit
            return result

        def int_to_chinese(num: int) -> str:
            if num == 0:
                return chinese_nums[0]
            
            # 处理负数
            is_negative = False
            if num < 0:
                is_negative = True
                num = -num

            num_str = str(num)
            # 去除整体前导零（开头的0全部忽略）
            num_str = num_str.lstrip('0')
            # 全零特殊处理：还原为"0"
            if not num_str:
                num_str = "0"

            # 从右往左4位分组，不补零
            groups = []
            for i in range(len(num_str), 0, -4):
                start = max(0, i - 4)
                groups.append(num_str[start:i])

            result = ''
            level_zero_flag = False
            # 逆序遍历分组（从万/亿级到个级）
            for i in reversed(range(len(groups))):
                group = groups[i]
                group_cn = four_digit_to_chinese(group)
                level_unit = level_units[i]

                if not group_cn:
                    level_zero_flag = True
                    continue

                if level_zero_flag:
                    result += chinese_nums[0]
                    level_zero_flag = False

                result += group_cn + level_unit

            # 清理末尾零和开头"一十"
            result = result.rstrip('零')
            if result.startswith('一十') and len(result) == 2:
                result = '十'

            return ('负' + result) if is_negative else result

        def decimal_to_chinese(decimal_str: str) -> str:
            if not decimal_str:
                return ''
            return '点' + ''.join([chinese_nums[int(c)] for c in decimal_str])

        def fraction_to_chinese(numerator: str, denominator: str) -> str:
            numerator_cn = int_to_chinese(int(numerator))
            denominator_cn = int_to_chinese(int(denominator))
            return f"{denominator_cn}分之{numerator_cn}" if denominator != '1' else numerator_cn

        # 关键修改1：正则新增匹配四则运算符号（+、-、*、/），保持原顺序提取
        pattern = r"""
            (-?\d+\/\d+) |                # 分数（优先匹配，避免被/符号单独匹配）
            (-?\d+\.?\d*%) |              # 百分数
            (-?\d+\.\d+) |                # 小数（正常格式如1.23）
            (-?\.\d+) |                   # 小数（点开头如.123）
            (-?\d+) |                     # 整数
            ([aAsSmMdD])                  # 四则运算符号（单独分组）
        """
        # 提取所有匹配项（包括数字类和符号类），保持原文本顺序
        matches = re.findall(pattern, self.text, re.VERBOSE | re.MULTILINE)

        chinese_results = []
        for match in matches:
            (fraction, percent, decimal_normal, decimal_dot_start, integer, op) = match
            if fraction:
                # 分数处理（注意：分数的/已包含在分组内，不会被符号匹配）
                numerator, denominator = fraction.split('/', 1)
                chinese_results.append(fraction_to_chinese(numerator, denominator))
            elif percent:
                num_part = percent[:-1]
                if '.' in num_part:
                    int_part, dec_part = num_part.split('.', 1)
                    chinese_results.append(f"百分之{int_to_chinese(int(int_part))}{decimal_to_chinese(dec_part)}")
                else:
                    chinese_results.append(f"百分之{int_to_chinese(int(num_part))}")
            elif decimal_normal:
                int_part, dec_part = decimal_normal.split('.', 1)
                chinese_results.append(f"{int_to_chinese(int(int_part))}{decimal_to_chinese(dec_part)}")
            elif decimal_dot_start:
                dec_part = decimal_dot_start.lstrip('.')
                chinese_results.append(f"零{decimal_to_chinese(dec_part)}")
            elif integer:
                chinese_results.append(int_to_chinese(int(integer)))
            elif op:
                # 关键修改2：符号映射，按规则添加前后空格
                chinese_results.append(op_map[op.lower()])

        # 关键修改3：拼接所有结果，最后清理首尾多余空格（避免符号在开头/结尾导致的空格）
        final_result = ''.join(chinese_results).strip()
        # 清理可能的连续空格（如符号前后与数字拼接时的冗余空格）
        final_result = re.sub(r'\s+', ' ', final_result)
        return final_result
