# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main_UI.py'],
    pathex=[],
    # llama_cpp（0.3.26+）运行时按「包目录/lib」搜索 libllama/libmtmd 等全部动态库，
    # 故须将整个 lib 目录拷入包内 llama_cpp/lib；另拷一份到 Frameworks 根目录兜底 @rpath 依赖解析
    binaries=[
        ('venv/lib/python3.13/site-packages/llama_cpp/lib', '.'),
        ('venv/lib/python3.13/site-packages/llama_cpp/lib', 'llama_cpp/lib'),
    ],
    # AppleTranslateTool.app 不能经 datas 打包：PyInstaller 会把目录名改写为 __dot__ 并产生循环符号链接，
    # 既让运行时找不到工具，又导致 codesign 报 Too many levels of symbolic links。
    # 由 build.command 在打包后用 ditto 拷入 Contents/Frameworks。
    datas=[('resources', 'resources'), ('locales', 'locales')],
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
        'CFBundleShortVersionString': '1.2.3',
    },
)