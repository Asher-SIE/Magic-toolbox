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
else
    RESOURCE_EXIST=1
    echo "找到资源目录：$RESOURCE_PATH"
fi

# 检查 locales 目录是否存在
LOCALES_PATH="$SCRIPT_DIR/locales"
if [ ! -d "$LOCALES_PATH" ]; then
    echo "警告：locales 目录 $LOCALES_PATH 不存在"
    LOCALES_EXIST=0
else
    LOCALES_EXIST=1
    echo "找到 locales 目录：$LOCALES_PATH"
fi

# 构建 Apple 翻译工具（需 macOS 26+，否则打包时跳过该功能）
MACOS_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if (( MACOS_MAJOR >= 26 )); then
    echo "正在构建 Apple 翻译工具..."
    bash "$SCRIPT_DIR/build_apple_translator.sh" || {
        echo "错误：Apple 翻译工具构建失败，请检查上方错误信息"
        exit 1
    }
else
    echo "macOS 版本低于 26，跳过 Apple 翻译工具（Apple 翻译模式不可用）"
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
else
    echo "打包失败，请检查终端错误信息"
    exit 1
fi

# 清理 .po 语言文件（打包后不需要）
echo "正在清理 .po 文件..."
find "$APP_BUNDLE" -name "*.po" -type f -delete 2>/dev/null
echo "清理完成"

# 清理 .DS_Store 文件
echo "正在清理 .DS_Store 文件..."
find "$APP_BUNDLE" -name ".DS_Store" -type f -delete 2>/dev/null
echo "清理完成"

# 清理 .dist-info 目录（仅包含许可证，不是运行时必需）
echo "正在清理 .dist-info 目录..."
find "$APP_BUNDLE" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null
echo "清理完成"

# 将 Apple 翻译工具作为嵌套 bundle 拷入 Frameworks：不能经 PyInstaller datas 打包
# （目录名被改写为 __dot__ 且复制产生循环符号链接，导致运行时找不到工具、codesign 报 Too many levels of symbolic links）
NESTED_APP="$SCRIPT_DIR/AppleTranslateTool.app"
if [ -d "$NESTED_APP" ]; then
    echo "正在拷入 Apple 翻译工具..."
    ditto "$NESTED_APP" "$APP_BUNDLE/Contents/Frameworks/AppleTranslateTool.app"
    echo "已拷入：$APP_BUNDLE/Contents/Frameworks/AppleTranslateTool.app"
else
    echo "未构建 AppleTranslateTool.app，跳过拷入（Apple 翻译功能不可用）"
fi

# 使用自签名证书签名（同一证书 → 签名身份稳定，TCC 权限不随重打包丢失）
SIGN_CERT="MagicToolbox Dev"
CERT_FILE="$SCRIPT_DIR/cert.p12"
# cert.p12 的导出密码
CERT_PASS="145896"

CAN_SIGN=0
CODESIGN_ARGS=(--force --deep)

# 诊断输出：全部身份（含无效）与有效身份分开列出，便于定位导入或信任问题
echo "当前签名身份（含无效项）："
security find-identity -p codesigning 2>/dev/null || true
echo "当前有效签名身份："
security find-identity -v -p codesigning 2>/dev/null || true

if security find-identity -v -p codesigning | grep -q "$SIGN_CERT"; then
    CAN_SIGN=1
    echo "使用钥匙串既有证书：$SIGN_CERT"
elif [ -f "$CERT_FILE" ]; then
    echo "未找到有效身份 \"$SIGN_CERT\"，正在将 cert.p12 导入登录钥匙串..."
    # 导入错误不屏蔽，失败原因直接可见；重复导入（证书已在钥匙串）报错可忽略
    security import "$CERT_FILE" -P "$CERT_PASS" -T /usr/bin/codesign || true
    if security find-identity -v -p codesigning | grep -q "$SIGN_CERT"; then
        CAN_SIGN=1
        echo "证书导入成功：$SIGN_CERT"
    else
        # 信任标记不存储在 p12 内，手动双击导入的证书默认不受信任，导致 find-identity -v 查不到；
        # 从 p12 提取纯证书写入用户信任域，等效于钥匙串访问中手动设置"始终信任"
        echo "证书未受信任或导入不完整，正在自动设置信任（可能弹出授权对话框，输入开机密码确认即可）..."
        TMP_CERT="$(mktemp -t magictoolbox-cert)"
        if openssl pkcs12 -in "$CERT_FILE" -passin "pass:$CERT_PASS" -nokeys -clcerts -out "$TMP_CERT" 2>/dev/null \
            && security add-trusted-cert -r trustRoot -k "$HOME/Library/Keychains/login.keychain-db" "$TMP_CERT" \
            && security find-identity -v -p codesigning | grep -q "$SIGN_CERT"; then
            CAN_SIGN=1
            echo "信任设置成功，签名身份可用：$SIGN_CERT"
        else
            echo "警告：自动设置信任未成功，跳过签名。排查指引："
            security find-identity -p codesigning 2>/dev/null || true
            echo "① 上方列出了 \"$SIGN_CERT\"：证书在钥匙串但未受信任（无 GUI 授权时自动信任会失败）。手动方法：钥匙串访问双击证书 → 展开\"信任\" → \"使用此证书时\"选\"始终信任\""
            echo "② 未列出 \"$SIGN_CERT\"：导入不含私钥或导错钥匙串。双击仓库 cert.p12（密码 145896）重新导入，确认出现在\"我的证书\"分类且证书下挂有私钥"
            echo "③ 导入日志有报错：密码不符或文件损坏"
        fi
        rm -f "$TMP_CERT"
    fi
else
    echo "警告：仓库中缺少 cert.p12，无法自动导入签名证书"
fi

if [ "$CAN_SIGN" -eq 1 ]; then
    echo "正在签名应用（证书：$SIGN_CERT）..."
    # 清除扩展属性：PyInstaller 产物常见 resource fork/Finder 元数据会阻断 codesign
    xattr -cr "$APP_BUNDLE" 2>/dev/null
    codesign "${CODESIGN_ARGS[@]}" --sign "$SIGN_CERT" "$APP_BUNDLE"
    if [ $? -eq 0 ]; then
        codesign --verify --verbose "$APP_BUNDLE"
        echo "签名成功"
    else
        echo "错误：签名失败！"
        exit 1
    fi
else
    echo "警告：未找到自签名证书 \"$SIGN_CERT\"，跳过签名（重打包后系统权限会失效）"
    echo "创建方法（一次性）：钥匙串访问 → 证书助理 → 创建证书，类型选\"代码签名\"，名称填 \"$SIGN_CERT\""
fi

echo "打包流程完成"