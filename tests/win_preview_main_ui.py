"""Windows 开发机主界面预览脚本

桩替换 macOS 专属依赖（appscript/llama_cpp/objc/AppKit）并将 VolumeController
替换为空实现后，加载真实 main_UI.MainFrame 显示主窗口，延时截图保存为
preview_main_ui.png 供检查外观；可传页索引切换选项卡后再截图（0-3）。
仅 UI 预览用，不验证 macOS 专属功能。
用法：python tests/win_preview_main_ui.py [页索引]
"""
import os
import subprocess
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 伪造 ioreg 输出：setting.py 导入期读取机器 UUID 派生配置加密键（macOS 专属命令）
_real_subprocess_run = subprocess.run


def _fake_subprocess_run(cmd, *args, **kwargs):
    if isinstance(cmd, list) and cmd and cmd[0] == 'ioreg':
        fake = mock.Mock(returncode=0)
        fake.stdout = '    "IOPlatformUUID" = "00000000-0000-0000-0000-PREVIEWMACHINE"'
        return fake
    return _real_subprocess_run(cmd, *args, **kwargs)


subprocess.run = _fake_subprocess_run

# 桩替换 macOS 专属顶层依赖
_fake_appscript = types.ModuleType("appscript")
_fake_appscript.app = lambda *a, **k: mock.MagicMock()
sys.modules.setdefault("appscript", _fake_appscript)

_fake_llama_cpp = types.ModuleType("llama_cpp")
_fake_llama_cpp.Llama = type("Llama", (), {})
sys.modules.setdefault("llama_cpp", _fake_llama_cpp)

sys.modules.setdefault("objc", types.ModuleType("objc"))

_fake_appkit = types.ModuleType("AppKit")
_fake_appkit.NSApplication = mock.MagicMock
_fake_appkit.NSApp = mock.MagicMock
_fake_appkit.NSWindow = mock.MagicMock
sys.modules.setdefault("AppKit", _fake_appkit)

import processer  # noqa: E402


class _StubVolumeController:
    """Windows 预览用空实现：替代 CoreAudio 音量控制器"""
    def __init__(self, *args, **kwargs):
        pass

    def set_config(self, limit, target):
        pass

    def start_worker(self, callback=None):
        pass


processer.VolumeController = _StubVolumeController
# 剪贴板监视线程依赖 NSPasteboard，Windows 下仅产生异常日志噪音，预览时静音
processer.ClipboardMonitor.start_worker = lambda self, callback=None: None

import wx  # noqa: E402
import main_UI  # noqa: E402

# 预览时不做启动更新检查，避免网络慢时模态弹窗阻塞截图
main_UI.MainFrame._check_update_on_startup = lambda self: None


def capture(frame, out_path):
    """截取窗口所在屏幕区域并保存 PNG"""
    wx.Yield()
    rect = frame.GetScreenRect()
    bmp = wx.Bitmap(rect.width, rect.height, 32)
    mem = wx.MemoryDC(bmp)
    mem.Blit(0, 0, rect.width, rect.height, wx.ScreenDC(), rect.x, rect.y)
    mem.SelectObject(wx.NullBitmap)
    bmp.SaveFile(out_path, wx.BITMAP_TYPE_PNG)
    print(f"截图已保存: {out_path}, current_module={frame.current_module}")


def main():
    page = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    app = wx.App(False)
    frame = main_UI.MainFrame(None, "MagicToolbox")
    frame.Show()

    def snap():
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           f"preview_main_ui_p{max(page, 0)}.png")
        try:
            # 窗口钳制到屏幕内，避免截图区域越界出现黑边
            sw, sh = wx.GetDisplaySize()
            fw = min(frame.GetSize().width, sw)
            fh = min(frame.GetSize().height, sh)
            frame.SetSize(fw, fh)
            frame.Move(0, 0)
            # 传页索引时走真实的选项卡切换事件链（SetSelection 会触发页面切换事件）
            if 0 <= page < frame.notebook.GetPageCount():
                frame.notebook.SetSelection(page)
                wx.Yield()
            capture(frame, out)
        except Exception as e:
            # Windows 预览环境特有断言（如工具栏空位图工具在 wxMSW 的断言，macOS 无此问题）：
            # 打印后仍尝试截图，保证预览不中断
            print(f"预览环境异常（不影响 macOS）: {e}")
            try:
                capture(frame, out)
            except Exception as e2:
                print(f"截图失败: {e2}")
        finally:
            wx.CallAfter(wx.GetApp().ExitMainLoop)

    wx.CallLater(2500, snap)
    app.MainLoop()
    # 跳过 macOS 专属的退出清理（on_exit 依赖 appscript/NSWorkspace 等）
    os._exit(0)


if __name__ == "__main__":
    main()
