# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/asher/Desktop/Magic-toolbox/main_UI.py'],
    pathex=[],
    binaries=[],
    datas=[('/Users/asher/Desktop/Magic-toolbox/resources', 'resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', 'pip', 'setuptools'],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [('O', None, 'OPTION'), ('O', None, 'OPTION')],
    exclude_binaries=True,
    name='Magic Toolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=['libpython*.so'],
    name='Magic Toolbox',
)
app = BUNDLE(
    coll,
    name='Magic Toolbox.app',
    icon=None,
    bundle_identifier=None,
)
