import appscript
import ctypes
import gzip
import logging
import llama_cpp
import os
import re 
import setting
import sys
import threading
import time
import wx

from ctypes import POINTER, c_uint32, c_float, c_bool, Structure, byref, c_void_p
from typing import Callable, Dict, List, Optional, Tuple


# 多线程管理基类
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
                # 退出循环
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
        # 创建守护线程
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
class Translator(BaseThreadedWorker):
    #  HY-MT1.5-1.8B 配置
    DEFAULT_CONFIG = {
        "n_ctx": 2048,
        "n_threads": 8,
        "n_gpu_layers": 25,
        "n_batch": 256,
        "verbose": False,
        "backend": "metal",
        "metal_ctx_alloc": "auto",
        "metal_dev_id": 0
    }
    # 支持的目标语言映射
    SUPPORTED_LANGS = {
        "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
        "fr": "法语", "de": "德语", "es": "西班牙语", "ru": "俄语"
    }
    DEFAULT_TARGET_LANG = "en"
    MAX_INPUT_TOKENS = 800

    def __init__(self, log_level: int = logging.WARNING, loop_interval: float = 1):
        """初始化翻译器：加载模型、本地词典"""
        super().__init__(log_level=log_level, loop_interval=loop_interval)
        
        self._model = None
        self._input_text: Optional[str] = None  # 待翻译文本
        self._dictionary: dict = {}

        # 查找模型
        self.model_available = False
        self._current_dir = os.path.dirname(os.path.abspath(__file__))
        self.external_dir = os.path.expanduser("~/Downloads")
        self.model_path = None
        self._dict_path = os.path.join(self._current_dir, "resources", "dict.txt")

        # 加载词典
        self._load_dictionary()

    def load_model(self, model_path: str) -> bool:
        """加载翻译模型
        
        Args:
            model_path: 模型文件路径
            
        Returns:
            是否加载成功
        """
        if not model_path:
            self.model_available = False
            self.logger.warning("未提供模型路径")
            return False
            
        if not os.path.exists(model_path):
            self.model_available = False
            self.logger.warning(f"模型文件未找到：{model_path}")
            return False
        
        try:
            self.model_path = model_path
            self._model = llama_cpp.Llama(
                model_path=self.model_path,
                **self.DEFAULT_CONFIG
            )
            self.model_available = True
            self.logger.info(f"模型加载成功：{self.model_path}")
            return True
        except Exception as e:
            self.model_available = False
            self._model = None
            self.logger.error(f"模型加载失败：{str(e)}")
            return False

    def _load_model(self) -> Optional[llama_cpp.Llama]:
        """加载模型"""
        if not self.model_path:
            self.model_available = False
            self.logger.warning("模型路径未设置，请通过浏览按钮选择翻译模型")
            return None
        
        if not os.path.exists(self.model_path):
            self.model_available = False
            self.logger.warning(f"模型文件未找到：{self.model_path}")
            return None
        
        try:
            self.model_available = True
            self._model = llama_cpp.Llama(
                model_path=self.model_path,
                **self.DEFAULT_CONFIG
            )
            return self._model
        except Exception as e:
            self.model_available = False
            self.logger.error(f"模型加载失败：{str(e)}")
            return None

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
                        self.logger.warning(f"词典第{line_num}行格式不正确（需至少两个字段），已跳过")
            
            # 加载完成日志
            self.logger.info(f"本地 gzip 词典加载完成，共加载 {len(self._dictionary)} 条有效记录（路径：{self._dict_path}）")
        except FileNotFoundError:
            # 文件不存在异常
            self.logger.error(f"词典加载失败：找不到 gzip 文件 {self._dict_path}")
        except gzip.BadGzipFile:
            self.logger.error(f"词典加载失败：{self._dict_path} 不是有效的 gzip 压缩文件")
        except Exception as e:
            self.logger.error(f"加载 gzip 词典时发生错误: {str(e)}")

    def lookup_dictionary(self, word: str) -> Optional[str]:
        """本地词典查询（完全原始代码，一字未改）"""
        if not isinstance(word, str) or not word.strip():
            self.logger.debug("词典查询：输入无效")
            return None
        
        # 统一转为小写
        lower_word = word.strip().lower()
        if lower_word in self._dictionary:
            self.logger.debug(f"词典命中：{word} → {self._dictionary[lower_word]}")
            return self._dictionary[lower_word]
        else:
            self.logger.debug(f"词典未命中：{word}")
            return None


    def translate(self, original_text, source_lang, target_lang):
        """公有方法：翻译接口"""
        if not self.model_available or not self._model:
            raise RuntimeError("翻译模型不可用，请通过设置面板浏览并选择翻译模型")

        text = original_text.strip()
        if not text:
            raise ValueError("请输入要翻译的内容")

        if target_lang:
            prompt = f"""将下列文本从{source_lang}翻译成{target_lang},无需额外解释.
Text: {text}"""

        try:
            output = self._model.create_completion(
                prompt=prompt,
                max_tokens=768,
                temperature=0.33,
                top_p=0.9,
                stop=["\n"],
                echo=False,
                repeat_penalty=1.1
            )
            translated_text = output["choices"][0]["text"].strip()
            translated_text = self._post_process_translation(translated_text, original_text)
            return translated_text or ""
        except Exception as e:
            raise RuntimeError(f"翻译失败：{str(e)}") from e
        finally:
            if self._model:
                self._model.reset()
            time.sleep(0.05)

    def _post_process_translation(self, translated_text: str, original_text: str) -> str:
        """后处理翻译结果"""
        clean_patterns = [
            r"^.*?###T###",
            r"^.*?#.*?T.*?#",
            r"^.*?#.*?T"
        ]
        for pattern in clean_patterns:
            translated_text = re.sub(
                pattern, "", translated_text, flags=re.DOTALL | re.IGNORECASE
            ).strip()

        if not translated_text or re.match(r'^[\s\.,!?;:\'"]*$', translated_text):
            return f"未生成有效结果\n输入：{original_text}"
        return translated_text

    def translate_with_streaming(self, original_text: str, source_lang: str, target_lang: str, 
                                   callback=None) -> str:
        """分段翻译长文本，支持流式输出
        
        Args:
            original_text: 原始文本
            source_lang: 源语言
            target_lang: 目标语言
            callback: 每段翻译完成后的回调函数，签名为 callback(segment_text, translated_text)
            
        Returns:
            完整的翻译结果
        """
        if not self.model_available or not self._model:
            raise RuntimeError("翻译模型不可用，请通过设置面板浏览并选择翻译模型")

        text = original_text.strip()
        if not text:
            raise ValueError("请输入要翻译的内容")

        segments = re.split(r'\n\n+', text)
        all_translated = []
        
        for i, segment in enumerate(segments):
            if not segment.strip():
                continue
                
            segment = segment.strip()
            prompt = f"""将下列文本从{source_lang}翻译成{target_lang},无需额外解释.
Text: {segment}"""
            
            try:
                output = self._model.create_completion(
                    prompt=prompt,
                    max_tokens=768,
                    temperature=0.33,
                    top_p=0.9,
                    stop=["\n"],
                    echo=False,
                    repeat_penalty=1.1
                )
                translated_segment = output["choices"][0]["text"].strip()
                translated_segment = self._post_process_translation(translated_segment, segment)
                
                all_translated.append(translated_segment)
                
                if callback:
                    callback(segment, translated_segment)
                    
            except Exception as e:
                self.logger.warning(f"分段翻译失败 (第{i+1}段): {e}")
                error_msg = f"[翻译失败: {segment[:20]}...]"
                all_translated.append(error_msg)
                if callback:
                    callback(segment, error_msg)
            finally:
                if self._model:
                    self._model.reset()
                time.sleep(0.05)
        
        return '\n\n'.join(all_translated)

    # 仅实现：父类抽象方法（空逻辑，满足继承要求，无任何新增功能）
    def _run_task(self) -> Optional[any]:
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
        self.repeat_threshold = repeat_threshold  # 阈值

    def get_last_phrase(self) -> Optional[Tuple[str, float]]:
        """
        获取最后朗读的内容及时间戳，返回元组(内容, 时间戳)
        若内容重复且未超过阈值，返回None；否则返回新内容
        """
        try:
            current_content = self.vo.last_phrase.content()
            current_timestamp = time.time()  # 获取当前时间戳
            
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
            
            # 更新缓存并返回
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
        # 使用线程局部存储来保存wx.App实例
        self._thread_local = threading.local()

    def _get_wx_app(self) -> wx.App:
        """确保每个线程都有一个wx.App实例"""
        if not hasattr(self._thread_local, 'app'):
            # 非GUI线程，必须创建一个wx.App实例
            self._thread_local.app = wx.App(False)
        return self._thread_local.app

    def _run_task(self) -> Optional[Tuple[str, float]]:
        """
        检查剪贴板内容是否变化。
        如果变化，则返回 (新内容, 时间戳) 元组，否则返回 None。
        """
        self._get_wx_app()
        
        clipboard = wx.Clipboard.Get()
        if not clipboard.Open():
            self.logger.error("无法打开剪贴板。")
            return None
            
        try:
            # 获取文本数据
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
            
        return None


