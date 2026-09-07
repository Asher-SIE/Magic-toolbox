"""IME 感知的 Escape 守卫（模态对话框防误关）。

问题背景
--------
用户在输入法组合（拼音/假名等未上屏字符串）过程中按 ESC，本意是取消
组合或候选，但 wx 的模态对话框会被直接关闭，已输入内容随对话框一起
丢失。这是 wxWidgets 的实现缺口而非系统限制：

* macOS：``wxWidgetCocoaImpl::DoHandleKeyEvent``（src/osx/cocoa/window.mm）
  在 ``interpretKeyEvents:``（把按键交给输入法的调用）**之前**生成
  ``wxEVT_CHAR_HOOK``，而 ``wxDialogBase::OnCharHook``
  （src/common/dlgcmn.cpp）对 ESC 无任何组合文本检查，于是对话框先于
  输入法消费了 ESC，组合根本没有机会被取消。
* Windows：wxMSW 的键盘钩子仅在 ``WM_IME_STARTCOMPOSITION`` 之后
  （组合仍激活）抑制 CHAR_HOOK（上游 #11386 的修复）。但现代 Windows
  输入法在用 ESC 取消组合后会把 ESC 作为普通 ``WM_KEYDOWN`` 透传给
  应用，此时防护已解除，ESC 照常触发 wxDialogBase 的“ESC = 取消”逻辑。

系统本身提供了区分“取消组合的 ESC”与“真正的 ESC”所需的全部信息
（Windows 的 ``WM_IME_*`` 消息与 IMM API；macOS 的 ``hasMarkedText``），
Qt、Chromium 等都据此正确处理，wx 未完全做到。本模块在应用层补齐：

* Windows：子类化对话框内各控件的原生窗口过程，跟踪
  ``WM_IME_STARTCOMPOSITION`` / ``WM_IME_COMPOSITION`` /
  ``WM_IME_ENDCOMPOSITION`` 生命周期；判定“组合中”或“组合刚结束”
  （短暂宽限窗，覆盖透传的 ESC）。另有 IMM 实时查询兜底。
* macOS：查询 keyWindow firstResponder 的 ``hasMarkedText``。由于 wx
  在 CHAR_HOOK 层拦截后 ``interpretKeyEvents:`` 不会被调用，输入法
  收不到 ESC，因此拦截时需代为调用 ``unmarkText()`` 取消组合，以还原
  原生行为。

对外接口
--------
``install(dialog)``
    给（模态）对话框装上 CHAR_HOOK 守卫，阻止组合期间的 ESC 关闭
    对话框；其余按键行为不变。
``guard_key_event(event)``
    供自定义 ``EVT_KEY_DOWN`` 处理器调用：返回 True 表示该 ESC 属于
    IME 取消操作、应被忽略（调用方直接 return，不要执行关闭逻辑）。
``is_ime_composing()`` / ``should_swallow_escape()``
    平台无关的组合状态查询。
"""

import logging
import sys
import time

import wx

__all__ = [
    "install",
    "guard_key_event",
    "is_ime_composing",
    "should_swallow_escape",
]

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

# 组合结束后仍拦截 ESC 的宽限窗（秒）。现代 Windows 输入法取消组合后
# 会紧跟着把 ESC 透传给应用（通常在同一轮消息循环内，间隔远小于此值）；
# 若用户确实是完成上屏后立刻想关对话框，多按一次 ESC 即可，与
# Chromium 等的处理方式一致。
_COMPOSITION_END_GRACE = 0.35

# ---------------------------------------------------------------------------
# 状态跟踪
# ---------------------------------------------------------------------------

_composing = False          # 最近一次消息指示组合仍激活
_last_composition_end = 0.0  # 组合结束时刻（monotonic），0 表示从未开始


def is_ime_composing(win=None):
    """输入法组合（未上屏字符串）当前是否处于激活状态。"""
    if _IS_WINDOWS:
        return _win_is_composing()
    if _IS_MACOS:
        return _mac_has_marked_text()
    return False


