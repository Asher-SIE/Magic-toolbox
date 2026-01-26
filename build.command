#!/bin/bash

# 确保脚本以UTF-8编码运行
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# 获取脚本绝对目录
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
echo "脚本所在目录: $SCRIPT_DIR"

# 定义应用名称和路径
APP_NAME="MagicToolbox"
MAIN_SCRIPT="main_UI.py"
RESOURCE_DIR="resources"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
SPEC_FILE="$SCRIPT_DIR/${APP_NAME}.spec"

# 切换到脚本目录
cd "$SCRIPT_DIR" || {
    echo "错误：无法切换到脚本所在目录 $SCRIPT_DIR"
    exit 1
}

# 激活虚拟环境
echo "激活虚拟环境..."
source venv/bin/activate || {
  echo "虚拟环境激活失败！请检查 venv 目录是否存在"
  exit 1
}

# 验证是否激活成功（检查 VIRTUAL_ENV 环境变量）
if [ -z "$VIRTUAL_ENV" ]; then
  echo "虚拟环境激活异常！"
  exit 1
fi
echo "虚拟环境激活成功：$VIRTUAL_ENV"

# 显示当前工作目录和文件列表（用于调试）
echo "当前工作目录: $(pwd)"

# 检查 .spec 文件是否存在】
if [ ! -f "$SPEC_FILE" ]; then
    echo "自定义.spec文件 $SPEC_FILE 不存在！"
    exit 1
fi
echo "找到自定义.spec文件：$SPEC_FILE"

# 检查主程序文件是否存在
MAIN_SCRIPT_PATH="$SCRIPT_DIR/$MAIN_SCRIPT"
if [ ! -f "$MAIN_SCRIPT_PATH" ]; then
    echo "错误：主程序文件 $MAIN_SCRIPT_PATH 不存在！"
    exit 1
fi

# 检查资源目录是否存在
RESOURCE_PATH="$SCRIPT_DIR/$RESOURCE_DIR"
if [ ! -d "$RESOURCE_PATH" ]; then
    echo "警告：资源目录 $RESOURCE_PATH 不存在，终止打包！"
    RESOURCE_EXIST=0
    exit 1
else
    RESOURCE_EXIST=1
    echo "找到资源目录：$RESOURCE_PATH"
fi

# 清除之前的构建文件
echo "正在清除之前的构建文件..."
rm -rf "$DIST_DIR" "$BUILD_DIR"

# 检查PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller未安装，正在安装..."
    pip install pyinstaller
    if [ $? -ne 0 ]; then
        echo "PyInstaller安装失败，请手动安装"
        exit 1
    fi
fi

# 执行打包
echo "开始打包 $APP_NAME ..."
pyinstaller --clean --noconfirm "$SPEC_FILE"

# 检查打包是否成功
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
if [ -d "$APP_BUNDLE" ]; then
    echo "打包成功！应用已生成在：$APP_BUNDLE"
    
    # 复制资源
    if [ $RESOURCE_EXIST -eq 1 ] && [ -d "$APP_BUNDLE/Contents/Resources" ]; then
        echo "正在复制资源文件..."
        cp -R "$RESOURCE_PATH"/* "$APP_BUNDLE/Contents/Resources/"
        echo "资源复制完成！"
    fi
else
    echo "打包失败，请检查终端错误信息"
    exit 1
fi

echo "打包流程完成"