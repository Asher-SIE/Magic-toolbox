#!/bin/bash
# 修复：关闭严格的未定义变量检查（u选项），保留e（错误终止）和pipefail（管道错误）
# 新手场景下u选项容易触发不必要的报错，适合关闭
set -eo pipefail

# 确保脚本以UTF-8编码运行
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# 获取脚本绝对目录
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
echo "脚本所在目录: $SCRIPT_DIR"

# 定义应用名称和路径（处理空格问题）
APP_NAME="Magic Toolbox"
APP_NAME_SAFE="MagicToolbox"  # 无空格的安全名称（用于spec文件）
MAIN_SCRIPT="main_UI.py"
RESOURCE_DIR="resources"
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
SPEC_FILE="$SCRIPT_DIR/${APP_NAME_SAFE}.spec"

# 自动检测芯片架构
detect_arch() {
    local arch=$(uname -m)
    if [ "$arch" = "arm64" ]; then
        echo "arm64"
    else
        echo "x86_64"
    fi
}
TARGET_ARCH=$(detect_arch)
echo "检测到当前芯片架构: $TARGET_ARCH"

# 切换到脚本目录
cd "$SCRIPT_DIR" || {
    echo "错误：无法切换到脚本所在目录 $SCRIPT_DIR"
    exit 1
}

# 显示当前工作目录和文件列表
echo "当前工作目录: $(pwd)"
echo "脚本目录下的文件列表:"
ls -lh

# 给main_UI.py 添加读/执行权限（解决Permission denied）
MAIN_SCRIPT_PATH="$SCRIPT_DIR/$MAIN_SCRIPT"
chmod +r "$MAIN_SCRIPT_PATH" 2>/dev/null || true
chmod +x "$MAIN_SCRIPT_PATH" 2>/dev/null || true

# 检查主程序文件是否存在
if [ ! -f "$MAIN_SCRIPT_PATH" ]; then
    echo "错误：主程序文件 $MAIN_SCRIPT_PATH 不存在！"
    exit 1
fi

# 检查资源目录（不存在直接退出，符合你的要求）
RESOURCE_PATH="$SCRIPT_DIR/$RESOURCE_DIR"
if [ ! -d "$RESOURCE_PATH" ]; then
    echo "错误：资源目录 $RESOURCE_PATH 不存在！"
    echo "必须存在资源目录才能继续打包，请创建该目录并放入必要资源后重试"
    exit 1
fi
# macOS下--add-data的正确格式（用:分隔，单引号包裹）
RESOURCE_OPTION="--add-data '${RESOURCE_PATH}:resources'"

# 清除之前的构建文件
echo "正在清除之前的构建文件..."
rm -rf "$DIST_DIR" "$BUILD_DIR" "$SPEC_FILE" 2>/dev/null || true

# 检查PyInstaller是否安装
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller未安装，正在安装..."
    pip3 install pyinstaller
    if [ $? -ne 0 ]; then
        echo "PyInstaller安装失败，请手动安装后重试：pip3 install pyinstaller"
        exit 1
    fi
fi

# 修复：UPX相关逻辑（给所有变量赋初始值，避免未定义）
UPX_OPTION=""
UPX_PATH=""
UPX_DIR=""
if command -v upx &> /dev/null; then
    UPX_PATH=$(which upx | tr -d '\n' | xargs)  # 移除换行和空格
    if [ -n "$UPX_PATH" ] && [ -f "$UPX_PATH" ]; then
        UPX_DIR=$(dirname "$UPX_PATH")
        # UPX参数用单引号包裹，避免空格/特殊字符
        UPX_OPTION="--upx-dir '$UPX_DIR' --upx-exclude 'libpython*.so'"
        echo "检测到UPX已安装：$UPX_PATH，将启用二进制压缩"
    else
        echo "警告：UPX路径无效，跳过二进制压缩"
        UPX_OPTION=""
    fi
else
    echo "警告：未安装UPX，将跳过二进制压缩，打包体积会偏大"
    UPX_OPTION=""
fi

# 核心：打包命令（单行拼接，避免换行分割参数）
echo "开始打包 $APP_NAME（架构：$TARGET_ARCH）..."
PYINSTALLER_CMD="
pyinstaller \
--name '$APP_NAME' \
--windowed \
--distpath '$DIST_DIR' \
--workpath '$BUILD_DIR' \
--clean \
--strip \
--optimize=2 \
--target-arch $TARGET_ARCH \
--exclude-module tkinter \
--exclude-module test \
--exclude-module pip \
--exclude-module setuptools \
$UPX_OPTION \
$RESOURCE_OPTION \
'$MAIN_SCRIPT_PATH'
"
# 打印命令（调试用）
echo "执行打包命令：$PYINSTALLER_CMD"
# 执行命令（用bash -c 避免eval的引号问题）
bash -c "$PYINSTALLER_CMD"

# 检查打包是否成功
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
if [ -d "$APP_BUNDLE" ]; then
    echo "✅ 打包成功！应用已生成在：$APP_BUNDLE"
    
    # 复制资源到应用包内
    echo "正在复制资源文件..."
    cp -R "$RESOURCE_PATH"/* "$APP_BUNDLE/Contents/Resources/" 2>/dev/null || true
    
    # 二次优化：剥离符号表
    BIN_PATH="$APP_BUNDLE/Contents/MacOS/$APP_NAME"
    if [ -f "$BIN_PATH" ]; then
        echo "正在对二进制文件进行二次优化（剥离符号表）..."
        strip -S -x "$BIN_PATH" 2>/dev/null || true
        echo "优化后二进制文件体积："
        ls -lh "$BIN_PATH"
    fi
else
    echo "❌ 打包失败，请检查错误信息"
    exit 1
fi

echo "🎉 打包流程完成！最终应用路径：$APP_BUNDLE"
