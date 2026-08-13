#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_DIR="$SCRIPT_DIR/AppleTranslateTool"
APP_BUNDLE="$SCRIPT_DIR/AppleTranslateTool.app"
CONTENTS="$APP_BUNDLE/Contents"
DESTINATION="$CONTENTS/MacOS/AppleTranslateTool-bin"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "错误：Apple Translation 工具只能在 macOS 15+ 上构建。" >&2
    exit 1
fi

if ! command -v xcrun >/dev/null 2>&1; then
    echo "错误：未找到 Xcode Command Line Tools。请先运行 xcode-select --install。" >&2
    exit 1
fi

MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if (( MACOS_MAJOR < 15 )); then
    echo "错误：Apple Translation 需要 macOS 15 或更高版本。" >&2
    exit 1
fi

echo "使用 $(xcrun swift --version | head -n 1)"
cd "$TOOL_DIR"
xcrun swift build -c release --product AppleTranslateTool-bin
BIN_DIR="$(xcrun swift build -c release --show-bin-path)"
rm -rf "$APP_BUNDLE"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"
install -m 755 "$BIN_DIR/AppleTranslateTool-bin" "$DESTINATION"
install -m 644 "$TOOL_DIR/Info.plist" "$CONTENTS/Info.plist"
codesign --force --sign - --identifier com.magictoolbox.AppleTranslateTool "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
echo "构建完成：$APP_BUNDLE"
