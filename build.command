#!/bin/bash

# 确保脚本以UTF-8编码运行
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# 获取脚本绝对目录
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
echo "脚本所在目录: $SCRIPT_DIR"

# 定义应用名称和路径
APP_NAME="Magic Toolbox"
MAIN_SCRIPT="main_UI.py"  # 主程序文件名
RESOURCE_DIR="resources"  # 资源目录名
DIST_DIR="$SCRIPT_DIR/dist"
BUILD_DIR="$SCRIPT_DIR/build"
SPEC_FILE="$SCRIPT_DIR/${APP_NAME}.spec"

# 切换到脚本目录
cd "$SCRIPT_DIR" || {
    echo "错误：无法切换到脚本所在目录 $SCRIPT_DIR"
    exit 1
}

# 显示当前工作目录和文件列表（用于调试）
echo "当前工作目录: $(pwd)"
echo "脚本目录下的文件列表:"
ls -lh

# 检查主程序文件是否存在
MAIN_SCRIPT_PATH="$SCRIPT_DIR/$MAIN_SCRIPT"
if [ ! -f "$MAIN_SCRIPT_PATH" ]; then
    echo "错误：主程序文件 $MAIN_SCRIPT_PATH 不存在！"
    echo "请确认主程序文件是否与脚本放在同一个目录，且文件名为 $MAIN_SCRIPT"
    exit 1
fi

# 检查资源目录是否存在
RESOURCE_PATH="$SCRIPT_DIR/$RESOURCE_DIR"
if [ ! -d "$RESOURCE_PATH" ]; then
    echo "警告：资源目录 $RESOURCE_PATH 不存在，将跳过资源打包"
    RESOURCE_OPTION=""
else
    RESOURCE_OPTION="--add-data \"$RESOURCE_PATH:resources\""
fi

# 清除之前的构建文件
echo "正在清除之前的构建文件..."
rm -rf "$DIST_DIR" "$BUILD_DIR" "$SPEC_FILE"

# 检查PyInstaller是否安装
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller未安装，正在安装..."
    pip3 install pyinstaller
    if [ $? -ne 0 ]; then
        echo "PyInstaller安装失败，请手动安装后重试：pip3 install pyinstaller"
        exit 1
    fi
fi

# 执行打包命令
echo "开始打包 $APP_NAME ..."
eval "pyinstaller \
    --name \"$APP_NAME\" \
    --windowed \
    --distpath \"$DIST_DIR\" \
    --workpath \"$BUILD_DIR\" \
    --clean \
    $RESOURCE_OPTION \
    \"$MAIN_SCRIPT_PATH\""

# 检查打包是否成功
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
if [ -d "$APP_BUNDLE" ]; then
    echo "打包成功！应用已生成在：$APP_BUNDLE"
    
    # 复制资源到应用包内
    if [ -d "$RESOURCE_PATH" ] && [ -d "$APP_BUNDLE/Contents/Resources" ]; then
        echo "正在复制资源文件..."
        cp -R "$RESOURCE_PATH"/* "$APP_BUNDLE/Contents/Resources/"
    fi
    
    # 打开输出目录
    echo "是否打开输出目录？(y/n)"
    read -r response
    if [ "$response" = "y" ] || [ "$response" = "Y" ]; then
        open "$DIST_DIR"
    fi
else
    echo "打包失败，请检查错误信息"
    exit 1
fi

echo "打包流程完成"
    