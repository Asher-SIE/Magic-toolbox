import json
import logging
import objc
import os
import pickle
import re
import setting
import subprocess
import sys
import threading
import time
import wx
import wx.adv

from AppKit import NSApplication, NSApp, NSWindow
from dialogs import FindReplaceDialog, EditDialog, AboutDialog, UrlSelectDialog
from dictionary import Dictionary
from processer import ClipboardMonitor, TextBrowser, Translator, reboot_VoiceOver, TextProcessor, VoiceOverHandler, VolumeController, extract_urls, insert_heading_dot, split_text_by_punctuation
from typing import Optional, Tuple

import update
import ime_guard


class MainFrame(wx.Frame):
    # 长按跳转热键表：热键名 -> (macOS 物理键码, 跳转方法名)
    LONG_PRESS_KEYS = {
        "altshift7": (26, "_jump_clipboard_head"),   # kVK_ANSI_7
        "altshift9": (25, "_jump_clipboard_tail"),   # kVK_ANSI_9
        "altshift8": (28, "_jump_text_first_line"),  # kVK_ANSI_8
        "altshiftk": (40, "_jump_text_last_line"),   # kVK_ANSI_K
    }
    LONG_PRESS_THRESHOLD = 0.4  # 长按判定阈值（秒），按住超过该时长直接跳到该方向尽头
    LONG_PRESS_POLL_MS = 50     # 长按监测轮询间隔（毫秒）

    def __init__(self, parent, title):
        super(MainFrame, self).__init__(parent, title=title, size=(1024, 768))
        
        if update.is_expired():
            wx.MessageBox(
                setting._('version_expired_msg') % update.get_expiry_date().strftime('%Y-%m-%d'),
                setting._('version_expired_title'),
                wx.OK | wx.ICON_ERROR
            )
            os._exit(0)
        
        if update.is_expiring_soon():
            wx.MessageBox(
                setting._('version_expiring_msg') % (update.get_expiry_date().strftime('%Y-%m-%d'), update.days_until_expiry()),
                setting._('version_expiring_title'),
                wx.OK | wx.ICON_WARNING
            )
        
        # 启动时后台检查更新
        self._check_update_on_startup()
        
        # 状态变量
        self.clipboard_list_data = []  # 剪贴板列表
        self.current_clipboard_idx = -1
        self.current_module = "translation"
        self._clipboard_filter_keyword = ""  # 搜索关键词
        self._clipboard_filtered_data = None  # 筛选后的数据
        
        self._translation_lock = threading.Lock()

        # 识别（OCR）：当前引擎模式、引擎实例、虚拟引擎列表（循环切换用）、实例缓存与防重入锁
        self._ocr_mode = 'apple'
        self.ocr_engine = None
        self._ocr_engine_keys = []
        self._ocr_engine_cache = {}
        self._ocr_lock = threading.Lock()
        
        self.edit_dialog = None
        
        self.lang_codes = [
            "English", "Chinese", "French", "Portuguese", "Spanish", "Japanese", 
            "Turkish", "Russian", "Arabic", "Korean", "Thai", "Italian", "German", 
            "Vietnamese", "Malay", "Indonesian", "Filipino", "Hindi", "Traditional Chinese",
            "Polish", "Czech", "Dutch", "Khmer", "Burmese", "Persian", "Gujarati", 
            "Urdu", "Telugu", "Marathi", "Hebrew", "Bengali", "Tamil", "Ukrainian",
            "Tibetan", "Kazakh", "Mongolian", "Uyghur", "Cantonese"
        ]
        
        self.trans_source_options = [setting.get_lang_display(code) for code in self.lang_codes]
        self.trans_target_options = self.trans_source_options
        
        self._source_lang = "English"
        self._target_lang = "Chinese"
        self.load_config()

        # 创建UI组件
        self.init_toolbar()
        
        self._toolbar_source_choice = None
        self._toolbar_target_choice = None
        self._ocr_engine_choice = None
        self._ocr_engine_key_by_display = {}
        
        self.init_ui()
        self.create_menu_bar()

        # 实例化核心处理器
        self.translator = None
        # 本地词典：与翻译模式无关，所有模式共用（先查词库、无匹配再翻译）
        self.dictionary = Dictionary()
        self.vo_handler = VoiceOverHandler(
            log_level=logging.INFO,
            repeat_threshold=0.02,
            loop_interval=0.01
        )
        
        self.clipboard_monitor = ClipboardMonitor(
            log_level=logging.INFO, 
            loop_interval=0.1)
        self.TB = TextBrowser()
        self.volume_controller = VolumeController(loop_interval=0.02)
        self.volume_controller.set_config(self._volume_limit, self._volume_target)

        # Option+Shift+P 粘贴当前行：粘贴前的系统剪贴板内容与延时还原计时器
        self._paste_original_clipboard = None
        self._paste_restore_timer = None
        self._is_pasting = False

        # 长按监测：虚拟浏览器方向键按住超过阈值后直接跳到该方向尽头
        self._long_press_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_long_press_timer, self._long_press_timer)
        self._long_press_start = 0.0
        self._long_press_keycode = 0
        self._long_press_action = None

        # 提示音缓存：wx 异步播放期间要求对象存活，统一持有引用
        self._sounds = {}

        # 应用启动时检查VoiceOver状态，如果未运行则后台启动
        if not self.vo_handler.is_voiceover_running():
            logging.info("VoiceOver未运行，后台启动VoiceOver")
            # 使用后台线程启动VoiceOver，避免阻塞UI
            def start_vo_background():
                import subprocess
                import time
                try:
                    # 使用同样的启动方法作为reboot_VoiceOver函数
                    subprocess.run(['osascript', '-e', 'tell application "System Events" to key code 96 using command down'],
                                check=True, capture_output=True)
                    # 验证启动成功
                    max_wait = 10
                    wait_interval = 0.5
                    waited = 0
                    while waited < max_wait:
                        if self.vo_handler.is_voiceover_running():
                            logging.info("VoiceOver后台启动成功")
                            break
                        time.sleep(wait_interval)
                        waited += wait_interval
                    else:
                        logging.error("VoiceOver后台启动失败")
                except Exception as e:
                    logging.error(f"后台启动VoiceOver时出错: {e}")
            
            # 在后台线程中启动VoiceOver
            vo_thread = threading.Thread(target=start_vo_background, daemon=True)
            vo_thread.start()
        
        self.volume_controller.start_worker()

        # 初始化翻译器
        self.init_translator()

        # 初始化 OCR 引擎（先构建虚拟引擎列表，供 Option+Shift+Q 循环切换）
        from ocr_engine import available_engines
        self._ocr_engine_keys = [engine.key for engine in available_engines(setting.is_internal_device())]
        if self._ocr_engine_keys and self._ocr_mode not in self._ocr_engine_keys:
            self._ocr_mode = self._ocr_engine_keys[0]
        self.init_ocr_engine()

        #启动处理器
        self.clipboard_monitor.start_worker(callback=self.on_new_clipboard_content)

        self.load_clipboard_data()

        # 注册热键
        self.hotkey_ids = {}
        self.register_hotkeys()

        self.Bind(wx.EVT_CLOSE, self.on_exit)
        # 显示窗口
        self.Centre()
        self.Show(True)

        # 程序就绪提示音（播报一次）
        self.play_sound("start")


    def init_toolbar(self):
        """工具栏"""
        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_TEXT)
        # toolbar_for_module 函数来填充内容。
        self.copy_btn_id = wx.NewIdRef()
        self.edit_btn_id = wx.NewIdRef()
        self.delete_btn_id = wx.NewIdRef()
        self.browse_ocr_btn_id = wx.NewIdRef()

        self.toolbar.Realize()


    def create_menu_bar(self):
        menubar = wx.MenuBar()
        # 2. 应用菜单
        app_menu = wx.Menu()

        # 关于
        about_item = app_menu.Append(
            wx.ID_ABOUT,  # 使用系统默认ID
            setting._('menu_about')
        )
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        # 分隔线
        app_menu.AppendSeparator()

        # 退出
        exit_item = app_menu.Append(
            wx.ID_EXIT, 
            setting._('exit_app'),
            setting._('exit_app_tips')  
        )
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        rebootVO = app_menu.Append(wx.NewId(), setting._('menu_opt_rebootVO'))
        self.Bind(wx.EVT_MENU, reboot_VoiceOver, rebootVO)
        rebootProc = app_menu.Append(wx.NewId(), setting._('menu_opt_reboot_proc'))
        self.Bind(wx.EVT_MENU, self.on_reboot_vo_processer, rebootProc)
        cleanList = app_menu.Append(wx.NewId(), setting._('menu_opt_clean_list'))
        self.Bind(wx.EVT_MENU, self.on_clean_list, cleanList)


        # 添加到菜单栏
        menubar.Append(app_menu, setting._('menubar_opt'))

        # 帮助菜单
        help_menu = wx.Menu()
        program_help = help_menu.Append(wx.NewId(), setting._('menu_help_program'))
        shortcuts_help = help_menu.Append(wx.NewId(), setting._('menu_help_shortcuts'))
        changelog_help = help_menu.Append(wx.NewId(), setting._('menu_help_changelog'))
        download_model = help_menu.Append(wx.NewId(), setting._('menu_help_download_model'))

        # 视觉模型下载子菜单：需分别下载主模型与视觉编码器两个文件，故分列直链与首页
        download_vlm_menu = wx.Menu()
        vlm_model_item = download_vlm_menu.Append(wx.NewId(), setting._('ocr_vlm_download_model'))
        vlm_mmproj_item = download_vlm_menu.Append(wx.NewId(), setting._('ocr_vlm_download_mmproj'))
        vlm_home_item = download_vlm_menu.Append(wx.NewId(), setting._('ocr_vlm_download_home'))
        help_menu.AppendSubMenu(download_vlm_menu, setting._('menu_help_download_vlm'))

        self.Bind(wx.EVT_MENU, self.on_help_program, program_help)
        self.Bind(wx.EVT_MENU, self.on_help_shortcuts, shortcuts_help)
        self.Bind(wx.EVT_MENU, self.on_help_changelog, changelog_help)
        self.Bind(wx.EVT_MENU, self.on_download_model, download_model)
        self.Bind(wx.EVT_MENU, self.on_download_vlm_model, vlm_model_item)
        self.Bind(wx.EVT_MENU, self.on_download_vlm_mmproj, vlm_mmproj_item)
        self.Bind(wx.EVT_MENU, self.on_download_vlm_home, vlm_home_item)

        # 检查更新菜单
        check_update = help_menu.Append(wx.NewId(), setting._('menu_help_check_update'))
        self.Bind(wx.EVT_MENU, self.on_check_update, check_update)

        # 分隔线
        help_menu.AppendSeparator()

        # 根据设备类型条件性地添加打赏和反馈菜单
        is_internal = setting.is_internal_device()
        if is_internal:
            feedback_help = help_menu.Append(wx.NewId(), setting._('menu_help_feedback'))
            self.Bind(wx.EVT_MENU, self.on_help_feedback, feedback_help)
        else:
            donate_help = help_menu.Append(wx.NewId(), setting._('menu_help_donate'))
            self.Bind(wx.EVT_MENU, self.on_help_donate, donate_help)

        menubar.Append(help_menu, setting._('menubar_help'))

       # 设置菜单栏到窗口
        self.SetMenuBar(menubar)


    def init_ui(self):
        """初始化用户界面"""
        # 标准选项卡容器（参考 Win 属性对话框）：四个功能面板作为选项卡页，
        # 等效替换原左侧 ListBox 导航，切换逻辑保持 switch_to_module 不变
        self.notebook = wx.Notebook(self)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.on_nav_page_changed)

        # --- 初始化各功能模块的面板 ---
        # 翻译面板
        self.translation_panel = wx.Panel(self.notebook)
        self.setup_translation_panel()

        # 剪贴板面板
        self.clipboard_panel = wx.Panel(self.notebook)
        self.setup_clipboard_panel()

        # 识别面板
        self.recognition_panel = wx.Panel(self.notebook)
        self.setup_recognition_panel()

        # 设置面板
        self.settings_panel = wx.Panel(self.notebook)
        self.setup_settings_panel()

        # 选项卡页与标题，顺序与原导航列表一致
        self.notebook.AddPage(self.translation_panel, setting._('nav_translation'))
        self.notebook.AddPage(self.clipboard_panel, setting._('nav_clipboard'))
        self.notebook.AddPage(self.recognition_panel, setting._('nav_recognition'))
        self.notebook.AddPage(self.settings_panel, setting._('nav_settings'))

        # 顶级 Sizer 管理选项卡容器
        main_frame_sizer = wx.BoxSizer(wx.VERTICAL)
        main_frame_sizer.Add(self.notebook, 1, wx.EXPAND)
        self.SetSizer(main_frame_sizer)

        # 初始显示翻译面板
        self.switch_to_module("translation")


    def setup_translation_panel(self):
        """设置翻译功能面板的UI元素"""
        static_box = wx.StaticBox(self.translation_panel, label=setting._("trans_input_placeholder"))
        sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL)

        self.text_ctrl = wx.TextCtrl(self.translation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_to_translate)

        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        self.translation_panel.SetSizer(sizer)

    def setup_recognition_panel(self):
        """设置识别（OCR）功能面板的UI元素，布局与翻译面板一致"""
        static_box = wx.StaticBox(self.recognition_panel, label=setting._("recognition_hint"))
        sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL)

        self.ocr_result_ctrl = wx.TextCtrl(self.recognition_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)

        sizer.Add(self.ocr_result_ctrl, 1, wx.EXPAND | wx.ALL, 5)

        self.recognition_panel.SetSizer(sizer)
    
    def on_toolbar_source_lang_changed(self, event):
        if hasattr(self, '_toolbar_source_choice') and self._toolbar_source_choice:
            display_text = self._toolbar_source_choice.GetStringSelection()
            for code in self.lang_codes:
                if setting.get_lang_display(code) == display_text:
                    self._source_lang = code
                    break
            self.save_config()
    
    def on_toolbar_target_lang_changed(self, event):
        if hasattr(self, '_toolbar_target_choice') and self._toolbar_target_choice:
            display_text = self._toolbar_target_choice.GetStringSelection()
            for code in self.lang_codes:
                if setting.get_lang_display(code) == display_text:
                    self._target_lang = code
                    break
            self.save_config()
    
    def on_translation_mode_changed(self, event):
        if hasattr(self, '_translation_mode_choice') and self._translation_mode_choice:
            display_text = self._translation_mode_choice.GetStringSelection()
            if display_text == setting._('mode_apple'):
                self._translation_mode = 'apple'
            else:
                self._translation_mode = 'llm'
            self.save_config()
            self._update_translator_for_mode()
    
    def _update_translator_for_mode(self):
        """根据翻译模式更新翻译器"""
        if self._translation_mode == 'apple':
            if not hasattr(self, 'apple_translator'):
                try:
                    from apple_translator import AppleTranslator
                    self.apple_translator = AppleTranslator()
                except Exception as e:
                    logging.warning(f"Apple翻译器初始化失败: {e}")
                    self._translation_mode = 'llm'
                    self.save_config()
        else:
            if hasattr(self, 'apple_translator'):
                del self.apple_translator
    
    def _do_translate(self, text: str, source_lang: str, target_lang: str, callback=None) -> str:
        """统一的翻译方法
        
        Args:
            text: 待翻译文本
            source_lang: 源语言
            target_lang: 目标语言
            callback: 回调函数
            
        Returns:
            翻译结果
        """
        if self._translation_mode == 'apple':
            if hasattr(self, 'apple_translator') and self.apple_translator.is_available():
                return self._translate_with_apple(text, source_lang, target_lang, callback)
            else:
                raise RuntimeError(setting._('apple_translation_not_available'))
        else:
            if not self.translator.model_available:
                # 模型可能因视觉识别被异步卸载：按配置路径重新加载（后台线程中执行，不阻塞界面）
                model_path = getattr(self, '_model_path', '') or ''
                if model_path and os.path.exists(model_path):
                    self.translator.load_model(model_path)
            return self.translator.translate_with_streaming(text, source_lang, target_lang, callback)

    APPLE_TRANSLATION_SEGMENT_CHARS = 1000

    def _translate_with_apple(self, text: str, source_lang: str, target_lang: str, callback=None) -> str:
        """Apple 翻译：长文本分段调用，每段完成后流式回调

        与 LLM 通道的 translate_with_streaming 行为对齐，
        结果以空行拼接，callback 签名为 callback(segment_text, translated_text)
        """
        max_chars = self.APPLE_TRANSLATION_SEGMENT_CHARS
        if len(text) <= max_chars:
            segments = [text]
        else:
            segments = split_text_by_punctuation(text, max_chars)

        results = []
        for segment in segments:
            translated = self.apple_translator.translate(segment, source_lang, target_lang)
            results.append(translated)
            if callback:
                callback(segment, translated)
        return '\n\n'.join(results)
    
    def _lookup_dictionary(self, word: str) -> str:
        """查词典（所有翻译模式共用：先查词库、无匹配再走翻译引擎）"""
        if self.dictionary:
            return self.dictionary.lookup(word)
        return None
    
    def on_source_lang_changed(self, event):
        pass
    
    def on_target_lang_changed(self, event):
        pass
    
    def load_config(self):
        config = setting.load_config()
        self._source_lang = config.get('source_lang', 'English')
        self._target_lang = config.get('target_lang', 'Chinese')
        self._model_path = config.get('model_path', '')
        self._clipboard_max_count = config.get('clipboard_max_count', 1000)
        self._volume_limit = config.get('volume_limit', 100)
        self._volume_target = config.get('volume_target', 80)
        self._translation_mode = config.get('translation_mode', 'llm')
        self._ocr_mode = config.get('ocr_mode', 'apple')
        self._ocr_model_path = config.get('ocr_model_path', '')
        self._ocr_mmproj_path = config.get('ocr_mmproj_path', '')
        self._sentence_punctuations = list(setting.sentence_punctuations)

        is_internal = setting.is_internal_device()
        supports_apple = setting.supports_apple_translation()

        # 内部机只开放 Apple（翻译/OCR 一致）；开发内部版本（DEBUG_BUILD）放开限制、开放全部能力
        if is_internal and not setting.DEBUG_BUILD:
            self._translation_mode = 'apple'
            self._ocr_mode = 'apple'
        elif not supports_apple:
            self._translation_mode = 'llm'

        if hasattr(self, '_toolbar_source_choice') and self._toolbar_source_choice and hasattr(self, '_toolbar_target_choice') and self._toolbar_target_choice:
            source_display = setting.get_lang_display(self._source_lang)
            target_display = setting.get_lang_display(self._target_lang)
            self._toolbar_source_choice.SetStringSelection(source_display)
            self._toolbar_target_choice.SetStringSelection(target_display)
        
        if hasattr(self, 'clipboard_count_input') and self.clipboard_count_input:
            self.clipboard_count_input.SetValue(str(self._clipboard_max_count))
        if hasattr(self, 'volume_limit_input') and self.volume_limit_input:
            self.volume_limit_input.SetValue(str(self._volume_limit))
        if hasattr(self, 'volume_target_input') and self.volume_target_input:
            self.volume_target_input.SetValue(str(self._volume_target))
        
        if hasattr(self, '_translation_mode_choice') and self._translation_mode_choice:
            mode_display = setting._('mode_apple') if self._translation_mode == 'apple' else setting._('mode_llm')
            self._translation_mode_choice.SetStringSelection(mode_display)
            self._translation_mode_choice.Enable(self._translation_mode != 'apple' or is_internal)

        if hasattr(self, '_ocr_engine_choice') and self._ocr_engine_choice:
            for display, key in self._ocr_engine_key_by_display.items():
                if key == self._ocr_mode:
                    self._ocr_engine_choice.SetStringSelection(display)
                    break

        if hasattr(self, 'ocr_model_path_text') and self.ocr_model_path_text:
            self.ocr_model_path_text.SetValue(self._ocr_model_path)
            self.ocr_mmproj_path_text.SetValue(self._ocr_mmproj_path)

        if hasattr(self, 'sentence_punct_input') and self.sentence_punct_input:
            self.sentence_punct_input.SetValue(self._format_sentence_punctuations(self._sentence_punctuations))

    def save_config(self):
        model_path = getattr(self, '_model_path', '') or ''
        clipboard_max_count = getattr(self, '_clipboard_max_count', 1000)
        volume_limit = getattr(self, '_volume_limit', 100)
        volume_target = getattr(self, '_volume_target', 80)
        translation_mode = getattr(self, '_translation_mode', 'llm')
        ocr_mode = getattr(self, '_ocr_mode', 'apple')
        ocr_model_path = getattr(self, '_ocr_model_path', '') or ''
        ocr_mmproj_path = getattr(self, '_ocr_mmproj_path', '') or ''
        sentence_punctuations = getattr(self, '_sentence_punctuations', None)
        setting.save_config(self._source_lang, self._target_lang, model_path, clipboard_max_count, volume_limit, volume_target, translation_mode, ocr_mode, ocr_model_path, ocr_mmproj_path, sentence_punctuations)


    def setup_clipboard_panel(self):
        """设置剪贴板功能面板的UI元素"""
        static_box = wx.StaticBox(self.clipboard_panel, label=setting._("clipboard_history"))
        
        sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL) 

        self.list_Box = wx.CheckListBox(self.clipboard_panel) # 使用 CheckListBox 实现复选功能
        self.list_Box.Bind(wx.EVT_LISTBOX, self.on_list_item_selected)
        self.list_Box.Bind(wx.EVT_CHECKLISTBOX, self.on_list_item_checked) # 绑定复选事件
        # 绑定键盘事件
        self.list_Box.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)

        sizer.Add(self.list_Box, 1, wx.EXPAND | wx.ALL, 5) # 拉伸填充并添加边距

        self.clipboard_panel.SetSizer(sizer)


    def setup_settings_panel(self):
        """设置功能面板的UI元素 """
        # 分组较多，外层套可滚动容器，窗口高度不足时可滚动查看全部分组
        settings_scroll = wx.ScrolledWindow(self.settings_panel)
        settings_scroll.SetScrollRate(20, 20)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        browse_model_static_box = wx.StaticBox(settings_scroll, label=setting._("browse_model"))
        browse_model_sizer = wx.StaticBoxSizer(browse_model_static_box, wx.VERTICAL)

        model_path_h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.model_path_text = wx.TextCtrl(browse_model_static_box, style=wx.TE_READONLY)
        model_path_h_sizer.Add(self.model_path_text, 1, wx.EXPAND | wx.RIGHT, 5)
        
        self.browse_model_button = wx.Button(browse_model_static_box, label=setting._("browse_btn"))
        self.browse_model_button.Bind(wx.EVT_BUTTON, self.on_browse_model_click)
        model_path_h_sizer.Add(self.browse_model_button, 0)
        
        browse_model_sizer.Add(model_path_h_sizer, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(browse_model_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # --- 图像识别模型分组 ---
        ocr_model_static_box = wx.StaticBox(settings_scroll, label=setting._("ocr_model_group"))
        ocr_model_sizer = wx.StaticBoxSizer(ocr_model_static_box, wx.VERTICAL)

        ocr_model_row = wx.BoxSizer(wx.HORIZONTAL)
        self.ocr_model_path_text = wx.TextCtrl(ocr_model_static_box, style=wx.TE_READONLY)
        self.ocr_model_path_text.SetValue(getattr(self, '_ocr_model_path', ''))
        ocr_model_row.Add(self.ocr_model_path_text, 1, wx.EXPAND | wx.RIGHT, 5)
        self.browse_ocr_model_button = wx.Button(ocr_model_static_box, label=setting._("browse_ocr_model"))
        self.browse_ocr_model_button.Bind(wx.EVT_BUTTON, self.on_browse_ocr_model_click)
        ocr_model_row.Add(self.browse_ocr_model_button, 0)
        ocr_model_sizer.Add(ocr_model_row, 0, wx.EXPAND | wx.ALL, 5)

        ocr_mmproj_row = wx.BoxSizer(wx.HORIZONTAL)
        self.ocr_mmproj_path_text = wx.TextCtrl(ocr_model_static_box, style=wx.TE_READONLY)
        self.ocr_mmproj_path_text.SetValue(getattr(self, '_ocr_mmproj_path', ''))
        ocr_mmproj_row.Add(self.ocr_mmproj_path_text, 1, wx.EXPAND | wx.RIGHT, 5)
        self.browse_ocr_mmproj_button = wx.Button(ocr_model_static_box, label=setting._("browse_ocr_mmproj"))
        self.browse_ocr_mmproj_button.Bind(wx.EVT_BUTTON, self.on_browse_ocr_mmproj_click)
        ocr_mmproj_row.Add(self.browse_ocr_mmproj_button, 0)
        ocr_model_sizer.Add(ocr_mmproj_row, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(ocr_model_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # --- 2. 剪贴板最大条数分组 ---
        clipboard_count_static_box = wx.StaticBox(settings_scroll, label=setting._("clipboard_max_count"))
        clipboard_count_sizer = wx.StaticBoxSizer(clipboard_count_static_box, wx.VERTICAL)

        self.clipboard_count_input = wx.TextCtrl(clipboard_count_static_box, value=str(getattr(self, '_clipboard_max_count', 1000)), style=wx.TE_RIGHT)
        self.clipboard_count_input.Bind(wx.EVT_TEXT, self.on_clipboard_count_text_change)
        self.clipboard_count_input.Bind(wx.EVT_KILL_FOCUS, self.on_clipboard_count_focus_lost)

        clipboard_count_sizer.Add(self.clipboard_count_input, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(clipboard_count_sizer, 0, wx.EXPAND | wx.ALL, 5)

        volume_control_static_box = wx.StaticBox(settings_scroll, label=setting._("volume_control"))
        volume_control_sizer = wx.StaticBoxSizer(volume_control_static_box, wx.VERTICAL)

        volume_limit_row = wx.BoxSizer(wx.HORIZONTAL)
        volume_limit_label = wx.StaticText(volume_control_static_box, label=setting._("volume_limit_label"))
        volume_limit_row.Add(volume_limit_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.volume_limit_input = wx.TextCtrl(volume_control_static_box, value=str(getattr(self, '_volume_limit', 100)), style=wx.TE_RIGHT)
        self.volume_limit_input.Bind(wx.EVT_TEXT, self.on_volume_limit_text_change)
        self.volume_limit_input.Bind(wx.EVT_KILL_FOCUS, self.on_volume_limit_focus_lost)
        volume_limit_row.Add(self.volume_limit_input, 1, wx.EXPAND)

        volume_target_row = wx.BoxSizer(wx.HORIZONTAL)
        volume_target_label = wx.StaticText(volume_control_static_box, label=setting._("volume_target_label"))
        volume_target_row.Add(volume_target_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.volume_target_input = wx.TextCtrl(volume_control_static_box, value=str(getattr(self, '_volume_target', 80)), style=wx.TE_RIGHT)
        self.volume_target_input.Bind(wx.EVT_TEXT, self.on_volume_target_text_change)
        self.volume_target_input.Bind(wx.EVT_KILL_FOCUS, self.on_volume_target_focus_lost)
        volume_target_row.Add(self.volume_target_input, 1, wx.EXPAND)

        volume_control_sizer.Add(volume_limit_row, 0, wx.EXPAND | wx.ALL, 5)
        volume_control_sizer.Add(volume_target_row, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(volume_control_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # --- 编辑器分句符号分组：一行一个标点，失焦解析保存，分句功能实时生效 ---
        sentence_punct_static_box = wx.StaticBox(settings_scroll, label=setting._("sentence_punct_group"))
        sentence_punct_sizer = wx.StaticBoxSizer(sentence_punct_static_box, wx.VERTICAL)

        sentence_punct_hint = wx.StaticText(sentence_punct_static_box, label=setting._("sentence_punct_hint"))
        sentence_punct_sizer.Add(sentence_punct_hint, 0, wx.ALL, 5)

        self.sentence_punct_input = wx.TextCtrl(sentence_punct_static_box, style=wx.TE_MULTILINE, size=(-1, 90))
        self.sentence_punct_input.SetValue(self._format_sentence_punctuations(getattr(self, '_sentence_punctuations', None)))
        self.sentence_punct_input.Bind(wx.EVT_KILL_FOCUS, self.on_sentence_punct_focus_lost)
        sentence_punct_sizer.Add(self.sentence_punct_input, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(sentence_punct_sizer, 0, wx.EXPAND | wx.ALL, 5)

        settings_scroll.SetSizer(main_sizer)
        settings_scroll.FitInside()  # 虚拟尺寸随内容扩展，内容超出窗口时出现滚动条
        scroll_outer_sizer = wx.BoxSizer(wx.VERTICAL)
        scroll_outer_sizer.Add(settings_scroll, 1, wx.EXPAND)
        self.settings_panel.SetSizer(scroll_outer_sizer)


    @staticmethod
    def _format_sentence_punctuations(punctuations) -> str:
        """分句符号列表转多行文本（一行一个符号）"""
        if not punctuations:
            punctuations = setting.sentence_punctuations
        return "\n".join(punctuations)

    @staticmethod
    def _parse_sentence_punctuations(text: str) -> list:
        """多行文本解析为分句符号列表：去空白、仅保留单字符、去重"""
        result = []
        for line in text.split('\n'):
            symbol = line.strip()
            if len(symbol) == 1 and symbol not in result:
                result.append(symbol)
        return result

    def on_sentence_punct_focus_lost(self, event):
        """分句符号编辑框失去焦点：解析保存并即时生效，无有效符号时还原显示"""
        if getattr(self, '_processing_sentence_punct', False):
            event.Skip()
            return

        self._processing_sentence_punct = True
        try:
            parsed = self._parse_sentence_punctuations(self.sentence_punct_input.GetValue())
            if not parsed:
                # 全部无效（含清空）时按无效输入处理，还原为当前生效值
                self.sentence_punct_input.SetValue(self._format_sentence_punctuations(self._sentence_punctuations))
                return
            if parsed != list(self._sentence_punctuations):
                self._sentence_punctuations = parsed
                setting.sentence_punctuations[:] = parsed
                self.save_config()
        finally:
            self._processing_sentence_punct = False
        event.Skip()


    def on_browse_model_click(self, event):
        """浏览并选择翻译模型"""
        wildcard = "GGUF Model (*.gguf)|*.gguf|All Files (*.*)|*.*"
        dialog = wx.FileDialog(
            self,
            message=setting._("select_model_file"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )
        
        if dialog.ShowModal() == wx.ID_OK:
            model_path = dialog.GetPath()
            self.model_path_text.SetValue(model_path)

            if self.translator:
                success = self.translator.load_model(model_path)
                if success:
                    self._model_path = model_path
                    self.save_config()
                    wx.MessageBox(setting._("model_load_success"), setting._("success"), wx.OK | wx.ICON_INFORMATION)
                    self.text_ctrl.SetValue("")
                else:
                    wx.MessageBox(setting._("model_load_failed"), setting._("error"), wx.OK | wx.ICON_WARNING)

        dialog.Destroy()

    def on_browse_ocr_model_click(self, event):
        """浏览并选择图像识别的视觉模型 GGUF 文件"""
        self._browse_ocr_model_file(self.ocr_model_path_text, 'select_ocr_model_file', '_ocr_model_path')

    def on_browse_ocr_mmproj_click(self, event):
        """浏览并选择图像识别的视觉编码器 mmproj 文件"""
        self._browse_ocr_model_file(self.ocr_mmproj_path_text, 'select_ocr_mmproj_file', '_ocr_mmproj_path')

    def _browse_ocr_model_file(self, path_text, message_key: str, attr_name: str):
        """图像识别模型文件选择的公共流程：选择后立即保存配置并重新初始化引擎预加载"""
        wildcard = "GGUF Model (*.gguf)|*.gguf|All Files (*.*)|*.*"
        dialog = wx.FileDialog(
            self,
            message=setting._(message_key),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        result = dialog.ShowModal()
        logging.info(f"OCR模型文件对话框关闭: result={result}, wx.ID_OK={wx.ID_OK}, 控件值={path_text.GetValue()!r}")
        if result == wx.ID_OK:
            path = dialog.GetPath()
            logging.info(f"OCR模型文件已选择: attr={attr_name}, path={path!r}")
            path_text.SetValue(path)
            setattr(self, attr_name, path)
            logging.info(f"OCR模型路径保存前: getattr={getattr(self, attr_name, '')!r}")
            self.save_config()
            self.init_ocr_engine()
            self._preload_ocr_engine()

        dialog.Destroy()


    def on_exit(self, event):
        """处理退出事件：释放线程、热键，关闭窗口"""
        self.save_config()
        # 存储剪贴板数据
        self.save_clipboard_data()
        #  停止核心处理器线程
        if self.translator:
            self.translator.stop_worker()
        if self.clipboard_monitor:
            self.clipboard_monitor.stop_worker()

        #  注销热键
        for hid in self.hotkey_ids.values():
            self.UnregisterHotKey(hid)
        self.hotkey_ids.clear()

        #  停止粘贴还原计时器
        if self._paste_restore_timer is not None:
            self._paste_restore_timer.Stop()

        #  关闭窗口
        os._exit(0)


    def on_about(self, event):
        dialog = AboutDialog(self)
        dialog.ShowModal()
        dialog.Destroy()


    def on_check_update(self, event):
        """检查更新"""
        self._do_check_update()


    def _check_update_on_startup(self):
        """启动时后台检查更新"""
        def _background_check():
            import time
            time.sleep(2)  # 等待UI加载完成
            wx.CallAfter(lambda: self._do_check_update(silent=True, speak=True))

        threading.Thread(target=_background_check, daemon=True).start()


    def _do_check_update(self, silent=False, speak=False):
        """执行更新检查"""
        has_update, latest_version, download_url = update.check_for_updates()
        if has_update:
            if speak:
                self.vo_handler.speak_text(setting._('update_available_msg') % latest_version)
            result = wx.MessageBox(
                setting._('update_available_msg') % latest_version,
                setting._('update_available_title'),
                wx.YES_NO | wx.ICON_INFORMATION
            )
            if result == wx.YES:
                def _background_download():
                    download_result = update.start_download(latest_version, download_url)
                    wx.CallAfter(lambda r=download_result, v=latest_version: self._show_download_result(r, v))

                threading.Thread(target=_background_download, daemon=True).start()
        elif latest_version and not silent:
            wx.MessageBox(
                setting._('update_latest_msg') % latest_version,
                setting._('update_latest_title'),
                wx.OK | wx.ICON_INFORMATION
            )


    def _show_download_result(self, result, latest_version):
        """显示下载结果"""
        if result == 'permission_denied':
            result_box = wx.MessageBox(
                setting._('permission_denied_msg'),
                setting._('permission_denied_title'),
                wx.YES_NO | wx.ICON_WARNING
            )
            if result_box == wx.YES:
                update.open_privacy_settings()
            return

        app_path = result[0] if isinstance(result, tuple) else result
        need_manual_process = result[1] if isinstance(result, tuple) and len(result) > 1 else False

        if app_path:
            if need_manual_process:
                msg = setting._('update_download_conflict_msg').format(
                    app_path=app_path,
                    version=latest_version
                )
            else:
                msg = setting._('update_download_success_msg') % app_path
            wx.MessageBox(
                msg,
                setting._('update_download_success_title'),
                wx.OK | wx.ICON_INFORMATION
            )
        else:
            wx.MessageBox(
                setting._('update_download_failed_msg'),
                setting._('update_download_failed_title'),
                wx.OK | wx.ICON_WARNING
            )


    def on_help_program(self, event):
        content = setting.load_help_content("help.txt")
        if not content:
            content = setting._('help_load_failed')
        
        dialog = wx.Dialog(self, title=setting._("menu_help_program"), size=(500, 450))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        text_ctrl = wx.TextCtrl(
            panel, 
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL
        )
        text_ctrl.SetValue(content)
        text_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        btn = wx.Button(panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        ime_guard.install(dialog)
        dialog.ShowModal()
        dialog.Destroy()


    def on_help_shortcuts(self, event):
        content = setting.load_help_content("shortcuts.txt")
        if not content:
            content = setting._('help_load_failed')
        
        dialog = wx.Dialog(self, title=setting._("menu_help_shortcuts"), size=(500, 450))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        text_ctrl = wx.TextCtrl(
            panel, 
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL
        )
        text_ctrl.SetValue(content)
        text_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        btn = wx.Button(panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        ime_guard.install(dialog)
        dialog.ShowModal()
        dialog.Destroy()


    def on_help_donate(self, event):
        import io
        from cryptography.fernet import Fernet
        
        DECRYPT_KEY = b'PN19ejPlfyN7s8f0TPpPl2dSALceTI9LWF8i0-chSYc='
        fernet = Fernet(DECRYPT_KEY)
        
        import os as os_module
        current_dir = os_module.path.dirname(os_module.path.abspath(__file__))
        qrc_path = os_module.path.join(current_dir, "resources", "qrc_encrypted.bin")
        with open(qrc_path, 'rb') as f:
            encrypted_data = f.read()
        decrypted_data = fernet.decrypt(encrypted_data)
        
        image = wx.Image(io.BytesIO(decrypted_data))
        bitmap = wx.Bitmap(image)
        
        dialog = wx.Dialog(self, title=setting._("menu_help_donate"), size=(400, 520))
        
        content_panel = wx.Panel(dialog)
        content_sizer = wx.BoxSizer(wx.VERTICAL)

        title_text = wx.StaticText(content_panel, label=setting._('donate_title'))
        title_text.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        
        qr_bitmap = wx.StaticBitmap(content_panel, bitmap=wx.Bitmap(bitmap.ConvertToImage().Scale(280, 280)))
        
        content_text = wx.StaticText(content_panel, label=setting._('donate_content'))
        content_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        content_text.Wrap(320)

        content_sizer.Add(title_text, 0, wx.ALIGN_CENTER | wx.TOP, 15)
        content_sizer.Add(qr_bitmap, 0, wx.ALIGN_CENTER | wx.ALL, 15)
        content_sizer.Add(content_text, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT, 15)
        content_panel.SetSizer(content_sizer)
        
        button_panel = wx.Panel(dialog)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        contact_btn = wx.Button(button_panel, label=setting._('donate_contact_btn'))
        contact_btn.Bind(wx.EVT_BUTTON, lambda e: (subprocess.run(['open', 'mailto:asher.sie@gmail.com']), dialog.Close()))
        
        btn = wx.Button(button_panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())
        
        button_sizer.Add(contact_btn, 0, wx.RIGHT, 15)
        button_sizer.Add(btn, 0)
        button_panel.SetSizer(button_sizer)
        
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(content_panel, 1, wx.EXPAND)
        main_sizer.Add(button_panel, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.TOP, 15)
        
        dialog.SetSizer(main_sizer)
        ime_guard.install(dialog)
        dialog.ShowModal()
        dialog.Destroy()


    def on_help_feedback(self, event):
        dialog = wx.Dialog(self, title=setting._("menu_help_feedback"), size=(400, 250))
        
        content_panel = wx.Panel(dialog)
        content_sizer = wx.BoxSizer(wx.VERTICAL)

        title_text = wx.StaticText(content_panel, label=setting._('feedback_title'))
        title_text.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        
        content_text = wx.StaticText(content_panel, label=setting._('feedback_content'))
        content_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        content_text.Wrap(320)

        content_sizer.Add(title_text, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        content_sizer.Add(content_text, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT | wx.TOP, 15)
        content_panel.SetSizer(content_sizer)
        
        button_panel = wx.Panel(dialog)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        contact_btn = wx.Button(button_panel, label=setting._('feedback_contact_btn'))
        contact_btn.Bind(wx.EVT_BUTTON, lambda e: (subprocess.run(['open', 'mailto:songting_xie@apple.com']), dialog.Close()))
        
        btn = wx.Button(button_panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())
        
        button_sizer.Add(contact_btn, 0, wx.RIGHT, 15)
        button_sizer.Add(btn, 0)
        button_panel.SetSizer(button_sizer)
        
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(content_panel, 1, wx.EXPAND)
        main_sizer.Add(button_panel, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.TOP, 15)
        
        dialog.SetSizer(main_sizer)
        ime_guard.install(dialog)
        dialog.ShowModal()
        dialog.Destroy()


    def on_download_model(self, event):
        import webbrowser
        
        result = wx.MessageBox(
            setting._('download_model_prompt'),
            setting._('download_model_title'),
            wx.YES_NO | wx.ICON_QUESTION
        )
        
        if result == wx.YES:
            webbrowser.open('https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF/resolve/main/HY-MT1.5-1.8B-Q4_K_M.gguf?download=true')
        else:
            webbrowser.open('https://huggingface.co/tencent/HY-MT1.5-1.8B-GGUF')


    # 本地视觉模型推荐下载地址（Qwen/Qwen3-VL-4B-Instruct-GGUF，模型说明见 README）
    VLM_HOME_URL = 'https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF'
    VLM_MODEL_URL = VLM_HOME_URL + '/resolve/main/Qwen3VL-4B-Instruct-Q4_K_M.gguf?download=true'
    VLM_MMPROJ_URL = VLM_HOME_URL + '/resolve/main/mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf?download=true'

    def on_download_vlm_model(self, event):
        """打开主模型直链"""
        import webbrowser
        webbrowser.open(self.VLM_MODEL_URL)

    def on_download_vlm_mmproj(self, event):
        """打开视觉编码器直链"""
        import webbrowser
        webbrowser.open(self.VLM_MMPROJ_URL)

    def on_download_vlm_home(self, event):
        """打开模型仓库首页"""
        import webbrowser
        webbrowser.open(self.VLM_HOME_URL)


    def on_help_changelog(self, event):
        import os as os_module
        current_dir = os_module.path.dirname(os_module.path.abspath(__file__))
        changelog_path = os_module.path.join(current_dir, "resources", "更新日志.txt")
        
        try:
            with open(changelog_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            content = setting._('help_load_failed')
        
        dialog = wx.Dialog(self, title=setting._("menu_help_changelog"), size=(500, 450))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        text_ctrl = wx.TextCtrl(
            panel, 
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL
        )
        text_ctrl.SetValue(content)
        text_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        btn = wx.Button(panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        ime_guard.install(dialog)
        dialog.ShowModal()
        dialog.Destroy()




    def update_toolbar_for_module(self, module_name: str):
        """更新工具栏"""
        self.toolbar.ClearTools()
        
        if module_name == "clipboard":
            self.toolbar.AddTool(
                self.copy_btn_id,
                setting._('copy_btn'),
                wx.NullBitmap,
                setting._('copy_btn_tips')
            )

            self.toolbar.AddTool(
                self.edit_btn_id,
                setting._('edit_btn'),
                wx.NullBitmap,
                setting._('edit_btn_tips')
            )

            self.toolbar.AddTool(
                self.delete_btn_id,
                setting._('delete_btn'),
                wx.NullBitmap,
                setting._('delete_btn_tips')
            )

            self.toolbar.AddSeparator()

            if hasattr(self, '_clipboard_search_input') and self._clipboard_search_input:
                self._clipboard_search_input.Destroy()
            self._clipboard_search_input = wx.TextCtrl(self.toolbar, value=self._clipboard_filter_keyword, style=wx.TE_PROCESS_ENTER, size=(150, -1))
            self._clipboard_search_input.Bind(wx.EVT_TEXT, self.on_clipboard_search_text_changed)
            self._clipboard_search_input.Bind(wx.EVT_TEXT_ENTER, self.on_clipboard_search_enter)
            self.toolbar.AddControl(self._clipboard_search_input)

            self.Bind(wx.EVT_TOOL, self.on_copy_btn, id=self.copy_btn_id)
            self.Bind(wx.EVT_TOOL, self.on_edit_btn, id=self.edit_btn_id)
            self.Bind(wx.EVT_TOOL, self.on_delete_btn, id=self.delete_btn_id)

            self.toolbar.EnableTool(self.copy_btn_id, False)
            self.toolbar.EnableTool(self.edit_btn_id, False)
            self.toolbar.EnableTool(self.delete_btn_id, False)

        elif module_name == "translation":
            if hasattr(self, '_toolbar_source_choice') and self._toolbar_source_choice:
                self._toolbar_source_choice.Destroy()
            if hasattr(self, '_toolbar_target_choice') and self._toolbar_target_choice:
                self._toolbar_target_choice.Destroy()
            if hasattr(self, '_translation_mode_choice') and self._translation_mode_choice:
                self._translation_mode_choice.Destroy()
            
            source_display = setting.get_lang_display(self._source_lang)
            target_display = setting.get_lang_display(self._target_lang)
            
            source_label = wx.StaticText(self.toolbar, label=setting._('source_lang') + ':')
            self.toolbar.AddControl(source_label)
            
            self._toolbar_source_choice = wx.Choice(self.toolbar, choices=self.trans_source_options)
            self._toolbar_source_choice.SetStringSelection(source_display)
            self._toolbar_source_choice.Bind(wx.EVT_CHOICE, self.on_toolbar_source_lang_changed)
            self.toolbar.AddControl(self._toolbar_source_choice)
            
            target_label = wx.StaticText(self.toolbar, label=setting._('target_lang') + ':')
            self.toolbar.AddControl(target_label)
            
            self._toolbar_target_choice = wx.Choice(self.toolbar, choices=self.trans_target_options)
            self._toolbar_target_choice.SetStringSelection(target_display)
            self._toolbar_target_choice.Bind(wx.EVT_CHOICE, self.on_toolbar_target_lang_changed)
            self.toolbar.AddControl(self._toolbar_target_choice)
            
            mode_label = wx.StaticText(self.toolbar, label=setting._('trans_mode') + ':')
            self.toolbar.AddControl(mode_label)
            
            self._translation_mode_choice = wx.Choice(self.toolbar, choices=[setting._('mode_llm'), setting._('mode_apple')])
            is_internal = setting.is_internal_device()
            supports_apple = setting.supports_apple_translation()
            
            if self._translation_mode == 'apple':
                self._translation_mode_choice.SetStringSelection(setting._('mode_apple'))
            else:
                self._translation_mode_choice.SetStringSelection(setting._('mode_llm'))
            
            self._translation_mode_choice.Bind(wx.EVT_CHOICE, self.on_translation_mode_changed)

            if (is_internal and not setting.DEBUG_BUILD) or not supports_apple:
                self._translation_mode_choice.Enable(False)

            self.toolbar.AddControl(self._translation_mode_choice)

        elif module_name == "recognition":
            if hasattr(self, '_ocr_engine_choice') and self._ocr_engine_choice:
                self._ocr_engine_choice.Destroy()

            engine_label = wx.StaticText(self.toolbar, label=setting._('ocr_engine_label'))
            self.toolbar.AddControl(engine_label)

            from ocr_engine import engine_display
            self._ocr_engine_key_by_display = {
                engine_display(key): key for key in self._ocr_engine_keys
            }
            self._ocr_engine_choice = wx.Choice(self.toolbar, choices=list(self._ocr_engine_key_by_display))
            for display, key in self._ocr_engine_key_by_display.items():
                if key == self._ocr_mode:
                    self._ocr_engine_choice.SetStringSelection(display)
                    break
            self._ocr_engine_choice.Bind(wx.EVT_CHOICE, self.on_ocr_engine_changed)

            # 仅一个可用引擎时禁用切换（当前内部机/公开版均只有 Apple OCR）
            if len(self._ocr_engine_key_by_display) <= 1:
                self._ocr_engine_choice.Enable(False)

            self.toolbar.AddControl(self._ocr_engine_choice)

            self.toolbar.AddSeparator()

            self.toolbar.AddTool(
                self.browse_ocr_btn_id,
                setting._('browse_ocr_image'),
                wx.NullBitmap,
                setting._('browse_ocr_image_tips')
            )
            self.Bind(wx.EVT_TOOL, self.on_browse_ocr_image, id=self.browse_ocr_btn_id)

        self.toolbar.Realize()




    def on_nav_page_changed(self, event):
        """选项卡切换事件：切换内容模块 + 更新工具栏"""
        module_by_panel = {
            self.translation_panel: "translation",
            self.clipboard_panel: "clipboard",
            self.recognition_panel: "recognition",
            self.settings_panel: "settings",
        }
        page = self.notebook.GetPage(event.GetSelection())
        module_name = module_by_panel.get(page)
        if module_name:
            self.switch_to_module(module_name)
        event.Skip()


    def switch_to_module(self, module_name: str):
        """统一切换逻辑：更新选项卡选中页 + 工具栏 + 状态"""
        # 定位目标选项卡页（与 init_ui 中 AddPage 顺序一致）
        module_to_index = {
            "translation": 0,
            "clipboard": 1,
            "recognition": 2,
            "settings": 3,
        }
        page_index = module_to_index.get(module_name, 0)
        # ChangeSelection 仅切换页不触发事件，避免与 on_nav_page_changed 互相递归
        if self.notebook.GetSelection() != page_index:
            self.notebook.ChangeSelection(page_index)

        # 目标页面的原有初始化逻辑（焦点、列表刷新）
        if module_name == "translation":
            self.text_ctrl.SetFocus()
        elif module_name == "clipboard":
            self.refresh_list_box()  # 刷新剪贴板列表
            self.list_Box.SetFocus()
        elif module_name == "recognition":
            self.ocr_result_ctrl.SetFocus()

        # 切换到其他模块时清空搜索
        if module_name != "clipboard":
            self._clipboard_filter_keyword = ""
            self._clipboard_filtered_data = None

        # 更新状态与工具栏
        self.current_module = module_name
        self.update_toolbar_for_module(module_name)


    def load_clipboard_data(self):
        """加载外部剪贴板列表"""
        max_count = getattr(self, '_clipboard_max_count', 1000)
        self.clipboard_list_data = setting.load_clipboard_data(max_count)
        self._apply_clipboard_filter()
        self.refresh_list_box()


    def init_translator(self):
        """初始化翻译器"""
        is_internal = setting.is_internal_device()
        
        if self._translation_mode == 'apple':
            self._init_apple_translator(is_internal)
        else:
            self._init_llm_translator()
    
    def _init_apple_translator(self, is_internal: bool):
        """初始化 Apple 翻译器"""
        try:
            from apple_translator import AppleTranslator
            self.apple_translator = AppleTranslator()

            if self.apple_translator.is_available():
                self.text_ctrl.SetValue(self.apple_translator.get_readiness_message())
                self._check_apple_language_status_background()
            elif is_internal:
                # 内部机不回退 LLM：系统低于 macOS 26 或工具缺失时直接禁用翻译
                self.text_ctrl.SetValue(setting._('apple_translation_not_available'))
            else:
                self._translation_mode = 'llm'
                self._init_llm_translator()
                self._update_mode_choice_ui()
                self.save_config()
        except Exception as e:
            logging.warning(f"Apple翻译器初始化失败: {e}")
            if is_internal:
                self.text_ctrl.SetValue(setting._('apple_translation_not_available'))
            else:
                self._translation_mode = 'llm'
                self._init_llm_translator()
                self._update_mode_choice_ui()
                self.save_config()

    def _check_apple_language_status_background(self):
        """后台预检当前语言对的语言包状态，未安装/不支持时给出引导提示"""
        source_lang, target_lang = self._source_lang, self._target_lang

        def status_worker():
            try:
                hint = self.apple_translator.get_language_hint(source_lang, target_lang)
            except Exception as e:
                logging.warning(f"Apple 翻译语言状态预检失败: {e}")
                return
            if hint:
                wx.CallAfter(self.text_ctrl.SetValue, hint)
                wx.CallAfter(self.vo_handler.speak_text, hint)

        threading.Thread(target=status_worker, daemon=True).start()
    
    def _update_mode_choice_ui(self):
        """更新翻译模式选择 UI"""
        if hasattr(self, '_translation_mode_choice') and self._translation_mode_choice:
            mode_display = setting._('mode_apple') if self._translation_mode == 'apple' else setting._('mode_llm')
            self._translation_mode_choice.SetStringSelection(mode_display)
    
    def _init_llm_translator(self):
        """初始化 LLM 翻译器"""
        try:
            self.translator = Translator(
                log_level=logging.INFO,
                loop_interval=0.1
            )
            model_path = getattr(self, '_model_path', '') or ''
            if model_path and os.path.exists(model_path):
                self.translator.load_model(model_path)
                if hasattr(self, 'model_path_text'):
                    self.model_path_text.SetValue(model_path)
        except Exception as e:
            logging.warning(f"翻译器初始化: {str(e)}")
            self.translator = Translator(
                log_level=logging.INFO,
                loop_interval=0.1
            )
        
        if not self.translator or self.translator.model_available == False:
            self.text_ctrl.SetValue(setting._('model_warning'))


    def register_hotkeys(self):
        """注册热键"""
        #  注销热键
        for hid in self.hotkey_ids.values():
            self.UnregisterHotKey(hid)
        self.hotkey_ids.clear()

        #  修饰键映射表（将字符串转换为wx对应的常量）
        modifier_map = {
            "ALT": wx.MOD_ALT,
            "SHIFT": wx.MOD_SHIFT,
            "CTRL": wx.MOD_CONTROL,
            "CMD": wx.MOD_CMD
        }

        #  遍历keys列表批量注册热键
        for hotkey in setting.hotKeys:
            try:
                # 解析修饰键
                modifiers = 0
                for mod in hotkey["modifiers"]:
                    modifiers |= modifier_map[mod]  # 按位或运算组合修饰键

                # 解析按键
                key_code = ord(hotkey["key"]) 

                # 生成唯一ID并注册热键
                hk_id = wx.NewIdRef()
                self.RegisterHotKey(hk_id, modifiers, key_code)
                self.hotkey_ids[hotkey["name"]] = hk_id

                # 绑定事件处理器（通过字符串获取类中的方法）
                handler = getattr(self, hotkey["handler"], None)
                if handler:
                    self.Bind(wx.EVT_HOTKEY, handler, id=hk_id)
                else:
                    logging.warning(f"热键'{hotkey['name']}'的处理器'{hotkey['handler']}'未定义")

            except Exception as e:
                logging.error(f"注册热键'{hotkey['name']}'失败: {str(e)}")


    def refresh_list_box(self):
        """刷新列表数据：仅加载原始文本，原生复选框自动显示勾选状态"""
        display_data = self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data
        self.list_Box.Clear()
        for item in display_data:
            if len(item) > 100:
                display_text = f"{item[:100]} ~~"
            else:
                display_text = item
            self.list_Box.Append(display_text)

    def _apply_clipboard_filter(self):
        """应用搜索筛选"""
        self._clipboard_filtered_data = setting.filter_clipboard_records(
            self.clipboard_list_data, 
            self._clipboard_filter_keyword
        )

    def _get_display_data(self):
        """获取当前显示的数据（筛选数据或原始数据）"""
        return self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data


    def update_clipboard_buttons_state(self):
        """更新剪贴板按钮状态：基于勾选项判断"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        has_select = len(checked_indices) > 0
        self.toolbar.EnableTool(self.copy_btn_id, has_select)
        self.toolbar.EnableTool(self.edit_btn_id, has_select)
        self.toolbar.EnableTool(self.delete_btn_id, has_select)


    def add_clipboard_content(self, content: str):
        """
        通用剪贴板内容添加方法：自动删除旧重复项，插入新内容到开头，刷新UI并保存
        :param content: 要添加的剪贴板内容
        """
        if not content:  # 空内容不处理
            return
        
        max_count = getattr(self, '_clipboard_max_count', 1000)
        
        #  倒序删除重复项
        indices_to_remove = [i for i, item in enumerate(self.clipboard_list_data) if item == content]
        for i in reversed(indices_to_remove):
            del self.clipboard_list_data[i]
        
        #  插入到开头
        self.clipboard_list_data.insert(0, content)
        
        #  超过最大数量时删除最旧的记录
        if len(self.clipboard_list_data) > max_count:
            self.clipboard_list_data = self.clipboard_list_data[:max_count]
        
        self._apply_clipboard_filter()
        
        #  刷新UI
        if self.current_module == "clipboard":
            self.refresh_list_box()
            self.list_Box.SetSelection(0)  # 选中新添加的项
            self.update_clipboard_buttons_state()
        
        #  持久化数据
        self.save_clipboard_data()


    def on_copy_btn(self, event):
        """拷贝勾选的项到剪贴板：多选拼接"""
        # 获取所有勾选项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return
        
        # 获取显示数据
        display_data = self._get_display_data()
        
        # 拼接
        content_list = [display_data[idx] for idx in checked_indices]
        content = "\n".join(content_list)
        
        # 复制到系统剪贴板
        clipboard = wx.Clipboard()
        clipboard.Open()
        clipboard.SetData(wx.TextDataObject(content))
        clipboard.Close()

        # 仅单选时删除原项（从原始数据中删除匹配项）
        if len(checked_indices) == 1:
            idx = checked_indices[0]
            if 0 <= idx < len(display_data):
                content_to_delete = display_data[idx]
                # 在原始数据中找到并删除
                for i, item in enumerate(self.clipboard_list_data):
                    if item == content_to_delete:
                        del self.clipboard_list_data[i]
                        break
                self._apply_clipboard_filter()
                self.refresh_list_box()


    def on_delete_btn(self, event):
        """删除勾选的项"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return

        # 确认删除
        if wx.MessageBox(setting._('delete_btn_tips'), setting._('confirm_btn'), wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return

        # 获取显示数据
        display_data = self._get_display_data()
        
        # 收集要删除的内容
        contents_to_delete = [display_data[idx] for idx in sorted(checked_indices) if 0 <= idx < len(display_data)]
        
        # 从原始数据中删除匹配项
        for content in contents_to_delete:
            for i, item in enumerate(self.clipboard_list_data):
                if item == content:
                    del self.clipboard_list_data[i]
                    break

        # 重新应用筛选
        self._apply_clipboard_filter()
        
        # 刷新
        self.refresh_list_box()
        self.update_clipboard_buttons_state()
        # 同步系统剪贴板
        if self.clipboard_list_data:
            clipboard = wx.Clipboard()
            clipboard.Open()
            clipboard.SetData(wx.TextDataObject(self.clipboard_list_data[0]))
            clipboard.Close()
        self.save_clipboard_data()


    def on_edit_btn(self, event):
        """编辑勾选的项：仅支持单个勾选项"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return
        
        # 多选时提示仅编辑第一个
        if len(checked_indices) > 1:
            wx.MessageBox(setting._("edit_single_item_tips"), setting._("notice"), wx.OK | wx.ICON_INFORMATION)
            return

        # 获取显示数据
        display_data = self._get_display_data()
        
        idx = checked_indices[0]
        if idx >= len(display_data):
            return
            
        init_content = display_data[idx]
        
        # 打开编辑窗口
        dialog = EditDialog(
            self, setting._('editor_title'),
            init_content)
        if dialog.ShowModal() == wx.ID_OK:
            new_content = dialog.get_result()
            
            # 在原始数据中找到并更新
            for i, item in enumerate(self.clipboard_list_data):
                if item == init_content:
                    if not new_content:
                        del self.clipboard_list_data[i]
                    else:
                        self.clipboard_list_data[i] = new_content
                    break
            
            # 重新应用筛选
            self._apply_clipboard_filter()
            
            # 刷新
            self.refresh_list_box()
            self.update_clipboard_buttons_state()
            # 同步系统剪贴板
            if self.clipboard_list_data:
                clipboard = wx.Clipboard()
                clipboard.Open()
                clipboard.SetData(wx.TextDataObject(self.clipboard_list_data[0]))
                clipboard.Close()

        dialog.Destroy()
        self.save_clipboard_data()


    def on_list_key_down(self, event):
        """列表键盘事件：基于勾选项处理"""
        key = event.GetKeyCode()
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            event.Skip()
            return

        if key == wx.WXK_DELETE:
            self.on_delete_btn(None)
        elif key == wx.WXK_RETURN:
            self.on_copy_btn(None)
        elif key == wx.WXK_F2:
            if len(checked_indices) == 1:
                self.on_edit_btn(None)
            else:
                wx.MessageBox(setting._("edit_single_item_tips"), setting._("notice"), wx.OK | wx.ICON_INFORMATION)
        else:
            event.Skip()


    def on_list_item_selected(self, event):
        """列表项选中"""
        #  获取当前选中的索引
        selected_idx = event.GetSelection()
        self.current_clipboard_idx = selected_idx  # 同步索引
        
        #  加载文本到TextBrowser
        display_data = self._get_display_data()
        if selected_idx != -1 and 0 <= selected_idx < len(display_data):
            selected_content = display_data[selected_idx]
            self.TB.set_text(selected_content) 

        self.update_clipboard_buttons_state()


    def on_list_item_checked(self, event):
        """复选框勾选/取消勾选"""
        self.update_clipboard_buttons_state()


    def on_list_item_deselected(self, event):
        """列表项取消选中：禁用按钮"""
        self.update_clipboard_buttons_state()


    def on_hotkey_altc(self, event):
        """alt+C: 当前字符解释"""
        last_phrase = self.vo_handler.get_last_phrase()
        if last_phrase:
            vo_text, _ = last_phrase
            explained_text = self.TB.get_char_explanation(vo_text)
            # 若解释存在（与原文本不同），则使用解释结果；否则用原文本
            if explained_text != vo_text:
                self.vo_handler.speak_text(explained_text)
                return

            # 注：保持取首字符的既有行为（与 _translate_last_phrase 传整串不一致，疑似历史遗留）
            result_text = self._lookup_dictionary(vo_text[0])
            # 词典未命中时回退朗读原字符，避免 speak_text(None) 静默无反馈
            self.vo_handler.speak_text(result_text or vo_text[0])


    def on_hotkey_altd(self, event):
        """Alt+D：英译中"""
        if event.GetId() != self.hotkey_ids["altd"]:
            return
        self._translate_last_phrase(self._source_lang, self._target_lang)


    def on_hotkey_altshiftd(self, event):
        """Alt+Shift+D：中译英"""

        if event.GetId() != self.hotkey_ids["altshiftd"]:
            return

        self._translate_last_phrase(self._target_lang, self._source_lang)

    def _translate_last_phrase(self, source_lang: str, target_lang: str):
        """Translate the last VoiceOver phrase using the selected backend."""
        last_phrase = self.vo_handler.get_last_phrase()
        if not last_phrase:
            self.vo_handler.speak_text(setting._('vo_warning'))
            return
        vo_text, _ = last_phrase
        explained_text = self.TB.get_char_explanation(vo_text)
        if explained_text != vo_text:
            self.vo_handler.speak_text(explained_text)
            return
        dictionary_result = self._lookup_dictionary(vo_text)
        if dictionary_result:
            self.vo_handler.speak_text(dictionary_result)
            return
        if not self._translation_lock.acquire(blocking=False):
            self.vo_handler.speak_text(setting._('translation_in_progress'))
            return
        if self._translation_mode == 'llm' and (not self.translator or not self.translator.model_available):
            model_path = getattr(self, '_model_path', '') or ''
            # 模型可能因视觉识别被卸载：配置路径仍有效时放行，由翻译线程重新加载
            if not (model_path and os.path.exists(model_path)):
                self._translation_lock.release()
                self.vo_handler.speak_text(setting._("model_unavailable"))
                return

        def translate_worker():
            try:
                result = self._do_translate(vo_text, source_lang, target_lang)
                wx.CallAfter(
                    self.vo_handler.speak_text,
                    result or setting._("translation_failed")
                )
            except Exception as e:
                logging.warning(f"翻译失败: {e}")
                wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            finally:
                self._translation_lock.release()

        threading.Thread(target=translate_worker, daemon=True).start()


    def on_hotkey_altt(self, event):
        """Alt+T：剪贴板编辑器"""
        if self.edit_dialog:
            return
        try:
            app = NSApp()
            # 强制激活当前应用
            app.activateIgnoringOtherApps_(True)
        except Exception as e:
            logging.error(f"激活应用失败: {str(e)}")
        #  读取系统剪贴板
        clipboard = wx.Clipboard()
        init_content = ""
        if clipboard.Open():
            # 获取文本
            text_data = wx.TextDataObject()
            if clipboard.GetData(text_data):
                init_content = text_data.GetText()
            clipboard.Close()

        self.edit_dialog = EditDialog(self, setting._("editor_title"), 
            init_content, cursor_pos=self.TB.focus_pos)
        self.Enable(False)
        result = self.edit_dialog.ShowModal()
        self.Enable(True)
        if result == wx.ID_OK:
            new_content = self.edit_dialog.get_result()
            if self.clipboard_list_data:
                del self.clipboard_list_data[0]
            if new_content:
                self.clipboard_list_data.insert(0, new_content)
                clipboard.Open()
                clipboard.SetData(wx.TextDataObject(new_content))
                clipboard.Close()
                self.refresh_list_box()
            elif self.clipboard_list_data:
                clipboard = wx.Clipboard()
                clipboard.Open()
                clipboard.SetData(wx.TextDataObject(self.clipboard_list_data[0]))
                clipboard.Close()
            else:
                clipboard.Open()
                clipboard.SetData(wx.TextDataObject(''))
                clipboard.Close()
        self.edit_dialog.Destroy()
        self.save_clipboard_data()
        self.refresh_list_box()
        self.system_level_hide_window(self)


    def on_hotkey_alta(self, event):
        """列表第一项追加VO内容（加换行）"""
        if event.GetId() != self.hotkey_ids["alta"]:
            return

        # 获取VO文本
        last_phrase = self.vo_handler.get_last_phrase()
        if not last_phrase:
            return
        vo_text, _ = last_phrase
        if not vo_text.strip():
            return

        if not self.clipboard_list_data:
            if not (self.clipboard_list_data and self.clipboard_list_data[0] == vo_text):
                self.clipboard_list_data.insert(0, vo_text)
                if self.current_module == "clipboard":
                    self.refresh_list_box()
                    self.update_clipboard_buttons_state()
                    self.save_clipboard_data()
            return

        # 列表非空，追加
        first_item = self.clipboard_list_data[0]
        if first_item.endswith(f"\n{vo_text}") or first_item == vo_text:
            return

        self.clipboard_list_data[0] = f"{first_item}\n{vo_text}"
        if self.current_module == "clipboard":
            self.refresh_list_box()
            self.list_Box.SetSelection(0)
        clipboard = wx.Clipboard()
        clipboard.Open()
        clipboard.SetData(wx.TextDataObject(self.clipboard_list_data[0]))
        clipboard.Close()
        self.save_clipboard_data()


    def on_hotkey_altshift7(self, event):
        """alt+shift+7: 剪贴板列表上一条"""
        display_data = self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data
        if not display_data:
            if hasattr(self, 'list_Box') and self.list_Box and self.current_module == 'clipboard':
                self.list_Box.SetSelection(-1)
            self.current_clipboard_idx = -1
            return

        total_count = len(display_data)
        current_idx = self.current_clipboard_idx

        if current_idx == -1 or current_idx == 0:
            new_idx = total_count - 1
        else:
            new_idx = current_idx - 1

        self.current_clipboard_idx = new_idx

        selected_content = display_data[new_idx]
        print(f"切换到索引 {new_idx}，内容：{selected_content[:20]}...")
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(new_idx)
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content[:1024]}")
        self.update_clipboard_buttons_state()

        self.TB.set_text(selected_content)
        self.TB.browse("prev_line")

        # 单步切换后开始长按监测，按住不放则快速跳到列表第一项
        self._start_long_press("altshift7")


    def on_hotkey_altshift8(self, event):
        """alt+shift+8: 当前剪贴板上一行"""
        result_text = self.TB.browse("prev_line")
        # markdown标题行（# 数字）在井号右侧补句点后朗读，仅作用于朗读拼接、不改原数据
        self.vo_handler.speak_text(insert_heading_dot(result_text))
        # 单步移动后开始长按监测，按住不放则快速跳到第一行
        self._start_long_press("altshift8")


    def on_hotkey_altshift9(self, event):
        """alt+shift+9: 剪贴板列表下一条"""
        display_data = self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data
        if not display_data:
            if hasattr(self, 'list_Box') and self.list_Box and self.current_module == 'clipboard':
                self.list_Box.SetSelection(-1)
            self.current_clipboard_idx = -1
            return

        total_count = len(display_data)
        current_idx = self.current_clipboard_idx

        if current_idx == -1 or current_idx >= total_count - 1:
            new_idx = 0
        else:
            new_idx = current_idx + 1

        self.current_clipboard_idx = new_idx
        selected_content = display_data[new_idx]
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(new_idx)
        
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content[:1024]}")
        self.TB.set_text(selected_content)
        self.TB.browse("prev_line")
        # 单步切换后开始长按监测，按住不放则快速跳到列表最后一项
        self._start_long_press("altshift9")


    def on_hotkey_altshiftu(self, event):
        """alt+shift+u: 当前剪贴板前一个字"""
        result_text = self.TB.browse("prev_char")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshifti(self, event):
        """alt+shift+i: 当前字符解释"""
        # browse 返回值已含符号库解释（含未收录符号的 unicodedata 兜底），与焦点原字符比对判断是否命中
        focus_pos = self.TB.focus_pos
        raw_char = self.TB.current_text[focus_pos:focus_pos + 1]
        result_text = self.TB.browse("explain_char")

        if result_text and result_text != raw_char:
            self.vo_handler.speak_text(result_text)
            return

        # 未命中解释（字母数字等旁白可直接朗读的字符）：走词典，查无词条时回退朗读原字符
        if result_text:
            dictionary_result = self._lookup_dictionary(result_text[0])
            self.vo_handler.speak_text(dictionary_result or result_text)


    def on_hotkey_altshifto(self, event):
        """alt+shift+o: 当前剪贴板后一个字"""
        result_text = self.TB.browse("next_char")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshiftj(self, event):
        """alt+shift+j: 剪贴板列表内容设置到系统"""
        display_data = self._get_display_data()
        if not display_data or self.current_clipboard_idx < 0 or self.current_clipboard_idx >= len(display_data):
            return
        
        # 目标文本
        target_text = display_data[self.current_clipboard_idx]
        
        #  对比
        current_clipboard_text = ""
        clipboard_check = wx.Clipboard()
        try:
            if clipboard_check.Open():
                data = wx.TextDataObject()
                if clipboard_check.GetData(data):
                    current_clipboard_text = data.GetText()
        except Exception as e:
            print(f"读取系统剪贴板失败：{e}")
        finally:
            if clipboard_check.IsOpened():
                clipboard_check.Close()
        

        if current_clipboard_text == target_text:
            return
        
        # 置剪贴板
        clipboard = wx.Clipboard()
        try:
            if not clipboard.Open():
                return
            
            clipboard.SetData(wx.TextDataObject(target_text))
        except Exception as e:
            wx.MessageBox(f"{setting._('set_clipboard_failed')}: {str(e)}", setting._("error"), wx.OK | wx.ICON_ERROR)
        finally:
            if clipboard.IsOpened():
                clipboard.Close()
        

        # 从原始数据中删除匹配项
        for i, item in enumerate(self.clipboard_list_data):
            if item == target_text:
                del self.clipboard_list_data[i]
                break
        
        # 重新应用筛选
        self._apply_clipboard_filter()
        
        # 校准current_clipboard_idx
        display_data = self._get_display_data()
        if not display_data:
            self.current_clipboard_idx = -1
        elif self.current_clipboard_idx >= len(display_data):
            self.current_clipboard_idx = len(display_data) - 1

        
        self.refresh_list_box()


    def on_hotkey_altshiftk(self, event):
        """alt+shift+k: 当前剪贴板下一行"""
        result_text = self.TB.browse("next_line")
        self.vo_handler.speak_text(insert_heading_dot(result_text))
        # 单步移动后开始长按监测，按住不放则快速跳到最后一行
        self._start_long_press("altshiftk")


    def play_sound(self, name: str) -> None:
        """播放 resources/sound 下的提示音（异步，不阻塞界面）"""
        try:
            sound = self._sounds.get(name)
            if sound is None:
                sound_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "resources", "sound", f"{name}.wav")
                sound = wx.adv.Sound(sound_path)
                if not sound.IsOk():
                    logging.warning(f"提示音文件不可用: {sound_path}")
                    return
                self._sounds[name] = sound
            sound.Play(wx.adv.SOUND_ASYNC)
        except Exception as e:
            logging.warning(f"播放提示音'{name}'失败: {e}")


    def _start_long_press(self, name: str) -> None:
        """虚拟浏览器方向键单步执行后开始长按监测（依赖 macOS Quartz 查询物理键状态）"""
        spec = self.LONG_PRESS_KEYS.get(name)
        if not spec:
            return
        try:
            import Quartz
        except Exception:
            return  # 非 macOS 环境无 Quartz，跳过长按监测
        self._long_press_start = time.monotonic()
        self._long_press_keycode = spec[0]
        self._long_press_action = getattr(self, spec[1])
        self._long_press_timer.Start(self.LONG_PRESS_POLL_MS)


    def _on_long_press_timer(self, event):
        """长按监测：按住超过阈值触发跳转，提前松开则结束监测"""
        if self._long_press_action is None:
            self._long_press_timer.Stop()
            return
        import Quartz
        key_down = Quartz.CGEventSourceKeyState(
            Quartz.kCGEventSourceStateCombinedSessionState, self._long_press_keycode)
        if not key_down:
            self._long_press_timer.Stop()
            self._long_press_action = None
        elif time.monotonic() - self._long_press_start >= self.LONG_PRESS_THRESHOLD:
            self._long_press_timer.Stop()
            action = self._long_press_action
            self._long_press_action = None
            action()


    def _jump_clipboard_head(self):
        """长按 alt+shift+7: 直接跳到剪贴板列表第一项"""
        display_data = self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data
        if not display_data:
            return
        self.current_clipboard_idx = 0
        selected_content = display_data[0]
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(0)
        self.update_clipboard_buttons_state()
        self.TB.set_text(selected_content)
        self.TB.browse("first_line")
        self.play_sound("index")
        self.vo_handler.speak_text(f"1, {selected_content[:1024]}")


    def _jump_clipboard_tail(self):
        """长按 alt+shift+9: 直接跳到剪贴板列表最后一项"""
        display_data = self._clipboard_filtered_data if self._clipboard_filtered_data is not None else self.clipboard_list_data
        if not display_data:
            return
        new_idx = len(display_data) - 1
        self.current_clipboard_idx = new_idx
        selected_content = display_data[new_idx]
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(new_idx)
        self.update_clipboard_buttons_state()
        self.TB.set_text(selected_content)
        self.TB.browse("first_line")
        self.play_sound("index")
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content[:1024]}")


    def _jump_text_first_line(self):
        """长按 alt+shift+8: 直接跳到当前剪贴板第一行"""
        result_text = self.TB.browse("first_line")
        self.play_sound("index")
        self.vo_handler.speak_text(insert_heading_dot(result_text))


    def _jump_text_last_line(self):
        """长按 alt+shift+k: 直接跳到当前剪贴板最后一行"""
        result_text = self.TB.browse("last_line")
        self.play_sound("index")
        self.vo_handler.speak_text(insert_heading_dot(result_text))


    def on_hotkey_altshiftm(self, event):
        """alt+shift+m: 剪贴板综述"""
        row_column = self.TB._row_column
        total_chars = self.TB._total_chars
        total_lines = len(self.TB.current_text.split('\n'))
        if row_column:
            row_label = setting._('row')
            col_label = setting._('column')
            total_lines_label = setting._('total_lines')
            total_chars_label = setting._('total_chars')
            print(f'当前语言{setting.current_lang}')
            self.vo_handler.speak_text(
                f"{row_column[0]} {row_label}; {row_column[1]} {col_label}; {total_lines_label}{total_lines} {row_label}; {total_chars}{total_chars_label}"
            )


    def on_hotkey_altshiftp(self, event):
        """alt+shift+p: 粘贴剪贴板当前行到前台应用输入框"""
        result_text = self.TB._current_line
        if not result_text:
            return

        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

            # 辅助功能权限预检：未授权时弹出系统授权窗口并播报提示
            if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
                logging.warning("粘贴失败：未授予辅助功能权限")
                self.vo_handler.speak_text("需要辅助功能权限，请在系统设置中授权后重试")
                return

            pasteboard = NSPasteboard.generalPasteboard()

            # 仅在无待还原任务时保存原剪贴板，避免把上一次粘贴的行误存为原始内容
            restore_pending = self._paste_restore_timer is not None and self._paste_restore_timer.IsRunning()
            if not restore_pending:
                original = pasteboard.stringForType_(NSPasteboardTypeString)
                self._paste_original_clipboard = str(original) if original else None

            self._is_pasting = True
            pasteboard.clearContents()
            pasteboard.setString_forType_(result_text, 'public.utf8-plain-text')

            # 延时合成按键：等待物理修饰键（Option/Shift）松开，且不阻塞 UI 线程
            wx.CallLater(100, self._post_paste_keystroke)

            # 还原计时器：连续触发时重置，从最后一次粘贴算起 1 秒后才还原剪贴板
            if restore_pending:
                self._paste_restore_timer.Stop()
            self._paste_restore_timer = wx.CallLater(1000, self._restore_clipboard_after_paste)
        except Exception as e:
            logging.warning(f"粘贴失败: {e}")
            self._is_pasting = False


    def _post_paste_keystroke(self):
        """向前台应用合成 Cmd+V（Quartz 优先，osascript 兜底）"""
        try:
            import Quartz

            v_keycode = 9  # kVK_ANSI_V
            for key_down in (True, False):
                key_event = Quartz.CGEventCreateKeyboardEvent(None, v_keycode, key_down)
                # 显式只设 Command 标志，覆盖仍被按住的物理修饰键（Option/Shift）
                Quartz.CGEventSetFlags(key_event, Quartz.kCGEventFlagMaskCommand)
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, key_event)
        except Exception as e:
            logging.warning(f"Quartz 合成 Cmd+V 失败，回退 osascript: {e}")
            script = 'delay 0.1\ntell application "System Events" to keystroke "v" using command down'
            try:
                proc = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
                if proc.returncode != 0:
                    logging.error(f"osascript 粘贴失败: {proc.stderr.strip()}")
            except Exception as fallback_error:
                logging.error(f"osascript 调用失败: {fallback_error}")


    def _restore_clipboard_after_paste(self):
        """延时还原系统剪贴板为粘贴前的内容"""
        try:
            from AppKit import NSPasteboard

            pasteboard = NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            original = self._paste_original_clipboard
            if original:
                pasteboard.setString_forType_(original, 'public.utf8-plain-text')
            self._paste_original_clipboard = None
            self._is_pasting = False
        except Exception as e:
            logging.warning(f"还原剪贴板失败: {e}")
            self._is_pasting = False


    def init_ocr_engine(self):
        """按当前 OCR 模式初始化引擎；本地视觉模型复用缓存实例，避免切换往返时重复加载模型"""
        try:
            from ocr_engine import create_engine
            config = {}
            if self._ocr_mode == 'vlm':
                config = {
                    'model_path': getattr(self, '_ocr_model_path', ''),
                    'mmproj_path': getattr(self, '_ocr_mmproj_path', ''),
                }
            cached = self._ocr_engine_cache.get(self._ocr_mode)
            if cached is not None:
                cached.configure(**config)
                self.ocr_engine = cached
            else:
                self.ocr_engine = create_engine(self._ocr_mode, **config)
                self._ocr_engine_cache[self._ocr_mode] = self.ocr_engine
        except Exception as e:
            logging.warning(f"OCR 引擎初始化失败: {e}")
            self.ocr_engine = None

    def on_ocr_engine_changed(self, event):
        """工具栏切换 OCR 引擎"""
        if hasattr(self, '_ocr_engine_choice') and self._ocr_engine_choice:
            display_text = self._ocr_engine_choice.GetStringSelection()
            engine_key = self._ocr_engine_key_by_display.get(display_text)
            if engine_key and engine_key != self._ocr_mode:
                self._ocr_mode = engine_key
                self.save_config()
                self.init_ocr_engine()

    def on_hotkey_altshiftq(self, event):
        """alt+shift+q: 循环切换识别引擎（当前两引擎间往返）"""
        self.switch_ocr_engine(1)

    def switch_ocr_engine(self, step: int):
        """在虚拟引擎列表中循环切换识别引擎，切换后经 VO 播报引擎名反馈"""
        from ocr_engine import engine_display, next_engine_key

        if not self._ocr_engine_keys:
            return
        new_key = next_engine_key(self._ocr_engine_keys, self._ocr_mode, step)
        if new_key != self._ocr_mode:
            self._ocr_mode = new_key
            self.save_config()
            self.init_ocr_engine()
            if hasattr(self, '_ocr_engine_choice') and self._ocr_engine_choice:
                self._ocr_engine_choice.SetStringSelection(engine_display(new_key))
        # TTS 反馈：循环回原引擎同样播报，确认按键已生效
        self.vo_handler.speak_text(engine_display(new_key))
        self._preload_ocr_engine()

    def _preload_ocr_engine(self):
        """本地视觉模型已配置未加载时后台预加载，完成后播报就绪"""
        engine = self.ocr_engine
        is_configured = getattr(engine, "is_configured", None)
        is_loaded = getattr(engine, "is_loaded", None)
        if not (callable(is_configured) and callable(is_loaded)):
            return
        if not is_configured() or is_loaded():
            return

        def preload_worker():
            try:
                engine.load_model()
            except Exception as e:
                # 预加载失败立即播报具体原因（模型文件/llama_cpp 环境问题），不静默等识别时才发现
                logging.warning(f"视觉模型预加载失败: {e}")
                wx.CallAfter(self.vo_handler.speak_text, str(e))
                return
            wx.CallAfter(self.vo_handler.speak_text, setting._('ocr_vlm_ready'))

        threading.Thread(target=preload_worker, daemon=True).start()

    def on_hotkey_altshiftt(self, event):
        """alt+shift+t: 循环切换翻译引擎（当前两引擎间往返）"""
        self.switch_translation_engine(1)

    def switch_translation_engine(self, step: int):
        """在翻译引擎（apple/llm）间循环切换，切换后经 VO 播报引擎名反馈"""
        if setting.is_internal_locked():
            # 内部机生产版锁定 Apple：不切换不写配置，播报当前引擎确认按键生效
            self.vo_handler.speak_text(setting._('mode_apple'))
            return
        if not setting.supports_apple_translation():
            # Apple 翻译不可用、仅 llm 可选：不切换，播报当前引擎确认按键生效
            self.vo_handler.speak_text(setting._('mode_llm'))
            return
        modes = ["apple", "llm"]
        if self._translation_mode not in modes:
            self._translation_mode = modes[0]
        new_mode = modes[(modes.index(self._translation_mode) + step) % len(modes)]
        if new_mode != self._translation_mode:
            self._translation_mode = new_mode
            self.save_config()
            self._update_translator_for_mode()
            mode_display = setting._('mode_apple') if self._translation_mode == 'apple' else setting._('mode_llm')
            if hasattr(self, '_translation_mode_choice') and self._translation_mode_choice:
                self._translation_mode_choice.SetStringSelection(mode_display)
        # TTS 反馈：循环回原引擎同样播报，确认按键已生效；Apple 初始化失败回退时播报实际引擎
        self.vo_handler.speak_text(setting._('mode_apple') if self._translation_mode == 'apple' else setting._('mode_llm'))

    def on_hotkey_altshifte(self, event):
        """alt+shift+e: 提取VO最后朗读内容中的URL并用默认浏览器打开，多个时弹窗选择"""
        spoken_text = self.vo_handler.get_last_spoken_text()
        urls = extract_urls(spoken_text)
        if not urls:
            self.vo_handler.speak_text(setting._('no_url_found'))
            return
        # 单个直接打开，多个弹窗让用户选择；取消或未选中则不打开
        url = urls[0]
        if len(urls) > 1:
            dialog = UrlSelectDialog(self, urls)
            result = dialog.ShowModal()
            url = dialog.get_selected() if result == wx.ID_OK else None
            dialog.Destroy()
            if not url:
                return
        import webbrowser
        webbrowser.open(url)

    def on_hotkey_altshiftr(self, event):
        """alt+shift+r: 识别剪贴板中的图片（OCR），结果回写识别面板并朗读"""
        try:
            from ocr_engine import extract_clipboard_image
            extracted = extract_clipboard_image()
        except Exception as e:
            logging.warning(f"读取剪贴板图片失败: {e}")
            extracted = None

        if not extracted:
            self.vo_handler.speak_text(setting._('ocr_no_image'))
            return

        image_path, is_temp = extracted
        self.run_ocr(image_path, temp_path=image_path if is_temp else None)

    def _hotkey_name_of(self, event) -> str:
        """通过事件ID反查热键名称，供通用热键处理器区分具体按键"""
        for name, hid in self.hotkey_ids.items():
            if hid == event.GetId():
                return name
        return ""

    def _current_app_id(self) -> str:
        """获取前台应用的持久化标识：bundle ID 优先，无 bundle 时退回可执行文件路径或应用名"""
        try:
            from AppKit import NSWorkspace
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if app:
                bundle_id = app.bundleIdentifier()
                if bundle_id:
                    return str(bundle_id)
                executable = app.executableURL()
                if executable and executable.path():
                    return str(executable.path())
                if app.localizedName():
                    return str(app.localizedName())
        except Exception as e:
            logging.warning(f"获取前台应用标识失败: {e}")
        return "unknown"

    def _get_mouse_position(self):
        """读取当前鼠标全局坐标（Quartz 左上原点），失败返回 None"""
        try:
            import Quartz
            location = Quartz.CGEventCreate(None).location
            return float(location.x), float(location.y)
        except Exception as e:
            logging.error(f"读取鼠标坐标失败: {e}")
        return None

    def _move_mouse_to(self, x, y) -> bool:
        """将鼠标指针移动到全局坐标 (x, y)"""
        try:
            import Quartz
            # pyobjc 不把非零 CGError 转成异常，必须显式判断返回值（0 为 kCGErrorSuccess）
            return Quartz.CGWarpMouseCursorPosition((x, y)) == 0
        except Exception as e:
            logging.error(f"移动鼠标失败: {e}")
        return False

    @staticmethod
    def _format_landmark_pos(position) -> str:
        """路标坐标播报：直接朗读整数坐标，不做冗余修饰"""
        return f"{int(round(position[0]))}, {int(round(position[1]))}"

    def on_hotkey_mouse_mark(self, event):
        """opt+shift+数字: 将当前鼠标位置标记为当前应用的路标槽位"""
        slot = self._hotkey_name_of(event).replace("mark_", "")
        if not slot:
            return
        position = self._get_mouse_position()
        if position is None:
            self.vo_handler.speak_text("读取鼠标坐标失败")
            return
        if not setting.set_mouse_landmark(self._current_app_id(), slot, position[0], position[1]):
            self.vo_handler.speak_text("保存失败")
            return
        self.vo_handler.speak_text(self._format_landmark_pos(position))

    def on_hotkey_mouse_jump(self, event):
        """cmd+opt+shift+数字: 将鼠标跳转到当前应用对应槽位标记的位置"""
        slot = self._hotkey_name_of(event).replace("jump_", "")
        if not slot:
            return
        position = setting.get_mouse_landmark(self._current_app_id(), slot)
        if position is None:
            self.vo_handler.speak_text("未标记")
            return
        if not self._move_mouse_to(position[0], position[1]):
            self.vo_handler.speak_text("跳转失败")
            return
        self.vo_handler.speak_text(self._format_landmark_pos(position))

    def on_browse_ocr_image(self, event):
        """工具栏浏览图片文件并识别"""
        wildcard = ("Image Files (*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.heic;*.bmp;*.gif;*.webp)"
                    "|*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.heic;*.bmp;*.gif;*.webp"
                    "|All Files (*.*)|*.*")
        dialog = wx.FileDialog(
            self,
            message=setting._("ocr_select_image"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST
        )

        if dialog.ShowModal() == wx.ID_OK:
            image_path = dialog.GetPath()
            dialog.Destroy()
            self.run_ocr(image_path)
        else:
            dialog.Destroy()

    def _unload_llm_for_vlm_ocr(self):
        """视觉模型识别内存开销大：VLM 识别触发时异步卸载已加载的翻译模型腾出统一内存

        卸载在后台线程执行（模型与推理互斥，翻译进行中会等待完成后再卸载）；
        下次翻译时由 _do_translate 按配置路径自动重新加载
        """
        if self._ocr_mode != 'vlm':
            return
        translator = getattr(self, 'translator', None)
        if not translator or not translator.model_available:
            return

        def unload_worker():
            try:
                translator.unload_model()
            except Exception as e:
                logging.warning(f"卸载翻译模型失败: {e}")

        threading.Thread(target=unload_worker, daemon=True).start()

    def run_ocr(self, image_path: str, temp_path: str = None):
        """在后台线程执行 OCR，结果覆盖写入识别面板并经 VO 朗读"""
        # 入口固化引擎引用：worker 内热键切换引擎时不应改用新引擎，播报与实际引擎保持一致
        engine = self.ocr_engine
        if not engine:
            self.vo_handler.speak_text(setting._('ocr_engine_unavailable'))
            self._remove_ocr_temp_file(temp_path)
            return
        self._unload_llm_for_vlm_ocr()
        if not self._ocr_lock.acquire(blocking=False):
            self.vo_handler.speak_text(setting._('ocr_in_progress'))
            self._remove_ocr_temp_file(temp_path)
            return

        def ocr_worker():
            try:
                needs_load = getattr(engine, "needs_load", None)
                if callable(needs_load) and needs_load():
                    wx.CallAfter(self.vo_handler.speak_text, setting._('ocr_vlm_loading'))
                text = engine.recognize(image_path)
                wx.CallAfter(self._on_ocr_result, text)
            except Exception as e:
                logging.warning(f"OCR 识别失败: {e}")
                wx.CallAfter(self._on_ocr_error, str(e))
            finally:
                self._remove_ocr_temp_file(temp_path)
                self._ocr_lock.release()

        threading.Thread(target=ocr_worker, daemon=True).start()

    @staticmethod
    def _remove_ocr_temp_file(temp_path: str) -> None:
        """删除识别用临时文件（剪贴板图片/降采样产物），失败仅忽略"""
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _on_ocr_result(self, text: str):
        """识别完成：结果覆盖写入编辑框并朗读（新内容覆盖模式）"""
        self.ocr_result_ctrl.SetValue(text)
        if text.strip():
            self.vo_handler.speak_text(text)
        else:
            self.vo_handler.speak_text(setting._('ocr_empty_result'))

    def _on_ocr_error(self, message: str):
        """识别失败：错误回写编辑框并朗读，避免界面表现为无响应"""
        self.ocr_result_ctrl.SetValue(f"[{setting._('ocr_failed')}: {message}]")
        self.vo_handler.speak_text(setting._('ocr_failed'))


    def on_to_translate(self, event, langType: str = None):
        """Option + 回车键：翻译文本"""
        apple_selected = (
            self._translation_mode == 'apple'
            and hasattr(self, 'apple_translator')
        )
        apple_ready = apple_selected and self.apple_translator.is_available()
        llm_ready = self._translation_mode == 'llm' and self.translator
        if not (apple_ready or llm_ready):
            if apple_selected and not llm_ready:
                # 内部机系统低于 macOS 26 或工具缺失：明确提示不可用，不回退 LLM
                message = setting._('apple_translation_not_available')
                self.text_ctrl.SetValue(message)
                self.vo_handler.speak_text(message)
                return
            wx.MessageBox(
                setting._("init_failed"), 
                setting._("error"), 
                wx.OK | wx.ICON_ERROR
            )
            return
        
        if langType == "reverse":
            source_lang = self._target_lang
            target_lang = self._source_lang
        else:
            source_lang = self._source_lang
            target_lang = self._target_lang
        
        text = self.text_ctrl.GetValue().strip()
        if not text:
            return
        
        result_text = self._lookup_dictionary(text)
        if result_text:
            self.text_ctrl.SetValue(result_text)
            return
        
        if not self._translation_lock.acquire(blocking=False):
            wx.MessageBox(setting._('translation_in_progress'), setting._('warning'), wx.OK | wx.ICON_WARNING)
            return
        
        if self._translation_mode == 'llm' and not self.translator.model_available:
            model_path = getattr(self, '_model_path', '') or ''
            # 模型可能因视觉识别被卸载：配置路径仍有效时放行，由翻译线程重新加载
            if not (model_path and os.path.exists(model_path)):
                self._translation_lock.release()
                self.vo_handler.speak_text(setting._("model_unavailable"))
                return

        text_length = len(text)
        LONG_TEXT_THRESHOLD = 2000
        
        if text_length > LONG_TEXT_THRESHOLD:
            self._translate_long_text(text, source_lang, target_lang)
        else:
            self._translate_short_text(text, source_lang, target_lang)

    def _translate_short_text(self, text: str, source_lang: str, target_lang: str):
        """翻译短文本（在线程中执行）"""
        def translate_worker():
            try:
                result_text = self._do_translate(text, source_lang, target_lang)
                if result_text:
                    wx.CallAfter(self.text_ctrl.SetValue, result_text)
                else:
                    wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            except Exception as e:
                logging.warning(f"翻译失败: {e}")
                # 错误必须回写编辑框，避免界面上表现为"卡在处理中"
                wx.CallAfter(self.text_ctrl.SetValue, f"[{setting._('translation_failed')}: {e}]")
                wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            finally:
                self._translation_lock.release()
        
        thread = threading.Thread(target=translate_worker, daemon=True)
        thread.start()

    def _translate_long_text(self, text: str, source_lang: str, target_lang: str):
        """翻译长文本（分段处理，实时返回结果）"""
        accumulated_result = []
        
        def segment_callback(segment: str, translated_segment: str):
            accumulated_result.append(translated_segment)
            wx.CallAfter(self._update_translation_result, '\n\n'.join(accumulated_result))
        
        def translate_worker():
            try:
                wx.CallAfter(self.vo_handler.speak_text, "开始翻译长文本")
                result_text = self._do_translate(
                    text, source_lang, target_lang, callback=segment_callback
                )
                if result_text:
                    wx.CallAfter(self.text_ctrl.SetValue, result_text)
                    wx.CallAfter(self.vo_handler.speak_text, "长文本翻译完成")
                else:
                    wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            except Exception as e:
                logging.warning(f"翻译失败: {e}")
                # 错误必须回写编辑框（保留已完成的分段结果），避免界面上表现为"卡在处理中"
                partial = '\n\n'.join(accumulated_result)
                error_line = f"[{setting._('translation_failed')}: {e}]"
                wx.CallAfter(self.text_ctrl.SetValue, f"{partial}\n\n{error_line}" if partial else error_line)
                wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            finally:
                self._translation_lock.release()
        
        thread = threading.Thread(target=translate_worker, daemon=True)
        thread.start()

    def _update_translation_result(self, translated_text: str):
        """实时更新翻译结果到编辑框"""
        current_pos = self.text_ctrl.GetInsertionPoint()
        self.text_ctrl.SetValue(translated_text)
        self.text_ctrl.SetInsertionPoint(current_pos)


    def on_key_to_translate(self, event):
        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()
        if key_code == wx.WXK_RETURN and modifiers == wx.MOD_ALT:
            self.on_to_translate(event)
        elif key_code == wx.WXK_RETURN and modifiers == (wx.MOD_ALT | wx.MOD_SHIFT):
            self.on_to_translate(event, "reverse")
        else:
            event.Skip()


    def on_translation_complete(self, original_text, translated_text):
        """翻译完成：更新UI"""
        wx.CallAfter(self._update_ui_with_translation, translated_text)

    def _update_ui_with_translation(self, translated_text):
        """更新编辑框内容"""
        current_pos = self.text_ctrl.GetInsertionPoint()
        self.text_ctrl.SetValue(translated_text)
        self.text_ctrl.SetInsertionPoint(current_pos)


    def on_new_clipboard_content(self, content: str, timestamp: float):
        if self._is_pasting:
            return
        wx.CallAfter(self._update_list_with_new_content, content, timestamp)


    def _update_list_with_new_content(self, content: str, timestamp: float):
        # 更新剪贴板
        self.add_clipboard_content(content)


    def on_reboot_vo_processer(self, event):
        """重启处理器线程"""

        try:
            
            #  停止当前线程
            if self.clipboard_monitor:
                self.clipboard_monitor.stop_worker()
                self.clipboard_monitor = None

                logging.info("已停止当前VO处理器线程")

            #  重新实例化并启动
            self.clipboard_monitor = ClipboardMonitor(
                log_level=logging.INFO, 
                loop_interval=0.1
            )
            self.clipboard_monitor.start_worker(callback=self.on_new_clipboard_content)
            
            logging.info("处理器线程已重启")

        except Exception as e:
            logging.error(f"重启处理器失败: {str(e)}")


    def on_clean_list(self, event):
        self.clipboard_list_data = []
        if self.current_module == 'clipboard':
            self.list_Box.Clear()  # 清空列表同时清空勾选状态
        self.update_clipboard_buttons_state()
        self.save_clipboard_data()


    def on_clipboard_search_text_changed(self, event):
        """实时搜索剪贴板记录"""
        keyword = self._clipboard_search_input.GetValue()
        self._clipboard_filter_keyword = keyword
        self._apply_clipboard_filter()
        self.refresh_list_box()


    def on_clipboard_search_enter(self, event):
        """搜索框回车事件"""
        pass


    def on_clipboard_count_text_change(self, event):
        """处理剪贴板记录数量文本输入，只允许数字"""
        current_value = self.clipboard_count_input.GetValue()
        new_value = ""
        for char in current_value:
            if char.isdigit():
                new_value += char
        if new_value != current_value:
            self.clipboard_count_input.ChangeValue(new_value)
        if new_value and int(new_value) > 2000:
            self.clipboard_count_input.SetValue("2000")
        event.Skip()

    def on_clipboard_count_focus_lost(self, event):
        """处理剪贴板记录数量编辑框失去焦点"""
        if hasattr(self, '_processing_clipboard_count') and self._processing_clipboard_count:
            event.Skip()
            return
        
        self._processing_clipboard_count = True
        try:
            current_value = self.clipboard_count_input.GetValue()
            if not current_value:
                value = 1000
            else:
                value = int(current_value)
                if value > 2000:
                    value = 2000
                    self.clipboard_count_input.SetValue("2000")
                elif value < 0:
                    value = 0
                    self.clipboard_count_input.SetValue("0")
            
            current_count = len(self.clipboard_list_data)
            if current_count > value:
                warning_msg = setting._("clipboard_max_count_warning").format(current=current_count, max=value)
                dialog = wx.MessageDialog(
                    self,
                    warning_msg,
                    setting._("clipboard_max_count_warning_title"),
                    wx.YES_NO | wx.ICON_WARNING
                )
                result = dialog.ShowModal()
                dialog.Destroy()
                if result == wx.ID_YES:
                    self.clipboard_list_data = self.clipboard_list_data[:value]
                    if self.current_module == "clipboard":
                        self.refresh_list_box()
                else:
                    value = current_count
                    self.clipboard_count_input.SetValue(str(value))
            
            self._clipboard_max_count = value
            self.save_config()
        finally:
            self._processing_clipboard_count = False
        event.Skip()

    def on_volume_limit_text_change(self, event):
        """处理音量限制输入，只允许数字和小数点，最多两位小数，不超过100"""
        current_value = self.volume_limit_input.GetValue()
        new_value = ""
        dot_count = 0
        decimal_places = 0
        for char in current_value:
            if char.isdigit():
                if dot_count > 0 and decimal_places >= 2:
                    continue
                new_value += char
                if dot_count > 0:
                    decimal_places += 1
            elif char == '.' and dot_count == 0:
                new_value += char
                dot_count += 1
        if new_value != current_value:
            self.volume_limit_input.ChangeValue(new_value)
        if new_value:
            value = float(new_value)
            if value > 100:
                value = 100.0
                self.volume_limit_input.SetValue("100")
            self._volume_limit = value
            self.volume_controller.set_config(self._volume_limit, self._volume_target)
        event.Skip()

    def on_volume_limit_focus_lost(self, event):
        """处理音量限制编辑框失去焦点"""
        if hasattr(self, '_processing_volume_limit') and self._processing_volume_limit:
            event.Skip()
            return
        
        self._processing_volume_limit = True
        try:
            current_value = self.volume_limit_input.GetValue()
            if not current_value:
                value = 100.0
            else:
                value = float(current_value)
                value = round(value, 2)
                if value > 100:
                    value = 100.0
                elif value < 0:
                    value = 0.0
                self.volume_limit_input.SetValue(str(value))
            
            self._volume_limit = value
            self.save_config()
            
            self.volume_controller.set_config(self._volume_limit, self._volume_target)
        finally:
            self._processing_volume_limit = False
        event.Skip()

    def on_volume_target_text_change(self, event):
        """处理目标音量输入，只允许数字和小数点，最多两位小数，不超过100"""
        current_value = self.volume_target_input.GetValue()
        new_value = ""
        dot_count = 0
        decimal_places = 0
        for char in current_value:
            if char.isdigit():
                if dot_count > 0 and decimal_places >= 2:
                    continue
                new_value += char
                if dot_count > 0:
                    decimal_places += 1
            elif char == '.' and dot_count == 0:
                new_value += char
                dot_count += 1
        if new_value != current_value:
            self.volume_target_input.ChangeValue(new_value)
        if new_value:
            value = float(new_value)
            if value > 100:
                value = 100.0
                self.volume_target_input.SetValue("100")
            self._volume_target = value
            self.volume_controller.set_config(self._volume_limit, self._volume_target)
        event.Skip()

    def on_volume_target_focus_lost(self, event):
        """处理目标音量编辑框失去焦点"""
        if hasattr(self, '_processing_volume_target') and self._processing_volume_target:
            event.Skip()
            return
        
        self._processing_volume_target = True
        try:
            current_value = self.volume_target_input.GetValue()
            if not current_value:
                value = 80.0
            else:
                value = float(current_value)
                value = round(value, 2)
                if value > 100:
                    value = 100.0
                elif value < 0:
                    value = 0.0
                self.volume_target_input.SetValue(str(value))
            
            self._volume_target = value
            self.save_config()
            
            self.volume_controller.set_config(self._volume_limit, self._volume_target)
        finally:
            self._processing_volume_target = False
        event.Skip()


    def save_clipboard_data(self):
        """保存剪贴板列表"""
        setting.save_clipboard_data(self.clipboard_list_data)


    def system_level_hide_window(self, window):
        """
         macOS 系统 API 隐藏窗口
        :param window: wx.Frame 实例（主窗口）
        """
        try:
            # 获取 wx 窗口对应的NSWindow 实例
            ns_window = window.GetHandle()
            if not ns_window:
                return

            # 获取当前应用实例
            app = NSApp()
            # 系统 API 隐藏应用
            app.hide_(None)
        except Exception as e:
            logging.error(f"系统级隐藏窗口失败: {str(e)}")


def main():
    # 日志配置（含 PID：用于区分多个实例交错写配置的情况）
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - PID%(process)d - %(name)s - %(levelname)s - %(message)s'
    )

    app = wx.App(False)
    #设置非后台应用
    if sys.platform == 'darwin':
        app.SetExitOnFrameDelete(True)  # 主窗口关闭时自动退出应用
    frame = MainFrame(None, setting._('app_name'))
    app.MainLoop()
    logging.info("应用主循环已结束，进程即将退出")
    sys.exit(0)


if __name__ == "__main__":
    main()
