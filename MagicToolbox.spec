# -*- mode: python ; coding: utf-8 -*-

import os

# macOS 15+ 且已构建时，将 Apple 翻译工具作为嵌套 bundle 打入应用
apple_tool_datas = []
if os.path.exists('AppleTranslateTool.app'):
    apple_tool_datas.append(('AppleTranslateTool.app', 'AppleTranslateTool.app'))


a = Analysis(
    ['main_UI.py'],
    pathex=[],
    # llama_cpp 运行时按「包目录/lib」搜索动态库；PyInstaller 钩子未收集 libmtmd.dylib，
    # 除拷入 Frameworks 根目录外，需再补一份到包内 lib 目录，否则打包版视觉模型报 mtmd not found
    binaries=[
        ('venv/lib/python3.13/site-packages/llama_cpp/lib', '.'),
        ('venv/lib/python3.13/site-packages/llama_cpp/lib/libmtmd.dylib', 'llama_cpp/lib'),
    ],
    datas=[('resources', 'resources'), ('locales', 'locales')] + apple_tool_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MagicToolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='MagicToolbox',
)
app = BUNDLE(
    coll,
    name='MagicToolbox.app',
    icon='MagicToolbox.icns',
    bundle_identifier='com.Asher.MagicToolbox',
    info_plist={
        'CFBundleDevelopmentRegion': 'zh_CN',
        'CFBundleLocalizations': ['zh_CN', 'en'],
        'CFBundleShortVersionString': '1.2.0',
    },
)