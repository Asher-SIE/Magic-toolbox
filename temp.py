    def init_ui(self):
        """
        重构UI：左侧导航列表 + 动态工具栏 + 内容区
        核心原则：
        - 工具栏由 Frame 直接创建管理（不放入任何 sizer）
        - Frame 设置 sizer 仅包含 main_panel（工具栏自动位于 sizer 上方）
        - main_panel 的 sizer 仅管理内容区域（分割窗口）
        """
        # ========== 1. Frame 工具栏已经由 init_toolbar 创建 ==========
        # self.toolbar = self.CreateToolBar(...) #  0
        
        # --- 移除了导致错误的代码块 ---
        # 这部分逻辑应该放在事件处理器或专用的状态更新函数中，
        # 例如 update_clipboard_buttons_state 方法中。
        
        # 在UI初始化时，确保按钮处于正确的初始状态（通常是禁用的，直到有项目被选中）
        # 假设在初始化时，列表是空的或者没有选中任何项目
        # 如果 current_module 是 "clipboard"，并且按钮已创建，则在此处禁用它们
        # 注意：在 init 期间，main_panel, translation_panel 等可能还未完全初始化
        # 最好在所有子面板创建后再调用一次状态更新
        # self.update_clipboard_buttons_state() # 可以考虑在 init 末尾调用一次
        # 或者在每个模块的 init_*_panel 方法最后调用
        pass # UI结构初始化的核心代码应该放在这里（例如创建 main_panel, sizers, splitter, nav_list, content_panels 等）

    # ... 其余方法保持不变 ...

确保事件处理函数调用状态更新方法：

检查你的列表事件绑定是否正确，并且 on_list_item_selected, on_list_item_checked, on_list_item_deselected 等方法确实调用了 update_clipboard_buttons_state()。

从你提供的代码来看，on_list_item_selected, on_list_item_checked, on_list_item_deselected 方法中都有对 self.update_clipboard_buttons_state() 的调用，这是正确的。

重要提示： 你还缺少创建主要内容面板 (main_panel, translation_panel, clipboard_panel, settings_panel) 的代码。init_ui 方法的主要职责应该是构建这些面板及其布局。

请确保你的 init_ui 方法包含了创建 wx.SplitterWindow、左侧导航列表、右侧内容面板容器以及各个具体功能面板（翻译、剪贴板、设置）的代码，并将它们正确地组织起来。在 init_ui 的最后，可以调用一次 switch_to_module 来设置默认显示的模块，这会自动处理面板切换和工具栏更新。


import pyttsx3

engine = pyttsx3.init()

print("=" * 60)
print("🔊 系统可用语音角色列表（自动匹配'美佳'）")
print("=" * 60)

voices = engine.getProperty('voices')
target_id = None

for idx, voice in enumerate(voices, 1):
    name_lower = voice.name.lower()
    # 智能匹配：同时识别"美佳"、"Mei-Jia"、"Meijia"等变体
    if any(kw in name_lower for kw in ['mei-jia', 'meijia', '美佳', '美 佳']):
        target_id = voice.id
        status = "✅ 已选中"
    else:
        status = "  "
    
    print(f"{status} [{idx}] {voice.name}")
    print(f"      ID: {voice.id}")
    print(f"      语言: {voice.languages} | 性别: {voice.gender or 'N/A'}")

if target_id:
    engine.setProperty('voice', target_id)
    print(f"n🎯 自动匹配成功: 使用语音 '{target_id}'")
else:
    print("n⚠️  未找到'美佳'语音！将使用系统默认语音")
    print("   请在【系统设置 → 辅助功能 → 语音】中下载'美佳'后重试")

engine.setProperty('rate', 950)    # 950 字/分钟
engine.setProperty('volume', 0.05) # 5% 音量

print("n" + "=" * 60)
print(f"🔊 当前语音: {engine.getProperty('voice').split('.')[-1]}")
print(f"⏱️  语速: {engine.getProperty('rate')} 字/分钟")
print(f"🔉 音量: {engine.getProperty('volume') * 100:.0f}%")
print("=" * 60)

text = "语音设置验证：语速九百五十，音量百分之五。"
engine.say(text)
engine.runAndWait()

print("n✅ 朗读完成 | 提示：音量5%非常小，如听不清请调高系统音量或修改volume参数")

