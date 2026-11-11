import json
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

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
        self.frame._mouse_limit_last_warp = 0.0
        self.frame._last_pull_sound_time = 0.0
        self.frame._mouse_limit_last_warp_x = 0.0
        self.frame._mouse_limit_last_warp_y = 0.0
        self.frame._mouse_limit_last_pos = None
        self.frame._mouse_lock_key_pressed = False
        self.frame._lock_key_error_logged = False
        self.frame._mouse_limit_auto_fit = True
        self.frame._mouse_limit_fitted_rect = None
        self.frame._mouse_limit_width = 1000
        self.frame._mouse_limit_height = 50
        self.positions = []
        self.warps = []
        self.speech = []
        self.sounds = []
        self.frame._get_mouse_position = lambda: self.positions[-1] if self.positions else None
        self.frame._move_mouse_to = lambda x, y: (self.warps.append((x, y)) or True)
        self.frame.play_sound = lambda name: self.sounds.append(name)
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

    def test_pull_clamps_to_boundary(self):
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_lock_enable()
        self.warps.clear()

        # 区域为 (500,300)-(1499,349)：越界钳制到最近边界并播一次提示音，而非拉回内部坐标
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0)])
        self.assertEqual(self.sounds, ["ding"])

        # 边界坐标属于界内：贴边不拉回
        self._set_mouse_position(1499.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0)])

        # 单轴越界只钳对应轴，另一轴保持
        self.frame._mouse_limit_last_warp_x = 0.0  # 模拟冷却时间已过
        self.frame._mouse_limit_last_warp_y = 0.0
        self._set_mouse_position(1600.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0), (1499.0, 320.0)])

        # 修改宽度即时生效，右边界收缩贴合屏幕
        self.frame.mouse_limit_width_input.SetValue("2000")
        self.frame.on_mouse_limit_width_focus_lost(types.SimpleNamespace(Skip=lambda: None))
        self.assertEqual(self.frame._mouse_limit_width, 2000)
        self.frame._mouse_limit_last_warp_x = 0.0  # 模拟冷却时间已过
        self.frame._mouse_limit_last_warp_y = 0.0
        self._set_mouse_position(2000.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0), (1499.0, 320.0), (1920.0, 320.0)])

    def test_pull_sound_min_interval(self):
        # 连续拉回时音效按最小间隔去重
        self.frame._play_pull_sound(100.0)
        self.frame._play_pull_sound(100.1)
        self.frame._play_pull_sound(100.31)
        self.assertEqual(self.sounds, ["ding", "ding"])

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

    def test_optshift_announce_flow(self):
        # 未按住 Option+Shift：不播报
        self._install_quartz_stub(0)
        self._set_mouse_position(100.0, 200.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])
        self.assertIsNone(self.frame._last_announce_pos)

        # 仅按 Ctrl 不算：需 Option+Shift 同时按住
        self._install_quartz_stub(1 << 18)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])
        # 按住 Option+Shift 不动：静默记录基准，不播报
        self._install_quartz_stub((1 << 19) | (1 << 17))
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

        # 松开修饰键清空记录；再次按住仍静默，需重新移动才播报
        self._install_quartz_stub(0)
        self.frame._poll_mouse_coord_announce()
        self._install_quartz_stub((1 << 19) | (1 << 17))
        self._set_mouse_position(106.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["105, 202"])
        self._set_mouse_position(111.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["105, 202", "111, 202"])

    def test_snap_warp_cooldown(self):
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_lock_enable()
        self._set_mouse_position(1000.0, 320.0)
        self.frame._poll_mouse_limit()
        self.warps.clear()

        # 第一次越界：立即钳制到边界
        self._set_mouse_position(1600.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0)])

        # 冷却期内再次越界：不重复 warp，避免触发系统节流导致指针卡顿
        self._set_mouse_position(1700.0, 450.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0)])

        # 冷却结束后恢复钳制
        self.frame._mouse_limit_last_warp_x = 0.0
        self.frame._mouse_limit_last_warp_y = 0.0
        self._set_mouse_position(1700.0, 450.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 349.0), (1499.0, 349.0)])

    def test_vertical_yields_to_horizontal_drag(self):
        # 左右移动优先：横向拖动进行中纵向小幅越界让路，保证滑块拖动顺滑
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_lock_enable()

        # 预置一次界内轮询作为横向移动基准
        self._set_mouse_position(600.0, 320.0)
        self.frame._poll_mouse_limit()

        # 拖动中纵向越界 16 像素（容忍带 20 内）：让路不拉回
        self._set_mouse_position(610.0, 365.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [])

        # 横向停止移动：立即钳回下边界
        self._set_mouse_position(610.0, 365.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(610.0, 349.0)])

        # 拖动中纵向越界超出容忍带：即使移动中也钳回防指针跑飞
        self.frame._mouse_limit_last_warp_y = 0.0  # 模拟冷却时间已过
        self._set_mouse_position(620.0, 400.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(610.0, 349.0), (620.0, 349.0)])

    def test_axis_independent_cooldown(self):
        # 一轴刚拉回不占用另一轴的修正配额：横纵冷却各自独立计时
        self._set_mouse_position(500.0, 300.0)
        self.frame._get_display_bounds_at = lambda x, y: (0.0, 0.0, 1920.0, 1080.0)
        self.frame.mouse_lock_enable()

        # 纵向刚拉回（冷却中），横向越界仍立即钳回
        self.frame._mouse_limit_last_warp_y = time.monotonic()
        self._set_mouse_position(1600.0, 320.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 320.0)])

        # 横向刚拉回（冷却中），纵向越界仍立即钳回（用户静止，不属于让路场景）
        self.frame._mouse_limit_last_warp_x = time.monotonic()
        self.frame._mouse_limit_last_warp_y = 0.0
        self._set_mouse_position(1600.0, 365.0)
        self.frame._poll_mouse_limit()
        self.assertEqual(self.warps, [(1499.0, 320.0), (1600.0, 349.0)])

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
