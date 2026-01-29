import logging
import objc
import os
import pickle
import setting
import sys
import time
import wx
import wx.adv

from AppKit import NSApplication, NSApp, NSWindow
from processer import ClipboardMonitor, TextBrowser, Translator, reboot_VoiceOver, TextProcessor, VoiceOverHandler
from typing import Optional, Tuple


# 剪贴板编辑对话框
class EditDialog(wx.Dialog):
    def __init__(self, parent, title: str, init_content: str, size=(420, 350)):
        super().__init__(parent, title=title, size=size)
        self.edit_content = init_content

        #  撤销/重做
        self.undo_stack = []  # 撤销栈：存储 (文本内容
        self.redo_stack = []  # 重做栈
        self.max_stack_size = 100  # 最大历史
        self.is_undoing = False
        self.is_redoing = False
        self.first_edit = True

        # 布局
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 编辑框
        self.text_ctrl = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.SetValue(init_content)
        self.text_ctrl.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # 处理器
        self.text_processor = TextProcessor(init_content)

        # 按钮区
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.more_btn = wx.Button(
            panel,
            label=setting.lang_dict[setting.current_lang].get('edd_more_btn', ' More'),
            style=wx.BU_EXACTFIT
        )
        self.ok_btn = wx.Button(panel, label=setting.lang_dict[setting.current_lang]['confirm_btn'])
        self.cancel_btn = wx.Button(panel, label=setting.lang_dict[setting.current_lang]['cancel_btn'])

        self.more_btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        # 弹出菜单
        self.func_menu = wx.Menu()
        self.remove_whitespace_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting.lang_dict[setting.current_lang]['edd_remove_whitespace_btn']} ⌥+1"
        )
        self.merge_spaces_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting.lang_dict[setting.current_lang]['edd_merge_spaces_btn']} ⌥+2"
        )
        self.num_to_chinese_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting.lang_dict[setting.current_lang]['edd_num_to_chinese_btn']} ⌥+3"
        )
        self.punc_to_newline_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting.lang_dict[setting.current_lang]['edd_punc_to_newline_btn']} ⌥+4"
        )

        # 按钮布局
        btn_sizer.Add(self.more_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.cancel_btn, 0)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.TOP, 10)

        panel.SetSizer(sizer)

        # 事件绑定
        self.ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.text_ctrl.Bind(wx.EVT_TEXT, self.on_text_changed)
        self.text_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        # 绑定应用级快捷键
        self.app = wx.GetApp()
        self.app.Bind(wx.EVT_KEY_DOWN, self.on_app_key_down)

        # 绑定"功能"按钮点击事件（弹出菜单）
        self.more_btn.Bind(wx.EVT_BUTTON, self.on_more_btn_click)
        # 菜单选项绑定处理方法
        self.Bind(wx.EVT_MENU, self.on_remove_whitespace, self.remove_whitespace_menu)
        self.Bind(wx.EVT_MENU, self.on_merge_spaces, self.merge_spaces_menu)
        self.Bind(wx.EVT_MENU, self.on_num_to_chinese, self.num_to_chinese_menu)
        self.Bind(wx.EVT_MENU, self.on_punc_to_newline, self.punc_to_newline_menu)


        # 将初始状态存入撤销栈（仅初始时执行一次）
        self.save_state_to_undo()
        # 强制获取焦点
        self.get_textCtrl_focus()


    def save_state_to_undo(self):
        """保存当前文本状态到撤销栈（去重+限制栈大小）"""
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()

        # 去重
        if self.undo_stack and self.undo_stack[-1] == (current_text, current_cursor):
            return

        # 限制栈大小
        if len(self.undo_stack) >= self.max_stack_size:
            self.undo_stack.pop(0)

        # 存入撤销栈
        self.undo_stack.append((current_text, current_cursor))

    def on_text_changed(self, event):
        """文本变化时触发：记录历史状态（修复首次编辑的初始状态记录）"""
        # 跳过撤销/重做过程中的文本变化
        if self.is_undoing or self.is_redoing:
            event.Skip()
            return

        # 首次编辑时：撤销栈只保留初始状态
        if self.first_edit:
            self.undo_stack = [self.undo_stack[0]]  # 重置为初始状态
            self.first_edit = False

        # 新操作触发后，清空重做栈（不能再重做之前的撤销操作）
        self.redo_stack.clear()

        # 记录当前状态到撤销栈
        self.save_state_to_undo()
        event.Skip()


    def on_app_key_down(self, event):
        #应用级快捷键
        if not self.IsShown():
            event.Skip(True)
            return

        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()
        is_alt_pressed = (modifiers & wx.MOD_ALT) == wx.MOD_ALT

        if is_alt_pressed:
            if key_code == ord('1'):
                self.on_remove_whitespace(None)
                event.Skip(False)
            elif key_code == ord('2'):
                self.on_merge_spaces(None)
                event.Skip(False)
            elif key_code == ord('3'):
                self.on_num_to_chinese(None)
                event.Skip(False)
            elif key_code == ord('4'):
                self.on_punc_to_newline(None)
                event.Skip(False)
            elif key_code in (ord('X'), ord('x')):
                self.on_ok(None)
                event.Skip(False)
        elif key_code == wx.WXK_ESCAPE:
            self.on_cancel(None)
            event.Skip(False)
        # 其他按键
        else:
            event.Skip(True)


    def on_key_down(self, event):
        """绑定撤销/重做热键：macOS标准 Cmd+Z / Cmd+Shift+Z"""
        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # 撤销
        if modifiers == wx.MOD_CMD and key_code == ord('Z'):
            self.undo()
            event.Skip(False)  # 阻止系统默认撤销行为
        # 重做
        elif modifiers == (wx.MOD_CMD | wx.MOD_SHIFT) and key_code == ord('Z'):
            self.redo()
            event.Skip(False)  # 阻止系统默认重做行为
        # 其他按键正常传递
        else:
            event.Skip(True)

    def undo(self):
        """撤销：恢复上一个文本状态和光标位置"""
        if len(self.undo_stack) <= 1:
            logging.debug("EditDialog: 没有可撤销的操作")
            return

        self.is_undoing = True

        # 将当前状态存入重做栈
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.redo_stack.append((current_text, current_cursor))

        # 从撤销栈取出上一个状态并恢复
        self.undo_stack.pop() 
        prev_text, prev_cursor = self.undo_stack[-1]
        self.text_ctrl.SetValue(prev_text)
        self.text_ctrl.SetInsertionPoint(prev_cursor)  # 恢复光标位置

        self.is_undoing = False

    def redo(self):
        """执行重做操作：恢复之前撤销的文本状态"""
        if not self.redo_stack:
            logging.debug("EditDialog: 没有可重做的操作")
            return

        self.is_redoing = True

        # 将当前状态存入撤销栈
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.undo_stack.append((current_text, current_cursor))

        #  重做栈取出状态并恢复
        next_text, next_cursor = self.redo_stack.pop()
        self.text_ctrl.SetValue(next_text)
        self.text_ctrl.SetInsertionPoint(next_cursor)  # 恢复光标位置

        self.is_redoing = False

    def on_ok(self, event):
        """确认按钮：保存编辑内容并关闭窗口"""
        self.edit_content = self.text_ctrl.GetValue()
        self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)  # 解绑事件
        self.EndModal(wx.ID_OK)


    def on_cancel(self, event):
        """取消按钮：放弃编辑并关闭窗口"""
        is_close = wx.MessageBox(
            setting.lang_dict[setting.current_lang].get('msg_is_close', '确定要退出吗？'),
            setting.lang_dict[setting.current_lang].get('msg_motice', '提示'),
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )
        if is_close == wx.NO:
            return

        self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)  # 解绑事件
        self.EndModal(wx.ID_CANCEL)

    def get_result(self) -> str:
        """获取编辑结果"""
        return self.edit_content

    def get_textCtrl_focus(self):
        """macOS专用：强制激活应用并给输入框设置焦点（解决焦点丢失问题）"""
        try:
            app = NSApp()
            app.activateIgnoringOtherApps_(True)  # 激活当前应用
            ns_window = self.GetHandle()
            if ns_window:
                ns_window.makeKeyAndOrderFront_(None)  # 置顶窗口
            self.text_ctrl.SetFocus()
            self.text_ctrl.SetInsertionPointEnd()  # 光标定位到末尾
        except Exception as e:
            logging.error(f"EditDialog: macOS 强制焦点失败: {str(e)}")


    def on_more_btn_click(self, event):
		# 在按钮下方弹出菜单
        btn_pos = self.more_btn.ClientToScreen(wx.Point(0, self.more_btn.GetSize().y))
        self.PopupMenu(self.func_menu, btn_pos)


    def on_remove_whitespace(self, event):
        """移除空白字符（空格、制表符、换行符）"""
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.remove_all_whitespace()
        self.text_ctrl.SetValue(result)
        


    def on_merge_spaces(self, event):
        """合并多个空格为单个空格"""
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.merge_multiple_spaces()
        self.text_ctrl.SetValue(result)


    def on_num_to_chinese(self, event):
        """数字转中文"""
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.arabic_to_chinese()
        self.text_ctrl.SetValue(result)



    def on_punc_to_newline(self, event):
        """分句"""
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.replace_punctuation_with_newline()
        self.text_ctrl.SetValue(result)


