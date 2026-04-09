# Apple Translate Tool 构建说明

需要手动构建翻译工具后才能使用苹果翻译功能。

## 构建步骤

### 方法1: 使用 Xcode（推荐）

1. 打开 `AppleTranslateTool/AppleTranslateTool.xcodeproj`
2. 在 Xcode 中选择 Product > Build (Cmd+B)
3. 构建成功后，可执行文件会在 `build/Release/AppleTranslateTool-bin`
4. 将 `build/Release/AppleTranslateTool-bin` 复制到主目录：
   ```bash
   cp build/Release/AppleTranslateTool-bin ../AppleTranslateTool-bin
   ```

### 方法2: 命令行

```bash
cd AppleTranslateTool
xcodegen generate
xcodebuild -project AppleTranslateTool.xcodeproj -scheme AppleTranslateTool-bin -configuration Release build
```

## 注意

- 需要 Xcode 15+ 
- 需要 macOS 14.4+
- 首次翻译时会提示下载语言模型