# 音量控制器类
class VolumeController(BaseThreadedWorker):
    """
    音量控制器：监控系统音量并强制修改为指定值
    使用 CoreAudio API 实现高性能音量控制
    """

    kAudioObjectSystemObject = 1
    kAudioObjectPropertyElementMain = 0
    kAudioHardwarePropertyDefaultOutputDevice = int.from_bytes(b'dOut', byteorder='big')
    kAudioHardwareServiceDeviceProperty_VirtualMainVolume = int.from_bytes(b'vmvc', byteorder='big')
    kAudioDevicePropertyScopeOutput = int.from_bytes(b'outp', byteorder='big')
    kAudioHardwareNoError = 0

    class AudioObjectPropertyAddress(Structure):
        _fields_ = [
            ("mSelector", c_uint32),
            ("mScope", c_uint32),
            ("mElement", c_uint32),
        ]

    def __init__(self, loop_interval: float = 0.25):
        super().__init__(loop_interval=loop_interval)
        self.logger = logging.getLogger(__name__)

        self._coreaudio = ctypes.CDLL(
            '/System/Library/Frameworks/CoreAudio.framework/Versions/A/CoreAudio'
        )
        self._coreaudio.AudioObjectGetPropertyData.argtypes = [
            c_uint32, POINTER(self.AudioObjectPropertyAddress), c_uint32, c_void_p, POINTER(c_uint32), c_void_p
        ]
        self._coreaudio.AudioObjectGetPropertyData.restype = c_uint32
        self._coreaudio.AudioObjectSetPropertyData.argtypes = [
            c_uint32, POINTER(self.AudioObjectPropertyAddress), c_uint32, c_void_p, c_uint32, c_void_p
        ]
        self._coreaudio.AudioObjectSetPropertyData.restype = c_uint32

        self._device_id: Optional[int] = None
        self._volume_limit: float = 0
        self._volume_target: float = 80
        self._last_set_volume: Optional[float] = None

    def set_config(self, volume_limit: float, volume_target: float):
        self._volume_limit = volume_limit
        self._volume_target = volume_target

    def _get_device_id(self) -> int:
        addr = self.AudioObjectPropertyAddress(
            mSelector=self.kAudioHardwarePropertyDefaultOutputDevice,
            mScope=0,
            mElement=0
        )
        device_id = c_uint32(0)
        data_size = c_uint32(ctypes.sizeof(device_id))
        result = self._coreaudio.AudioObjectGetPropertyData(
            self.kAudioObjectSystemObject, byref(addr), 0, None, byref(data_size), byref(device_id)
        )
        if result != self.kAudioHardwareNoError:
            raise RuntimeError(f"获取输出设备失败: {result}")
        return device_id.value

    def get_volume(self) -> float:
        if self._device_id is None:
            self._device_id = self._get_device_id()

        addr = self.AudioObjectPropertyAddress(
            mSelector=self.kAudioHardwareServiceDeviceProperty_VirtualMainVolume,
            mScope=self.kAudioDevicePropertyScopeOutput,
            mElement=self.kAudioObjectPropertyElementMain
        )
        volume = c_float(0.0)
        data_size = c_uint32(ctypes.sizeof(volume))
        result = self._coreaudio.AudioObjectGetPropertyData(
            self._device_id, byref(addr), 0, None, byref(data_size), byref(volume)
        )
        if result != self.kAudioHardwareNoError:
            raise RuntimeError(f"获取音量失败: {result}")
        return volume.value

    def _set_volume(self, volume: float):
        if self._device_id is None:
            self._device_id = self._get_device_id()

        addr = self.AudioObjectPropertyAddress(
            mSelector=self.kAudioHardwareServiceDeviceProperty_VirtualMainVolume,
            mScope=self.kAudioDevicePropertyScopeOutput,
            mElement=self.kAudioObjectPropertyElementMain
        )
        volume_val = c_float(max(0.0, min(1.0, volume)))
        data_size = c_uint32(ctypes.sizeof(volume_val))
        result = self._coreaudio.AudioObjectSetPropertyData(
            self._device_id, byref(addr), 0, None, data_size, byref(volume_val)
        )
        if result != self.kAudioHardwareNoError:
            raise RuntimeError(f"设置音量失败: {result}")
        self._last_set_volume = volume_val.value

    def _run_task(self):
        if self._volume_limit == 0:
            return None

        try:
            current = self.get_volume()
            current_percent = int(current * 100)

            if current_percent > self._volume_limit:
                self._set_volume(self._volume_target / 100.0)
        except Exception as e:
            self.logger.debug(f"音量控制异常: {e}")

        return None