def should_swallow_escape():
    """此刻的 ESC 是否应视为“取消输入法组合”而忽略。"""
    if is_ime_composing():
        return True
    if _IS_WINDOWS and _last_composition_end:
        return (time.monotonic() - _last_composition_end) < _COMPOSITION_END_GRACE
    return False


# ---------------------------------------------------------------------------
# Windows：WndProc 子类化跟踪 WM_IME_* 生命周期 + IMM 实时查询兜底
# ---------------------------------------------------------------------------

if _IS_WINDOWS:
    import ctypes
    import atexit
    from ctypes import wintypes

    _WM_IME_STARTCOMPOSITION = 0x010D
    _WM_IME_ENDCOMPOSITION = 0x010E
    _WM_IME_COMPOSITION = 0x010F
    _WM_NCDESTROY = 0x0082
    _GCS_COMPSTR = 0x0008
    _GWLP_WNDPROC = -4

    _LRESULT = ctypes.c_ssize_t
    _WNDPROC = ctypes.WINFUNCTYPE(
        _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    )

    _user32 = ctypes.windll.user32
    _imm32 = ctypes.windll.imm32

    if hasattr(_user32, "SetWindowLongPtrW"):
        _getWndProc = _user32.GetWindowLongPtrW
        _setWndProc = _user32.SetWindowLongPtrW
    else:  # 32 位回退
        _getWndProc = _user32.GetWindowLongW
        _setWndProc = _user32.SetWindowLongW
    _getWndProc.restype = _LRESULT
    _getWndProc.argtypes = [wintypes.HWND, ctypes.c_int]
    _setWndProc.restype = _LRESULT
    _setWndProc.argtypes = [wintypes.HWND, ctypes.c_int, _LRESULT]
    _user32.CallWindowProcW.restype = _LRESULT
    _user32.CallWindowProcW.argtypes = [
        _LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]

    _watched = {}  # hwnd -> 原窗口过程地址

    def _unwatch(hwnd):
        """恢复原窗口过程（必须在窗口销毁前调用）。"""
        old_proc = _watched.pop(hwnd, None)
        if old_proc is None:
            return None
        _setWndProc(hwnd, _GWLP_WNDPROC, old_proc)
        return old_proc

    @_WNDPROC
    def _ime_wnd_proc(hwnd, msg, wparam, lparam):
        # 只观察消息，不改变其走向；异常绝不能外泄到原生消息循环。
        try:
            global _composing, _last_composition_end
            if msg in (_WM_IME_STARTCOMPOSITION, _WM_IME_COMPOSITION):
                _composing = True
            elif msg == _WM_IME_ENDCOMPOSITION:
                _composing = False
                _last_composition_end = time.monotonic()
            elif msg == _WM_NCDESTROY:
                # 窗口销毁路径上恢复原过程，避免悬空回调。
                old_proc = _unwatch(hwnd)
                if old_proc is not None:
                    return _user32.CallWindowProcW(
                        old_proc, hwnd, msg, wparam, lparam
                    )
        except Exception:
            logging.exception("ime_guard: 处理 WM_IME 消息失败")
        old_proc = _watched.get(hwnd)
        if old_proc is not None:
            return _user32.CallWindowProcW(old_proc, hwnd, msg, wparam, lparam)
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _watch_hwnd(hwnd):
        if not hwnd or hwnd in _watched:
            return
        old_proc = _getWndProc(hwnd, _GWLP_WNDPROC)
        if not old_proc:
            return
        _watched[hwnd] = old_proc
        proc_addr = ctypes.cast(_ime_wnd_proc, ctypes.c_void_p).value
        _setWndProc(hwnd, _GWLP_WNDPROC, proc_addr)

    def _watch_tree(win):
        """递归子类化窗口及其所有子控件的原生窗口过程。"""
        try:
            _watch_hwnd(win.GetHandle())
        except Exception:
            pass
        for child in win.GetChildren():
            _watch_tree(child)

    def _unwatch_all():
        """进程退出前恢复全部窗口过程，避免解释器析构阶段回调进 Python。"""
        for hwnd in list(_watched):
            try:
                _unwatch(hwnd)
            except Exception:
                pass

    atexit.register(_unwatch_all)

    def _win_is_composing():
        # 子类化跟踪的状态优先；再用 IMM 对当前焦点窗口做实时查询兜底
        # （覆盖未被跟踪的窗口，例如守卫安装后才创建的控件）。
        if _composing:
            return True
        try:
            hwnd = _user32.GetFocus()
            if not hwnd:
                return False
            himc = _imm32.ImmGetContext(hwnd)
            if not himc:
                return False
            try:
                if not _imm32.ImmGetOpenStatus(himc):
                    return False
                _imm32.ImmGetCompositionStringW.restype = ctypes.c_int
                _imm32.ImmGetCompositionStringW.argtypes = [
                    ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
                ]
                size = _imm32.ImmGetCompositionStringW(
                    himc, _GCS_COMPSTR, None, 0
                )
                return bool(size and size > 0)
            finally:
                _imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            return False

