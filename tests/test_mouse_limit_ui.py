import json
import os
import sys
import tempfile
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

    def _install_quartz_stub(self, flags):
        stub = types.ModuleType("Quartz")
        stub.kCGEventSourceStateCombinedSessionState = 0
        stub.kCGEventFlagMaskControl = 1 << 18
        stub.CGEventSourceFlagsState = lambda source: flags
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
        self.assertIn("鼠标限制已开启", self.speech)
        self.assertTrue(self._read_saved_config()["mouse_limit_enabled"])

        # 热键切换：关闭
        event_id = self.frame.hotkey_ids["mouselock"]
        self.frame.on_hotkey_mouse_lock_toggle(types.SimpleNamespace(GetId=lambda: event_id))
        self.assertFalse(self.frame._mouse_limit_active)
        self.assertIsNone(self.frame._mouse_limit_origin)
        self.assertFalse(self.frame.mouse_limit_check.GetValue())
        self.assertIn("鼠标限制已关闭", self.speech)
        self.assertFalse(self._read_saved_config()["mouse_limit_enabled"])

        # 热键 id 不匹配时不动作
        self.frame.on_hotkey_mouse_lock_toggle(types.SimpleNamespace(GetId=lambda: -1))
        self.assertFalse(self.frame._mouse_limit_active)

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

    def test_ctrl_announce_flow(self):
        # 未按住 Ctrl：不播报
        self._install_quartz_stub(0)
        self._set_mouse_position(100.0, 200.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, [])
        self.assertIsNone(self.frame._last_announce_pos)

        # 按住 Ctrl：按住后首次立即播报
        self._install_quartz_stub(1 << 18)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["100, 200"])

        # 移动不足精度阈值不播报
        self._set_mouse_position(103.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["100, 200"])

        # 任一轴移动达到 5 像素播报一次
        self._set_mouse_position(105.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["100, 200", "105, 202"])

        # 松开 Ctrl 清空记录，再次按住重新立即播报
        self._install_quartz_stub(0)
        self.frame._poll_mouse_coord_announce()
        self._install_quartz_stub(1 << 18)
        self._set_mouse_position(106.0, 202.0)
        self.frame._poll_mouse_coord_announce()
        self.assertEqual(self.speech, ["100, 200", "105, 202", "106, 202"])


if __name__ == "__main__":
    unittest.main()
