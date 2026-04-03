# MagicToolbox
MagicToolbox 是一款专为 macOS VoiceOver 视障用户设计的辅助工具，集成实时翻译、剪贴板管理、文本快捷处理等核心功能。

## 功能特性
### 翻译功能
- **实时翻译**：支持对 VoiceOver 朗读的内容进行即时翻译
- **多语言支持**：支持 38 种以上语言，包含英语、中文、法语、日语、韩语、西班牙语等
- **离线翻译**：搭载腾讯混元大模型（需单独下载模型文件），无网络也可正常使用
- **长文本翻译**：智能拆分长篇文章，自动分段翻译并拼接完整结果
- **翻译缓存**：记录翻译历史，相同文本快速得到结果

### 剪贴板管理
- **历史记录**：自动保存剪贴板内容，支持历史记录浏览
- **多选操作**：支持勾选多条记录，执行批量复制、删除操作
- **编辑功能**：内置文本编辑器，支持撤销与重做操作
- **快捷处理**：提供移除空白、合并空格、数字转中文、文本分句等快捷功能

### 语音增强
- **VoiceOver 集成**：专为 VoiceOver 优化设计，可与屏幕阅读器无缝配合使用
- **音量限制**：内置听力保护机制，自动限制音量在安全范围内
- **自动旁白**：应用启动时如果旁白未运行自动在后台启用 VoiceOver
- **字符解释**：支持查看单个字符的详细释义
- **内容追加**：支持追加拷贝 VoiceOver 朗读的文本内容

## 权限要求
首次使用时，需授予以下权限：

1. 打开「旁白实用工具」 -> 「通用」 -> 勾选「允许使用 AppleScript 来控制旁白」复选框
2. 打开「系统设置」 -> 「隐私与安全性」 -> 「辅助功能」 -> 「允许辅助应用程序控制电脑」 -> 添加 MagicToolbox 到列表中

## 使用说明
### 界面导航
应用采用左侧导航栏搭配右侧内容面板的布局形式：
- **翻译面板**：输入文本即可执行翻译操作
- **剪贴板面板**：浏览并管理剪贴板历史记录
- **设置面板**：配置翻译模型路径、剪贴板记录最大保存条数

### 快捷键列表
| 快捷键 | 功能 |
|--------|------|
### 一、文本翻译/解释快捷键
| Option+C | 当前字符解释 |
| Option+D | 翻译 VoiceOver 最后朗读的文字 |
| Option+Shift+D | 反向翻译 |
| Option+Enter | 翻译翻译界面编辑框内的内容 |
| Option+Shift+Enter | 反向翻译翻译界面编辑框内的内容 |

### 二、剪贴板编辑器快捷键
| Option+T | 打开剪贴板编辑器 |
| Option+1 | 移除空白字符 |
| Option+2 | 合并多个空格 |
| Option+3 | 数字转中文 |
| Option+4 | 文本分行 |
| Option+F | 查找下一个 |
| Option+Shift+F | 查找上一个 |
| Option+H | 打开替换对话框 |
| Command+Z | 撤销操作 |
| Command+Shift+Z | 重做操作 |
| Escape | 退出编辑器 |
| Option+X | 保存编辑内容并退出编辑器 |

### 三、文字浏览快捷键
| Option+A | 追加拷贝 VoiceOver 朗读的内容 |
| Option+Shift+7 | 切换至剪贴板列表上一条 |
| Option+Shift+8 | 切换至当前剪贴板内容上一行 |
| Option+Shift+9 | 切换至剪贴板列表下一条 |
| Option+Shift+U | 切换至当前剪贴板内容前一个字 |
| Option+Shift+I | 剪贴板浏览模式下查看当前字符解释 |
| Option+Shift+O | 切换至当前剪贴板内容后一个字 |
| Option+Shift+J | 将剪贴板内容同步至系统剪贴板 |
| Option+Shift+K | 切换至当前剪贴板内容下一行 |
| Option+Shift+M | 查看剪贴板综述（行列信息） |

## 环境要求
- macOS 12.0 及以上版本
- Python 3.10 及以上版本
- Homebrew（用于安装项目依赖）

## 安装步骤
### 1. 克隆项目
```bash
git clone <repository-url>
cd Magic-toolbox
```

### 2. 创建虚拟环境
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖
```bash
pip install -r requirements.txt
```

### 4. 下载翻译模型
翻译功能需下载腾讯混元大模型（GGUF 格式）：
1. 访问 Hugging Face 平台下载模型文件
2. 将模型文件保存至本地任意目录
3. 首次运行应用时，通过内置设置面板选择模型文件路径

### 5. 运行应用
```bash
python main_UI.py
```

## 构建打包
### 使用打包脚本
```bash
chmod +x build.command
./build.command
```
打包完成后，应用文件将生成在 `dist/MagicToolbox.app` 目录下。

### 注意事项
- 确保项目根目录中存在 `resources` 文件夹，且包含全部必要资源文件
- 首次打包前，需先安装打包工具：`pip install pyinstaller`

## 项目结构
```
Magic-toolbox/
├── main_UI.py          # 主界面程序代码
├── processer.py        # 核心处理器（翻译、剪贴板、VoiceOver 功能）
├── setting.py          # 配置文件与国际化模块
├── resources/          # 资源文件目录
│   └── dict.txt        # 本地词典文件
├── locales/            # 国际化语言文件
│   ├── zh_CN/          # 中文语言包
│   └── en/             # 英文语言包
├── build.command       # 项目打包脚本
├── MagicToolbox.spec   # PyInstaller 打包配置文件
└── requirements.txt    # Python 依赖清单
```

## 技术栈
- **GUI 框架**：wxPython 4.2
- **翻译模型**：llama.cpp + 腾讯混元大模型
- **系统集成**：appscript、PyObjC
- **打包工具**：PyInstaller

## 许可证
MIT License
