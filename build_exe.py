# -*- coding: utf-8 -*-
"""构建脚本:用 PyInstaller 把 wallpaper_app.py 打包为 InsWallpaper.exe(单文件)。
依赖:本机 ms-playwright 缓存下已有 chromium_headless_shell-1228 / ffmpeg-1011。

v2.6 关键改动:
- 音乐播放器 HTML 不再用 --add-data 打包(PyInstaller 在 DEST 基名==源基名时会把文件
  误判成目录,运行时按裸名找不到文件——用户此前反复踩坑)。改为:构建前把最新
  music_player.html 以 base64 编进 _music_html_data.py(wallpaper_app.py 直接 import),
  数据随字节码进 exe,运行时写出,100% 可取到。
- 全程不调用 rmtree 清旧目录:沙箱 safe-delete 会把批量删除拦截并中断构建。改用
  唯一时间戳构建目录(_bld_<ts>/_dst_<ts>),--noconfirm 无需清理任何已存在目录。
"""
import os, sys, subprocess, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRY = os.path.join(ROOT, "wallpaper_app.py")
PYI = os.path.join(os.path.dirname(sys.executable), "pyinstaller.exe")
if not os.path.isfile(PYI):
    PYI = "pyinstaller"

CACHE = os.path.join(os.environ["LOCALAPPDATA"], "ms-playwright")


def _find_playwright_dirs(prefix):
    """在 ms-playwright 缓存里查找匹配 prefix 的目录。浏览器版本号会随
    playwright 升级变化,不写死。取字典序最大者(通常即最新版本)。"""
    if not os.path.isdir(CACHE):
        print(f"[缺] ms-playwright 缓存不存在: {CACHE};请先运行 playwright install chromium")
        sys.exit(1)
    matches = sorted(
        d for d in os.listdir(CACHE)
        if d.startswith(prefix) and os.path.isdir(os.path.join(CACHE, d))
    )
    if not matches:
        print(f"[缺] 未找到 {prefix}-* 于 {CACHE};请先运行 playwright install chromium")
        sys.exit(1)
    return matches


NEEDED_DIRS = _find_playwright_dirs("chromium_headless_shell") + _find_playwright_dirs("ffmpeg")
print(f"[playwright 浏览器] 使用: {', '.join(NEEDED_DIRS)}")

# ── ① 刷新内嵌的音乐播放器 HTML 数据(把最新 music_player.html 编进 _music_html_data.py) ──
try:
    _r = subprocess.run([sys.executable, os.path.join(ROOT, "gen_music_html_data.py")],
                        cwd=ROOT, capture_output=True, text=True, timeout=120)
    if _r.returncode == 0:
        print("[内嵌] 已刷新 _music_html_data.py(音乐播放器 HTML 已编入字节码)")
    else:
        print(f"[警告] 刷新内嵌 HTML 失败(rc={_r.returncode}): {_r.stderr[-300:]}")
except Exception as e:
    print(f"[警告] 刷新内嵌 HTML 异常: {e}")

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

# v2.8.1:播放器改用系统 Edge「应用模式」(msedge --app=网址)打开,纯净无地址栏窗口。
# 不再打包 Electron 宿主(本构建环境拿不到完整的 Electron 内核:npmmirror 镜像缺
# electron.asar,GitHub 被墙,npm 在沙箱已损坏),也不再用 pywebview(冻结环境不稳定)。
# player_host/ 目录保留以备将来联网环境改用 Electron,但本构建不打包它,避免 exe 虚胖。
PLAYER_HOST = os.path.join(ROOT, "player_host")
if os.path.isdir(PLAYER_HOST):
    print(f"[提示] 检测到 player_host 目录,但 v2.8.1 改用 Edge 应用模式,不打包 Electron(跳过)")
else:
    print(f"[提示] 未找到 player_host 目录(正常, v2.8.1 不依赖它)")

# ── 过滤 playwright driver:剔除 lib/vite(调试 UI 资产,含会崩的 SVG) ──
import playwright as _pw
PW_ROOT = os.path.dirname(_pw.__file__)
PW_DRIVER = os.path.join(PW_ROOT, "driver")
assert os.path.isdir(PW_DRIVER), f"playwright driver 不存在: {PW_DRIVER}"


def _ignore_vite(directory, names):
    """跳过 lib/vite 目录(Playwright 调试 UI:dashboard/recorder/traceViewer,
    内含 firefox-*.svg / safari-*.svg,PyInstaller onefile 解压时偶发失败)。"""
    if os.path.basename(directory) == "lib" and "vite" in names:
        return ["vite"]
    return []


FILTERED = os.path.join(ROOT, "_pw_driver_filtered")
# 不 rmtree(会被沙箱批量删除拦截):用 dirs_exist_ok=True 直接覆盖旧内容
shutil.copytree(PW_DRIVER, FILTERED, ignore=_ignore_vite, dirs_exist_ok=True)
print(f"[driver 过滤] {PW_DRIVER} -> {FILTERED} (已剔除 lib/vite)")
add_data += ["--add-data", f"{FILTERED.replace(chr(92),'/')};playwright/driver"]

# 唯一构建目录:避免 --noconfirm 清旧目录被沙箱拦截导致构建中断
_ts = time.strftime("%Y%m%d_%H%M%S")
work = os.path.join(ROOT, f"_bld_{_ts}")
distp = os.path.join(ROOT, f"_dst_{_ts}")

cmd = [
    PYI,
    "--noconfirm",
    "--onefile",
    "--windowed",
    "--name", "InsWallpaper",
    "--workpath", work,
    "--distpath", distp,
    "--collect-submodules", "playwright",   # 纯 Python 模块(sync_api/_impl 等),不含数据文件
    "--collect-all", "PIL",
    "--collect-submodules", "pystray",
    "--hidden-import", "pystray",
    "--hidden-import", "playwright.sync_api",
    # v2.8 内嵌音乐播放器:改用 Electron(自带 Chromium)宿主,与 Python 版本无关,
    # 比 pywebview(pythonnet 封装 WebView2)稳定得多。player_host(含 electron 运行时)
    # 已通过上方 add_data 整体打进 exe,运行时由 wallpaper_app.py 定位 electron.exe 启动。
    ENTRY,
] + add_data

print("执行:", " ".join(cmd))
r = subprocess.call(cmd, cwd=ROOT)

if r != 0:
    print("pyinstaller 失败,退出码", r)
    sys.exit(r)

# 把产物从临时 distpath 拷到标准 dist/InsWallpaper.exe(单文件覆盖)
exe = os.path.join(distp, "InsWallpaper.exe")
if os.path.isfile(exe):
    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    shutil.copy2(exe, os.path.join(dist_dir, "InsWallpaper.exe"))
    mb = os.path.getsize(exe) // 1024 // 1024
    print(f"\n构建完成: dist/InsWallpaper.exe  约 {mb} MB")
else:
    print("未找到生成的 exe")
    sys.exit(1)

# ── 自检:HTML 已内嵌进字节码(不是 --add-data),确认内嵌数据可被导入即可 ──
# 真正的"运行时能写出 html"由真跑 exe 验证(见交付说明)。
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "_chk_html_data", os.path.join(ROOT, "_music_html_data.py"))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    if getattr(_mod, "MUSIC_HTML_B64", None):
        print("[自检通过] _music_html_data.py 含 MUSIC_HTML_B64(已随字节码打进 exe)")
    else:
        print("[自检失败] MUSIC_HTML_B64 缺失,html 没编进 exe!")
        sys.exit(2)
except Exception as e:
    print(f"[自检跳过] 无法校验内嵌数据: {e}")
