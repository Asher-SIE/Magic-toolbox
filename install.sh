#!/bin/bash

set -e

REPO_OWNER="Asher-SIE"
REPO_NAME="Magic-toolbox"
APP_NAME="MagicToolbox.app"
DESKTOP_DIR="$HOME/Desktop"

echo "=========================================="
echo "  Magic Toolbox 安装脚本"
echo "=========================================="
echo ""

# 检查 curl 是否可用
if ! command -v curl &> /dev/null; then
    echo "错误: curl 未安装"
    exit 1
fi

# 检查 unzip 是否可用
if ! command -v unzip &> /dev/null; then
    echo "错误: unzip 未安装"
    exit 1
fi

# 检查 xattr 是否可用
if ! command -v xattr &> /dev/null; then
    echo "错误: xattr 未安装"
    exit 1
fi

echo "[1/5] 获取最新版本信息..."
LATEST_INFO=$(curl -s -L "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest")

TAG_NAME=$(echo "$LATEST_INFO" | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
if [ -z "$TAG_NAME" ]; then
    echo "错误: 无法获取最新版本信息"
    exit 1
fi

VERSION=$(echo "$TAG_NAME" | sed 's/^v//')
echo "最新版本: $VERSION"

DOWNLOAD_URL=$(echo "$LATEST_INFO" | grep -o '"browser_download_url": *"[^"]*\.zip"' | cut -d'"' -f4)
if [ -z "$DOWNLOAD_URL" ]; then
    echo "错误: 无法获取下载链接"
    exit 1
fi

echo "[2/5] 下载安装包到桌面..."
ZIP_NAME="MagicToolbox-${VERSION}.zip"
ZIP_PATH="${DESKTOP_DIR}/${ZIP_NAME}"

if curl -L -o "$ZIP_PATH" --connect-timeout 30 --max-time 600 "$DOWNLOAD_URL"; then
    echo "下载完成"
else
    echo "下载失败，请检查网络连接后重试"
    rm -f "$ZIP_PATH"
    exit 1
fi

echo "[3/5] 解压到桌面..."
if unzip -q "$ZIP_PATH" -d "$DESKTOP_DIR"; then
    echo "解压完成"
else
    echo "解压失败"
    rm -f "$ZIP_PATH"
    exit 1
fi

# 获取解压后的 app 路径
EXTRACTED_PATH=""
for item in "$DESKTOP_DIR"/*; do
    if [ -d "$item" ] && [[ "$item" == *".app" ]]; then
        EXTRACTED_PATH="$item"
        break
    fi
done

if [ -z "$EXTRACTED_PATH" ]; then
    echo "错误: 未找到 .app 文件"
    rm -f "$ZIP_PATH"
    exit 1
fi

APP_BUNDLE_NAME=$(basename "$EXTRACTED_PATH")

# 如果解压后的名称不是 MagicToolbox.app，进行重命名
if [ "$APP_BUNDLE_NAME" != "$APP_NAME" ]; then
    NEW_PATH="${DESKTOP_DIR}/${APP_NAME}"
    if [ -d "$NEW_PATH" ]; then
        echo "桌面已存在 ${APP_NAME}，正在重命名..."
        rm -rf "$NEW_PATH"
    fi
    mv "$EXTRACTED_PATH" "$NEW_PATH"
    EXTRACTED_PATH="$NEW_PATH"
fi

echo "[4/5] 移除扩展属性..."
xattr -cr "$EXTRACTED_PATH"
echo "属性已清除"

# 检查桌面是否已有同名 app（排除刚解压的这个）
EXISTING_APP="${DESKTOP_DIR}/${APP_NAME}"
if [ -d "$EXISTING_APP" ] && [ "$(realpath "$EXISTING_APP")" != "$(realpath "$EXTRACTED_PATH")" ]; then
    echo "[5/5] 桌面已存在同名应用，重命名新版本..."
    RENAME_PATH="${DESKTOP_DIR}/${APP_NAME%.app}-${VERSION}.app"
    mv "$EXTRACTED_PATH" "$RENAME_PATH"
    EXTRACTED_PATH="$RENAME_PATH"
    echo "已重命名为: $(basename "$RENAME_PATH")"
else
    echo "[5/5] 安装完成"
fi

# 清理 zip 文件
rm -f "$ZIP_PATH"

echo ""
echo "=========================================="
echo "  安装成功！"
echo "=========================================="
echo ""
echo "应用已安装到: $EXTRACTED_PATH"
echo ""
echo "请将应用拖入 Applications 文件夹后使用"
echo ""
