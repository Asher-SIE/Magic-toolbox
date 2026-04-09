#!/bin/bash

# Apple Translate Tool 构建脚本
# 运行方式: bash build_apple_translator.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_DIR="$SCRIPT_DIR/AppleTranslateTool"

echo "构建 Apple Translate Tool..."

cd "$TOOL_DIR"

# 检查 Swift 版本
SWIFT_VERSION=$(swift --version | head -n 1)
echo "Swift 版本: $SWIFT_VERSION"

# 构建
echo "编译中..."
swift build -c release

# 复制可执行文件到主目录
BUILD_PRODUCT=$(swift build -c release --show-bin-path 2>/dev/null)
if [ -z "$BUILD_PRODUCT" ]; then
    echo "编译失败"
    exit 1
fi

cp "$BUILD_PRODUCT/AppleTranslateTool" "$SCRIPT_DIR/AppleTranslateTool"
echo "构建完成! 可执行文件: $SCRIPT_DIR/AppleTranslateTool"

echo "Apple Translate Tool 已就绪，可以使用苹果翻译功能。"