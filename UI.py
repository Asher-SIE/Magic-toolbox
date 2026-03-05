#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

# ============================================
# 第一步：在任何其他导入之前，强制设置环境变量
# ============================================
os.environ['LANG'] = 'zh_CN.UTF-8'
os.environ['LC_ALL'] = 'zh_CN.UTF-8'
os.environ['LANGUAGE'] = 'zh_CN'

# ============================================
# 第二步：使用 PyObjC 强制 macOS 语言（如果可用）
# ============================================
def force_chinese_on_macos():
    """尝试多种方法强制 macOS 使用中文"""
    if sys.platform != 'darwin':
        return
    
    try:
        from Foundation import (
            NSUserDefaults, 
            NSBundle,
            NSLocale
        )
        
        # 方法 A：修改 standardUserDefaults
        defaults = NSUserDefaults.standardUserDefaults()
        defaults.setObject_forKey_(["zh-Hans", "zh_CN", "zh"], "AppleLanguages")
        defaults.setObject_forKey_("zh_CN", "AppleLocale")
        defaults.synchronize()
        
        # 方法 B：尝试强制主 Bundle 的本地化
        bundle = NSBundle.mainBundle()
        
        # 方法 C：注册默认值
        defaults.registerDefaults_({
            "AppleLanguages": ["zh-Hans"],
            "AppleLocale": "zh_CN"
        })
        
        print("[调试] macOS 语言强制设置完成")
        print(f"[调试] 当前 Locale: {NSLocale.currentLocale().localeIdentifier()}")
        
    except ImportError as e:
        print(f"[警告] pyobjc 未安装: {e}")
    except Exception as e:
        print(f"[警告] 设置失败: {e}")

# 在导入 wx 之前执行
force_chinese_on_macos()

# ============================================
# 第三步：现在才导入 wx
# ============================================
import wx
import datetime

class MyFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(500, 400))
        
        self.panel = wx.Panel(self)
        self.create_toolbar()
        
        # 创建 ListBox
        sample_data = ["苹果", "香蕉", "橘子"]
        self.listbox = wx.ListBox(
            self.panel, 
            choices=sample_data, 
            style=wx.LB_SINGLE
        )
        
        # 设置无障碍名称
        self.listbox.SetName("水果列表")
        
        # 尝试设置无障碍描述（如果支持）
        try:
            self.listbox.SetAccessibleDescription("这是一个水果列表")
        except AttributeError:
            pass
        
        # 布局
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.listbox, 1, wx.EXPAND | wx.ALL, 10)
        self.panel.SetSizer(sizer)
        
        # 状态栏
        self.CreateStatusBar()
        self.SetStatusText("程序已启动")
        
        self.Centre()
        
        # 打印调试信息
        self.print_debug_info()
    
    def print_debug_info(self):
        """打印调试信息"""
        print("\n" + "="*50)
        print("调试信息：")
        print(f"  wx 版本: {wx.version()}")
        print(f"  平台: {wx.PlatformInfo}")
        
        # 检查当前 locale
        try:
            import locale
            print(f"  系统 locale: {locale.getlocale()}")
            print(f"  默认编码: {locale.getpreferredencoding()}")
        except:
            pass
        
        print("="*50 + "\n")
    
    def create_toolbar(self):
        toolbar = self.CreateToolBar()
        
        # 添加按钮 - 使用中文标签
        add_tool = toolbar.AddTool(
            wx.ID_ANY, 
            "添加",
            wx.ArtProvider.GetBitmap(wx.ART_NEW, wx.ART_TOOLBAR),
            shortHelp="添加新项目"
        )
        
        del_tool = toolbar.AddTool(
            wx.ID_ANY, 
            "删除",
            wx.ArtProvider.GetBitmap(wx.ART_DELETE, wx.ART_TOOLBAR),
            shortHelp="删除选中项"
        )
        
        clear_tool = toolbar.AddTool(
            wx.ID_ANY, 
            "清空",
            wx.ArtProvider.GetBitmap(wx.ART_CROSS_MARK, wx.ART_TOOLBAR),
            shortHelp="清空列表"
        )
        
        toolbar.Realize()
        
        self.Bind(wx.EVT_TOOL, self.on_add, add_tool)
        self.Bind(wx.EVT_TOOL, self.on_delete, del_tool)
        self.Bind(wx.EVT_TOOL, self.on_clear, clear_tool)
    
    def on_add(self, event):
        now = datetime.datetime.now().strftime("%H:%M:%S")
        item = f"新水果 {now}"
        self.listbox.Append(item)
        
        # 选中新添加的项
        self.listbox.SetSelection(self.listbox.GetCount() - 1)
        self.SetStatusText(f"已添加：{item}")
    
    def on_delete(self, event):
        sel = self.listbox.GetSelection()
        if sel != wx.NOT_FOUND:
            text = self.listbox.GetString(sel)
            self.listbox.Delete(sel)
            self.SetStatusText(f"已删除：{text}")
            
            # 重新选择
            count = self.listbox.GetCount()
            if count > 0:
                self.listbox.SetSelection(min(sel, count - 1))
        else:
            # 使用中文消息框
            wx.MessageBox(
                "请先选择一个项目", 
                "提示", 
                wx.OK | wx.ICON_INFORMATION
            )
    
    def on_clear(self, event):
        self.listbox.Clear()
        self.SetStatusText("列表已清空")


class MyApp(wx.App):
    def OnInit(self):
        # 设置 wx 的 locale
        self.locale = wx.Locale()
        
        # 尝试初始化中文
        if self.locale.Init(wx.LANGUAGE_CHINESE_SIMPLIFIED):
            print("[调试] wx.Locale 初始化为简体中文成功")
        else:
            print("[调试] wx.Locale 初始化失败，使用默认")
            self.locale = wx.Locale(wx.LANGUAGE_DEFAULT)
        
        frame = MyFrame(None, "VoiceOver 中文测试")
        frame.Show()
        return True


if __name__ == "__main__":
    print("启动程序...")
    print(f"Python 版本: {sys.version}")
    print(f"平台: {sys.platform}")
    
    app = MyApp()
    app.MainLoop()