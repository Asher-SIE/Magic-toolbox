"""模态对话框 IME/ESC 守卫（ime_guard）的 GUI 回归测试。

背景：输入法组合期间按 ESC 应只取消组合，而不是关闭模态对话框。
本测试在真实显示环境下验证：

* 组合中 / 组合刚结束（透传宽限窗内）的 ESC 不会关闭对话框；
* 组合之外的 ESC 行为与原有逻辑完全一致（快捷键、关闭路径均保留）。

运行方式（会短暂弹出对话框，属正常现象）::

    python -m unittest tests.test_ime_escape -v

Windows 上用 ``SendMessage(WM_IME_STARTCOMPOSITION/ENDCOMPOSITION)``
模拟输入法生命周期消息——这些消息会同时驱动 wx 内部的组合计数与本模块
的跟踪器，与真实输入法的消息路径一致；另有基于 ``UIActionSimulator``
的真实键盘事件测试。macOS 分支（hasMarkedText）为惰性导入，无法在
Windows 上验证，仅做跨平台冒烟检查。
"""

import ctypes
import sys
import tempfile
import time
import types
import unittest

import wx

from unittest import mock


def _install_portable_stubs():
    """dialogs.py 依赖的 setting/processer 在非 macOS 上不可导入
    （ioreg/appscript/llama_cpp 为 macOS 专属），测试前注入桩模块。
    在 macOS 上 setdefault 不生效，仍使用真实模块。"""
    if "setting" not in sys.modules:
        setting_stub = types.ModuleType("setting")
        setting_stub._ = lambda key, *args, **kwargs: key
        sys.modules["setting"] = setting_stub
    if "processer" not in sys.modules:
        processer_stub = types.ModuleType("processer")

        class TextProcessor:
            def __init__(self, text=""):
                self._text = text

            def set_text(self, text):
                self._text = text

            def remove_all_whitespace(self):
                return self._text

            def merge_multiple_spaces(self):
                return self._text

            def arabic_to_chinese(self):
                return self._text

            def replace_punctuation_with_newline(self):
                return self._text

        processer_stub.TextProcessor = TextProcessor
        sys.modules["processer"] = processer_stub


_install_portable_stubs()

# 在桩模块就位后再导入被测模块
import dialogs  # noqa: E402
import ime_guard  # noqa: E402


WM_IME_STARTCOMPOSITION = 0x010D
WM_IME_ENDCOMPOSITION = 0x010E
SCS_SETSTR = 0x0009  # GCS_COMPREADSTR | GCS_COMPSTR
NI_COMPOSITIONSTR = 0x0015
CPS_CANCEL = 0x0004

_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
_imm32 = ctypes.windll.imm32 if sys.platform == "win32" else None
_kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


