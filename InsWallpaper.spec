# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/h5e5t/AppData/Local/ms-playwright/chromium_headless_shell-1228', 'ms-playwright/chromium_headless_shell-1228'), ('C:/Users/h5e5t/AppData/Local/ms-playwright/ffmpeg-1011', 'ms-playwright/ffmpeg-1011'), ('C:/Users/h5e5t/WorkBuddy/2026-07-23-08-55-38/realesrgan', 'realesrgan'), ('C:/Users/h5e5t/WorkBuddy/2026-07-23-08-55-38/music_player.html', 'music_player.html'), ('C:/Users/h5e5t/WorkBuddy/2026-07-23-08-55-38/_pw_driver_filtered', 'playwright/driver')]
binaries = []
hiddenimports = ['playwright.sync_api']
hiddenimports += collect_submodules('playwright')
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\h5e5t\\WorkBuddy\\2026-07-23-08-55-38\\wallpaper_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='InsWallpaper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
