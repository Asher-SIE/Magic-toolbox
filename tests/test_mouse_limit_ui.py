import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

class _FakeAXElement:
    """模拟 AXUIElement：仅支持测试所需的四个属性"""

    def __init__(self, role, parent=None, position=None, size=None):
        self._role = role
        self._parent = parent
        self._position = position
        self._size = size

    def ax_attr(self, attribute):
        if attribute == "AXRole":
            return (0, self._role)
        if attribute == "AXParent":
            return (0, self._parent) if self._parent is not None else (1, None)
        if attribute == "AXPosition":
            return (0, self._position) if self._position is not None else (1, None)
        if attribute == "AXSize":
            return (0, self._size) if self._size is not None else (1, None)
        return (1, None)


@unittest.skipUnless(sys.platform == "win32", "依赖 Windows 预览桩环境（win_preview_main_ui）")
class MouseLimitUITests(unittest.TestCase):
    """鼠标限制与坐标播报的界面层功能测试：开关切换、越界吸附、Ctrl 播报节流、持久化"""

    @classmethod
    def setUpClass(cls):
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        # 导入预览模块完成 macOS 专属依赖的桩替换
        import win_preview_main_ui as preview
        import setting
        import wx
        cls._wx = wx
        cls._preview = preview
        cls._setting = setting
        # 配置文件指向临时目录，避免测试写坏真实用户配置
        cls._tmp_home = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp_home.cleanup)
        cls._config_dir = os.path.join(cls._tmp_home.name, "MagicToolbox")
        os.makedirs(cls._config_dir, exist_ok=True)
        patcher = mock.patch.object(setting, "config_path", os.path.join(cls._config_dir, "config.json"))
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        cls.app = wx.App(False)
        cls.frame = preview.main_UI.MainFrame(None, "MagicToolbox")
        cls.frame.Hide()
        # 测试期间停掉轮询定时器，改为直接调用轮询方法保证确定性
        cls.frame._mouse_poll_timer.Stop()
        cls.addClassCleanup(cls.frame.Destroy)

    @classmethod
    def tearDownClass(cls):
        cls.app = None

    def setUp(self):
        import setting
        setting.mouse_limit_enabled = False
        self.frame._mouse_limit_active = False
        self.frame._mouse_limit_origin = None
        self.frame._mouse_limit_display = None
        self.frame._last_announce_pos = None
        self.frame._announce_flags_error_logged = False
        self.frame._mouse_lock_key_pressed = False
        self.frame._lock_key_error_logged = False
        self.frame._mouse_limit_auto_fit = True
        self.frame._mouse_limit_fitted_rect = None
        self.frame._mouse_limit_width = 1000
        self.frame._mouse_limit_height = 50
        self.positions = []
        self.warps = []
        self.speech = []
        self.frame._get_mouse_position = lambda: self.positions[-1] if self.positions else None
        self.frame._move_mouse_to = lambda x, y: (self.warps.append((x, y)) or True)
        self.frame.vo_handler.speak_text = lambda text: self.speech.append(text)

    def _set_mouse_position(self, x, y):
        self.positions.append((x, y))

    def _install_quartz_stub(self, flags, grave_down=False):
        import main_UI as main_ui_mod
        stub = types.ModuleType("Quartz")
        stub.kCGEventSourceStateCombinedSessionState = 0
        stub.kCGEventFlagMaskControl = 1 << 18
        stub.kCGEventFlagMaskAlternate = 1 << 19
        stub.kCGEventFlagMaskShift = 1 << 17
        stub.CGEventSourceFlagsState = lambda source: flags
        stub.CGEventSourceKeyState = lambda state, key: grave_down and key == main_ui_mod.MOUSE_LOCK_KEYCODE
        sys.modules["Quartz"] = stub
        self.addCleanup(sys.modules.pop, "Quartz", None)

    def _read_saved_config(self):
        with open(self._setting.config_path, encoding="utf-8") as f:
            return json.load(f)

    def test_enable_disable_and_persist(self):
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_limit_check.SetValue(False)

        self.frame.mouse_lock_enable()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertEqual(self.frame._mouse_limit_origin, (500.0, 300.0))
        self.assertTrue(self.frame.mouse_limit_check.GetValue())
        self.assertIn("区域锁定开", self.speech)
        self.assertTrue(self._read_saved_config()["mouse_limit_enabled"])

        # 共用切换入口（轮询按键边沿与复选框共用）：关闭
        self.frame._mouse_lock_toggle()
        self.assertFalse(self.frame._mouse_limit_active)
        self.assertIsNone(self.frame._mouse_limit_origin)
        self.assertFalse(self.frame.mouse_limit_check.GetValue())
        self.assertIn("区域锁定关", self.speech)
        self.assertFalse(self._read_saved_config()["mouse_limit_enabled"])

        # 复选框切换：开启与关闭
        self.frame.on_mouse_limit_check(types.SimpleNamespace(IsChecked=lambda: True, Skip=lambda: None))
        self.assertTrue(self.frame._mouse_limit_active)
        self.frame.on_mouse_limit_check(types.SimpleNamespace(IsChecked=lambda: False, Skip=lambda: None))
        self.assertFalse(self.frame._mouse_limit_active)

    def test_enable_without_mouse_position_fails(self):
        # 读取坐标失败时不开启，复选框保持未勾选
        self.frame.mouse_lock_enable()
        self.assertFalse(self.frame._mouse_limit_active)
        self.assertFalse(self.frame.mouse_limit_check.GetValue())
        self.assertIn("读取鼠标坐标失败", self.speech)

    def test_snap_pulls_back_to_boundary(self):
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_lock_enable()
        self.warps.clear()

        # 区域为 (500,300)-(1500,350)：越界点吸附到右/下边界
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1500.0, 350.0)])

        # 界内点不触发拉回
        self.warps.clear()
        self._set_mouse_position(1000.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [])

        # 修改宽度即时生效，且右边界收缩贴合屏幕
        self.frame.mouse_limit_width_input.SetValue("2000")
        self.frame.on_mouse_limit_width_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.assertEqual(self.frame._mouse_limit_width, 2000)
        self._set_mouse_position(1800.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [])
        self._set_mouse_position(2000.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1920.0, 320.0)])

    def test_focus_lost_sanitizes_invalid_input(self):
        # 非法输入（清空/0/非数字）还原为当前生效值
        self.frame.mouse_limit_width_input.SetValue("")
        self.frame.on_mouse_limit_width_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.assertEqual(self.frame._mouse_limit_width, 1000)
        self.assertEqual(self.frame.mouse_limit_width_input.GetValue(), "1000")
        self.frame.mouse_limit_height_input.SetValue("abc")
        self.frame.on_mouse_limit_height_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.assertEqual(self.frame._mouse_limit_height, 50)
        # 合法输入保存并即时生效
        self.frame.mouse_limit_height_input.SetValue("80")
        self.frame.on_mouse_limit_height_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.assertEqual(self.frame._mouse_limit_height, 80)
        self.assertEqual(self._read_saved_config()["mouse_limit_height"], 80)

    def _install_ax_stub(self, hit_element):
        """安装带 AX 函数的 Quartz 桩：hit_element 为元素或 (x, y)->元素 回调，None 表示未命中"""
        stub = types.ModuleType("Quartz")
        stub.kCGEventSourceStateCombinedSessionState = 0
        stub.kCGEventFlagMaskControl = 1 << 18
        stub.CGEventSourceFlagsState = lambda source: 0
        stub.AXUIElementCreateSystemWide = lambda: object()

        def _hit(system, x, y):
            element = hit_element(x, y) if callable(hit_element) else hit_element
            return (0, element) if element is not None else (1, None)

        stub.AXUIElementCopyElementAtPosition = _hit
        stub.AXUIElementCopyAttributeValue = lambda element, attribute: element.ax_attr(attribute)
        sys.modules["Quartz"] = stub
        self.addCleanup(sys.modules.pop, "Quartz", None)

    @staticmethod
    def _make_ax_chain():
        """构造 内部文本 -> AXSlider 的元素链，滑块位于 (500,300) 尺寸 1000x50"""
        slider = _FakeAXElement("AXSlider",
                                position=types.SimpleNamespace(x=500.0, y=300.0),
                                size=types.SimpleNamespace(width=1000.0, height=50.0))
        inner = _FakeAXElement("AXStaticText", parent=slider,
                               position=types.SimpleNamespace(x=600.0, y=310.0),
                               size=types.SimpleNamespace(width=10.0, height=20.0))
        return slider, inner

    def test_ctrl_announce_flow(self):
        # 未按住 Ctrl：不播报
        self._install_quartz_stub(0)
        self._set_mouse_position(100.0, 200.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])
        self.assertIsNone(self.frame._last_announce_pos)

        # 按住 Ctrl 不动：静默记录基准，不播报
        self._install_quartz_stub(1 << 18)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])

        # 移动不足精度阈值不播报
        self._set_mouse_position(103.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])

        # 任一轴移动达到 5 像素开始播报
        self._set_mouse_position(105.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["105, 202"])

        # 松开 Ctrl 清空记录；再次按住仍静默，需重新移动才播报
        self._install_quartz_stub(0)
        self.frame._poll_mouse_coord_announce()
        self._install_quartz_stub(1 << 18)
        self._set_mouse_position(106.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["105, 202"])
        self._set_mouse_position(111.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["105, 202", "111, 202"])

    def test_autofit_slider(self):
        # 命中滑块（经由内部文本沿父链向上找到 AXSlider）：矩形取滑块外接框并外扩 2 像素
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        slider, inner = self._make_ax_chain()
        button = _FakeAXElement("AXButton")
        self._install_ax_stub(lambda x, y: inner if 500 <= x <= 1500 and 300 <= y <= 350 else button)

        self.frame.mouse_lock_enable()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertEqual(self.frame._mouse_limit_fitted_rect, (498.0, 298.0, 1502.0, 352.0))
        self.assertIn("适配滑块宽度1000，高度50", self.speech[-1])

        # 吸附按适配矩形拉回
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1502.0, 352.0)])

        # 适配矩形不随宽高输入变化
        self.frame.mouse_limit_width_input.SetValue("100")
        self.frame.on_mouse_limit_width_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.warps.clear()
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1502.0, 352.0)])

        # 关闭后清除适配矩形
        self.frame.mouse_lock_disable()
        self.assertIsNone(self.frame._mouse_limit_fitted_rect)

    def test_autofit_falls_back_without_slider(self):
        # 命中的不是滑块（也无滑块祖先）时回退手动宽高
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        button = _FakeAXElement("AXButton")
        self._install_ax_stub(lambda x, y: button)
        self.frame.mouse_lock_enable()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertIsNone(self.frame._mouse_limit_fitted_rect)
        self.assertIn("区域锁定开", self.speech)

    def test_autofit_disabled_uses_manual_rect(self):
        # 复选框关闭时即使命中滑块也走手动宽高
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        slider, inner = self._make_ax_chain()
        self._install_ax_stub(lambda x, y: inner)
        self.frame.on_mouse_limit_autofit_check(types.SimpleNamespace(IsChecked=lambda: False, Skip=lambda: None))
        self.frame.mouse_lock_enable()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertIsNone(self.frame._mouse_limit_fitted_rect)
        # 手动矩形：(500,300) + 1000x50
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1500.0, 350.0)])

    def test_lock_key_poll_toggles(self):
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        mods = (1 << 19) | (1 << 17)  # option + shift

        # 无修饰键按波浪号：不触发
        self._install_quartz_stub(0, grave_down=True)
        self.frame._poll_mouse_lock_key()
        self.assertFalse(self.frame._mouse_limit_active)

        # opt+shift+波浪号 按下边沿：开启
        self._install_quartz_stub(mods, grave_down=True)
        self.frame._poll_mouse_lock_key()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertIn("区域锁定开", self.speech)

        # 持续按住不重复触发
        self.frame._poll_mouse_lock_key()
        self.assertTrue(self.frame._mouse_limit_active)
        self.assertEqual(self.speech.count("区域锁定开"), 1)

        # 松开后再次按下：关闭
        self._install_quartz_stub(0, grave_down=False)
        self.frame._poll_mouse_lock_key()
        self._install_quartz_stub(mods, grave_down=True)
        self.frame._poll_mouse_lock_key()
        self.assertFalse(self.frame._mouse_limit_active)
        self.assertIn("区域锁定关", self.speech)

    def test_ax_trusted_hint_when_untrusted(self):
        fake = types.ModuleType("ApplicationServices")
        fake.AXIsProcessTrustedWithOptions = lambda options: False
        fake.kAXTrustedCheckOptionPrompt = "AXTrustedCheckOptionPrompt"
        sys.modules["ApplicationServices"] = fake
        self.addCleanup(sys.modules.pop, "ApplicationServices", None)

        # 未授权：检查返回 False 并播报权限提示
        self.assertFalse(self.frame._check_ax_trusted(prompt=True))
        # assertIn 对列表是整串相等判断，播报为完整长句，须用子串匹配
        self.assertTrue(any("需要辅助功能权限" in s for s in self.speech))

        # 读坐标失败且未授权时：开启播报权限提示而非坐标失败
        self.assertFalse(self.frame.mouse_lock_enable())
        self.assertFalse(self.frame._mouse_limit_active)
        self.assertNotIn("读取鼠标坐标失败", self.speech)



if __name__ == "__main__":
    unittest.main()