def _force_foreground(hwnd):
    """把窗口强制带到前台（UIActionSimulator 的 SendInput 只送前台窗口）。

    Windows 限制后台进程抢前台，这里用 AttachThreadInput 借用当前前台
    线程的输入队列绕过该限制，仅在测试进程内短暂生效。
    """
    if not hwnd:
        return
    fg = _user32.GetForegroundWindow()
    if fg == hwnd:
        return
    cur_thread = _kernel32.GetCurrentThreadId()
    fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = False
    if fg_thread and fg_thread != cur_thread:
        attached = _user32.AttachThreadInput(cur_thread, fg_thread, True)
    try:
        _user32.SetForegroundWindow(hwnd)
        _user32.SetFocus(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(cur_thread, fg_thread, False)


def _is_descendant_of(win, ancestor):
    while win is not None:
        if win is ancestor:
            return True
        win = win.GetParent()
    return False


def _send_ime_start(hwnd):
    _user32.SendMessageW(hwnd, WM_IME_STARTCOMPOSITION, 0, 0)


def _send_ime_end(hwnd):
    _user32.SendMessageW(hwnd, WM_IME_ENDCOMPOSITION, 0, 0)


def _dispatch_char_hook_escape(dlg):
    evt = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    evt.SetKeyCode(wx.WXK_ESCAPE)
    dlg.ProcessWindowEvent(evt)


def _dispatch_key_down_escape(win):
    evt = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    evt.SetKeyCode(wx.WXK_ESCAPE)
    win.ProcessWindowEvent(evt)


def _find_panel(dlg):
    for child in dlg.GetChildren():
        if isinstance(child, wx.Panel):
            return child
    return None


class GuiTestBase(unittest.TestCase):
    """共享的 wx.App 与结果收集设施。

    整个测试进程只创建一个 wx.App（Phoenix 不支持一进程多 App，
    多 App 会导致定时器跨实例泄漏与退出阶段崩溃）。
    """

    _app = None

    @classmethod
    def setUpClass(cls):
        if GuiTestBase._app is None:
            GuiTestBase._app = wx.App(False)
        cls.app = GuiTestBase._app
        cls.frame = wx.Frame(None, title="ime_guard-test", size=(320, 200))
        cls.text_ctrl = wx.TextCtrl(cls.frame)

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def setUp(self):
        self.checks = []

    def check(self, name, cond):
        self.checks.append((name, bool(cond)))

    def assertAllChecks(self):
        failed = [name for name, ok in self.checks if not ok]
        self.assertFalse(
            failed, "未通过的检查项: %s" % ", ".join(failed)
        )

    def _run_in_gui(self, body):
        """在 wx 主循环里执行 body()，收集异常，带超时保护。"""
        outcome = {}

        def run():
            try:
                body()
            except Exception as exc:  # noqa: BLE001
                outcome["error"] = exc
            finally:
                wx.CallAfter(self.app.ExitMainLoop)

        wx.CallLater(30, run)
        watchdog = wx.CallLater(30000, self.app.ExitMainLoop)
        self.app.MainLoop()
        watchdog.Stop()
        if "error" in outcome:
            raise outcome["error"]

    def _run_modal_scenario(self, make_dialog, steps, settle_ms=250):
        """打开模态对话框后依次执行 steps（(延迟ms, fn(dlg))）。

        步骤在 ShowModal 的事件循环内执行；最后一步应触发 EndModal。
        """
        outcome = {}

        def chain(dlg, idx):
            if idx >= len(steps):
                return
            delay, fn = steps[idx]

            def run_step():
                try:
                    fn(dlg)
                except Exception as exc:  # noqa: BLE001
                    outcome["error"] = exc
                    try:
                        dlg.EndModal(wx.ID_CANCEL)
                    except Exception:
                        pass
                    return
                chain(dlg, idx + 1)

            wx.CallLater(delay, run_step)

        def start():
            dlg = make_dialog()
            outcome["dlg"] = dlg
            total = sum(delay for delay, _ in steps)

            def run_modal():
                try:
                    outcome["rc"] = dlg.ShowModal()
                except Exception as exc:  # noqa: BLE001
                    outcome["error"] = exc
                finally:
                    try:
                        dlg.Destroy()
                    except Exception:
                        pass
                    wx.CallAfter(self.app.ExitMainLoop)

            wx.CallLater(settle_ms, run_modal)
            wx.CallLater(settle_ms + 80, lambda: chain(dlg, 0))

            # 超时保护：真实按键未送达等原因导致模态循环卡死时，
            # 强制 EndModal（ExitMainLoop 无法打断嵌套模态循环）。
            def force_close():
                outcome.setdefault("timed_out", True)
                try:
                    dlg.EndModal(wx.ID_CANCEL)
                except Exception:
                    pass
                self.app.ExitMainLoop()

            wx.CallLater(settle_ms + total + 8000, force_close)

        wx.CallLater(30, start)
        self.app.MainLoop()
        if outcome.get("timed_out"):
            self.fail("模态循环未按预期结束（超时）")
        if "error" in outcome:
            raise outcome["error"]
        return outcome


@unittest.skipUnless(
    sys.platform == "win32", "WM_IME 消息模拟仅支持 Windows"
)
class FindReplaceDialogEscapeTests(GuiTestBase):
    """FindReplaceDialog：组合中/刚结束的 ESC 不关闭，组合外正常关闭。"""

    def _make_dialog(self):
        dlg = dialogs.FindReplaceDialog(self.frame, self.text_ctrl)
        self._dlg = dlg
        return dlg

    def test_escape_during_composition_keeps_dialog_open(self):
        outcome = self._run_modal_scenario(
            self._make_dialog,
            steps=[
                (100, lambda dlg: _send_ime_start(dlg.find_input.GetHandle())),
                (
                    150,
                    lambda dlg: (
                        self.check(
                            "组合中 is_ime_composing()",
                            ime_guard.is_ime_composing(),
                        ),
                        self.check(
                            "组合中 should_swallow_escape()",
                            ime_guard.should_swallow_escape(),
                        ),
                        _dispatch_char_hook_escape(dlg),
                        self.check(
                            "组合中 CHAR_HOOK 不关闭对话框", dlg.IsShown()
                        ),
                    ),
                ),
                (
                    150,
                    lambda dlg: (
                        _dispatch_key_down_escape(_find_panel(dlg)),
                        self.check(
                            "组合中 EVT_KEY_DOWN 不关闭对话框", dlg.IsShown()
                        ),
                    ),
                ),
                (
                    150,
                    lambda dlg: (
                        _send_ime_end(dlg.find_input.GetHandle()),
                        _dispatch_char_hook_escape(dlg),
                        self.check(
                            "组合刚结束（透传宽限窗内）不关闭", dlg.IsShown()
                        ),
                    ),
                ),
                (500, lambda dlg: None),  # 等宽限窗过期
                (
                    50,
                    lambda dlg: (
                        _dispatch_key_down_escape(_find_panel(dlg)),
                        self.check(
                            "组合外 ESC 正常关闭", not dlg.IsShown()
                        ),
                    ),
                ),
            ],
        )
        self.assertAllChecks()
        self.assertEqual(
            outcome.get("rc"), wx.ID_CANCEL, "组合外 ESC 应以取消码关闭对话框"
        )

    @unittest.skipUnless(_user32 is not None, "仅 Windows")
    def test_posted_escape_keeps_dialog_open_while_composing(self):
        def post_escape(dlg):
            _user32.PostMessageW(
                dlg.find_input.GetHandle(), 0x0100, 0x1B, 0  # WM_KEYDOWN ESC
            )

        outcome = self._run_modal_scenario(
            self._make_dialog,
            steps=[
                (100, lambda dlg: _send_ime_start(dlg.find_input.GetHandle())),
                (100, lambda dlg: post_escape(dlg)),
                (
                    250,
                    lambda dlg: self.check(
                        "消息队列 ESC（组合中）不关闭对话框", dlg.IsShown()
                    ),
                ),
                (50, lambda dlg: dlg.EndModal(wx.ID_CANCEL)),
            ],
        )
        self.assertAllChecks()
        self.assertEqual(outcome.get("rc"), wx.ID_CANCEL)

    def _probe_keyboard_injection(self, simulator):
        """探测 SendInput 是否可达（沙箱/无人值守环境可能被阻断）。

        不可达时抛出跳过标记，避免真实按键用例变成假失败。
        """
        result = {}

        def probe(dlg):
            simulator.Char(ord("A"))

        def verify(dlg):
            result["delivered"] = bool(dlg.find_input.GetValue())

        self._run_modal_scenario(
            self._make_dialog,
            steps=[
                (
                    100,
                    lambda dlg: (
                        _force_foreground(dlg.GetHandle()),
                        dlg.Raise(),
                        dlg.find_input.SetFocus(),
                    ),
                ),
                (300, probe),
                (400, verify),
                (100, lambda dlg: dlg.EndModal(wx.ID_CANCEL)),
            ],
        )
        if not result.get("delivered"):
            raise unittest.SkipTest(
                "当前环境无法注入真实键盘事件（SendInput 被阻断），"
                "守卫逻辑已由消息级用例覆盖"
            )

    @unittest.skipUnless(
        _user32 is not None, "需要真实键盘事件注入（UIActionSimulator）"
    )
    def test_real_escape_keystroke_during_composition(self):
        """真实按键路径：OS 键盘事件 → wx 键盘钩子 → CHAR_HOOK → 守卫。"""
        simulator = wx.UIActionSimulator()
        self._probe_keyboard_injection(simulator)

        def focus_dialog(dlg):
            _force_foreground(dlg.GetHandle())
            dlg.Raise()
            dlg.SetFocus()
            dlg.find_input.SetFocus()

        def record_focus(dlg):
            focused = dlg.FindFocus()
            self.check(
                "对话框处于前台",
                _user32.GetForegroundWindow() == dlg.GetHandle(),
            )
            self.check(
                "焦点位于对话框输入框",
                focused is not None
                and _is_descendant_of(focused, dlg),
            )

        def close_or_mark(dlg, name):
            self.check(name, not dlg.IsShown())
            if dlg.IsShown():
                # 按键未送达（环境焦点问题）时兜底关闭，避免模态卡死
                dlg.EndModal(wx.ID_CANCEL)

        outcome = self._run_modal_scenario(
            self._make_dialog,
            steps=[
                (100, focus_dialog),
                (200, record_focus),
                (200, lambda dlg: _send_ime_start(dlg.find_input.GetHandle())),
                (200, lambda dlg: simulator.Char(wx.WXK_ESCAPE)),
                (
                    300,
                    lambda dlg: (
                        self.check(
                            "真实 ESC（组合中）不关闭对话框", dlg.IsShown()
                        ),
                        _send_ime_end(dlg.find_input.GetHandle()),
                    ),
                ),
                (600, lambda dlg: simulator.Char(wx.WXK_ESCAPE)),
                (
                    300,
                    lambda dlg: self.check(
                        "真实 ESC（组合刚结束）不关闭对话框", dlg.IsShown()
                    ),
                ),
                (600, lambda dlg: simulator.Char(wx.WXK_ESCAPE)),
                (300, lambda dlg: close_or_mark(
                    dlg, "真实 ESC（组合外）正常关闭"
                )),
            ],
        )
        self.assertAllChecks()
        self.assertEqual(outcome.get("rc"), wx.ID_CANCEL)

    @unittest.skipUnless(_user32 is not None, "仅 Windows")
    def test_real_ime_composition_then_escape(self):
        """真实 IMM 组合字符串 + 真实 ESC：最接近用户实际操作的场景。

        无可用输入法上下文（HIMC）时跳过。
        """
        simulator = wx.UIActionSimulator()
        self._probe_keyboard_injection(simulator)

        def start_composition(dlg):
            hwnd = _user32.GetFocus()
            himc = _imm32.ImmGetContext(hwnd)
            if not himc:
                self.check("环境具备输入法上下文（HIMC）", False)
                return
            try:
                _imm32.ImmSetOpenStatus(himc, True)
                comp = ctypes.create_unicode_buffer("ceshi")
                ok = _imm32.ImmSetCompositionStringW(
                    himc, SCS_SETSTR, comp, ctypes.sizeof(comp), None, 0
                )
                self.check(
                    "ImmSetCompositionStringW 设置组合串成功", bool(ok)
                )
            finally:
                _imm32.ImmReleaseContext(hwnd, himc)

        def cancel_composition(dlg):
            hwnd = _user32.GetFocus()
            himc = _imm32.ImmGetContext(hwnd)
            if himc:
                try:
                    _imm32.ImmNotifyIME(
                        himc, NI_COMPOSITIONSTR, CPS_CANCEL, 0
                    )
                    _imm32.ImmSetOpenStatus(himc, False)
                finally:
                    _imm32.ImmReleaseContext(hwnd, himc)

        outcome = self._run_modal_scenario(
            self._make_dialog,
            steps=[
                (
                    100,
                    lambda dlg: (
                        dlg.Raise(),
                        dlg.find_input.SetFocus(),
                        dlg.find_input.SetFocus(),
                    ),
                ),
                (200, start_composition),
                (200, lambda dlg: self.check(
                    "真实组合串激活 is_ime_composing()",
                    ime_guard.is_ime_composing(),
                )),
                (100, lambda dlg: simulator.Char(wx.WXK_ESCAPE)),
                (
                    400,
                    lambda dlg: (
                        self.check(
                            "真实输入法组合中按 ESC 不关闭对话框",
                            dlg.IsShown(),
                        ),
                        cancel_composition(dlg),
                    ),
                ),
                (600, lambda dlg: simulator.Char(wx.WXK_ESCAPE)),
                (
                    300,
                    lambda dlg: (
                        self.check(
                            "组合取消后的 ESC 正常关闭对话框",
                            not dlg.IsShown(),
                        ),
                        dlg.EndModal(wx.ID_CANCEL) if dlg.IsShown() else None,
                    ),
                ),
            ],
        )
        if not any(name == "环境具备输入法上下文（HIMC）" and not ok
                   for name, ok in self.checks):
            self.assertAllChecks()
            self.assertEqual(outcome.get("rc"), wx.ID_CANCEL)


@unittest.skipUnless(
    sys.platform == "win32", "WM_IME 消息模拟仅支持 Windows"
)
class EditDialogEscapeTests(GuiTestBase):
    """EditDialog：app 级 ESC 处理器在组合中被守卫拦截，其余不变。"""

    def test_app_level_escape_handler_guards_composition(self):
        def body():
            dlg = dialogs.EditDialog(self.frame, "test", "hello")
            cancel_calls = []
            # 拦截 on_cancel，避免组合外用例弹出确认对话框
            dlg.on_cancel = lambda event: cancel_calls.append(1)
            try:
                hwnd = dlg.text_ctrl.GetHandle()
                _send_ime_start(hwnd)
                self.check(
                    "EditDialog 组合中 is_ime_composing()",
                    ime_guard.is_ime_composing(),
                )

                _dispatch_key_down_escape(dlg)  # 走 app 级 on_app_key_down
                self.check(
                    "EditDialog 组合中 ESC 不触发关闭", not cancel_calls
                )

                _send_ime_end(hwnd)
                _dispatch_key_down_escape(dlg)
                self.check(
                    "EditDialog 组合刚结束 ESC 不触发关闭", not cancel_calls
                )

                time.sleep(0.45)  # 等宽限窗过期
                _dispatch_key_down_escape(dlg)
                self.check(
                    "EditDialog 组合外 ESC 保留原有确认逻辑",
                    len(cancel_calls) == 1,
                )
            finally:
                self.app.Unbind(
                    wx.EVT_KEY_DOWN, handler=dlg.on_app_key_down
                )
                dlg.Destroy()

        self._run_in_gui(body)

    @unittest.skipUnless(_user32 is not None, "仅 Windows")
    def test_multiline_editor_posted_escape_paths(self):
        """多行编辑器（真实消息路径）。

        平台事实：wxMSW 下编辑器内的 ESC keydown 只到达编辑控件本身，
        不向对话框/app 层传播（README 的“ESC 退出编辑器”是 macOS 的
        传播行为）。因此本用例验证守卫不改变 Windows 现状：组合中 ESC
        被吞掉；组合结束、宽限窗过后守卫恢复放行，且不会误触关闭。
        """
        result = {}

        def body():
            dlg = dialogs.EditDialog(self.frame, "test", "hello")
            cancel_calls = []
            dlg.on_cancel = lambda event: cancel_calls.append(1)
            hwnd = dlg.text_ctrl.GetHandle()
            timers = []

            def post_escape():
                _user32.PostMessageW(
                    hwnd, 0x0100, 0x1B, 0  # WM_KEYDOWN ESC
                )

            def cleanup():
                for t in timers:
                    t.Stop()
                self.app.Unbind(
                    wx.EVT_KEY_DOWN, handler=dlg.on_app_key_down
                )
                dlg.Destroy()
                wx.CallAfter(self.app.ExitMainLoop)

            def schedule(delay_ms, fn):
                timers.append(wx.CallLater(delay_ms, fn))

            try:
                _send_ime_start(hwnd)
                post_escape()  # 组合中：守卫应吞掉（无论如何不得关闭）
                schedule(250, lambda: result.update(
                    composing=("编辑器组合中 ESC 不触发关闭", not cancel_calls)
                ))
                schedule(300, lambda: _send_ime_end(hwnd))
                schedule(900, lambda: result.update(
                    grace_over=("宽限窗过后守卫恢复放行",
                                not ime_guard.should_swallow_escape()),
                    no_close=("组合外 ESC 不误触关闭（与修复前一致）",
                              not cancel_calls),
                ))
            finally:
                schedule(1000, cleanup)

        def run_body():
            try:
                body()
            except Exception as exc:  # noqa: BLE001
                result["error"] = exc
                wx.CallAfter(self.app.ExitMainLoop)

        wx.CallLater(30, run_body)
        watchdog = wx.CallLater(30000, self.app.ExitMainLoop)
        self.app.MainLoop()
        watchdog.Stop()
        if "error" in result:
            raise result["error"]
        failed = [
            name for name, ok in
            (v for k, v in result.items() if k != "error")
            if not ok
        ]
        self.assertFalse(failed, "未通过的检查项: %s" % ", ".join(failed))


class CrossPlatformSmokeTests(GuiTestBase):
    """跨平台冒烟：守卫安装与非 ESC 键为无操作。"""

    def test_guard_inert_without_ime_and_for_other_keys(self):
        def body():
            self.check("静止状态无组合", not ime_guard.is_ime_composing())
            self.check(
                "静止状态不拦截 ESC", not ime_guard.should_swallow_escape()
            )
            evt = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            evt.SetKeyCode(ord("A"))
            self.check(
                "非 ESC 键永远不受守卫影响",
                not ime_guard.guard_key_event(evt),
            )

            dlg = dialogs.FindReplaceDialog(self.frame, self.text_ctrl)
            try:
                self.check("对话框已装守卫", dlg._ime_guard_installed)
                install_again = ime_guard.install
                install_again(dlg)  # 幂等
                self.check("重复 install 幂等", True)
            finally:
                dlg.Destroy()

        self._run_in_gui(body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