# ---------------------------------------------------------------------------
# macOS：通过 pyobjc 查询 firstResponder 的组合（marked text）状态
# ---------------------------------------------------------------------------

if _IS_MACOS:
    def _mac_first_responder():
        try:
            from AppKit import NSApp
        except Exception:
            return None
        try:
            key_window = NSApp.keyWindow()
            return key_window.firstResponder() if key_window else None
        except Exception:
            return None

    def _mac_has_marked_text():
        responder = _mac_first_responder()
        if responder is None:
            return False
        try:
            return bool(
                responder.respondsToSelector_("hasMarkedText")
                and responder.hasMarkedText()
            )
        except Exception:
            return False

    def _mac_cancel_composition():
        # wx 在 CHAR_HOOK 层拦截 ESC 后，事件不会再经 interpretKeyEvents:
        # 交给输入法，组合不会被取消；这里代为执行与 ESC 等效的
        # unmarkText，还原原生“ESC 取消组合”的行为。
        responder = _mac_first_responder()
        if responder is None:
            return
        try:
            if responder.respondsToSelector_("unmarkText"):
                responder.unmarkText()
        except Exception:
            logging.exception("ime_guard: 取消输入法组合失败")

# ---------------------------------------------------------------------------
# 守卫接入
# ---------------------------------------------------------------------------

def _on_dialog_char_hook(event):
    if event.GetKeyCode() == wx.WXK_ESCAPE and should_swallow_escape():
        if _IS_MACOS:
            _mac_cancel_composition()
        # 不调用 Skip：终止事件，阻止 wxDialogBase::OnCharHook 的
        # “ESC = 关闭对话框”逻辑；Windows 键盘钩子据此还会拦下随后的
        # WM_KEYDOWN，自定义的 EVT_KEY_DOWN 处理器不会收到该键。
        return
    event.Skip()


def install(dialog):
    """给对话框装上 ESC 守卫。须在控件创建完成后调用（对话框 __init__ 末尾）。

    对非 Windows/macOS 平台是无害的空操作（守卫条件永远不成立）。
    """
    if getattr(dialog, "_ime_guard_installed", False):
        return
    dialog._ime_guard_installed = True
    dialog.Bind(wx.EVT_CHAR_HOOK, _on_dialog_char_hook)
    if _IS_WINDOWS:
        _watch_tree(dialog)


def guard_key_event(event):
    """自定义 EVT_KEY_DOWN 处理器的 ESC 守卫。

    返回 True 表示该 ESC 属于 IME 取消操作：调用方应直接 return（不要
    Skip、不要执行关闭逻辑）。返回 False 时按原逻辑继续处理。
    """
    if event.GetKeyCode() == wx.WXK_ESCAPE and should_swallow_escape():
        if _IS_MACOS:
            _mac_cancel_composition()
        return True
    return False
