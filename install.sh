#!/bin/bash

set -e

REPO_OWNER="Asher-SIE"
REPO_NAME="Magic-toolbox"
APP_NAME="MagicToolbox.app"
DESKTOP_DIR="$HOME/Desktop"
TEMP_DIR="/tmp"

echo "  Magic Toolbox 安装脚本"
echo ""

echo "[1/6] 获取最新版本信息..."
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

echo "[2/6] 清理旧文件..."
rm -rf "${TEMP_DIR}/MagicToolbox"*
rm -f "${DESKTOP_DIR}/MagicToolbox-${VERSION}.zip" 2>/dev/null || true
echo "清理完成"

echo "[3/6] 下载安装包..."
ZIP_PATH="${TEMP_DIR}/MagicToolbox-${VERSION}.zip"

if curl -L -o "$ZIP_PATH" --connect-timeout 30 --max-time 600 "$DOWNLOAD_URL"; then
    echo "下载完成"
else
    echo "下载失败，请检查网络连接后重试"
    rm -f "$ZIP_PATH"
    exit 1
fi

echo "[4/6] 解压到临时目录..."
rm -rf "${TEMP_DIR}/MagicToolbox.app"
if unzip -q "$ZIP_PATH" -d "$TEMP_DIR" -x "__MACOSX/*"; then
    echo "解压完成"
else
    echo "解压失败"
    rm -f "$ZIP_PATH"
    exit 1
fi

EXTRACTED_APP="${TEMP_DIR}/MagicToolbox.app"
if [ ! -d "$EXTRACTED_APP" ]; then
    echo "错误: 未找到 .app 文件"
    rm -f "$ZIP_PATH"
    exit 1
fi

echo "[5/6] 安装应用..."
EXISTING_APP="${DESKTOP_DIR}/${APP_NAME}"
if [ -d "$EXISTING_APP" ]; then
    DEST_APP="${DESKTOP_DIR}/${APP_NAME%.app}-${VERSION}.app"
    cp -R "$EXTRACTED_APP" "$DEST_APP"
    xattr -cr "$DEST_APP"
    APP_INSTALLED=true
else
    DEST_APP="${DESKTOP_DIR}/${APP_NAME}"
    cp -R "$EXTRACTED_APP" "$DEST_APP"
    xattr -cr "$DEST_APP"
    APP_INSTALLED=true
fi

rm -rf "$EXTRACTED_APP" "$ZIP_PATH"

echo "[6/6] 下载说明文件..."
README_URL="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main/README.md"
if curl -fsSL "$README_URL" -o "${TEMP_DIR}/README.md"; then
    cp "${TEMP_DIR}/README.md" "${DESKTOP_DIR}/${APP_NAME%.app}说明.md"
    echo "说明文件已下载"
fi
rm -f "${TEMP_DIR}/README.md"

echo ""
echo "=========================================="
echo "  下载完成！"
echo "=========================================="
echo ""

if [ "$APP_INSTALLED" = true ] && [ -d "$EXISTING_APP" ]; then
    echo "应用已下载到桌面「$(basename "$DEST_APP")」，请手动清理旧版本"
else
    echo "应用已下载到桌面文件夹"
fi

echo ""
echo "请将应用拖入 Applications 文件夹后使用"
echo ""
