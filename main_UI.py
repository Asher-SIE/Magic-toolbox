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
from processer import MBartTranslator, VoiceOverHandler, ClipboardMonitor, TextBrowser, reboot_VoiceOver, TextProcessor
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


        # 初始化：将初始状态存入撤销栈（仅初始时执行一次）
        self.save_state_to_undo()
        # 强制获取焦点（macOS专用）
        self.get_textCtrl_focus()


    def save_state_to_undo(self):
        """保存当前文本状态到撤销栈（去重+限制栈大小）"""
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()

        # 去重：避免重复存储相同的状态（防止栈冗余）
        if self.undo_stack and self.undo_stack[-1] == (current_text, current_cursor):
            return

        # 限制栈大小：超过最大数量时删除最旧的记录
        if len(self.undo_stack) >= self.max_stack_size:
            self.undo_stack.pop(0)

        # 存入撤销栈
        self.undo_stack.append((current_text, current_cursor))

    def on_text_changed(self, event):
        """文本变化时触发：记录历史状态（修复首次编辑的初始状态记录）"""
        # 跳过撤销/重做过程中的文本变化（避免栈混乱）
        if self.is_undoing or self.is_redoing:
            event.Skip()
            return

        # 首次编辑时：确保撤销栈只保留初始状态，避免初始状态被覆盖
        if self.first_edit:
            self.undo_stack = [self.undo_stack[0]]  # 重置为初始状态（清除可能的重复）
            self.first_edit = False

        # 新操作触发后，清空重做栈（不能再重做之前的撤销操作）
        self.redo_stack.clear()

        # 记录当前状态到撤销栈
        self.save_state_to_undo()
        event.Skip()


    def on_app_key_down(self, event):
        #应用级快捷键：不管焦点在文本框/按钮，只要对话框打开就生效"""
        if not self.IsShown():
            event.Skip(True)
            return

        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()
        is_alt_pressed = (modifiers & wx.MOD_ALT) == wx.MOD_ALT

        # 1. Alt+1~4 功能菜单
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
        # 2. ESC 取消
        elif key_code == wx.WXK_ESCAPE:
            self.on_cancel(None)
            event.Skip(False)
        # 其他按键正常传递（不影响Tab切焦点、文本输入）
        else:
            event.Skip(True)


    def on_key_down(self, event):
        """绑定撤销/重做热键：macOS标准 Cmd+Z / Cmd+Shift+Z"""
        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # 撤销：Cmd+Z
        if modifiers == wx.MOD_CMD and key_code == ord('Z'):
            self.undo()
            event.Skip(False)  # 阻止系统默认撤销行为（避免冲突）
        # 重做：Cmd+Shift+Z
        elif modifiers == (wx.MOD_CMD | wx.MOD_SHIFT) and key_code == ord('Z'):
            self.redo()
            event.Skip(False)  # 阻止系统默认重做行为
        # 其他按键：正常传递（确保输入、删除、方向键等正常工作）
        else:
            event.Skip(True)

    def undo(self):
        """执行撤销操作：恢复上一个文本状态和光标位置"""
        # 至少保留初始状态（不能撤销到空栈）
        if len(self.undo_stack) <= 1:
            logging.debug("EditDialog: 没有可撤销的操作")
            return

        self.is_undoing = True

        # 1. 将当前状态存入重做栈（用于后续可能的重做）
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.redo_stack.append((current_text, current_cursor))

        # 2. 从撤销栈取出上一个状态并恢复
        self.undo_stack.pop()  # 移除当前状态（文本变化时已存入）
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

        # 1. 将当前状态存入撤销栈（用于后续可能的再次撤销）
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.undo_stack.append((current_text, current_cursor))

        # 2. 从重做栈取出状态并恢复
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
            self.text_ctrl.SetFocus()  # 输入框获取焦点
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
        
        # 创建UI组件
        self.init_toolbar()
        self.init_ui()

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
        #self.vo_handler.start_worker()  # 启动 VO 监听线程

        # 状态变量
        self.current_mode = "clipboard"
        self.clipboard_list_data = []  # 剪贴板列表
        # 外部剪贴板数据
        app_support_dir = os.path.expanduser("~/Library/Application Support/")
        self.app_data_dir = os.path.join(app_support_dir, "MagicToolbox")
        os.makedirs(self.app_data_dir, exist_ok=True)
        self._clipboard_data_path = os.path.join(self.app_data_dir, ".clipboard_data")

        self.load_clipboard_data()
        self.edit_dialog = None

        # 注册热键
        self.hotkey_ids = {}
        self.register_hotkeys()

        self.create_menu_bar()
        self.Bind(wx.EVT_CLOSE, self.on_exit)
        # 显示窗口
        self.Centre()
        self.Show(True)


    def init_toolbar(self):
        """创建工具栏：模式单选+功能按钮"""
        self.toolbar = self.CreateToolBar(wx.TB_HORIZONTAL | wx.NO_BORDER)
        # 模式单选框
        self.mode_group = wx.RadioBox(
            self.toolbar, label=setting.lang_dict[setting.current_lang]['tbr_mode'], choices=[setting.lang_dict[setting.current_lang]['trans_radio'], setting.lang_dict[setting.current_lang]['clipboard_radio']], style=wx.RA_SPECIFY_ROWS
        )
        self.mode_group.SetSelection(1)
        self.toolbar.AddControl(self.mode_group)
        self.toolbar.AddSeparator()
        # 剪贴板功能按钮
        self.copy_btn = self.toolbar.AddTool(wx.NewIdRef(), setting.lang_dict[setting.current_lang]['copy_btn'], wx.Bitmap(), setting.lang_dict[setting.current_lang]['copy_btn_tips'])
        self.delete_btn = self.toolbar.AddTool(wx.NewIdRef(), setting.lang_dict[setting.current_lang]['delete_btn'], wx.Bitmap(), setting.lang_dict[setting.current_lang]['delete_btn_tips'])
        self.edit_btn = self.toolbar.AddTool(wx.NewIdRef(), setting.lang_dict[setting.current_lang]['edit_btn'], wx.Bitmap(), setting.lang_dict[setting.current_lang]['edit_btn_tips'])
        self.toolbar.EnableTool(self.copy_btn.GetId(), False)
        self.toolbar.EnableTool(self.delete_btn.GetId(), False)
        self.toolbar.EnableTool(self.edit_btn.GetId(), False)
        self.toolbar.Realize()

        # 事件绑定
        self.Bind(wx.EVT_RADIOBOX, self.on_mode_switch, self.mode_group)
        self.Bind(wx.EVT_TOOL, self.on_copy_btn, self.copy_btn)
        self.Bind(wx.EVT_TOOL, self.on_delete_btn, self.delete_btn)
        self.Bind(wx.EVT_TOOL, self.on_edit_btn, self.edit_btn)


    def create_menu_bar(self):
        menubar = wx.MenuBar()
        # 2. 应用专属菜单
        app_menu = wx.Menu()

        # 2.1 关于Magic Toolbox
        about_item = app_menu.Append(
            wx.ID_ABOUT,  # 使用系统默认ID，自动匹配macOS关于项风格
            setting.lang_dict[setting.current_lang]['menu_about']
        )
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        # 2.2 分隔线（区分“关于”和“退出”）
        app_menu.AppendSeparator()

        # 2.3 退出Magic Toolbox（带系统默认退出图标和快捷键⌘Q）
        exit_item = app_menu.Append(
            wx.ID_EXIT,  # 使用系统默认ID，自动匹配macOS退出项风格和快捷键
            "退出 Magic Toolbox",
            "退出应用（快捷键：⌘Q）"  # 菜单提示
        )
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        rebootVO = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_rebootVO'])
        self.Bind(wx.EVT_MENU, reboot_VoiceOver, rebootVO)
        rebootProc = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_reboot_proc'])
        self.Bind(wx.EVT_MENU, self.on_reboot_vo_processer, rebootProc)
        cleanList = app_menu.Append(wx.NewId(), setting.lang_dict[setting.current_lang]['menu_opt_clean_list'])
        self.Bind(wx.EVT_MENU, self.on_clean_list, cleanList)


        # 将应用菜单添加到菜单栏
        menubar.Append(app_menu, setting.lang_dict[setting.current_lang]['menubar_opt'])

       # 设置菜单栏到窗口
        self.SetMenuBar(menubar)


    def on_exit(self, event):
        """处理退出事件：释放线程、热键，关闭窗口"""
        # 存储剪贴板数据
        self.save_clipboard_data()
        # 1. 停止核心处理器线程
        if self.translator:
            self.translator.stop_worker()
        #if self.vo_handler:
            #self.vo_handler.stop_worker()
        if self.clipboard_monitor:
            self.clipboard_monitor.stop_worker()

        # 2. 注销所有热键
        for hid in self.hotkey_ids.values():
            self.UnregisterHotKey(hid)
        self.hotkey_ids.clear()

        # 3. 关闭窗口（触发应用退出）
        os._exit(0)


    def on_about(self, event):
        about_content = f""" """
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

        # 添加关闭按钮
        btn = wx.Button(panel, label="Got it")
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()


    def init_ui(self):
        """初始化主界面：编辑框+列表"""
        self.main_panel = wx.Panel(self)
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 翻译模式
        self.text_ctrl = wx.TextCtrl(
            self.main_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER
        )
        self.text_ctrl.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.text_ctrl.SetHint("输入文本进行翻译...")
        self.main_sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        self.text_ctrl.Hide()

        # 剪贴板模式
        self.list_Box = wx.CheckListBox(self.main_panel, style=wx.LB_HSCROLL | wx.SUNKEN_BORDER)
        self.main_sizer.Add(self.list_Box, 1, wx.EXPAND | wx.ALL, 10)
        
        self.main_panel.SetSizer(self.main_sizer)
        self.text_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_key_to_translate)
        self.text_ctrl.Bind(wx.EVT_TEXT, self.on_text_changed)
        self.list_Box.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)
        # 绑定复选框勾选事件（替代原EVT_LISTBOX）
        self.list_Box.Bind(wx.EVT_CHECKLISTBOX, self.on_list_item_checked)
        # 保留列表项选中事件（兼容热键/键盘操作）
        self.list_Box.Bind(wx.EVT_LISTBOX, self.on_list_item_selected)


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
            self.translator = MBartTranslator(
                log_level=logging.INFO,
                loop_interval=0.1
            )
            self.translator.start_worker(callback=self.on_translation_complete)
        except Exception as e:
            wx.MessageBox(str(e), "初始化错误", wx.OK | wx.ICON_ERROR)
            self.translator = None
        if self.translator.model_available == False:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['model_warning'])


    def register_hotkeys(self):
        """注册热键"""
        # 1. 注销原有热键
        for hid in self.hotkey_ids.values():
            self.UnregisterHotKey(hid)
        self.hotkey_ids.clear()

        # 2. 修饰键映射表（将字符串转换为wx对应的常量）
        modifier_map = {
            "ALT": wx.MOD_ALT,
            "SHIFT": wx.MOD_SHIFT,
            "CTRL": wx.MOD_CONTROL
        }

        # 3. 遍历keys列表批量注册热键
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


    def on_mode_switch(self, event):
        """翻译/剪贴板模式切换"""
        new_mode = "clipboard" if self.mode_group.GetSelection() == 1 else "translation"
        if new_mode == self.current_mode:
            return

        self.current_mode = new_mode
        if new_mode == "translation":
            # 显示编辑框，隐藏列表
            self.text_ctrl.Show()
            self.list_Box.Hide()
            self.toolbar.EnableTool(self.copy_btn.GetId(), False)
            self.toolbar.EnableTool(self.delete_btn.GetId(), False)
            self.toolbar.EnableTool(self.edit_btn.GetId(), False)
        else:
            # 显示列表，隐藏编辑框
            self.text_ctrl.Hide()
            self.list_Box.Show()
            self.refresh_list_box()
            self.update_clipboard_buttons_state()
        
        self.main_sizer.Layout()
        self.main_panel.Layout()
        self.Layout()


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
        # 获取所有勾选的项索引（原生API）
        checked_indices = self.list_Box.GetCheckedItems()
        has_select = len(checked_indices) > 0
        self.toolbar.EnableTool(self.copy_btn.GetId(), has_select)
        self.toolbar.EnableTool(self.delete_btn.GetId(), has_select)
        self.toolbar.EnableTool(self.edit_btn.GetId(), has_select)


    def on_copy_btn(self, event):
        """拷贝勾选的项到剪贴板：多选拼接，单选复制单个"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return
        
        # 拼接所有勾选的内容（多选用换行分隔）
        content_list = [self.clipboard_list_data[idx] for idx in checked_indices]
        content = "\n".join(content_list)
        
        # 复制到系统剪贴板
        clipboard = wx.Clipboard()
        clipboard.Open()
        clipboard.SetData(wx.TextDataObject(content))
        clipboard.Close()

        # 仅单选时删除原项（保持原有逻辑）
        if len(checked_indices) == 1:
            idx = checked_indices[0]
            if idx > 0:
                del self.clipboard_list_data[idx]
                self.refresh_list_box()


    def on_delete_btn(self, event):
        """删除勾选的项：批量倒序删除，避免索引错乱"""
        # 获取所有勾选的项索引
        checked_indices = self.list_Box.GetCheckedItems()
        if not checked_indices:
            return

        # 确认删除
        if wx.MessageBox(setting.lang_dict[setting.current_lang]['delete_btn_tips'], setting.lang_dict[setting.current_lang]['confirm_btn'], wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return

        # 核心：倒序删除，防止索引偏移
        sorted_indices = sorted(checked_indices, reverse=True)
        for idx in sorted_indices:
            if 0 <= idx < len(self.clipboard_list_data):
                del self.clipboard_list_data[idx]

        # 刷新列表+更新按钮状态
        self.refresh_list_box()
        self.update_clipboard_buttons_state()
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
            # F2编辑仅支持单个勾选项
            if len(checked_indices) == 1:
                self.on_edit_btn(None)
            else:
                wx.MessageBox("编辑功能仅支持单个项，请取消其他勾选后重试", "提示", wx.OK | wx.ICON_INFORMATION)
        else:
            event.Skip()


    def on_list_item_selected(self, event):
        """列表项选中：兼容热键/键盘操作，更新按钮状态"""
        self.update_clipboard_buttons_state()


    def on_list_item_checked(self, event):
        """复选框勾选/取消勾选：仅更新按钮状态，无刷新卡顿"""
        self.update_clipboard_buttons_state()


    def on_list_item_deselected(self, event):
        """列表项取消选中：禁用按钮"""
        self.update_clipboard_buttons_state()


    def on_hotkey_altc(self, event):
        """Alt+C：查字典和英译中"""
        if event.GetId() != self.hotkey_ids["altc"]:
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
                self.translator.set_input_text(vo_text, "EN")
        else:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['vo_warning'])


    def on_hotkey_altshiftc(self, event):
        """Alt+Shift+C：中译英"""

        if event.GetId() != self.hotkey_ids["altshiftc"]:
            return

        last_phrase = self.vo_handler.get_last_phrase()
        if last_phrase:
            vo_text, _ = last_phrase
            if self.translator:
                self.translator.set_input_text(vo_text, "ZH")
        else:
            self.text_ctrl.SetValue(setting.lang_dict[setting.current_lang]['vo_warning'])


    def on_hotkey_altt(self, event):
        """Alt+T：剪贴板编辑器"""
        if self.edit_dialog:
            return
        try:
            app = NSApp()
            # 强制激活当前应用，把焦点从其他 App 抢过来
            app.activateIgnoringOtherApps_(True)
        except Exception as e:
            logging.error(f"激活应用失败: {str(e)}")
        # 1. 读取系统剪贴板内容
        clipboard = wx.Clipboard()
        init_content = ""
        if clipboard.Open():
            # 获取文本
            text_data = wx.TextDataObject()
            if clipboard.GetData(text_data):
                init_content = text_data.GetText()
            clipboard.Close()  # 关闭剪贴板

        # 2. 打开编辑对话框
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
                self.list_Box.SetSelection(0)  # 确保选中第一项
            elif self.clipboard_list_data:
                self.list_Box.SetSelection(0)
                self.on_copy_btn(event)
            else:
                clipboard.Open()
                clipboard.SetData(wx.TextDataObject(''))
                clipboard.Close()
        self.edit_dialog.Destroy()
        self.save_clipboard_data()
        self.refresh_list_box()
        self.system_level_hide_window(self)


    def on_hotkey_altd(self, event):
        """VO内容添加到列表第一行"""
        if event is not None and event.GetId() != self.hotkey_ids["altd"]:
            return

        last_phrase = self.vo_handler.get_last_phrase()
        if not last_phrase:
            return

        vo_text, _ = last_phrase
        # 与第一行相同则不添加（ListBox通过GetItems()获取所有项）
        if self.clipboard_list_data and self.clipboard_list_data[0] == vo_text:
            return

        self.clipboard_list_data.insert(0, vo_text)
        if self.current_mode == "clipboard":
            self.refresh_list_box()
            self.update_clipboard_buttons_state()
            self.save_clipboard_data()


    def on_hotkey_alta(self, event):
        """列表第一项追加VO内容（加换行）"""
        if event.GetId() != self.hotkey_ids["alta"]:
            return

        # 列表为空则返回
        if not self.clipboard_list_data:
            self.on_hotkey_altd(None)
            return

        last_phrase = self.vo_handler.get_last_phrase()
        if not last_phrase:
            return

        vo_text, _ = last_phrase
        # 追加内容（原内容+\n+VO内容）
        self.clipboard_list_data[0] = f"{self.clipboard_list_data[0]}\n{vo_text}"
        self.refresh_list_box()
        # ListBox使用SetSelection()选中项，参数为索引
        self.list_Box.SetSelection(0)
        self.on_copy_btn(event)
        self.save_clipboard_data()


    def on_hotkey_altshift7(self, event):
        """alt+shift+7: 剪贴板列表上一条"""
        new_idx = 0
        # 检查列表是否有数据
        if not self.clipboard_list_data:
            return

        # 获取当前选中项索引
        current_idx = self.list_Box.GetSelection()
        # 计算上一项索引（循环切换：顶部再往上回到最后一项）
        if current_idx <= 0:
            new_idx = len(self.clipboard_list_data) - 1  # 回到最后一项
        else:
            new_idx = current_idx - 1

        # 选中新项并获取内容
        self.list_Box.SetSelection(new_idx)
        selected_content = self.clipboard_list_data[new_idx]

        # 调用vo_handler朗读
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content}")
        # 更新按钮状态
        self.update_clipboard_buttons_state()

        self.TB.set_text(selected_content)
        self.TB.browse("prev_line")


    def on_hotkey_altshift8(self, event):
        """alt+shift+8: 当前剪贴板上一行"""
        result_text = self.TB.browse("prev_line")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshift9(self, event):
        """a lt+shift+9: 剪贴板列表下一条"""
        new_idx = 0
        # 检查列表是否有数据
        if not self.clipboard_list_data:
            return
    
        # 获取当前选中项索引（-1表示无选中）
        current_idx = self.list_Box.GetSelection()
        # 计算下一项索引（循环切换：底部再往下回到第一项）
        if current_idx == -1 or current_idx == len(self.clipboard_list_data) - 1:
            new_idx = 0  # 回到第一项
        else:
            new_idx = current_idx + 1  # 下一项

        # 选中新项并获取内容
        self.list_Box.SetSelection(new_idx)
        selected_content = self.clipboard_list_data[new_idx]  # 局部变量存储选中内容

        # 调用vo_handler朗读
        self.vo_handler.speak_text(f"{new_idx + 1}, {selected_content}")
        # 更新按钮状态
        self.update_clipboard_buttons_state()
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
            self.translator.set_input_text(result_text[0], "EN")


    def on_hotkey_altshifto(self, event):
        """alt+shift+o: 当前剪贴板后一个字"""
        result_text = self.TB.browse("next_char")
        self.vo_handler.speak_text(result_text)


    def on_hotkey_altshiftj(self, event):
        """alt+shift+j: 获取当前剪贴板到系统"""
        self.on_copy_btn(event)


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


    def on_text_changed(self, event):
        """文本框内容变化：自动朗读"""
        current_text = self.text_ctrl.GetValue()
        self.vo_handler.speak_text(current_text)
        event.Skip()


    def on_to_translate(self, event, langType: str):
        """Option + 回车键：翻译文本"""
        if not self.translator:
            wx.MessageBox(
                "initialization failed", 
                "Error", 
                wx.OK | wx.ICON_ERROR
            )

        text = self.text_ctrl.GetValue().strip()
        if text:
            self.translator.set_input_text(text, langType)


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
        if self.clipboard_list_data and self.clipboard_list_data[0] == content:
            return
        self.clipboard_list_data.insert(0, content)
        if self.current_mode == "clipboard":
            self.refresh_list_box()
            self.list_Box.SetSelection(0)
            self.save_clipboard_data()


    def on_reboot_vo_processer(self, event):
        """重启VoiceOver处理器线程"""

        try:
            
            # 1. 停止当前线程
            if self.clipboard_monitor:
                self.clipboard_monitor.stop_worker()
                self.clipboard_monitor = None

                logging.info("已停止当前VO处理器线程")

            # 2. 重新实例化并启动
            self.clipboard_monitor = ClipboardMonitor(
                log_level=logging.INFO, 
                loop_interval=0.1
            )
            self.clipboard_monitor.start_worker(callback=self.on_new_clipboard_content)
            
            logging.info("VO处理器线程已重启")

        except Exception as e:
            logging.error(f"重启处理器失败: {str(e)}")


    def on_clean_list(self, event):
        self.clipboard_list_data = []
        self.list_Box.Clear()  # 清空列表同时清空勾选状态
        self.update_clipboard_buttons_state()
        self.save_clipboard_data()


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
        调用 macOS 系统 API 隐藏窗口，效果和 Cmd+H 完全一致
        :param window: wx.Frame 实例（主窗口）
        """
        try:
            # 获取 wx 窗口对应的 macOS 原生 NSWindow 实例
            ns_window = window.GetHandle()
            if not ns_window:
                return

            # 获取当前应用实例
            app = NSApp()
            # 调用系统 API 执行“隐藏应用”（和 Cmd+H 触发的系统行为完全相同）
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
    frame = MainFrame(None, setting.lang_dict[setting.current_lang]['app_name'])
    app.MainLoop()


if __name__ == "__main__":
    main()