class MainFrame(wx.Frame):
    def __init__(self, parent, title):
        super(MainFrame, self).__init__(parent, title=title, size=(1024, 768))
        
        # 状态变量
        self.version='V1.0.3\nBuild: 251230'""''
        self.clipboard_list_data = []  # 剪贴板列表
        self.current_clipboard_idx = -1
        self.current_module = "translation"
        # 外部剪贴板数据
        app_support_dir = os.path.expanduser("~/Library/Application Support/")
        self.app_data_dir = os.path.join(app_support_dir, "MagicToolbox")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self._clipboard_data_path = os.path.join(self.app_data_dir, ".clipboard_data")  # 剪贴板数据文件
        self.edit_dialog = None

        # 创建UI组件
        self.init_toolbar()
        self.init_ui()
        self.create_menu_bar()

        # 实例化核心处理器
        self.translator = None
        self.vo_handler = VoiceOverHandler(
            log_level=logging.INFO,
            repeat_threshold=0.02,
            loop_interval=0.01
        )
        
        self.clipboard_monitor = ClipboardMonitor(
            log_level=logging.INFO, 
            loop_interval=0.1)
        self.TB = TextBrowser()

        # 初始化翻译器
        self.init_translator()

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


    def init_toolbar(self):
        """工具栏"""
        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER | wx.TB_TEXT)
        # toolbar_for_module 函数来填充内容。
        self.copy_btn_id = wx.NewIdRef()
        self.edit_btn_id = wx.NewIdRef()
        self.delete_btn_id = wx.NewIdRef()

        self.toolbar.Realize()


    def create_menu_bar(self):
        menubar = wx.MenuBar()
        # 2. 应用菜单
        app_menu = wx.Menu()

        # 关于
        about_item = app_menu.Append(
            wx.ID_ABOUT,  # 使用系统默认ID
            setting.lang_dict[setting.current_lang]['menu_about']
        )
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        # 分隔线
        app_menu.AppendSeparator()

        # 退出
        exit_item = app_menu.Append(
            wx.ID_EXIT, 
            "退出 Magic Toolbox",
            "退出应用（快捷键：⌘Q）"  
        )
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        rebootVO = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_rebootVO'])
        self.Bind(wx.EVT_MENU, reboot_VoiceOver, rebootVO)
        rebootProc = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_reboot_proc'])
        self.Bind(wx.EVT_MENU, self.on_reboot_vo_processer, rebootProc)
        cleanList = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_clean_list'])
        self.Bind(wx.EVT_MENU, self.on_clean_list, cleanList)


        # 添加到菜单栏
        menubar.Append(app_menu, setting.lang_dict[setting.current_lang]['menubar_opt'])

       # 设置菜单栏到窗口
        self.SetMenuBar(menubar)


    def init_ui(self):
        """初始化用户界面"""
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        
        # 创建左侧导航容器
        self.nav_container_panel = wx.Panel(self.splitter)

        static_box = wx.StaticBox(self.nav_container_panel, label="选择功能：") 
        static_box_sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL) 

        self.nav_list = wx.ListBox(self.nav_container_panel, choices=[
            setting.lang_dict[setting.current_lang]['trans_radio'],  # "翻译 / Translation"
            setting.lang_dict[setting.current_lang]['clipboard_radio'],   # "剪贴板 / Clipboard"
            setting.lang_dict[setting.current_lang]['menubar_opt']     # "设置 / Settings"
        ])
        self.nav_list.SetMinSize((150, -1)) # 设置最小宽度
        self.nav_list.SetSelection(0)
        self.nav_list.Bind(wx.EVT_LISTBOX, self.on_nav_selection_changed)

        static_box_sizer.Add(self.nav_list, 1, wx.EXPAND | wx.ALL, 5) # 拉伸填充并添加边    距
        self.nav_container_panel.SetSizer(static_box_sizer)


        # 创建右侧内容面板容器
        self.main_panel = wx.Panel(self.splitter)

        # 创建一个 Sizer 来管理 main_panel 内部的内容
        self.main_panel_sizer = wx.BoxSizer(wx.VERTICAL)
        self.main_panel.SetSizer(self.main_panel_sizer)

        # --- 初始化各功能模块的面板 ---
        # 翻译面板
        self.translation_panel = wx.Panel(self.main_panel)
        self.setup_translation_panel()
        self.translation_panel.Hide() # 默认隐藏

        # 剪贴板面板
        self.clipboard_panel = wx.Panel(self.main_panel)
        self.setup_clipboard_panel()
        self.clipboard_panel.Hide() # 默认隐藏

        # 设置面板
        self.settings_panel = wx.Panel(self.main_panel)
        self.setup_settings_panel()
        self.settings_panel.Hide() # 默认隐藏

        # 将各功能面板添加到 main_panel 的 Sizer 中
        self.main_panel_sizer.Add(self.translation_panel, 1, wx.EXPAND)
        self.main_panel_sizer.Add(self.clipboard_panel, 1, wx.EXPAND)
        self.main_panel_sizer.Add(self.settings_panel, 1, wx.EXPAND)

        # 将左右两部分加入分割窗口
        self.splitter.SplitVertically(self.nav_container_panel, self.main_panel)
        self.splitter.SetSashGravity(0.2) # 设置分割线位置，左边占20%
        self.splitter.SetMinimumPaneSize(100) # 设置最小窗格大小

        # 创建一个顶级 Sizer 并将其设置给主框架
        # 这样主框架就能管理分割窗口
        main_frame_sizer = wx.BoxSizer(wx.VERTICAL)
        main_frame_sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(main_frame_sizer)

        # 初始显示翻译面板
        self.switch_to_module("translation")


    def setup_translation_panel(self):
        """设置翻译功能面板的UI元素"""
        # 创建 StaticBox，其 label 说明文字
        static_box = wx.StaticBox(self.translation_panel, label="请输入待翻译文本：") 
        
        #  创建 StaticBoxSizer，将 StaticBox 与 Panel 关联
        sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL) 

        self.text_ctrl = wx.TextCtrl(self.translation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_to_translate) # 绑定按键钩子以捕获 Option+Enter

        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5) # 拉伸填充并添加边距

        self.translation_panel.SetSizer(sizer)


    def setup_clipboard_panel(self):
        """设置剪贴板功能面板的UI元素"""
        static_box = wx.StaticBox(self.clipboard_panel, label="剪贴板历史记录：")
        
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
        # 主布局管理器，垂直方向
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- 1. 浏览翻译模型分组 ---
        # 创建 StaticBox 和 StaticBoxSizer
        browse_model_static_box = wx.StaticBox(self.settings_panel, label="浏览翻译模型")
        browse_model_sizer = wx.StaticBoxSizer(browse_model_static_box, wx.VERTICAL)

        # 创建按钮并添加到该分组的 sizer
        browse_model_button = wx.Button(self.settings_panel, label="浏览...")
        # browse_model_button.Bind(wx.EVT_BUTTON, self.on_browse_model_click) # 绑定事件（如果需要）
        browse_model_sizer.Add(browse_model_button, 0, wx.EXPAND | wx.ALL, 5)

        # 将整个分组 sizer 添加到主 sizer
        main_sizer.Add(browse_model_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # --- 2. 锁定旁白音量分组 ---
        lock_volume_static_box = wx.StaticBox(self.settings_panel, label="锁定旁白音量")
        lock_volume_sizer = wx.StaticBoxSizer(lock_volume_static_box, wx.VERTICAL)

        # 为了在分组内水平排列编辑框和复选框
        inner_h_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 创建编辑框和复选框
        volume_input = wx.TextCtrl(self.settings_panel, value="", style=wx.TE_RIGHT)
        volume_input.Bind(wx.EVT_TEXT, lambda evt: self.on_volume_text_change(evt, volume_input))
        toggle_lock_checkbox = wx.CheckBox(self.settings_panel, label="开/关")

        # 将编辑框和复选框添加到内部的水平 sizer
        inner_h_sizer.Add(volume_input, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5) # 给复选框留点空间
        inner_h_sizer.Add(toggle_lock_checkbox, 0, wx.ALIGN_CENTER_VERTICAL)

        # 将内部的水平 sizer 整体添加到分组的 sizer
        lock_volume_sizer.Add(inner_h_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # 将整个分组 sizer 添加到主 sizer
        main_sizer.Add(lock_volume_sizer, 0, wx.EXPAND | wx.ALL, 5)


        # 应用主布局到 settings_panel
        self.settings_panel.SetSizer(main_sizer)




    def on_exit(self, event):
        """处理退出事件：释放线程、热键，关闭窗口"""
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

        #  关闭窗口
        os._exit(0)


    def on_about(self, event):
        about_content = f"""{self.version} """
        dialog = wx.Dialog(self, title="关于 Magic Toolbox", size=(500, 400))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 带滚动条的文本控件
        text_ctrl = wx.TextCtrl(
            panel, 
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL
        )
        text_ctrl.SetValue(about_content)
        text_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        # 关闭按钮
        btn = wx.Button(panel, label="Got it")
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()




    def update_toolbar_for_module(self, module_name: str):
        """更新工具栏"""
        self.toolbar.ClearTools()  # 清除旧工具
        
        if module_name == "clipboard":
            # 添加剪贴板工具
            self.toolbar.AddTool(
                self.copy_btn_id,
                setting.lang_dict[setting.current_lang]['copy_btn'],
                wx.NullBitmap,
                setting.lang_dict[setting.current_lang]['copy_btn_tips']
            )

            self.toolbar.AddTool(
                self.edit_btn_id,
                setting.lang_dict[setting.current_lang]['edit_btn'],
                wx.NullBitmap,
                setting.lang_dict[setting.current_lang]['edit_btn_tips']
            )

            self.toolbar.AddTool(
                self.delete_btn_id,
                setting.lang_dict[setting.current_lang]['delete_btn'],
                wx.NullBitmap,
                setting.lang_dict[setting.current_lang]['delete_btn_tips']
            )

            # 绑定事件
            self.Bind(wx.EVT_TOOL, self.on_copy_btn, id=self.copy_btn_id)
            self.Bind(wx.EVT_TOOL, self.on_edit_btn, id=self.edit_btn_id)
            self.Bind(wx.EVT_TOOL, self.on_delete_btn, id=self.delete_btn_id)

            # 初始禁用状态
            self.toolbar.EnableTool(self.copy_btn_id, False)
            self.toolbar.EnableTool(self.edit_btn_id, False)
            self.toolbar.EnableTool(self.delete_btn_id, False)

        elif module_name == "translation":
            # 添加翻译工具栏
            translate_id = wx.NewIdRef()
            self.toolbar.AddTool(translate_id, "翻译", wx.ArtProvider.GetBitmap(wx.ART_FIND), "翻译为英文")
            self.Bind(wx.EVT_TOOL, lambda e: self.on_to_translate(e, "EN"), id=translate_id)
        
        self.toolbar.Realize()  # 刷新显示




    def on_nav_selection_changed(self, event):
        """导航选择事件：切换内容面板 + 更新工具栏"""
        selection = event.GetString()
        if "翻译" in selection or "Translation" in selection:
            self.switch_to_module("translation")
        elif "剪贴板" in selection or "Clipboard" in selection:
            self.switch_to_module("clipboard")
        elif "操作" in selection or "Settings" in selection:
            self.switch_to_module("settings")


    def switch_to_module(self, module_name: str):
        """统一切换逻辑：更新面板显隐 + 工具栏 + 状态"""
        # 隐藏所有面板
        self.translation_panel.Hide()
        self.clipboard_panel.Hide()
        self.settings_panel.Hide()
        
        # 显示目标面板
        if module_name == "translation":
            self.translation_panel.Show()
            self.text_ctrl.SetFocus()
        elif module_name == "clipboard":
            self.clipboard_panel.Show()
            self.refresh_list_box()  # 刷新剪贴板列表
            self.list_Box.SetFocus()
        elif module_name == "settings":
            self.settings_panel.Show()
        
        # 更新状态与工具栏
        self.current_module = module_name
        self.update_toolbar_for_module(module_name)
        self.main_panel.Layout()


    def load_clipboard_data(self):
        """加载外部剪贴板列表"""
        try:
            if os.path.exists(self._clipboard_data_path):
                with open(self._clipboard_data_path, "rb") as f:  # 二进制读取
                    self.clipboard_list_data = pickle.load(f)  # 列表对象
                self.refresh_list_box()
                logging.info(f"加载剪贴板数据成功，共 {len(self.clipboard_list_data)} 条")
        except Exception as e:
            logging.warning(f"加载剪贴板数据失败（首次运行或文件损坏）: {str(e)}")


    def init_translator(self):
        """初始化翻译器"""
        try:
            self.translator = Translator(
                log_level=logging.INFO,
                loop_interval=0.1
            )
        except Exception as e:
            wx.MessageBox(str(e), "初始化错误", wx.OK | wx.ICON_ERROR)
            self.translator = None
        if self.translator.model_available == False:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['model_warning'])


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
            "CTRL": wx.MOD_CONTROL
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
        self.list_Box.Clear()
        for item in self.clipboard_list_data:
            if len(item) > 100:
                display_text = f"{item[:100]} ~~"
            else:
                display_text = item
            self.list_Box.Append(display_text)


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
        
        #  倒序删除
        indices_to_remove = [i for i, item in enumerate(self.clipboard_list_data) if item == content]
        for i in reversed(indices_to_remove):
            del self.clipboard_list_data[i]
        
        #  插入到开头
        self.clipboard_list_data.insert(0, content)
        
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
        
        # 拼接
        content_list = [self.clipboard_list_data[idx] for idx in checked_indices]
        content = "\n".join(content_list)
        
        # 复制到系统剪贴板
        clipboard = wx.Clipboard()
        clipboard.Open()
        clipboard.SetData(wx.TextDataObject(content))
        clipboard.Close()

        # 仅单选时删除原项
        if len(checked_indices) == 1:
            idx = checked_indices[0]
            if idx > 0:
                del self.clipboard_list_data[idx]
                self.refresh_list_box()


    def on_delete_btn(self, event):
        """删除勾选的项"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return

        # 确认删除
        if wx.MessageBox(setting.lang_dict[setting.current_lang]['delete_btn_tips'], setting.lang_dict[setting.current_lang]['confirm_btn'], wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return

        # 倒序删除
        sorted_indices = sorted(checked_indices, reverse=True)
        for idx in sorted_indices:
            if 0 <= idx < len(self.clipboard_list_data):
                del self.clipboard_list_data[idx]

        # 刷新
        self.refresh_list_box()
        self.update_clipboard_buttons_state()
        # 同步系统剪贴板
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
            wx.MessageBox("编辑功能仅支持单个项，请取消其他勾选后重试", "提示", wx.OK | wx.ICON_INFORMATION)
            return

        idx = checked_indices[0]
        init_content = self.clipboard_list_data[idx]
        # 打开编辑窗口
        dialog = EditDialog(
            self, setting.lang_dict[setting.current_lang]['editor_title'],
            init_content)
        if dialog.ShowModal() == wx.ID_OK:
            new_content = dialog.get_result()
            list_len = len(self.clipboard_list_data)  # 记录当前列表长度
            if not new_content:
                del self.clipboard_list_data[idx]
                # 刷新
                self.refresh_list_box()
                if list_len > 1:
                    new_idx = idx - 1 if idx == list_len - 1 else idx
                    # 取消所有勾选，选中新项
                    self.list_Box.UncheckAll()
                    if new_idx >= 0:
                        self.list_Box.SetSelection(new_idx)
                else:
                    new_idx = -1
            else:
                self.clipboard_list_data[idx] = new_content
                new_idx = idx  # 选中当前项
            self.refresh_list_box()
            if self.clipboard_list_data and new_idx != -1:
                self.list_Box.SetSelection(new_idx)  # 确保选中有效项
                self.list_Box.Check(new_idx, True)  # 勾选新项
                self.on_copy_btn(event)

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
                wx.MessageBox("编辑功能仅支持单个项，请取消其他勾选后重试", "提示", wx.OK | wx.ICON_INFORMATION)
        else:
            event.Skip()


    def on_list_item_selected(self, event):
        """列表项选中"""
        #  获取当前选中的索引
        selected_idx = event.GetSelection()
        self.current_clipboard_idx = selected_idx  # 同步索引
        
        #  加载文本到TextBrowser
        if selected_idx != -1 and 0 <= selected_idx < len(self.clipboard_list_data):
            selected_content = self.clipboard_list_data[selected_idx]
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

            result_text = self.translator.lookup_dictionary(vo_text[0])
            self.vo_handler.speak_text(result_text)


    def on_hotkey_altd(self, event):
        """Alt+D：英译中"""
        if event.GetId() != self.hotkey_ids["altd"]:
            return

        last_phrase = self.vo_handler.get_last_phrase()
        if last_phrase:
            vo_text, _ = last_phrase
            explained_text = self.TB.get_char_explanation(vo_text)
            # 若解释存在（与原文本不同），则使用解释结果；否则用原文本
            
            if explained_text != vo_text:
                self.vo_handler.speak_text(explained_text)
                return

            if self.translator:
                result_text = self.translator.lookup_dictionary(vo_text)
                if result_text:
                    self.vo_handler.speak_text(result_text)
                    return
                result_text = self.translator.translate(vo_text, "English", "Chinese")
                self.vo_handler.speak_text(result_text)
        else:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['vo_warning'])


    def on_hotkey_altshiftd(self, event):
        """Alt+Shift+D：中译英"""

        if event.GetId() != self.hotkey_ids["altshiftd"]:
            return

        last_phrase = self.vo_handler.get_last_phrase()
        if last_phrase:
            vo_text, _ = last_phrase
            explained_text = self.TB.get_char_explanation(vo_text)
            # 若解释存在（与原文本不同），则使用解释结果；否则用原文本
            
            if explained_text != vo_text:
                self.vo_handler.speak_text(explained_text)
                return

            if self.translator:
                result_text = self.translator.lookup_dictionary(vo_text)
                if result_text:
                    self.vo_handler.speak_text(result_text)
                    return
                result_text = self.translator.translate(vo_text, "Chinese", "English")
                self.vo_handler.speak_text(result_text)
        else:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['vo_warning'])


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

        self.edit_dialog = EditDialog(self, setting.lang_dict[setting.current_lang]["editor_title"], 
            init_content)
        if self.edit_dialog.ShowModal() == wx.ID_OK:
            new_content = self.edit_dialog.get_result()
            if self.clipboard_list_data:
                del self.clipboard_list_data[0]
            if new_content:
                self.clipboard_list_data.insert(0, new_content)  # 新增/替换为第一项
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
        # 数据列表为空直接返回
        if not self.clipboard_list_data:
            if hasattr(self, 'list_Box') and self.list_Box and self.current_module == 'clipboard':
                self.list_Box.SetSelection(-1)
            self.current_clipboard_idx = -1
            return

        total_count = len(self.clipboard_list_data)
        current_idx = self.current_clipboard_idx

        # 计算上一条索引
        if current_idx == -1 or current_idx == 0:
            # 无选中 或 已到第一项 → 切换到最后一项
            new_idx = total_count - 1
        else:
            # 否则切换到上一项
            new_idx = current_idx - 1

        self.current_clipboard_idx = new_idx

        selected_content = self.clipboard_list_data[new_idx]
        print(f"切换到索引 {new_idx}，内容：{selected_content[:20]}...")
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(new_idx)  # UI选中对应行
        # 调用vo_handler朗读
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content[:1024]}")
        # 更新按钮状态
        self.update_clipboard_buttons_state()

        self.TB.set_text(selected_content)
        self.TB.browse("prev_line")


    def on_hotkey_altshift8(self, event):
        """alt+shift+8: 当前剪贴板上一行"""
        result_text = self.TB.browse("prev_line")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshift9(self, event):
        """alt+shift+9: 剪贴板列表下一条"""
        if not self.clipboard_list_data:
            if hasattr(self, 'list_Box') and self.list_Box and self.current_module == 'clipboard':
                self.list_Box.SetSelection(-1)
            self.current_clipboard_idx = -1
            return

        total_count = len(self.clipboard_list_data)
        current_idx = self.current_clipboard_idx

        # 下一条索引
        if current_idx == -1 or current_idx >= total_count - 1:
            new_idx = 0
        else:
            new_idx = current_idx + 1

        self.current_clipboard_idx = new_idx
        # 获取选中内容
        selected_content = self.clipboard_list_data[new_idx]
        if self.current_module == 'clipboard':
            self.list_Box.SetSelection(new_idx)
        
        # 调用vo_handler朗读
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content[:1024]}")
        self.TB.set_text(selected_content)
        self.TB.browse("prev_line")


    def on_hotkey_altshiftu(self, event):
        """alt+shift+u: 当前剪贴板前一个字"""
        result_text = self.TB.browse("prev_char")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshifti(self, event):
        """alt+shift+i: 当前字符解释"""
        result_text = self.TB.browse("explain_char")

        if result_text:
            explained_text = self.TB.get_char_explanation(result_text)
            # 若解释存在（与原文本不同），则使用解释结果；否则用原文本
            if explained_text != result_text:
                self.vo_handler.speak_text(explained_text)
                return

        if self.translator:
            result_text = self.translator.lookup_dictionary(result_text[0])
            self.vo_handler.speak_text(result_text)


    def on_hotkey_altshifto(self, event):
        """alt+shift+o: 当前剪贴板后一个字"""
        result_text = self.TB.browse("next_char")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshiftj(self, event):
        """alt+shift+j: 剪贴板列表内容设置到系统"""
        if not self.clipboard_list_data or self.current_clipboard_idx < 0 or self.current_clipboard_idx >= len(self.clipboard_list_data):
            return
        
        # 目标文本
        target_text = self.clipboard_list_data[self.current_clipboard_idx]
        
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
            wx.MessageBox(f"设置剪贴板失败：{str(e)}", "错误", wx.OK | wx.ICON_ERROR)
        finally:
            if clipboard.IsOpened():
                clipboard.Close()
        

        del self.clipboard_list_data[self.current_clipboard_idx]
        
        # 校准current_clipboard_idx

        if not self.clipboard_list_data:
            self.current_clipboard_idx = -1
        elif self.current_clipboard_idx >= len(self.clipboard_list_data):
            self.current_clipboard_idx = len(self.clipboard_list_data) - 1

        
        self.refresh_list_box()


    def on_hotkey_altshiftk(self, event):
        """alt+shift+k: 当前剪贴板下一行"""
        result_text = self.TB.browse("next_line")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshiftm(self, event):
        """alt+shift+m: 剪贴板综述"""
        row_column = self.TB._row_column
        total_chars = self.TB._total_chars
        if row_column:
            self.vo_handler.speak_text(
                f"{setting.lang_dict[setting.current_lang]['now']}: {row_column[0]} {setting.lang_dict[setting.current_lang]['row']}; {row_column[1]} {setting.lang_dict[setting.current_lang]['column']}; {total_chars}: {setting.lang_dict[setting.current_lang]['total_chars']}"
            )


    def on_hotkey_altshiftp(self, event):
        """alt+shift+p: 粘贴剪贴板当前行"""
        result_text = self.TB._current_line
        if not result_text:
            return
        self.vo_handler.speak_text(result_text)


    def on_to_translate(self, event, langType: str):
        """Option + 回车键：翻译文本"""
        if not self.translator:
            wx.MessageBox(
                "initialization failed", 
                "Error", 
                wx.OK | wx.ICON_ERROR
            )
        if langType == 'EN':
            text = self.text_ctrl.GetValue().strip()
            if text:
                result_text = self.translator.lookup_dictionary(text)
                if result_text:
                    self.text_ctrl.SetValue(result_text)
                    return
                result_text = self.translator.translate(text, "English", "Chinese")
                if result_text:
                    self.text_ctrl.SetValue(result_text)

        if langType == 'ZH':
            text = self.text_ctrl.GetValue().strip()
            if text:
                result_text = self.translator.lookup_dictionary(text)
                if result_text:
                    self.text_ctrl.SetValue(result_text)
                    return
                result_text = self.translator.translate(text, "Chinese", "English")
                if result_text:
                    self.text_ctrl.SetValue(result_text)

        self.vo_handler.speak_text(result_text)


    def on_key_to_translate(self, event):
        # 检查按键
        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()
        if key_code == wx.WXK_RETURN and modifiers == wx.MOD_ALT:
            self.on_to_translate(event, "EN")

        elif key_code == wx.WXK_RETURN and modifiers == (wx.MOD_ALT | wx.MOD_SHIFT):
            self.on_to_translate(event, "ZH")
        else:
            event.Skip()


    def on_translation_complete(self, original_text, translated_text):
        """翻译完成：更新UI"""
        wx.CallAfter(self._update_ui_with_translation, translated_text)

    def _update_ui_with_translation(self, translated_text):
        """更新编辑框内容"""
        self.text_ctrl.SetValue(translated_text)


    def on_new_clipboard_content(self, content: str, timestamp: float):
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


    def on_volume_text_change(self, event, text_ctrl):
        """
        只允许输入数字和小数
        """
        current_value = text_ctrl.GetValue()
        # 允许的字符：数字和小数点
        allowed_chars = set("0123456789.")
        new_value = ""
        decimal_point_count = 0

        # 遍历当前文本
        for char in current_value:
            if len(new_value) >= 4:
                break
            if char in allowed_chars:
                # 检查小数点的数量
                if char == '.':
                    if decimal_point_count >= 1:
                        # 如果已经有小数点了，就跳过当前的小数点
                        continue
                    else:
                        decimal_point_count += 1
                new_value += char

        # 如果过滤后的文本与原文本不同，则更新控件内容
        if new_value != current_value:
            text_ctrl.ChangeValue(new_value)
            # 光标移到末尾
            text_ctrl.SetInsertionPointEnd()

        event.Skip()


    def save_clipboard_data(self):
        """保存剪贴板列表"""
        try:
            with open(self._clipboard_data_path, "wb") as f:  # 二进制写入
                pickle.dump(self.clipboard_list_data, f)  # 直接存储列表对象
            logging.debug(f"保存剪贴板数据成功（{len(self.clipboard_list_data)} 条）")
        except Exception as e:
            logging.error(f"保存剪贴板数据失败: {str(e)}")


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
    # 日志配置
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    app = wx.App(False)
    #设置非后台应用
    if sys.platform == 'darwin':
        app.SetExitOnFrameDelete(True)  # 主窗口关闭时自动退出应用
    frame = MainFrame(None, setting.lang_dict[setting.current_lang]['app_name'])
    app.MainLoop()
    logging.info("应用主循环已结束，进程即将退出")
    sys.exit(0)


if __name__ == "__main__":
    main()
