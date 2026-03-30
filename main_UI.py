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
from processer import ClipboardMonitor, TextBrowser, Translator, reboot_VoiceOver, TextProcessor, VoiceOverHandler, VolumeController
from typing import Optional, Tuple

VERSION_INFO = f'V1.1.0\nBuild: 260313'


class FindReplaceDialog(wx.Dialog):
    def __init__(self, parent, text_ctrl, show_replace=False, last_find_pos=0,
                 find_text="", replace_text="", use_regex=False, case_sensitive=False, use_escape=False):
        super().__init__(parent, title=setting._('edd_find_replace_title'), size=(420, 180))
        self.text_ctrl = text_ctrl
        self.parent = parent
        self.last_find_pos = last_find_pos
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        top_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.replace_checkbox = wx.CheckBox(panel, label=setting._('edd_show_replace'))
        self.replace_checkbox.SetValue(show_replace)
        top_sizer.Add(self.replace_checkbox, 0)
        sizer.Add(top_sizer, 0, wx.LEFT | wx.TOP | wx.RIGHT, 10)
        
        find_sizer = wx.BoxSizer(wx.HORIZONTAL)
        find_sizer.Add(wx.StaticText(panel, label=setting._('edd_find_label')), 0, wx.CENTER | wx.RIGHT, 5)
        self.find_input = wx.TextCtrl(panel, size=(250, -1))
        self.find_input.SetValue(find_text)
        find_sizer.Add(self.find_input, 1, wx.RIGHT, 10)
        
        self.find_next_btn = wx.Button(panel, label=setting._('edd_find_next'))
        self.find_prev_btn = wx.Button(panel, label=setting._('edd_find_prev'))
        find_sizer.Add(self.find_next_btn)
        find_sizer.Add(self.find_prev_btn, 0, wx.LEFT, 10)
        
        sizer.Add(find_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        self.replace_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.replace_sizer.Add(wx.StaticText(panel, label=setting._('edd_replace_label')), 0, wx.CENTER | wx.RIGHT, 5)
        self.replace_input = wx.TextCtrl(panel, size=(250, -1))
        self.replace_input.SetValue(replace_text)
        self.replace_sizer.Add(self.replace_input, 1, wx.RIGHT, 10)
        
        self.replace_one_btn = wx.Button(panel, label=setting._('edd_replace_one'))
        self.replace_all_btn = wx.Button(panel, label=setting._('edd_replace_all'))
        self.replace_sizer.Add(self.replace_one_btn)
        self.replace_sizer.Add(self.replace_all_btn, 0, wx.LEFT, 5)
        
        sizer.Add(self.replace_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        option_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.regex_check = wx.CheckBox(panel, label=setting._('edd_use_regex'))
        self.regex_check.SetValue(use_regex)
        self.case_check = wx.CheckBox(panel, label=setting._('edd_case_sensitive'))
        self.case_check.SetValue(case_sensitive)
        self.escape_check = wx.CheckBox(panel, label=setting._('edd_escape'))
        self.escape_check.SetValue(use_escape)
        option_sizer.Add(self.regex_check, 0, wx.RIGHT, 10)
        option_sizer.Add(self.case_check, 0, wx.RIGHT, 10)
        option_sizer.Add(self.escape_check)
        
        sizer.Add(option_sizer, 0, wx.LEFT | wx.BOTTOM, 10)
        
        self.status_text = wx.StaticText(panel, label="")
        sizer.Add(self.status_text, 0, wx.LEFT | wx.BOTTOM, 10)
        
        panel.SetSizer(sizer)
        
        self.replace_checkbox.Bind(wx.EVT_CHECKBOX, self.on_toggle_replace)
        self.find_next_btn.Bind(wx.EVT_BUTTON, self.on_find_next)
        self.find_prev_btn.Bind(wx.EVT_BUTTON, self.on_find_prev)
        self.replace_one_btn.Bind(wx.EVT_BUTTON, self.on_replace_one)
        self.replace_all_btn.Bind(wx.EVT_BUTTON, self.on_replace_all)
        panel.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        
        self.replace_sizer.ShowItems(show_replace)
        self._update_size()
        
        self.Centre()
    
    def on_key_down(self, event):
        key_code = event.GetKeyCode()
        if key_code == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        else:
            event.Skip()
    
    def on_toggle_replace(self, event):
        show = self.replace_checkbox.GetValue()
        self.replace_sizer.ShowItems(show)
        self.Fit()
    
    def _update_size(self):
        self.Fit()
    
    def _get_pattern(self, search_text):
        use_regex = self.regex_check.GetValue()
        case_sensitive = self.case_check.GetValue()
        use_escape = self.escape_check.GetValue()
        
        if not search_text:
            return None, 0
        
        flags = 0 if case_sensitive else re.IGNORECASE
        
        if use_regex:
            try:
                pattern = re.compile(search_text, flags)
            except re.error:
                return None, 0
        else:
            if use_escape:
                escaped = re.escape(search_text)
                pattern = re.compile(escaped, flags)
            else:
                pattern = re.compile(search_text, flags)
        
        return pattern, 1 if use_regex else 0
    
    def _find(self, direction='next'):
        search_text = self.find_input.GetValue()
        if not search_text:
            return False
        
        pattern, pattern_type = self._get_pattern(search_text)
        if not pattern:
            return False
        
        full_text = self.text_ctrl.GetValue()
        text_len = len(full_text)
        
        if direction == 'next':
            start_pos = self.text_ctrl.GetInsertionPoint()
            start_pos = start_pos if start_pos < text_len else 0
            match = pattern.search(full_text, start_pos)
            if not match:
                match = pattern.search(full_text, 0)
        else:
            start_pos = self.text_ctrl.GetInsertionPoint() - 1
            start_pos = start_pos if start_pos >= 0 else text_len - 1
            matches = list(pattern.finditer(full_text))
            if not matches:
                self.status_text.SetLabel(setting._('edd_not_found'))
                return False
            match = None
            for m in matches:
                if m.start() < start_pos:
                    match = m
            if match is None:
                match = matches[-1]
        
        if match:
            start, end = match.span()
            self.text_ctrl.SetSelection(start, end)
            self.text_ctrl.SetInsertionPoint(end)
            self.last_find_pos = end if direction == 'next' else start
            self.status_text.SetLabel("")
            return True
        else:
            self.status_text.SetLabel(setting._('edd_not_found'))
            return False
    
    def on_find_next(self, event):
        if self._find('next'):
            self.EndModal(wx.ID_OK)
    
    def on_find_prev(self, event):
        if self._find('prev'):
            self.EndModal(wx.ID_OK)
    
    def on_replace_one(self, event):
        search_text = self.find_input.GetValue()
        replace_text = self.replace_input.GetValue()
        
        if not search_text:
            return
        
        pattern, pattern_type = self._get_pattern(search_text)
        if not pattern:
            return
        
        full_text = self.text_ctrl.GetValue()
        
        start_pos = self.text_ctrl.GetInsertionPoint()
        match = pattern.search(full_text, start_pos)
        if not match:
            match = pattern.search(full_text, 0)
        
        if match:
            start, end = match.span()
            new_text = full_text[:start] + replace_text + full_text[end:]
            self.text_ctrl.SetValue(new_text)
            new_cursor = start + len(replace_text)
            self.text_ctrl.SetSelection(new_cursor, new_cursor)
            self.text_ctrl.SetInsertionPoint(new_cursor)
            self.last_find_pos = new_cursor
            self.status_text.SetLabel(setting._('edd_replaced_count') % 1)
        else:
            self.status_text.SetLabel(setting._('edd_not_found'))
    
    def on_replace_all(self, event):
        search_text = self.find_input.GetValue()
        replace_text = self.replace_input.GetValue()
        
        if not search_text:
            return
        
        pattern, pattern_type = self._get_pattern(search_text)
        if not pattern:
            return
        
        full_text = self.text_ctrl.GetValue()
        
        new_text, count = pattern.subn(replace_text, full_text)
        
        self.text_ctrl.SetValue(new_text)
        self.last_find_pos = 0
        self.status_text.SetLabel(setting._('edd_replaced_count') % count)


# 剪贴板编辑对话框
class EditDialog(wx.Dialog):
    def __init__(self, parent, title: str, init_content: str, cursor_pos: int = None, size=(420, 350)):
        super().__init__(parent, title=title, size=size)
        self.edit_content = init_content

        self.last_find_pos = 0
        self.last_find_text = ""
        self.last_replace_text = ""
        self.last_regex = False
        self.last_case = False
        self.last_escape = False

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
        if cursor_pos is not None:
            self.text_ctrl.SetInsertionPoint(cursor_pos)
        self.text_ctrl.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        # 处理器
        self.text_processor = TextProcessor(init_content)

        # 按钮区
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.find_replace_btn = wx.Button(
            panel,
            label=setting._('edd_find_replace_btn'),
            style=wx.BU_EXACTFIT
        )
        self.more_btn = wx.Button(
            panel,
            label=setting._('edd_more_btn'),
            style=wx.BU_EXACTFIT
        )
        self.ok_btn = wx.Button(panel, label=setting._('confirm_btn'))
        self.cancel_btn = wx.Button(panel, label=setting._('cancel_btn'))

        self.find_replace_btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.more_btn.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        # 弹出菜单
        self.func_menu = wx.Menu()
        self.remove_whitespace_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting._('edd_remove_whitespace_btn')} ⌥+1"
        )
        self.merge_spaces_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting._('edd_merge_spaces_btn')} ⌥+2"
        )
        self.num_to_chinese_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting._('edd_num_to_chinese_btn')} ⌥+3"
        )
        self.punc_to_newline_menu = self.func_menu.Append(
            wx.NewIdRef(),
            f"{setting._('edd_punc_to_newline_btn')} ⌥+4"
        )

        # 按钮布局
        btn_sizer.Add(self.find_replace_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.more_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.cancel_btn, 0)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.TOP, 10)

        panel.SetSizer(sizer)

        # 事件绑定
        self.ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.find_replace_btn.Bind(wx.EVT_BUTTON, self.on_find_replace_click)
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
            elif key_code in (ord('F'), ord('f')):
                if modifiers & wx.MOD_SHIFT:
                    if self.last_find_text:
                        self._quick_find('prev')
                    else:
                        self.on_find_replace_click(None, show_replace=False)
                else:
                    if self.last_find_text:
                        self._quick_find('next')
                    else:
                        self.on_find_replace_click(None, show_replace=False)
                event.Skip(False)
            elif key_code in (ord('H'), ord('h')):
                self.on_find_replace_click(None, show_replace=True)
                event.Skip(False)
            else:
                event.Skip(True)  # 放行未处理的 ALT+按键（如 Option+Arrow）
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
            setting._('msg_is_close'),
            setting._('msg_motice'),
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )
        if is_close == wx.NO:
            return

        self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)  # 解绑事件
        self.EndModal(wx.ID_CANCEL)

    def get_result(self) -> str:
        """获取编辑结果"""
        return self.edit_content


    def on_find_replace_click(self, event, show_replace=False, find_next=True):
        """点击查找/替换按钮"""
        if not hasattr(self, 'find_replace_dialog') or self.find_replace_dialog is None:
            self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)
            self.find_replace_dialog = FindReplaceDialog(
                self, self.text_ctrl, 
                show_replace=show_replace, 
                last_find_pos=self.last_find_pos,
                find_text=self.last_find_text,
                replace_text=self.last_replace_text,
                use_regex=self.last_regex,
                case_sensitive=self.last_case,
                use_escape=self.last_escape
            )
            self.Enable(False)
            result = self.find_replace_dialog.ShowModal()
            self.last_find_pos = self.find_replace_dialog.last_find_pos
            self.last_find_text = self.find_replace_dialog.find_input.GetValue()
            self.last_replace_text = self.find_replace_dialog.replace_input.GetValue()
            self.last_regex = self.find_replace_dialog.regex_check.GetValue()
            self.last_case = self.find_replace_dialog.case_check.GetValue()
            self.last_escape = self.find_replace_dialog.escape_check.GetValue()
            self.Enable(True)
            self.app.Bind(wx.EVT_KEY_DOWN, self.on_app_key_down)
            self.find_replace_dialog = None
        else:
            self.find_replace_dialog.find_input.SetFocus()
            self.find_replace_dialog.ShowModal()
            self.last_find_pos = self.find_replace_dialog.last_find_pos
            self.find_replace_dialog = None

    def _quick_find(self, direction='next'):
        """快速查找，不打开对话框"""
        if not self.last_find_text:
            return False
        
        pattern, _ = self._get_pattern_for_quick_find()
        if not pattern:
            return False
        
        full_text = self.text_ctrl.GetValue()
        text_len = len(full_text)
        
        if direction == 'next':
            start_pos = self.text_ctrl.GetInsertionPoint()
            start_pos = start_pos if start_pos < text_len else 0
            match = pattern.search(full_text, start_pos)
            if not match:
                match = pattern.search(full_text, 0)
        else:
            start_pos = self.text_ctrl.GetInsertionPoint() - 1
            start_pos = start_pos if start_pos >= 0 else text_len - 1
            matches = list(pattern.finditer(full_text))
            if not matches:
                return False
            match = None
            for m in matches:
                if m.start() < start_pos:
                    match = m
            if match is None:
                match = matches[-1]
        
        if match:
            start, end = match.span()
            self.text_ctrl.SetSelection(start, end)
            self.text_ctrl.SetInsertionPoint(end)
            self.last_find_pos = end if direction == 'next' else start
            return True
        return False
    
    def _get_pattern_for_quick_find(self):
        """为快速查找获取模式"""
        search_text = self.last_find_text
        if not search_text:
            return None, 0
        
        flags = 0 if self.last_case else re.IGNORECASE
        
        if self.last_regex:
            try:
                pattern = re.compile(search_text, flags)
            except re.error:
                return None, 0
        else:
            if self.last_escape:
                escaped = re.escape(search_text)
                pattern = re.compile(escaped, flags)
            else:
                pattern = re.compile(search_text, flags)
        
        return pattern, 1 if self.last_regex else 0


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
        self.clipboard_list_data = []  # 剪贴板列表
        self.current_clipboard_idx = -1
        self.current_module = "translation"
        self._clipboard_filter_keyword = ""  # 搜索关键词
        self._clipboard_filtered_data = None  # 筛选后的数据
        
        self._is_translating = False
        self._translation_lock = threading.Lock()
        
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
        self.volume_controller = VolumeController(loop_interval=0.02)
        self.volume_controller.set_config(self._volume_limit, self._volume_target)
        self.volume_controller.start_worker()

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
        donate_help = help_menu.Append(wx.NewId(), setting._('menu_help_donate'))

        self.Bind(wx.EVT_MENU, self.on_help_program, program_help)
        self.Bind(wx.EVT_MENU, self.on_help_shortcuts, shortcuts_help)
        self.Bind(wx.EVT_MENU, self.on_help_changelog, changelog_help)
        self.Bind(wx.EVT_MENU, self.on_help_donate, donate_help)

        menubar.Append(help_menu, setting._('menubar_help'))

       # 设置菜单栏到窗口
        self.SetMenuBar(menubar)


    def init_ui(self):
        """初始化用户界面"""
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        
        # 创建左侧导航容器
        self.nav_container_panel = wx.Panel(self.splitter)

        static_box = wx.StaticBox(self.nav_container_panel, label=setting._("nav_select_func")) 
        static_box_sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL) 

        self.nav_list = wx.ListBox(self.nav_container_panel, choices=[
            setting._('nav_translation'),
            setting._('nav_clipboard'),
            setting._('nav_settings')
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
        static_box = wx.StaticBox(self.translation_panel, label=setting._("trans_input_placeholder")) 
        sizer = wx.StaticBoxSizer(static_box, wx.VERTICAL) 
        
        self.text_ctrl = wx.TextCtrl(self.translation_panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.Bind(wx.EVT_CHAR_HOOK, self.on_key_to_translate)
        
        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        
        self.translation_panel.SetSizer(sizer)
    
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
    
    def save_config(self):
        model_path = getattr(self, '_model_path', '') or ''
        clipboard_max_count = getattr(self, '_clipboard_max_count', 1000)
        volume_limit = getattr(self, '_volume_limit', 100)
        volume_target = getattr(self, '_volume_target', 80)
        setting.save_config(self._source_lang, self._target_lang, model_path, clipboard_max_count, volume_limit, volume_target)


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
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        browse_model_static_box = wx.StaticBox(self.settings_panel, label=setting._("browse_model"))
        browse_model_sizer = wx.StaticBoxSizer(browse_model_static_box, wx.VERTICAL)

        model_path_h_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.model_path_text = wx.TextCtrl(browse_model_static_box, style=wx.TE_READONLY)
        model_path_h_sizer.Add(self.model_path_text, 1, wx.EXPAND | wx.RIGHT, 5)
        
        self.browse_model_button = wx.Button(browse_model_static_box, label=setting._("browse_btn"))
        self.browse_model_button.Bind(wx.EVT_BUTTON, self.on_browse_model_click)
        model_path_h_sizer.Add(self.browse_model_button, 0)
        
        browse_model_sizer.Add(model_path_h_sizer, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(browse_model_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # --- 2. 剪贴板最大条数分组 ---
        clipboard_count_static_box = wx.StaticBox(self.settings_panel, label=setting._("clipboard_max_count"))
        clipboard_count_sizer = wx.StaticBoxSizer(clipboard_count_static_box, wx.VERTICAL)

        self.clipboard_count_input = wx.TextCtrl(clipboard_count_static_box, value=str(getattr(self, '_clipboard_max_count', 1000)), style=wx.TE_RIGHT)
        self.clipboard_count_input.Bind(wx.EVT_TEXT, self.on_clipboard_count_text_change)
        self.clipboard_count_input.Bind(wx.EVT_KILL_FOCUS, self.on_clipboard_count_focus_lost)

        clipboard_count_sizer.Add(self.clipboard_count_input, 0, wx.EXPAND | wx.ALL, 5)

        main_sizer.Add(clipboard_count_sizer, 0, wx.EXPAND | wx.ALL, 5)

        volume_control_static_box = wx.StaticBox(self.settings_panel, label=setting._("volume_control"))
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

        self.settings_panel.SetSizer(main_sizer)


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

        #  关闭窗口
        os._exit(0)


    def on_about(self, event):
        
        dialog = wx.Dialog(self, title=setting._("about_title"), size=(500, 400))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # 带滚动条的文本控件
        text_ctrl = wx.TextCtrl(
            panel, 
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL
        )
        text_ctrl.SetValue(VERSION_INFO)
        text_ctrl.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        # 关闭按钮
        btn = wx.Button(panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(text_ctrl, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.LEFT | wx.RIGHT, 10)

        panel.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()


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
        dialog.ShowModal()
        dialog.Destroy()


    def on_help_donate(self, event):
        dialog = wx.Dialog(self, title=setting._("menu_help_donate"), size=(400, 300))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        title_text = wx.StaticText(panel, label=setting._('donate_title'))
        title_text.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        
        content_text = wx.StaticText(panel, label=setting._('donate_content'))
        content_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))

        btn = wx.Button(panel, label=setting._("got_it_btn"))
        btn.Bind(wx.EVT_BUTTON, lambda e: dialog.Close())

        sizer.Add(title_text, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        sizer.Add(content_text, 0, wx.ALIGN_CENTER | wx.ALL, 20)
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 20)

        panel.SetSizer(sizer)
        dialog.ShowModal()
        dialog.Destroy()


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
        
        self.toolbar.Realize()




    def on_nav_selection_changed(self, event):
        """导航选择事件：切换内容面板 + 更新工具栏"""
        selection = event.GetString()
        if selection == setting._('nav_translation'):
            self.switch_to_module("translation")
        elif selection == setting._('nav_clipboard'):
            self.switch_to_module("clipboard")
        elif selection == setting._('nav_settings'):
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
        
        # 切换到其他模块时清空搜索
        if module_name != "clipboard":
            self._clipboard_filter_keyword = ""
            self._clipboard_filtered_data = None
        
        # 更新状态与工具栏
        self.current_module = module_name
        self.update_toolbar_for_module(module_name)
        self.main_panel.Layout()


    def load_clipboard_data(self):
        """加载外部剪贴板列表"""
        max_count = getattr(self, '_clipboard_max_count', 1000)
        self.clipboard_list_data = setting.load_clipboard_data(max_count)
        self._apply_clipboard_filter()
        self.refresh_list_box()


    def init_translator(self):
        """初始化翻译器"""
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
                
                if not self._translation_lock.acquire(blocking=False):
                    self.vo_handler.speak_text(setting._('translation_in_progress'))
                    return
                
                if not self.translator.model_available:
                    self._translation_lock.release()
                    self.vo_handler.speak_text(setting._("model_unavailable"))
                    return
                
                def translate_worker():
                    try:
                        result = self.translator.translate_with_streaming(
                            vo_text, self._source_lang, self._target_lang
                        )
                        if result:
                            wx.CallAfter(self.vo_handler.speak_text, result)
                        else:
                            wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
                    except Exception as e:
                        logging.warning(f"翻译失败: {e}")
                        wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
                    finally:
                        self._is_translating = False
                        self._translation_lock.release()
                
                self._is_translating = True
                threading.Thread(target=translate_worker, daemon=True).start()
        else:
            self.text_ctrl.SetValue(setting._('vo_warning'))


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
                
                if not self._translation_lock.acquire(blocking=False):
                    self.vo_handler.speak_text(setting._('translation_in_progress'))
                    return
                
                if not self.translator.model_available:
                    self._translation_lock.release()
                    self.vo_handler.speak_text(setting._("model_unavailable"))
                    return
                
                def translate_worker():
                    try:
                        result = self.translator.translate_with_streaming(
                            vo_text, self._target_lang, self._source_lang
                        )
                        if result:
                            wx.CallAfter(self.vo_handler.speak_text, result)
                        else:
                            wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
                    except Exception as e:
                        logging.warning(f"翻译失败: {e}")
                        wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
                    finally:
                        self._is_translating = False
                        self._translation_lock.release()
                
                self._is_translating = True
                threading.Thread(target=translate_worker, daemon=True).start()
        else:
            self.text_ctrl.SetValue(setting._('vo_warning'))


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


    def on_hotkey_altshift8(self, event):
        """alt+shift+8: 当前剪贴板上一行"""
        result_text = self.TB.browse("prev_line")
        self.vo_handler.speak_text(result_text)


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
        self.vo_handler.speak_text(result_text)


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
        """alt+shift+p: 粘贴剪贴板当前行"""
        result_text = self.TB._current_line
        if not result_text:
            return
        
        try:
            from AppKit import NSPasteboard
            from ApplicationServices import AXUIElementCreateSystemWide, AXUIElementCopyAttributeValue, AXUIElementSetAttributeValue
            
            pasteboard = NSPasteboard.general()
            pasteboard.clearContents()
            pasteboard.setString_forType_(result_text, 'public.utf8-plain-text')
            
            system_wide = AXUIElementCreateSystemWide()
            focused_app, _ = AXUIElementCopyAttributeValue(system_wide, "AXFocusedApplication")
            if focused_app:
                focused_element, _ = AXUIElementCopyAttributeValue(focused_app, "AXFocusedUIElement")
                if focused_element:
                    AXUIElementSetAttributeValue(focused_element, "AXValue", result_text)
                    return
            
            subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'], capture_output=True)
        except Exception as e:
            logging.warning(f"粘贴失败: {e}")


    def on_to_translate(self, event, langType: str = None):
        """Option + 回车键：翻译文本"""
        if not self.translator:
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
        
        result_text = self.translator.lookup_dictionary(text)
        if result_text:
            self.text_ctrl.SetValue(result_text)
            return
        
        if not self._translation_lock.acquire(blocking=False):
            wx.MessageBox(setting._('translation_in_progress'), setting._('warning'), wx.OK | wx.ICON_WARNING)
            return
        
        if not self.translator.model_available:
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
                result_text = self.translator.translate(text, source_lang, target_lang)
                if result_text:
                    wx.CallAfter(self.text_ctrl.SetValue, result_text)
                else:
                    wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            except Exception as e:
                logging.warning(f"翻译失败: {e}")
                wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            finally:
                self._is_translating = False
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
                result_text = self.translator.translate_with_streaming(
                    text, source_lang, target_lang, callback=segment_callback
                )
                if result_text:
                    wx.CallAfter(self.text_ctrl.SetValue, result_text)
                    wx.CallAfter(self.vo_handler.speak_text, "长文本翻译完成")
                else:
                    wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            except Exception as e:
                logging.warning(f"翻译失败: {e}")
                wx.CallAfter(self.vo_handler.speak_text, setting._("translation_failed"))
            finally:
                self._is_translating = False
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
    # 日志配置
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
