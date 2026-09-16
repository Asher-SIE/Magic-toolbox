# Apple Translation 本地桥接工具

此工具使用 macOS 26 的 Apple Translation 框架无头 API（`TranslationSession(installedSource:target:)`），以纯命令行方式在设备本地完成翻译。主程序通过标准输入发送 JSON，工具通过标准输出返回 JSON；无窗口、无弹框、不抢焦点，译文不会发送到第三方服务。

## 要求

- macOS 26 或更高版本（运行与构建均是）
- Xcode 26 工具链（swift-tools-version 6.2）
- 语言包需已安装：无头 session 不能触发下载，语言包缺失时翻译会立即报 `language_not_installed` 错误。请到 系统设置 > 通用 > 语言与地区 > 翻译语言 手动下载。

## 构建

在项目根目录执行：

```bash
./build_apple_translator.sh
```

脚本会生成并临时签名根目录下的 `AppleTranslateTool.app`。应用 bundle 仅为保持主程序路径解析不变的外壳（内部是纯 CLI 可执行文件），属于本机构建产物，不应提交到 Git。

## 手动验证

语言包状态查询：

```bash
printf '%s' '{"action":"status","sourceLanguage":"en","targetLanguage":"zh-Hans"}' | ./AppleTranslateTool.app/Contents/MacOS/AppleTranslateTool-bin
```

返回示例：`{"ok":true,"translatedText":null,"error":null,"code":null,"status":"installed"}`

翻译：

```bash
printf '%s' '{"action":"translate","sourceLanguage":"en","targetLanguage":"zh-Hans","text":"Hello"}' | ./AppleTranslateTool.app/Contents/MacOS/AppleTranslateTool-bin
```

成功时返回类似：

```json
{"ok":true,"translatedText":"你好","error":null,"code":null,"status":null}
```

语言包未安装时返回 `{"ok":false,...,"code":"language_not_installed",...}` 并以非零退出码结束。
