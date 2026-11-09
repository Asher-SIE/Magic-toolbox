import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

_test_home = tempfile.TemporaryDirectory()
with mock.patch("os.path.expanduser", return_value=_test_home.name), mock.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, '"IOPlatformUUID" = "TEST-UUID"\n', ""),
    ):
    import setting


class MouseLimitTests(unittest.TestCase):
    """鼠标移动范围限制：矩形计算、越界吸附、坐标播报节流、配置持久化、开关热键"""

    def setUp(self):
        # 以 setting 实际生效的 config_path 为准（多测试模块共享同一 setting 导入）
        self._config_path = setting.config_path
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if os.path.exists(self._config_path):
            os.remove(self._config_path)

    def test_compute_rect_basic(self):
        rect = setting.compute_mouse_limit_rect((100, 200), 1000, 50)
        self.assertEqual(rect, (100.0, 200.0, 1099.0, 249.0))

    def test_compute_rect_shrinks_to_display(self):
        # 鼠标点靠近屏幕右/下边缘时，右/下边收缩贴合屏幕边缘
        display = (0.0, 0.0, 1920.0, 1080.0)
        rect = setting.compute_mouse_limit_rect((1900, 1050), 1000, 50, display)
        self.assertEqual(rect, (1900.0, 1050.0, 1920.0, 1080.0))
        # 未提供显示器边界时按配置原样计算
        rect = setting.compute_mouse_limit_rect((1900, 1050), 1000, 50)
        self.assertEqual(rect, (1900.0, 1050.0, 2899.0, 1099.0))

    def test_compute_rect_min_size(self):
        # 宽高非法（0/负数）时按 1 处理，退化为单像素矩形
        rect = setting.compute_mouse_limit_rect((10, 10), 0, -5)
        self.assertEqual(rect, (10.0, 10.0, 10.0, 10.0))

    def test_outside_and_clamp(self):
        rect = (100.0, 200.0, 1100.0, 250.0)
        # 边界值属于矩形内部，不触发吸附
        self.assertFalse(setting.is_point_outside_rect(100.0, 200.0, rect))
        self.assertFalse(setting.is_point_outside_rect(1100.0, 250.0, rect))
        self.assertTrue(setting.is_point_outside_rect(1100.5, 220.0, rect))
        self.assertTrue(setting.is_point_outside_rect(50.0, 100.0, rect))
        # 越界点吸附回边界，界内点保持不变
        self.assertEqual(setting.clamp_point_to_rect(1100.5, 100.0, rect), (1100.0, 200.0))
        self.assertEqual(setting.clamp_point_to_rect(500.0, 300.0, rect), (500.0, 250.0))
        self.assertEqual(setting.clamp_point_to_rect(500.0, 220.0, rect), (500.0, 220.0))

    def test_should_announce_coord_change(self):
        # 刚按住修饰键（上次为空）不播报，需移动后按阈值播报
        self.assertFalse(setting.should_announce_coord_change((100, 200), None, 5))
        # 任一轴移动达到精度阈值即播报
        self.assertTrue(setting.should_announce_coord_change((105, 200), (100, 200), 5))
        self.assertTrue(setting.should_announce_coord_change((100, 205.5), (100, 200), 5))
        # 未达阈值不播报
        self.assertFalse(setting.should_announce_coord_change((104.9, 204.9), (100, 200), 5))

    def test_parse_limit_dimension(self):
        self.assertEqual(setting.parse_limit_dimension("1000", 50), 1000)
        self.assertEqual(setting.parse_limit_dimension(" 50 ", 1000), 50)
        self.assertEqual(setting.parse_limit_dimension("abc", 1000), 1000)
        self.assertEqual(setting.parse_limit_dimension("", 1000), 1000)
        self.assertEqual(setting.parse_limit_dimension("0", 1000), 1000)
        self.assertEqual(setting.parse_limit_dimension("-3", 1000), 1000)
        self.assertEqual(setting.parse_limit_dimension(None, 1000), 1000)

    def test_config_persist_and_defaults(self):
        config = setting.load_config()
        # 默认值：宽 1000、高 50、开关关闭
        self.assertFalse(config["mouse_limit_enabled"])
        self.assertEqual(config["mouse_limit_width"], 1000)
        self.assertEqual(config["mouse_limit_height"], 50)
        # 保存后重新加载可恢复
        setting.save_config("English", "Chinese", mouse_limit_enabled=True, mouse_limit_width=1200, mouse_limit_height=60)
        config = setting.load_config()
        self.assertTrue(config["mouse_limit_enabled"])
        self.assertEqual(config["mouse_limit_width"], 1200)
        self.assertEqual(config["mouse_limit_height"], 60)
        self.assertTrue(setting.mouse_limit_enabled)
        self.assertEqual(setting.mouse_limit_width, 1200)

    def test_save_config_preserves_limit_values(self):
        # 设置面板保存其它配置时不应冲掉鼠标限制的生效值
        setting.save_config("English", "Chinese", mouse_limit_enabled=True, mouse_limit_width=800, mouse_limit_height=40)
        setting.save_config("English", "Chinese")
        self.assertTrue(setting.mouse_limit_enabled)
        self.assertEqual(setting.mouse_limit_width, 800)
        self.assertEqual(setting.mouse_limit_height, 40)
        with open(self._config_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(saved["mouse_limit_enabled"])
        self.assertEqual(saved["mouse_limit_width"], 800)
        self.assertEqual(saved["mouse_limit_height"], 40)

    def test_load_config_sanitizes_invalid_values(self):
        # 配置文件中的非法值按默认值清洗后返回
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump({"mouse_limit_enabled": "yes", "mouse_limit_width": "200", "mouse_limit_height": 0}, f)
        config = setting.load_config()
        self.assertFalse(config["mouse_limit_enabled"])
        self.assertEqual(config["mouse_limit_width"], 1000)
        self.assertEqual(config["mouse_limit_height"], 50)

    def test_mouselock_hotkey_not_registered(self):
        # 区域锁定开关不经 wx 热键注册（macOS 键码映射表无波浪号，注册必失败），由轮询实现
        names = [h["name"] for h in setting.hotKeys]
        self.assertNotIn("mouselock", names)
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
