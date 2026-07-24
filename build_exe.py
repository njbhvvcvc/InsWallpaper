# -*- coding: utf-8 -*-
"""构建脚本:用 PyInstaller 把 wallpaper_app.py 打包为 InsWallpaper.exe(单文件)。
依赖:本机 ms-playwright 缓存下已有 chromium_headless_shell-1228 / ffmpeg-1011。

v2.4+ 修复:不再用 --collect-all playwright(它把 webkit/firefox 资产一锅端,
运行时解压 vite/dashboard 里的 safari/firefox SVG 会偶发失败导致启动崩)。
改为:--collect-submodules playwright(纯 .py 模块)+ 手动 add-data 一份
过滤后的 driver 目录(剔除 lib/vite 整个调试 UI 资产,我们只用 headless chromium)。
"""
import os, sys, subprocess, shutil, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(ROOT, "wallpaper_app.py")
PYI = os.path.join(os.path.dirname(sys.executable), "pyinstaller.exe")
if not os.path.isfile(PYI):
    PYI = "pyinstaller"

CACHE = os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")
NEEDED_DIRS = ["chromium_headless_shell-1228", "ffmpeg-1011"]
for d in NEEDED_DIRS:
    if not os.path.isdir(os.path.join(CACHE, d)):
        print(f"[缺] {d} 不在 {CACHE};请先运行 playwright install chromium(Headless Shell)")
        sys.exit(1)

add_data = []
for d in NEEDED_DIRS:
    src = os.path.join(CACHE, d).replace("\\", "/")
    add_data += ["--add-data", f"{src};ms-playwright/{d}"]

# Real-ESRGAN
REALESRGAN = os.path.join(ROOT, "realesrgan")
if os.path.isdir(REALESRGAN) and os.path.isfile(os.path.join(REALESRGAN, "realesrgan-ncnn-vulkan.exe")):
    add_data += ["--add-data", f"{REALESRGAN.replace(chr(92),'/')};realesrgan"]
else:
    print(f"[警告] 未找到 realesrgan 目录/二进制,将跳过超分打包({REALESRGAN})")

# ── 过滤 playwright driver:剔除 lib/vite(调试 UI 资产,含会崩的 SVG) ──
import playwright as _pw
PW_ROOT = os.path.dirname(_pw.__file__)
PW_DRIVER = os.path.join(PW_ROOT, "driver")
assert os.path.isdir(PW_DRIVER), f"playwright driver 不存在: {PW_DRIVER}"

FILTERED = os.path.join(ROOT, "_pw_driver_filtered")
if os.path.exists(FILTERED):
    shutil.rmtree(FILTERED, ignore_errors=True)

def _ignore_vite(directory, names):
    """跳过 lib/vite 目录(Playwright 调试 UI:dashboard/recorder/traceViewer,
    内含 firefox-*.svg / safari-*.svg,PyInstaller onefile 解压时偶发失败)。"""
    if os.path.basename(directory) == "lib" and "vite" in names:
        return ["vite"]
    return []

shutil.copytree(PW_DRIVER, FILTERED, ignore=_ignore_vite, dirs_exist_ok=False)
print(f"[driver 过滤] {PW_DRIVER} -> {FILTERED} (已剔除 lib/vite)")
add_data += ["--add-data", f"{FILTERED.replace(chr(92),'/')};playwright/driver"]

cmd = [
    PYI,
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "InsWallpaper",
    "--collect-submodules", "playwright",   # 纯 Python 模块(sync_api/_impl 等),不含数据文件
    "--collect-all", "PIL",
    "--hidden-import", "playwright.sync_api",
    ENTRY,
] + add_data

print("执行:", " ".join(cmd))
for d in [os.path.join(ROOT, "build"), os.path.join(ROOT, "dist")]:
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
for f in [os.path.join(ROOT, "InsWallpaper.spec")]:
    if os.path.isfile(f):
        os.remove(f)

r = subprocess.call(cmd, cwd=ROOT)

# 清理临时过滤目录
shutil.rmtree(FILTERED, ignore_errors=True)

if r != 0:
    print("pyinstaller 失败,退出码", r)
    sys.exit(r)

exe = os.path.join(ROOT, "dist", "InsWallpaper.exe")
if os.path.isfile(exe):
    mb = os.path.getsize(exe) // 1024 // 1024
    print(f"\n构建完成: {exe}  约 {mb} MB")
else:
    print("未找到生成的 exe")
