import logging
import os
import re
import setting
import wx
import wx.adv

from processer import TextProcessor
import update


def _open_url(url):
    import webbrowser
    webbrowser.open(url)


class AboutDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=setting._('about_title'), size=(400, 380))
        
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources", "icon.png")
        if os.path.exists(icon_path):
            icon = wx.Bitmap(icon_path, wx.BITMAP_TYPE_PNG)
            static_icon = wx.StaticBitmap(panel, bitmap=icon)
            sizer.Add(static_icon, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        
        app_name = wx.StaticText(panel, label=setting._('app_name'))
        app_name.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        sizer.Add(app_name, 0, wx.ALIGN_CENTER | wx.TOP, 15)
        
        version = wx.StaticText(panel, label=setting._('about_version') % update.get_current_version())
        version.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(version, 0, wx.ALIGN_CENTER | wx.TOP, 8)
        
        developer = wx.StaticText(panel, label=setting._('about_developer'))
        developer.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(developer, 0, wx.ALIGN_CENTER | wx.TOP, 15)
        
        copyright_text = wx.StaticText(panel, label=setting._('about_copyright'))
        copyright_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(copyright_text, 0, wx.ALIGN_CENTER | wx.TOP, 5)
        
        license_text = wx.StaticText(panel, label=setting._('about_license'))
        license_text.SetFont(wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(license_text, 0, wx.ALIGN_CENTER | wx.TOP, 8)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        github_btn = wx.Button(panel, label=setting._('about_view_github'), size=(140, 32))
        github_btn.Bind(wx.EVT_BUTTON, lambda e: _open_url("https://github.com/Asher-SIE/Magic-toolbox"))
        btn_sizer.Add(github_btn, 0, wx.RIGHT, 10)
        
        license_btn = wx.Button(panel, label=setting._('about_view_license'), size=(140, 32))
        license_btn.Bind(wx.EVT_BUTTON, lambda e: _open_url(
            "https://raw.githubusercontent.com/Asher-SIE/Magic-toolbox/main/LICENSE"
        ))
        btn_sizer.Add(license_btn, 0)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        
        btn = wx.Button(panel, label=setting._('got_it_btn'), size=(100, 32))
        btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        sizer.Add(btn, 0, wx.ALIGN_CENTER | wx.TOP, 20)
        
        panel.SetSizer(sizer)
        self.Centre()


class FindReplaceDialog(wx.Dialog):
    def __init__(self, parent, text_ctrl, show_replace=False, last_find_pos=0,
                 find_text="", replace_text="", use_regex=False, case_sensitive=False):
        super().__init__(parent, title=setting._('edd_find_replace_title'), size=(420, 180))
        self.text_ctrl = text_ctrl
        self.parent = parent
        self.last_find_pos = last_find_pos
        self.vo_handler = parent.vo_handler if hasattr(parent, 'vo_handler') else None
        self._is_speaking = False
        
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
        option_sizer.Add(self.regex_check, 0, wx.RIGHT, 10)
        option_sizer.Add(self.case_check)
        
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
        self.find_input.SetFocus()
        if find_text:
            self.find_input.SelectAll()
    
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
        
        if not search_text:
            return None, 0
        
        flags = 0 if case_sensitive else re.IGNORECASE
        
        if use_regex:
            try:
                pattern = re.compile(search_text, flags)
            except re.error:
                return None, 0
        else:
            pattern = re.compile(re.escape(search_text), flags)
        
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
                if self.vo_handler:
                    self.vo_handler.speak_text(setting._('edd_not_found'))
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
            if self.vo_handler:
                self.vo_handler.speak_text(setting._('edd_not_found'))
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


class EditDialog(wx.Dialog):
    def __init__(self, parent, title: str, init_content: str, cursor_pos: int = None, size=(420, 350)):
        super().__init__(parent, title=title, size=size)
        self.edit_content = init_content

        self.last_find_pos = 0
        self.last_find_text = ""
        self.last_replace_text = ""
        self.last_regex = False
        self.last_case = False
        self.find_count = 0
        self.last_find_direction = None
        self.find_dialog_opening = False

        self.undo_stack = []
        self.redo_stack = []
        self.max_stack_size = 100
        self.is_undoing = False
        self.is_redoing = False
        self.first_edit = True

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.text_ctrl = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.text_ctrl.SetValue(init_content)
        if cursor_pos is not None:
            self.text_ctrl.SetInsertionPoint(cursor_pos)
        self.text_ctrl.SetFont(wx.Font(12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 10)

        self.text_processor = TextProcessor(init_content)

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

        btn_sizer.Add(self.find_replace_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.more_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.ok_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.cancel_btn, 0)

        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM | wx.TOP, 10)

        panel.SetSizer(sizer)

        self.ok_btn.Bind(wx.EVT_BUTTON, self.on_ok)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        self.find_replace_btn.Bind(wx.EVT_BUTTON, self.on_find_replace_click)
        self.text_ctrl.Bind(wx.EVT_TEXT, self.on_text_changed)
        self.text_ctrl.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        self.app = wx.GetApp()
        self.app.Bind(wx.EVT_KEY_DOWN, self.on_app_key_down)

        self.more_btn.Bind(wx.EVT_BUTTON, self.on_more_btn_click)
        self.Bind(wx.EVT_MENU, self.on_remove_whitespace, self.remove_whitespace_menu)
        self.Bind(wx.EVT_MENU, self.on_merge_spaces, self.merge_spaces_menu)
        self.Bind(wx.EVT_MENU, self.on_num_to_chinese, self.num_to_chinese_menu)
        self.Bind(wx.EVT_MENU, self.on_punc_to_newline, self.punc_to_newline_menu)

        self.save_state_to_undo()
        

    def save_state_to_undo(self):
        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()

        if self.undo_stack and self.undo_stack[-1] == (current_text, current_cursor):
            return

        if len(self.undo_stack) >= self.max_stack_size:
            self.undo_stack.pop(0)

        self.undo_stack.append((current_text, current_cursor))

    def on_text_changed(self, event):
        if self.is_undoing or self.is_redoing:
            event.Skip()
            return

        if self.first_edit:
            self.undo_stack = [self.undo_stack[0]]
            self.first_edit = False

        self.redo_stack.clear()

        self.save_state_to_undo()
        event.Skip()


    def on_app_key_down(self, event):
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
                event.Skip(True)
        elif key_code == wx.WXK_ESCAPE:
            self.on_cancel(None)
            event.Skip(False)
        else:
            event.Skip(True)


    def on_key_down(self, event):
        key_code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        if modifiers == wx.MOD_CMD and key_code == ord('Z'):
            self.undo()
            event.Skip(False)
        elif modifiers == (wx.MOD_CMD | wx.MOD_SHIFT) and key_code == ord('Z'):
            self.redo()
            event.Skip(False)
        else:
            event.Skip(True)

    def undo(self):
        if len(self.undo_stack) <= 1:
            logging.debug("EditDialog: 没有可撤销的操作")
            return

        self.is_undoing = True

        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.redo_stack.append((current_text, current_cursor))

        self.undo_stack.pop() 
        prev_text, prev_cursor = self.undo_stack[-1]
        self.text_ctrl.SetValue(prev_text)
        self.text_ctrl.SetInsertionPoint(prev_cursor)

        self.is_undoing = False

    def redo(self):
        if not self.redo_stack:
            logging.debug("EditDialog: 没有可重做的操作")
            return

        self.is_redoing = True

        current_text = self.text_ctrl.GetValue()
        current_cursor = self.text_ctrl.GetInsertionPoint()
        self.undo_stack.append((current_text, current_cursor))

        next_text, next_cursor = self.redo_stack.pop()
        self.text_ctrl.SetValue(next_text)
        self.text_ctrl.SetInsertionPoint(next_cursor)

        self.is_redoing = False

    def on_ok(self, event):
        self.edit_content = self.text_ctrl.GetValue()
        self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)
        self.EndModal(wx.ID_OK)


    def on_cancel(self, event):
        is_close = wx.MessageBox(
            setting._('msg_is_close'),
            setting._('msg_motice'),
            wx.YES_NO | wx.ICON_QUESTION | wx.NO_DEFAULT
        )
        if is_close == wx.NO:
            return

        self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)
        self.EndModal(wx.ID_CANCEL)

    def get_result(self) -> str:
        return self.edit_content


    def on_find_replace_click(self, event, show_replace=False, find_next=True):
        if self.find_dialog_opening:
            return
        self.find_dialog_opening = True
        
        if not hasattr(self, 'find_replace_dialog') or self.find_replace_dialog is None:
            self.app.Unbind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)
            self.find_replace_dialog = FindReplaceDialog(
                self, self.text_ctrl, 
                show_replace=show_replace, 
                last_find_pos=self.last_find_pos,
                find_text=self.last_find_text,
                replace_text=self.last_replace_text,
                use_regex=self.last_regex,
                case_sensitive=self.last_case
            )
            self.Enable(False)
            result = self.find_replace_dialog.ShowModal()
            self.last_find_pos = self.find_replace_dialog.last_find_pos
            self.last_find_text = self.find_replace_dialog.find_input.GetValue()
            self.last_replace_text = self.find_replace_dialog.replace_input.GetValue()
            self.last_regex = self.find_replace_dialog.regex_check.GetValue()
            self.last_case = self.find_replace_dialog.regex_check.GetValue()
            self.Enable(True)
            self.app.Bind(wx.EVT_KEY_DOWN, handler=self.on_app_key_down)
            self.find_replace_dialog = None
            self.find_dialog_opening = False
        else:
            self.find_dialog_opening = False
            if self.find_replace_dialog and self.find_replace_dialog.IsShown():
                self.find_replace_dialog.Raise()
                self.find_replace_dialog.find_input.SetFocus()
            else:
                self.find_replace_dialog = None
                self.on_find_replace_click(event, show_replace, find_next)

    def _quick_find(self, direction='next'):
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
                if not match:
                    if self.last_find_direction == direction:
                        self.find_count += 1
                    else:
                        self.find_count = 1
                        self.last_find_direction = direction
                    
                    if self.find_count >= 6:
                        self.find_count = 0
                        self.last_find_direction = None
                        self.on_find_replace_click(None, show_replace=False)
                    else:
                        if hasattr(self, 'Parent') and hasattr(self.Parent, 'vo_handler'):
                            self.Parent.vo_handler.speak_text(setting._('edd_search_not_found'))
                    return False
        else:
            start_pos = self.text_ctrl.GetInsertionPoint() - 1
            start_pos = start_pos if start_pos >= 0 else text_len - 1
            matches = list(pattern.finditer(full_text))
            if not matches:
                if self.last_find_direction == direction:
                    self.find_count += 1
                else:
                    self.find_count = 1
                    self.last_find_direction = direction
                
                if self.find_count >= 6:
                    self.find_count = 0
                    self.last_find_direction = None
                    self.on_find_replace_click(None, show_replace=False)
                else:
                    if hasattr(self, 'Parent') and hasattr(self.Parent, 'vo_handler'):
                        self.Parent.vo_handler.speak_text(setting._('edd_search_not_found'))
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
            self.find_count = 0
            self.last_find_direction = None
            return True
        return False
    
    def _get_pattern_for_quick_find(self):
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
            pattern = re.compile(re.escape(search_text), flags)
        
        return pattern, 1 if self.last_regex else 0


    def on_more_btn_click(self, event):
        btn_pos = self.more_btn.ClientToScreen(wx.Point(0, self.more_btn.GetSize().y))
        self.PopupMenu(self.func_menu, btn_pos)


    def on_remove_whitespace(self, event):
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.remove_all_whitespace()
        self.text_ctrl.SetValue(result)
        

    def on_merge_spaces(self, event):
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.merge_multiple_spaces()
        self.text_ctrl.SetValue(result)


    def on_num_to_chinese(self, event):
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.arabic_to_chinese()
        self.text_ctrl.SetValue(result)



    def on_punc_to_newline(self, event):
        self.text_processor.set_text(self.text_ctrl.GetValue())
        result = self.text_processor.replace_punctuation_with_newline()
        self.text_ctrl.SetValue(result)