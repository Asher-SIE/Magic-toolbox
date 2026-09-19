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


class MouseLandmarkTests(unittest.TestCase):
    """鼠标路标：按应用分槽位存取、配置文件持久化、非法数据清洗、热键槽位键位"""

    def setUp(self):
        # 以 setting 实际生效的 config_path 为准（多测试模块共享同一 setting 导入）
        self._config_path = setting.config_path
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        setting.mouse_landmarks = {}
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        setting.mouse_landmarks = {}
        if os.path.exists(self._config_path):
            os.remove(self._config_path)

    def test_set_get_roundtrip(self):
        setting.set_mouse_landmark("com.apple.Safari", "1", 100.5, 200.25)
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "1"), [100.5, 200.25])
        # 槽位与应用互相独立
        setting.set_mouse_landmark("com.apple.Safari", "0", 5, 6)
        setting.set_mouse_landmark("com.apple.Finder", "1", 7, 8)
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "0"), [5.0, 6.0])
        self.assertEqual(setting.get_mouse_landmark("com.apple.Finder", "1"), [7.0, 8.0])
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "1"), [100.5, 200.25])
        self.assertIsNone(setting.get_mouse_landmark("com.apple.Safari", "3"))

    def test_persist_and_reload(self):
        setting.set_mouse_landmark("com.apple.Safari", "2", 1280, 720)
        # 标记后配置文件已写入
        with open(self._config_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["mouse_landmarks"]["com.apple.Safari"]["2"], [1280.0, 720.0])
        # 清空内存后重新加载配置可恢复路标
        setting.mouse_landmarks = {}
        setting.load_config()
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "2"), [1280.0, 720.0])

    def test_save_config_keeps_landmarks(self):
        setting.set_mouse_landmark("com.apple.Safari", "1", 10, 20)
        # 设置面板保存其它配置时不应冲掉路标
        setting.save_config("English", "Chinese")
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "1"), [10.0, 20.0])

    def test_set_landmark_keeps_other_config(self):
        # 先由设置面板写入完整配置，再标记路标，确认路标写入不冲掉其它配置项
        setting.save_config("English", "Chinese", translation_mode="llm", ocr_mode="apple")
        setting.set_mouse_landmark("com.apple.Safari", "1", 3, 4)
        with open(self._config_path, encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["source_lang"], "English")
        self.assertEqual(saved["ocr_mode"], "apple")

    def test_normalize_drops_invalid(self):
        self.assertEqual(setting._normalize_mouse_landmarks("bad"), {})
        self.assertEqual(setting._normalize_mouse_landmarks({"app": "bad"}), {})
        self.assertEqual(
            setting._normalize_mouse_landmarks(
                # 字典坐标会触发 KeyError、两字符数字串 "12" 会被误收为 [1.0, 2.0]，均应丢弃
                {"app": {"1": [1, 2], "2": "x", "3": [1], "4": {"x": 1, "y": 2}, "5": "12"}}
            ),
            {"app": {"1": [1.0, 2.0]}},
        )

    def test_set_landmark_merges_file_landmarks(self):
        # 模拟另一实例已写入文件的路标：本进程标记时按槽位合并，不冲掉文件中的其他应用/槽位
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump({"mouse_landmarks": {"other.App": {"5": [9, 9]}, "com.apple.Safari": {"4": [8, 8]}}}, f)
        setting.mouse_landmarks = {"com.apple.Safari": {"1": [1.0, 1.0]}}
        self.assertTrue(setting.set_mouse_landmark("com.apple.Safari", "2", 3, 4))
        self.assertEqual(setting.get_mouse_landmark("other.App", "5"), [9.0, 9.0])
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "4"), [8.0, 8.0])
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "2"), [3.0, 4.0])
        self.assertEqual(setting.get_mouse_landmark("com.apple.Safari", "1"), [1.0, 1.0])

    def test_set_landmark_reports_write_failure(self):
        # 写盘失败时返回 False，供热键处理器播报"保存失败"
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            self.assertFalse(setting.set_mouse_landmark("com.apple.Safari", "1", 1, 2))

    def test_hotkey_slots_avoid_clipboard_nav(self):
        # 标记/跳转槽位为 1-6 与 0，不得占用剪贴板导航的 7/8/9；热键与菜单共用该定义
        slots = set(setting.MOUSE_LANDMARK_SLOTS)
        self.assertEqual(slots, {"1", "2", "3", "4", "5", "6", "0"})
        mark_keys = {h["key"] for h in setting.hotKeys if h["name"].startswith("mark_")}
        jump_keys = {h["key"] for h in setting.hotKeys if h["name"].startswith("jump_")}
        self.assertEqual(mark_keys, slots)
        self.assertEqual(jump_keys, slots)
        self.assertEqual(mark_keys & {"7", "8", "9"}, set())


if __name__ == "__main__":
    unittest.main()