class TextBrowser:
    def __init__(self):
        self.current_text = ""
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
            # 找到第一个非零数字的位置
            first_non_zero = 0
            while first_non_zero < len(num_str) and num_str[first_non_zero] == '0':
                first_non_zero += 1
            if first_non_zero == len(num_str):
                return ''  # 全零返回空

            for i in range(len(num_str)):
                digit = int(num_str[i])
                unit = digit_units[4 - len(num_str) + i]  # 匹配正确位权
                if digit == 0:
                    zero_flag = True
                else:
                    if zero_flag:
                        result += chinese_nums[0]
                        zero_flag = False
                    # 十位
                    if unit == '十' and digit == 1 and first_non_zero == i:
                        result += unit
                    else:
                        result += chinese_nums[digit] + unit
            return result

        def int_to_chinese(num: int) -> str:
            if num == 0:
                return chinese_nums[0]
            
            # 负数
            is_negative = False
            if num < 0:
                is_negative = True
                num = -num

            num_str = str(num)
            num_str = num_str.lstrip('0')
            # 全零
            if not num_str:
                num_str = "0"

            # 从右往左4位分组
            groups = []
            for i in range(len(num_str), 0, -4):
                start = max(0, i - 4)
                groups.append(num_str[start:i])

            result = ''
            level_zero_flag = False
            # 逆序遍历分组
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

        # 正则匹配四则运算符号
        pattern = r"""
            (-?\d+\/\d+) |                # 分数（优先匹配
            (-?\d+\.?\d*%) |              # 百分数
            (-?\d+\.\d+) |                # 小数
            (-?\.\d+) |                   # 小数点开头
            (-?\d+) |                     # 整数
            ([aAsSmMdD])                  # 四则运算符号
        """
        # 提取所有匹配项
        matches = re.findall(pattern, self.text, re.VERBOSE | re.MULTILINE)

        chinese_results = []
        for match in matches:
            (fraction, percent, decimal_normal, decimal_dot_start, integer, op) = match
            if fraction:
                # 分数处理
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
                #  符号映射
                chinese_results.append(op_map[op.lower()])

        #  拼接结果
        final_result = ''.join(chinese_results).strip()
        # 清理空格
        final_result = re.sub(r'\s+', ' ', final_result)
        return final_result
