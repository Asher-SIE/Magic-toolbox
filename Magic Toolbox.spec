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
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Magic Toolbox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Magic Toolbox',
)
app = BUNDLE(
    coll,
    name='Magic Toolbox.app',
    icon=None,
    bundle_identifier=None,
)
