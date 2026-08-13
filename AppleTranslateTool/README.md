# Apple Translation 本地桥接工具

此工具使用 macOS 15 的 Apple Translation 框架，在设备本地完成翻译。主程序通过标准输入发送 JSON，工具通过标准输出返回 JSON；译文不会发送到第三方服务。

## 要求

- macOS 15 或更高版本
- Xcode 16 或对应版本的 Command Line Tools
- 首次使用某个语言对时允许系统下载离线语言模型

## 构建

在项目根目录执行：

```bash
./build_apple_translator.sh
```

脚本会生成并临时签名根目录下的 `AppleTranslateTool.app`。应用 bundle 提供 Translation 框架系统验证所需的稳定 bundle identifier，属于本机构建产物，不应提交到 Git。

## 手动验证

```bash
printf '%s' '{"action":"translate","sourceLanguage":"en","targetLanguage":"zh-Hans","text":"Hello"}' | ./AppleTranslateTool.app/Contents/MacOS/AppleTranslateTool-bin
```

成功时会返回类似：

```json
{"ok":true,"translatedText":"你好"}
```

首次下载模型时，系统会显示 Apple 提供的授权与进度界面。工具必须作为当前登录用户的图形会话进程运行，不能在无 GUI 的 SSH/后台服务会话中完成首次模型下载。
