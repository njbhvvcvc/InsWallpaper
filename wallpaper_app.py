# -*- coding: utf-8 -*-
"""INS 壁纸轮播器 v2.8.1
支持五类图片来源:
  - IG 账户(ig)      : 粘贴 Instagram 链接自动抓取(并保存每张图发布时间)
  - 歌手(singer)     : 输入歌手名,自动抓该歌手全部专辑封面当壁纸(数据来自 GD 音乐台 API)
  - 本地文件夹(folder): 引用一个本地图片文件夹(不复制,实时读取)
  - 本地单张集合(local): 手动导入的单张图片归集
  - 随机图(内置,net) : 内置几个免费API随机好图(Picsum / Bing 壁纸镜像),免 key 直连
支持批量导入多个 IG 账户(每行一个链接);每个来源可设每日轮播时段(开始-结束),
仅在该时段内参与轮播,多个来源可设相同时段实现"同段轮播多账户"。
支持"统一刷新"一次性刷新全部 IG 账户(错峰防锁死);并可在轮播中自动更新(更新与轮换合一)。
"轮换跨度"可限定只轮换最近 永久/1年/20天/10天 内的照片。
来源列表显示每个 IG 账户"最近更新(按天)"的发布日期。
壁纸铺法:铺满(不变形,默认)/拼贴(16:9,多张拼满)/适应(黑边)/居中/平铺。
  - 铺满(不变形):等比放大铺满屏幕,裁掉溢出,无黑边,不变形(黑边仅作兜底)。
  - 拼贴(16:9):把多张同格式图片拼成一张精确填满屏幕的网格,无黑边、不变形。
  - 适应(黑边):整图等比缩进屏幕四周补黑边,绝不裁切;会在黑边角落烤上发布日期。
画质增强:
  - 抓取画质可选 标准(640)/高清(1080)/超清(1440),改写下载链接尺寸令牌尽量拿更大图。
  - 可选"AI 超分(显卡)":用本地 Real-ESRGAN(NCNN/Vulkan)对每张图做 GPU 超分并缓存。
文件名含发布日期(如 img_01_2026-06-09.jpg),状态栏也显示日期。
按 F12 可快捷打开报错查看窗口。
音乐播放器(v2.8.1 起)以系统 Edge 应用模式(msedge --app,无地址栏纯净窗口)打开 music.html,
不再弹出带地址栏/标签的系统浏览器;"加封面做壁纸"仍通过本地服务 /add_cover 一体化配置。
仅供个人将图片设为自己的桌面壁纸;图片版权归原作者所有,请勿用于分发或商业用途。
"""
import os, sys
# 冻结为 EXE 后,把 Playwright 浏览器目录指向打包内自带的一份
if getattr(sys, "frozen", False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(sys._MEIPASS, "ms-playwright")

import json, time, random, re, threading, glob, subprocess, io, base64, atexit
import http.server
import urllib.request, urllib.parse
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import ctypes
import winreg

# PIL:用于把图片合成"黑边铺满"的壁纸,保证绝不裁切/变形
try:
    from PIL import Image
    HAVE_PIL = True
except Exception:
    Image = None
    HAVE_PIL = False

# 音乐播放器 HTML:打包进 exe 时以 base64 内嵌在 _music_html_data.py(由 gen_music_html_data.py 生成),
# 运行时写出到 APP_DIR,彻底绕开 PyInstaller --add-data 的 DEST 路径坑。
try:
    from _music_html_data import MUSIC_HTML_B64
except Exception:
    MUSIC_HTML_B64 = None

# ---------- 路径 ----------
APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "InsWallpaper")
CFG_PATH = os.path.join(APP_DIR, "config.json")
ACCOUNTS_DIR = os.path.join(APP_DIR, "accounts")
os.makedirs(ACCOUNTS_DIR, exist_ok=True)
LOCAL_NAME = "_local"   # 本地单张集合来源名

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
# 铺法:
#   cover   = 铺满(不变形):等比放大铺满屏幕,裁掉溢出,无黑边(默认)
#   collage = 拼贴(16:9)  :把多张同格式图片拼成一张精确填满屏幕的网格,无黑边、不变形
#   fit     = 适应(黑边)  :整图等比缩进屏幕,四周补黑边,绝不裁切(会在黑边烤发布日期)
#   center  = 居中        :小于屏幕时按原尺寸居中(不放大);大于屏幕时同 适应
#   tile    = 平铺        :原图重复铺排
FIT_CN = {"铺满(不变形)": "cover", "拼贴(16:9)": "collage",
          "适应(黑边)": "fit", "居中": "center", "平铺": "tile"}
FIT_KEYS = list(FIT_CN.keys())
TYPE_CN = {"ig": "IG", "folder": "文件夹", "local": "本地", "net": "随机图", "singer": "歌手"}
# 轮换跨度:只轮换发布时间在"最近 N 天"内的照片;0=永久(全部)
SPAN_CN = {"永久": 0, "1年": 365, "20天": 20, "10天": 10}
SPAN_KEYS = list(SPAN_CN.keys())
# 内置免费随机好图 API(无需 key,轮播时可直接用;国内可达性不一,可在此增删)
#   {seed} 会被替换为随机整数,用于拿到不同图片
NET_ENDPOINTS = [
    "https://picsum.photos/1920/1080",                       # Lorem Picsum(Unsplash 授权,免费)
    "https://picsum.photos/seed/{seed}/1920/1080",
    "https://bing.img.run/uhd.php",                          # Bing 每日壁纸镜像(国内友好)
    "https://api.dujin.org/bing/1920.php",                   # Bing 壁纸另一镜像(国内友好)
]
NET_BATCH = 15   # 每次抓取的内置随机图数量

# Real-ESRGAN(NCNN/Vulkan)本地超分:把目录打进 EXE,或放在脚本同级的 realesrgan/
def realesrgan_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "realesrgan")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "realesrgan")

def realesrgan_exe():
    d = realesrgan_dir()
    return os.path.join(d, "realesrgan-ncnn-vulkan.exe")   # 不存在时返回预期路径(供报错提示)

# ---------- 配置 ----------
def load_cfg():
    if os.path.exists(CFG_PATH):
        try:
            return json.load(open(CFG_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {"accounts": [], "selected": [], "interval": 30, "order": "random", "fit": "cover",
            "refresh_gap": 20, "span": 0, "auto_update": True, "auto_hours": 6,
            "upscale": False, "collage_n": 4, "max_photos": 0}

def save_cfg(cfg):
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def safe_name(url):
    m = re.search(r"instagram\.com/([^/?#]+)", url)
    if m:
        return m.group(1)
    return re.sub(r"\W+", "_", url)[:40]

def account_images(acc):
    return [p for p, _ in account_items(acc)]

def load_meta(acc):
    """读取账户目录下的 meta.json: {文件名: 发布日期 YYYY-MM-DD}。"""
    p = os.path.join(acc.get("dir", ""), "meta.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return {}

def account_items(acc):
    """返回 [(path, date_or_None), ...] 按文件名排序。IG 用发布时间;文件夹/单张回退文件修改时间。"""
    d = acc.get("dir")
    if not d or not os.path.isdir(d):
        return []
    meta = load_meta(acc)
    items = []
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith(IMG_EXT) or f == "meta.json":
            continue
        p = os.path.join(d, f)
        date = meta.get(f)
        if not date and acc.get("type") in ("folder", "local"):
            try:
                date = datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
            except Exception:
                date = None
        items.append((p, date))
    return items

def _parse_title_date(title):
    """igram.world 的 title 形如 '2026/6/9 18:04:48' -> '2026-06-09'。"""
    if not title:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(title.strip(), fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return None

def extract_post_time(it):
    """从 li.profile-media-list__item 取发布日期(YYYY-MM-DD)。igram.world: p.media-content__meta-time[title]。"""
    el = it.query_selector("p.media-content__meta-time")
    if el:
        d = _parse_title_date(el.get_attribute("title"))
        if d:
            return d
    for el in it.query_selector_all("[title]"):
        d = _parse_title_date(el.get_attribute("title"))
        if d:
            return d
    return None

def _parse_hm(s):
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None

def in_window(acc, now):
    """acc 是否在其时段内(无时段或格式错 => 始终参与)。"""
    s = (acc.get("start") or "").strip()
    e = (acc.get("end") or "").strip()
    if not s and not e:
        return True
    a, b = _parse_hm(s), _parse_hm(e)
    if a is None or b is None:
        return True
    cur = now.hour * 60 + now.minute
    if a <= b:
        return a <= cur < b
    return cur >= a or cur < b   # 跨午夜(如 23:00-01:00)

# ---------- 抓取(playwright + igram.world,仅 ig 类型) ----------
def fetch_account(acc, log):
    t = acc.get("type")
    if t == "net":
        return fetch_net(acc, log)
    if t == "singer":
        return fetch_singer(acc, log)
    return fetch_ig(acc, log)

# ---------- 抓取(歌手专辑封面,GD 音乐台 API,仅 singer 类型) ----------
def _gd_get(params, proxy=""):
    """调用 GD 音乐台 API,返回解析后的 JSON(失败返回 {})。仅用标准库,便于打进 exe。"""
    import urllib.request, urllib.parse
    qs = urllib.parse.urlencode(params)
    url = "https://music-api.gdstudio.xyz/api.php?" + qs
    if proxy:
        url = proxy + urllib.parse.quote(url, safe="")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Referer": "https://music-api.gdstudio.xyz/",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return {}

def fetch_singer(acc, log):
    """歌手来源:抓该歌手全部专辑封面,存入账户目录当壁纸。增量保留(按 pic_id 命名,不删旧图)。"""
    import urllib.request, urllib.parse
    artist = acc.get("artist", "")
    source = acc.get("source", "netease")
    out = acc["dir"]
    os.makedirs(out, exist_ok=True)
    if not artist:
        log("歌手名为空,跳过")
        return 0
    log(f"正在搜索歌手「{artist}」的全部专辑(来源:{source})…")
    # 1) 分页搜索该歌手,收集全部曲目
    raw = []
    for p in range(1, 9):
        d = _gd_get({"types": "search", "source": source, "name": artist, "count": 20, "pages": p})
        arr = d if isinstance(d, list) else (d.get("data") or d.get("result") or d.get("list") or [])
        if not arr:
            break
        raw += arr
        if len(arr) < 20:
            break
    # 2) 去重专辑(按 pic_id 封面唯一)
    seen, albums = {}, []
    for t in raw:
        pid = str(t.get("pic_id") or "")
        key = pid or (t.get("album") or "")
        if not key:
            continue
        if key not in seen:
            seen[key] = 1
            ar = t.get("artist")
            if isinstance(ar, list):
                ar = "/".join(ar)
            albums.append({"album": t.get("album") or "(未知专辑)",
                           "artist": ar or artist, "pic_id": pid, "source": source})
    if not albums:
        log("未找到该歌手的专辑封面")
        return 0
    log(f"找到 {len(albums)} 张专辑,开始下载封面…")
    saved = 0
    for a in albums:
        if not a["pic_id"]:
            continue
        fn = f"album_{a['pic_id']}.jpg"
        fpath = os.path.join(out, fn)
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 1000:
            saved += 1
            continue
        pic = _gd_get({"types": "pic", "source": source, "id": a["pic_id"], "size": 500})
        url = pic.get("url") if isinstance(pic, dict) else None
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            if len(data) < 1000:
                continue
            with open(fpath, "wb") as fp:
                fp.write(data)
            saved += 1
            log(f"  已保存专辑《{a['album']}》封面")
        except Exception as e:
            log(f"  封面下载失败《{a['album']}》: {e}")
    return saved

def fetch_net(acc, log):
    """内置免费随机图:从 NET_ENDPOINTS 轮流抓 NET_BATCH 张,存到账户目录。无发布时间。"""
    import urllib.request, random
    out = acc["dir"]
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        try:
            os.remove(os.path.join(out, f))
        except Exception:
            pass
    log(f"正在抓取内置随机图(免费API),共 {NET_BATCH} 张…")
    saved = 0
    eps = NET_ENDPOINTS[:]
    for i in range(1, NET_BATCH + 1):
        ok = False
        for ep in random.sample(eps, len(eps)):
            url = ep.replace("{seed}", str(random.randint(1, 10 ** 9))) if "{seed}" in ep else ep
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                if len(data) < 3000:
                    continue
                ct = (resp.headers.get("Content-Type") or "").lower()
                ext = ".png" if "png" in ct else (".webp" if "webp" in ct else ".jpg")
                with open(os.path.join(out, f"net_{i:02d}{ext}"), "wb") as fp:
                    fp.write(data)
                saved += 1
                log(f"  已保存第 {saved} 张")
                ok = True
                break
            except Exception as e:
                log(f"  [{i}] {ep} 失败: {e}")
        if not ok:
            log(f"  [{i}] 所有免费API均失败,跳过")
    return saved

def fetch_ig(acc, log):
    from playwright.sync_api import sync_playwright
    url = acc["url"]
    out = acc["dir"]
    os.makedirs(out, exist_ok=True)
    # ---- 增量保留: 绝不删除本地旧图, 只补抓新增的 ----
    import hashlib, re
    HASH_RE = re.compile(r"_([0-9a-fA-F]{12})\.(jpe?g|png|webp)$", re.I)
    OLD_RE = re.compile(r"^img_\d{2}(?:_(.+?))?\.(jpe?g|png|webp)$", re.I)
    # 读取已有 meta(保留旧图的发布日期记录)
    old_meta = {}
    try:
        with open(os.path.join(out, "meta.json"), "r", encoding="utf-8") as _mf:
            old_meta = json.load(_mf) or {}
    except Exception:
        old_meta = {}
    existing = set()  # 已存在图片的内容哈希(用于去重,避免重复下载)
    for f in sorted(os.listdir(out)):
        fp = os.path.join(out, f)
        if not os.path.isfile(fp) or f.lower() == "meta.json":
            continue
        m = HASH_RE.search(f)
        if m:
            existing.add(m.group(1).lower())
            continue
        m = OLD_RE.match(f)  # 旧版顺序命名 -> 升级为新哈希命名,纳入增量体系
        if m:
            date = m.group(1) or ""
            try:
                with open(fp, "rb") as _fh:
                    h = hashlib.sha256(_fh.read()).hexdigest()[:12]
                new_name = f"img_{date}_{h}{os.path.splitext(f)[1].lower()}"
                new_path = os.path.join(out, new_name)
                if os.path.exists(new_path):
                    os.remove(fp)  # 已存在同哈希文件,删冗余
                else:
                    os.rename(fp, new_path)
                existing.add(h)
                if f in old_meta:
                    old_meta[new_name] = old_meta.pop(f)
            except Exception:
                pass
    log(f"本地已保留 {len(existing)} 张旧图, 开始补抓新图…")
    log(f"正在抓取 {url} ...")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(accept_downloads=True)
        pg = ctx.new_page()
        pg.goto("https://igram.world/en1/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        # 切换到 Photo 标签(2025+新版 igram.world 默认是 Video,需切到 Photo 才是图片下载流)
        tab_clicked = False
        for el in pg.query_selector_all("div, li, a, button, span"):
            if (el.inner_text() or "").strip() == "Photo":
                try:
                    el.click()
                    tab_clicked = True
                    log("已切换到 Photo 标签")
                    break
                except Exception:
                    continue
        if not tab_clicked:
            log("未找到 Photo 标签(页面结构可能已变)")
        time.sleep(2)
        pg.fill("input.search-form__input", url)
        for el in pg.query_selector_all("button.search-form__button"):
            el.click()
            log("已点击 Download,正在下载资料(首次较慢)...")
            break

        # igram.world 后端不稳定,加自动重试(最多 3 次,每次 120s)
        appeared = False
        for retry in range(3):
            try:
                pg.wait_for_selector("li.profile-media-list__item", timeout=120000)
                appeared = True
                break
            except Exception as e:
                log(f"等待结果超时(第 {retry+1}/3 次): {e}; URL={pg.url}")
                if retry < 2:
                    log("igram.world 似乎临时不可用,10 秒后自动重试...")
                    time.sleep(10)
                    try:
                        pg.goto("https://igram.world/en1/", wait_until="domcontentloaded", timeout=60000)
                        time.sleep(2)
                        for el2 in pg.query_selector_all("div, li, a, button, span"):
                            if (el2.inner_text() or "").strip() == "Photo":
                                try:
                                    el2.click(); break
                                except Exception:
                                    continue
                        time.sleep(2)
                        pg.fill("input.search-form__input", url)
                        for el2 in pg.query_selector_all("button.search-form__button"):
                            el2.click(); break
                        log("已重新点击 Download,继续等待...")
                    except Exception as e2:
                        log(f"重试导航失败: {e2}")
        if not appeared:
            log("3 次重试均未拿到结果,请稍后手动点「刷新」再试,或用「导入图片」手动添加。")
            try:
                pg.screenshot(path=os.path.join(out, "_debug_fail.png"), full_page=True)
            except Exception:
                pass
            b.close()
            return 0
        log("结果已加载,开始提取")
        # 触发 igram.world 懒加载: 必须用 scrollIntoView 把最后一项滚进视口,
        # 它靠 IntersectionObserver 监听元素进视口才加载更多; window.scrollTo
        # 对该站内嵌滚动容器无效(实测永远停在初始 6 张)。反复滚到最后一项,
        # 直到连续 3 轮数量不再增长(动态停止, 既抓全又不会死等)。
        prev_n = 0
        stable = 0
        for _ in range(60):
            pg.evaluate("""() => {
                const lis = document.querySelectorAll('li.profile-media-list__item');
                if (lis.length) lis[lis.length - 1].scrollIntoView();
            }""")
            time.sleep(1.2)
            n = len(pg.query_selector_all("li.profile-media-list__item"))
            if n == prev_n:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
                prev_n = n
        items = pg.query_selector_all("li.profile-media-list__item")
        log(f"找到 {len(items)} 条帖子")
        # 张数限制:最多抓取 N 张(0=不限制,全部)
        max_photos = int(load_cfg().get("max_photos", 0))
        if max_photos > 0 and len(items) > max_photos:
            items = items[:max_photos]
            log(f"按设置只抓取前 {max_photos} 张")
        saved = 0
        meta = {}
        # 直接抓取预览原图:igram.world 的「下载按钮」与「预览图」画质完全一致,
        # 改写尺寸令牌(s640x640→s1080x1080)会被服务器判定签名失效而回退 640,
        # 故这里直接拿预览地址(src),简单可靠。
        for i, it in enumerate(items, 1):
            prev = it.query_selector("img[alt='preview']")
            src = prev.get_attribute("src") if prev else None
            if not src:
                continue
            # 先取发布时间,用于文件名与状态栏
            date = None
            try:
                date = extract_post_time(it)
            except Exception:
                pass
            data, ext = b"", ".jpg"
            try:
                resp = ctx.request.get(src, timeout=60000)
                d = resp.body()
                if len(d) >= 3000:
                    mime = resp.headers.get("content-type", "")
                    e = ".jpg" if "jpeg" in mime else (".webp" if "webp" in mime else ".bin")
                    if d[:4] in (b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xdb"):
                        e = ".jpg"
                    elif d[:4] == b"RIFF" and d[8:12] == b"WEBP":
                        e = ".webp"
                    data, ext = d, e
            except Exception:
                pass
            if not data:
                log(f"  [{i}] 下载失败")
                continue
            # 内容哈希: 同一张图无论命名/顺序如何变化都去重,避免重复下载
            h = hashlib.sha256(data).hexdigest()[:12]
            if h in existing:
                log(f"  [{i}] 已存在, 跳过")
                existing.add(h)
                continue
            existing.add(h)
            name = f"img_{date}_{h}" if date else f"img_{h}"
            path = os.path.join(out, name + ext)
            with open(path, "wb") as f:
                f.write(data)
            meta[os.path.basename(path)] = date
            saved += 1
            log(f"  已保存第 {saved} 张(新)" + (f" ({date})" if date else ""))
        # 写出发布时间元数据(合并旧记录, 保留已删除/旧图日期信息)
        try:
            meta.update(old_meta)
            with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as mf:
                json.dump(meta, mf, ensure_ascii=False, indent=2)
        except Exception:
            pass
        b.close()
    return saved

# ---------- 设置壁纸 ----------
def _screen_size():
    # 先让进程 DPI 感知,这样 GetSystemMetrics 返回【物理像素】。
    # 否则高 DPI 屏(如 1920x1080 设了 125% 缩放)会返回逻辑像素 1536x864,
    # 合成出的壁纸比屏幕小,居中贴上去四周留黑边("填不满")。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # 旧系统兜底
        except Exception:
            pass
    try:
        w = ctypes.windll.user32.GetSystemMetrics(0)   # SM_CXSCREEN (物理像素)
        h = ctypes.windll.user32.GetSystemMetrics(1)   # SM_CYSCREEN
        if w and h:
            return w, h
    except Exception:
        pass
    return 1920, 1080

def img_size(path):
    """返回图片像素尺寸字符串(如 1080x1350),失败返回空。"""
    if not HAVE_PIL:
        return ""
    try:
        with Image.open(path) as im:
            return f"{im.size[0]}x{im.size[1]}"
    except Exception:
        return ""

def _draw_date(canvas, date):
    """在黑边整图的左下角画发布日期(白色小字,不裁切/不遮挡照片)。"""
    if not date:
        return
    try:
        from PIL import ImageDraw, ImageFont
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 30)
        except Exception:
            font = ImageFont.load_default()
        draw = ImageDraw.Draw(canvas)
        text = f"发布 {date}"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        m = 18
        x, y = m, canvas.height - th - m
        draw.rectangle([x - 8, y - 8, x + tw + 8, y + th + 8], fill=(20, 20, 20))
        draw.text((x, y), text, font=font, fill=(255, 255, 255))
    except Exception:
        pass

def _compose_letterbox(path, fit, date=""):
    """把单张图片合成一张屏幕大小的整图。
    - cover : 等比放大铺满屏幕,裁掉溢出部分,不变形,无黑边(默认;黑边只是兜底)
    - fit   : 等比缩进屏幕,留黑边,绝不裁切(在黑边角落烤发布日期)
    - center: 原尺寸居中(过大则等比缩进),留黑边(同样烤日期)
    返回合成后的临时文件路径;异常时回退原图路径。"""
    if not HAVE_PIL:
        return path
    try:
        sw, sh = _screen_size()
        with Image.open(path) as im:
            im = im.convert("RGB")
            iw, ih = im.size
            if fit == "cover":
                # 铺满:取较大比例,保证宽高都 >= 屏幕,再裁中间多余部分
                scale = max(sw / iw, sh / ih)
                nw, nh = max(sw, int(iw * scale)), max(sh, int(ih * scale))
                im = im.resize((nw, nh), Image.LANCZOS)
                left, top = (nw - sw) // 2, (nh - sh) // 2
                im = im.crop((left, top, left + sw, top + sh))
                canvas = im                      # 已是屏幕精确尺寸,无黑边
            else:
                # fit / center:整图等比缩进屏幕,四周补黑边,绝不裁切
                if fit == "center" and iw <= sw and ih <= sh:
                    nw, nh = iw, ih              # 小于屏幕,原尺寸居中,不放大
                else:
                    scale = min(sw / iw, sh / ih)
                    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                if (nw, nh) != (iw, ih):
                    im = im.resize((nw, nh), Image.LANCZOS)
                canvas = Image.new("RGB", (sw, sh), (0, 0, 0))   # 黑底(允许黑边)
                canvas.paste(im, ((sw - nw) // 2, (sh - nh) // 2))
                _draw_date(canvas, date)         # 仅在黑边模式烤发布日期
            tmp = os.path.join(APP_DIR, "_wallpaper_tmp.png")
            canvas.save(tmp, "PNG")
            return tmp
    except Exception:
        return path

def _best_grid(n, sw, sh):
    """为 n 张图选一个 cols*rows==n 的网格,使每个格子宽高比尽量接近 1(最不畸形)。"""
    import math
    best, best_score = (1, n), 1e9
    for a in range(1, int(math.isqrt(n)) + 1):
        if n % a == 0:
            b = n // a
            for cols, rows in ((a, b), (b, a)):
                cell_aspect = (sw / cols) / (sh / rows)
                score = abs(math.log(cell_aspect))
                if score < best_score:
                    best_score, best = score, (cols, rows)
    return best

def _compose_collage(paths):
    """把多张图拼成一张精确填满屏幕的整图(无黑边、不变形)。
    每格按 cover 方式裁切填满;网格行列按屏幕比例与张数自适应(无空格)。"""
    if not paths:
        return ""
    if not HAVE_PIL or len(paths) == 1:
        return paths[0]
    try:
        sw, sh = _screen_size()
        n = len(paths)
        cols, rows = _best_grid(n, sw, sh)
        cw, ch = sw // cols, sh // rows
        canvas = Image.new("RGB", (sw, sh), (0, 0, 0))
        for idx, p in enumerate(paths):
            r, c = divmod(idx, cols)
            x, y = c * cw, r * ch
            try:
                with Image.open(p) as im:
                    im = im.convert("RGB")
                    iw, ih = im.size
                    scale = max(cw / iw, ch / ih)
                    nw, nh = max(cw, int(iw * scale)), max(ch, int(ih * scale))
                    im = im.resize((nw, nh), Image.LANCZOS)
                    im = im.crop(((nw - cw) // 2, (nh - ch) // 2,
                                  (nw - cw) // 2 + cw, (nh - ch) // 2 + ch))
                    canvas.paste(im, (x, y))
            except Exception:
                continue
        tmp = os.path.join(APP_DIR, "_wallpaper_collage.png")
        canvas.save(tmp, "PNG")
        return tmp
    except Exception:
        return paths[0]

def _upscale(path):
    """用本地 Real-ESRGAN(NCNN/Vulkan)对图片做 GPU 超分;结果按源路径哈希缓存到独立目录
    (不写在源图目录,避免被轮播池重复扫描)。
    真实照片用 realesrgan-x4plus 模型(4x,画质最佳);无二进制 / 失败 / 无显卡 Vulkan 时
    返回原图路径(不阻断壁纸设置)。"""
    exe = realesrgan_exe()
    if not os.path.isfile(exe):
        return path
    try:
        import subprocess, hashlib
        cache_dir = os.path.join(APP_DIR, "_upscale_cache")
        os.makedirs(cache_dir, exist_ok=True)
        key = hashlib.md5(os.path.abspath(path).encode("utf-8", "ignore")).hexdigest()[:16]
        out = os.path.join(cache_dir, f"{key}_esrgan_x4.png")
        # 命中缓存且未过期,直接复用
        if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(path):
            return out
        models = os.path.join(realesrgan_dir(), "models")
        cmd = [exe, "-i", path, "-o", out, "-s", "4",
               "-n", "realesrgan-x4plus", "-f", "png"]
        if os.path.isdir(models):
            cmd += ["-m", models]
        # CREATE_NO_WINDOW(0x08000000):隐藏 Real-ESRGAN 的 Vulkan 控制台弹窗
        subprocess.run(cmd, capture_output=True, timeout=600,
                       creationflags=0x08000000)
        if os.path.isfile(out) and os.path.getsize(out) > 3000:
            return out
    except Exception:
        pass
    return path

def set_wallpaper(path, fit, date=""):
    target = path
    if fit == "collage":
        # 拼贴图已由调用方合成好(精确屏幕尺寸),直接铺满
        ws, tp = ("0", "0")
    elif fit in ("fit", "center", "cover") and HAVE_PIL:
        # 合成后 target 已是屏幕尺寸的整图,用 center(0/0)即可完美铺满
        target = _compose_letterbox(path, fit, date)
        ws, tp = ("0", "0")
    else:
        # 无 PIL 时交给系统原生样式处理
        if fit == "tile":
            ws, tp = ("0", "1")      # 平铺
        elif fit == "cover":
            ws, tp = ("10", "0")     # 系统原生"填充"(裁切铺满,不变形)
        elif fit == "fit":
            ws, tp = ("6", "0")      # 系统原生"适应"(留黑边,不变形)
        else:                        # center
            ws, tp = ("0", "0")
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, ws)
    winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tp)
    winreg.CloseKey(key)
    SPI_SETDESKTOPWALLPAPER = 20
    SPIF_UPDATEINIFILE = 0x01
    SPIF_SENDCHANGE = 0x02
    ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETDESKTOPWALLPAPER, 0, target, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
    global CURRENT_WALLPAPER
    try:
        CURRENT_WALLPAPER = os.path.abspath(target)
    except Exception:
        pass

# ---------- 本地 HTTP 服务(音乐播放器一体化) ----------
# 让壁纸 App 自己托管 music.html,并接收"加封面做壁纸"请求:
# HTML 用相对路径 /add_cover 把封面交给 App,由 App 下载图片并自动配置成壁纸来源,
# 与 IG/歌手 同等待遇(自动进账户列表、参与轮播、带每组 GPU 超分开关),无需手动导入。
WALL_APP = None
CURRENT_WALLPAPER = None   # 当前桌面壁纸绝对路径(供 /current_wallpaper 端点返回)
WALL_PORT = 18765
WALL_HOST = "127.0.0.1"
GD_API = "https://music-api.gdstudio.xyz/api.php"

# WMO 天气代码 -> 中文描述(用于桌面天气显示)
WMO_DESC = {
    0: "晴", 1: "大致晴朗", 2: "局部多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴冰雹", 99: "雷暴伴冰雹",
}
# 微软天气(中国)官方页面,点击天气数字跳转此处
MS_WEATHER_URL = "https://www.msn.cn/zh-cn/weather"

# 国内主要城市代码表(weather.com.cn 数字代码,长期稳定),作为城市代码查询的兜底。
# 运行时优先用官方接口 toy1.weather.com.cn 查最新代码;该接口偶发限流时回退本表;都没有则用默认城市。
_CN_CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "天津": "101030100", "重庆": "101040100",
    "广州": "101280101", "深圳": "101280601", "成都": "101270101", "杭州": "101210101",
    "武汉": "101200101", "西安": "101110101", "南京": "101190101", "苏州": "101190401",
    "郑州": "101180101", "长沙": "101250101", "青岛": "101120201", "沈阳": "101070101",
    "大连": "101070201", "济南": "101120101", "合肥": "101220101", "福州": "101230101",
    "厦门": "101230201", "南昌": "101240101", "昆明": "101290101", "贵阳": "101260101",
    "南宁": "101300101", "海口": "101310101", "兰州": "101160101", "太原": "101100101",
    "石家庄": "101090101", "哈尔滨": "101050101", "长春": "101060101", "呼和浩特": "101080101",
    "银川": "101170101", "西宁": "101150101", "乌鲁木齐": "101130101", "拉萨": "101140101",
    "宁波": "101210401", "无锡": "101190201", "东莞": "101281701", "佛山": "101280800",
    "常州": "101191101", "温州": "101210701", "泉州": "101230501", "嘉兴": "101210301",
}

def _cover_dir_for(artist):
    """该歌手封面存放目录(保留中文,只去掉文件系统非法字符)。"""
    safe = re.sub(r'[\\/:*?"<>|]', "_", (artist or "未知歌手").strip())
    safe = safe[:60] or "未知歌手"
    return os.path.join(APP_DIR, "covers", safe)

class WallServer(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/music.html"):
            html = None
            if MUSIC_HTML_B64:
                try:
                    html = base64.b64decode(MUSIC_HTML_B64).decode("utf-8")
                except Exception:
                    html = None
            if html is None:
                p = self._html_file()
                if p and os.path.isfile(p):
                    try:
                        html = open(p, encoding="utf-8").read()
                    except Exception:
                        html = None
            if html is None:
                self.send_response(404); self._cors(); self.end_headers(); return
            data = html.encode("utf-8")
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if path == "/health":
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers(); self.wfile.write(b'{"ok":true}'); return
        if path == "/current_wallpaper":
            wp = CURRENT_WALLPAPER
            url = ("file:///" + wp.replace("\\", "/")) if (wp and os.path.isfile(wp)) else None
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"wallpaper": url}).encode("utf-8")); return
        if path == "/appcfg":
            # 供播放器网页读取:若开启「字体同步到网页」,返回歌词同款字体族名
            fam = ""
            app = WALL_APP
            if app is not None:
                fam = app._ui_font_family()
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"uiFont": fam}).encode("utf-8")); return
        self.send_response(404); self._cors(); self.end_headers()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/add_cover":
            try:
                ln = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(ln) if ln else b"{}"
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_response(400); self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8")); return
            # 立即回执,重活在后台线程做(避免浏览器转圈卡住)
            self.send_response(202); self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "accepted": True}).encode("utf-8"))
            app = WALL_APP
            if app is not None:
                threading.Thread(
                    target=app._add_cover_source,
                    args=(req.get("artist", ""), req.get("source", ""),
                          req.get("covers", []), req.get("mode", "single")),
                    daemon=True).start()
            return
        if path == "/lyric":
            try:
                ln = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(ln) if ln else b"{}"
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception as e:
                self.send_response(400); self._cors(); self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8")); return
            self.send_response(202); self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
            app = WALL_APP
            if app is not None:
                threading.Thread(target=app.update_desktop_lyric,
                                args=(req.get("line", ""), req.get("trans", "")),
                                daemon=True).start()
            return
        self.send_response(404); self._cors(); self.end_headers()

    def _html_file(self):
        for c in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_player.html"),
                  os.path.join(APP_DIR, "music_player.html")):
            if os.path.isfile(c):
                return c
        return None

    def log_message(self, *a):  # 静默,不打到控制台
        pass

def start_wall_server(app, host=WALL_HOST, port=WALL_PORT):
    """启动本地服务(后台线程)。端口被占则顺延探测,成功返回 httpd。"""
    global WALL_APP, WALL_PORT
    WALL_APP = app
    httpd = None
    for p in range(port, port + 11):
        try:
            httpd = http.server.ThreadingHTTPServer((host, p), WallServer)
            WALL_PORT = p
            break
        except OSError:
            continue
    if httpd is None:
        return None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

# ---------- GUI ----------
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_cfg()
        self.running = False
        self.thread = None
        self.vars = {}      # name -> BooleanVar
        self.pool = []
        self.idx = 0
        self._last_fetch_start = 0.0   # 上次抓取开始时间,用于全局限速错峰
        self._last_auto = 0.0          # 上次自动更新时间
        self.log_lines = []            # 运行日志环形缓冲(F12 查看)
        self._fetching = set()         # 正在抓取的账户名(防同账户并发互相覆盖)
        self.desk_lyric_win = None     # 桌面歌词置顶窗(Toplevel)
        self.desk_lyric_label = None   # 桌面歌词文本控件
        self.desk_lyric_grip = None    # 桌面歌词右下角「缩放手柄」
        self._lyric_font_size = int(self.cfg.get("lyric_font_size", 22))  # 歌词字号
        self._lyric_drag_unlocked = False   # 歌词拖动是否处于限时解锁窗口
        self._lyric_drag_remaining = 0      # 剩余可拖动秒数
        self._lyric_drag_after = None       # 倒计时 after id
        self.lyric_drag_btn = None          # 主界面「解锁歌词拖动」按钮引用

        root.title("INS 壁纸轮播器  v2.8.1")
        root.geometry("840x690")
        try:
            root.iconbitmap()
        except Exception:
            pass
        self._style()
        self._register_custom_fonts()   # 重启后重新注册自定义字体(在构建 UI 前)
        self._build()
        self.refresh_account_list()
        self._restore_settings()
        # 系统托盘:关闭主窗口默认最小化到托盘,避免"关了之后换壁纸失效"
        self.tray_icon = None
        self._setup_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F12>", lambda e: self.show_errors())

        # 「字体同步到软件界面」:若开启,把歌词同款字体应用到整个软件
        self._apply_global_font()
        # 天气(可选 · 非强制):开启则立即获取并每30分钟刷新一次
        self._weather_timer = None
        self._geo_cache = {}
        self._auto_geo = None        # 自动定位得到的 (lat, lon)
        self._auto_city = ""         # 自动定位得到的城市名
        self._frozen = False         # 壁纸定格(暂停轮播换图)标志:F1+F2 切换
        if self.cfg.get("weather_enabled"):
            self._start_weather()
        # 单实例:启动"被二次点击时把窗口提到最前"的等待线程(仅 Windows 主实例)
        self._start_show_thread()
        # 全局热键(默认 F1+F2,可自定义,须 >=2 键同时按):定格/取消定格壁纸,托盘模式也生效
        self._freeze_hk = FreezeHotkey(self._toggle_freeze, self._on_hotkey_status,
                                       get_keys=self._get_freeze_codes)
        self._freeze_hk.start()
        if not self._freeze_hk.is_active():
            self.log("[热键] 注意: 系统级热键不可用,可使用托盘菜单『定格/恢复壁纸轮播』")

    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("vista")
        except Exception:
            pass
        s.configure("TButton", font=("Microsoft YaHei", 10))
        s.configure("TLabel", font=("Microsoft YaHei", 10))
        s.configure("Title.TLabel", font=("Microsoft YaHei", 15, "bold"))

    def _build(self):
        pad = dict(padx=10, pady=6)

        ttk.Label(self.root, text="INS 壁纸轮播器", style="Title.TLabel").pack(anchor="w", **pad)

        # 天气(可选 · 非强制开启):平时显示温度+天气,每30分钟更新,点数字跳微软天气
        f_weather = ttk.LabelFrame(self.root, text="天气（可选 · 非强制开启）")
        f_weather.pack(fill="x", **pad)
        self.weather_on_var = tk.BooleanVar(value=bool(self.cfg.get("weather_enabled", False)))
        ttk.Checkbutton(f_weather, text="显示天气（每30分钟自动更新）",
                        variable=self.weather_on_var, command=self._on_weather_toggle).pack(side="left")
        self.weather_auto_var = tk.BooleanVar(value=bool(self.cfg.get("weather_auto", True)))
        ttk.Checkbutton(f_weather, text="自动获取位置",
                        variable=self.weather_auto_var, command=self._on_weather_auto_change).pack(side="left", padx=(10, 2))
        self.weather_city_var = tk.StringVar(value=self.cfg.get("weather_city", "北京"))
        self.weather_city_lbl = ttk.Label(f_weather, text="城市：")
        self.weather_city_lbl.pack(side="left")
        self.weather_city_entry = ttk.Entry(f_weather, textvariable=self.weather_city_var, width=12)
        self.weather_city_entry.pack(side="left", padx=2)
        self.weather_city_btn = ttk.Button(f_weather, text="应用城市", command=self._on_weather_city_change)
        self.weather_city_btn.pack(side="left", padx=2)
        self.weather_var = tk.StringVar(value="—")
        self.weather_label = ttk.Label(f_weather, textvariable=self.weather_var, cursor="hand2",
                                       foreground="#1a73e8", font=("Microsoft YaHei", 11, "bold"))
        self.weather_label.pack(side="left", padx=12)
        self.weather_label.bind("<Button-1>", lambda e: self._open_microsoft_weather())
        self.weather_label.bind("<Enter>", lambda e: self.weather_label.configure(foreground="#0b57d0"))
        self.weather_label.bind("<Leave>", lambda e: self.weather_label.configure(foreground="#1a73e8"))
        self.weather_loc_var = tk.StringVar(value="")
        self.weather_loc_lbl = ttk.Label(f_weather, textvariable=self.weather_loc_var, foreground="#999", font=("Microsoft YaHei", 8))
        self.weather_loc_lbl.pack(side="left")
        ttk.Label(f_weather, text="（点数字打开微软天气）", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left")
        # 初始根据「自动获取位置」状态启用/禁用手动城市输入
        self._apply_weather_auto_state()

        # 导入来源
        f0 = ttk.LabelFrame(self.root, text="导入来源")
        f0.pack(fill="x", **pad)
        ttk.Label(f0, text="IG 链接(每行一个,可批量粘贴多个):").pack(anchor="w", padx=6, pady=(4, 0))
        self.url_text = tk.Text(f0, height=3, width=86)
        self.url_text.pack(fill="x", padx=6, pady=2)
        row0 = ttk.Frame(f0)
        row0.pack(fill="x", padx=6, pady=2)
        ttk.Button(row0, text="导入 IG 账户", command=self.import_account).pack(side="left")
        ttk.Button(row0, text="导入文件夹", command=self.import_folder).pack(side="left", padx=8)
        ttk.Button(row0, text="导入单张图片", command=self.import_single).pack(side="left")
        ttk.Button(row0, text="导入随机图(内置)", command=self.import_net).pack(side="left", padx=8)
        ttk.Button(row0, text="统一刷新所有IG", command=self.refresh_all).pack(side="left", padx=8)
        row0b = ttk.Frame(f0)
        row0b.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(row0b, text="刷新间隔(秒):", foreground="#666").pack(side="left")
        self.gap_var = tk.IntVar(value=20)
        ttk.Spinbox(row0b, from_=0, to=600, increment=5, textvariable=self.gap_var, width=6).pack(side="left", padx=4)
        ttk.Label(row0b, text="(统一刷新时各账户错峰启动,防 igram.world 锁死;0=不等待)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)
        ttk.Label(row0b, text="  最多抓取(张):", foreground="#666").pack(side="left", padx=(10, 0))
        self.max_photos_var = tk.IntVar(value=0)
        ttk.Spinbox(row0b, from_=0, to=300, increment=1, textvariable=self.max_photos_var, width=5).pack(side="left", padx=4)
        ttk.Label(row0b, text="(0=全部)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        # 歌手(音乐)来源:抓全部专辑封面当壁纸 + 打开音乐播放器
        row0c = ttk.Frame(f0)
        row0c.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(row0c, text="歌手(专辑壁纸):", foreground="#666").pack(side="left")
        self.singer_var = tk.StringVar(value="")
        ttk.Entry(row0c, textvariable=self.singer_var, width=22).pack(side="left", padx=4)
        ttk.Button(row0c, text="导入该歌手专辑", command=self.import_singer).pack(side="left")
        ttk.Button(row0c, text="打开音乐播放器", command=lambda: self.open_player(self.singer_var.get().strip())).pack(side="left", padx=6)
        # 歌词拖动限时解锁按钮(按下后 20 秒内可拖动,到时自动锁定防误触)
        self.lyric_drag_btn = ttk.Button(row0c, text="解锁歌词拖动", command=self.unlock_lyric_drag)
        self.lyric_drag_btn.pack(side="left", padx=6)
        ttk.Label(row0c, text="(抓该歌手全部专辑封面当壁纸;播放器用 GD 音乐台 API,数据仅供学习)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        # 桌面歌词外观:透明度 / 字体 / 文字颜色(实时调节,存 cfg)
        row0d = ttk.Frame(f0)
        row0d.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(row0d, text="桌面歌词外观:", foreground="#666").pack(side="left")
        ttk.Label(row0d, text="透明度").pack(side="left", padx=(4, 0))
        self.lyric_alpha_var = tk.DoubleVar(value=float(self.cfg.get("lyric_alpha", 0.7)))
        tk.Scale(row0d, from_=0.2, to=1.0, resolution=0.02, orient="horizontal",
                 length=120, variable=self.lyric_alpha_var,
                 command=self._on_lyric_alpha_change).pack(side="left", padx=2)
        ttk.Label(row0d, text="字体").pack(side="left", padx=(10, 0))
        self.lyric_font_var = tk.StringVar(value=self.cfg.get("lyric_font", "Microsoft YaHei"))
        self.lyric_font_cb = ttk.Combobox(row0d, textvariable=self.lyric_font_var, width=14,
                                          values=["Microsoft YaHei", "SimHei", "SimSun", "KaiTi", "等线", "黑体", "YouYuan", "Arial", "导入字体…"],
                                          state="readonly")
        self.lyric_font_cb.pack(side="left", padx=2)
        self.lyric_font_cb.bind("<<ComboboxSelected>>", self._on_lyric_font_change)
        ttk.Button(row0d, text="文字颜色", command=self._choose_lyric_color).pack(side="left", padx=(10, 2))
        # 「字体同步到软件与网页」:把歌词同款字体也应用到整个软件界面 + 打开的网页(播放器)
        self.ui_font_sync_var = tk.BooleanVar(value=bool(self.cfg.get("ui_font_sync", False)))
        ttk.Checkbutton(row0d, text="同步到软件与网页", variable=self.ui_font_sync_var,
                        command=self._on_ui_font_sync_change).pack(side="left", padx=(10, 2))

        # 来源列表(可滚动 + 勾选 + 时段)
        f1 = ttk.LabelFrame(self.root, text="来源列表(勾选参与轮播,可设每日时段)")
        f1.pack(fill="both", expand=True, **pad)
        list_frame = ttk.Frame(f1)
        list_frame.pack(fill="both", expand=True, padx=6, pady=4)
        self.canvas = tk.Canvas(list_frame, height=210, bg="white")
        self.scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.acct_inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.acct_inner, anchor="nw")
        self.acct_inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # 轮播设置
        f2 = ttk.LabelFrame(self.root, text="轮播设置")
        f2.pack(fill="x", **pad)
        r = ttk.Frame(f2)
        r.pack(fill="x", padx=6, pady=4)
        ttk.Label(r, text="间隔(秒):").pack(side="left")
        self.interval_var = tk.IntVar(value=30)
        ttk.Spinbox(r, from_=5, to=3600, increment=5, textvariable=self.interval_var, width=8).pack(side="left", padx=4)

        ttk.Label(r, text="顺序:").pack(side="left", padx=(12, 0))
        self.order_var = tk.StringVar(value="random")
        ttk.Radiobutton(r, text="随机", variable=self.order_var, value="random").pack(side="left")
        ttk.Radiobutton(r, text="顺序", variable=self.order_var, value="sequence").pack(side="left")

        r2 = ttk.Frame(f2)
        r2.pack(fill="x", padx=6, pady=2)
        ttk.Label(r2, text="填充方式:").pack(side="left")
        self.fit_var = tk.StringVar(value="铺满(不变形)")
        ttk.OptionMenu(r2, self.fit_var, "铺满(不变形)", *FIT_KEYS).pack(side="left", padx=4)
        ttk.Button(r2, text="打开缓存目录", command=self.open_cache).pack(side="left", padx=12)

        # AI 超分 + 拼贴张数(新功能行)
        r5 = ttk.Frame(f2)
        r5.pack(fill="x", padx=6, pady=(0, 4))
        self.upscale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r5, text="AI 超分(全局默认,显卡4×)", variable=self.upscale_var).pack(side="left")
        ttk.Label(r5, text="(下方每组可单独覆盖;本地 Real-ESRGAN/NCNN-Vulkan 跑显卡,固定 4× 最佳画质;需显卡支持 Vulkan,失败自动回退原图)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        r7 = ttk.Frame(f2)
        r7.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(r7, text="拼贴张数:").pack(side="left")
        self.collage_n_var = tk.IntVar(value=4)
        ttk.Spinbox(r7, from_=2, to=9, increment=1, textvariable=self.collage_n_var, width=4).pack(side="left", padx=4)
        ttk.Label(r7, text="(填充方式选「拼贴(16:9)」时,把这么多张图拼满屏幕)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        # 定格快捷键(可自定义,须 >=2 键同时按)
        r8 = ttk.Frame(f2)
        r8.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(r8, text="定格快捷键:").pack(side="left")
        self.hotkey_label_var = tk.StringVar(value=self._hotkey_text())
        ttk.Label(r8, textvariable=self.hotkey_label_var, foreground="#0066cc",
                  font=("Microsoft YaHei", 9, "bold")).pack(side="left", padx=4)
        ttk.Button(r8, text="更换快捷键", command=self._change_hotkey).pack(side="left", padx=8)
        ttk.Label(r8, text="(须 2 个及以上按键同时按下;同按一次定格壁纸,再同按一次恢复)",
                  foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        r3 = ttk.Frame(f2)
        r3.pack(fill="x", padx=6, pady=2)
        ttk.Label(r3, text="轮换跨度:").pack(side="left")
        self.span_var = tk.StringVar(value="永久")
        ttk.OptionMenu(r3, self.span_var, "永久", *SPAN_KEYS).pack(side="left", padx=4)
        ttk.Label(r3, text="(只轮换最近这段时间内的照片)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        r4 = ttk.Frame(f2)
        r4.pack(fill="x", padx=6, pady=(0, 4))
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(r4, text="轮播时自动更新IG", variable=self.auto_var).pack(side="left")
        ttk.Label(r4, text="每").pack(side="left", padx=(8, 0))
        self.auto_hours_var = tk.IntVar(value=6)
        ttk.Spinbox(r4, from_=1, to=720, increment=1, textvariable=self.auto_hours_var, width=5).pack(side="left", padx=2)
        ttk.Label(r4, text="小时(更新与轮换合一,无需手动刷新)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        # 控制
        f3 = ttk.Frame(self.root)
        f3.pack(fill="x", **pad)
        self.btn_start = ttk.Button(f3, text="▶ 开始轮播", command=self.start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(f3, text="■ 停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_save = ttk.Button(f3, text="保存设置", command=self.save_settings)
        self.btn_save.pack(side="left", padx=4)

        # 状态
        self.status = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status, foreground="#555").pack(anchor="w", **pad)

        # 免责声明
        ttk.Label(self.root,
                  text="声明:本软件仅供个人将图片设为自己的桌面壁纸使用;图片版权归原作者所有,请勿用于分发或商业用途。",
                  foreground="#999", font=("Microsoft YaHei", 8)).pack(anchor="w", padx=10, pady=(0, 6))

    # ---- 来源列表渲染 ----
    def refresh_account_list(self):
        for w in self.acct_inner.winfo_children():
            w.destroy()
        self.vars.clear()
        if not self.cfg["accounts"]:
            ttk.Label(self.acct_inner, text="(暂无来源,在上方导入 IG 账户 / 文件夹 / 单张图片)", foreground="#999").pack(anchor="w", padx=6, pady=8)
            return
        for acc in self.cfg["accounts"]:
            name = acc["name"]
            var = tk.BooleanVar(value=(name in self.cfg.get("selected", [])))
            self.vars[name] = var
            row = ttk.Frame(self.acct_inner)
            row.pack(fill="x", padx=4, pady=3)
            cb = ttk.Checkbutton(row, text=f"{name} [{TYPE_CN.get(acc.get('type'),'?')}]",
                                 variable=var, width=28,
                                 command=lambda a=acc, v=var: self.on_toggle(a, v))
            cb.pack(side="left")
            # 时段
            ttk.Label(row, text="时段", foreground="#888").pack(side="left", padx=(2, 0))
            sv = tk.StringVar(value=acc.get("start", ""))
            ev = tk.StringVar(value=acc.get("end", ""))
            e1 = ttk.Entry(row, textvariable=sv, width=5)
            e1.pack(side="left", padx=1)
            sv.trace_add("write", lambda *a, acc=acc, sv=sv: self._set_win(acc, "start", sv.get()))
            ttk.Label(row, text="-").pack(side="left")
            e2 = ttk.Entry(row, textvariable=ev, width=5)
            e2.pack(side="left", padx=1)
            ev.trace_add("write", lambda *a, acc=acc, ev=ev: self._set_win(acc, "end", ev.get()))
            ttk.Label(row, text="(空=始终)", foreground="#aaa", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)
            # 张数
            n = len(account_images(acc))
            ttk.Label(row, text=f"{n}张", foreground="#666").pack(side="left", padx=6)
            # 按钮(按类型)
            if acc.get("type") in ("ig", "net", "singer"):
                ttk.Button(row, text="刷新", command=lambda a=acc: self.refresh_one(a)).pack(side="left", padx=2)
            if acc.get("type") in ("singer", "cover"):
                ttk.Button(row, text="打开播放器", command=lambda a=acc: self.open_player(a.get("artist", ""))).pack(side="left", padx=2)
            if acc.get("type") in ("ig", "local"):
                ttk.Button(row, text="导入图片", command=lambda a=acc: self.import_images(a)).pack(side="left", padx=2)
            ttk.Button(row, text="删除", command=lambda a=acc: self.delete_account(a)).pack(side="left", padx=2)
            # 每组 GPU 超分开关(覆盖全局默认;账户未单独设置时回退全局)
            up_var = tk.BooleanVar(value=bool(acc.get("upscale", False)))
            ttk.Checkbutton(row, text="GPU超分", variable=up_var,
                            command=lambda a=acc, v=up_var: self._set_upscale(a, v)).pack(side="left", padx=2)
            # 第二行:源路径
            sub = ttk.Frame(self.acct_inner)
            sub.pack(fill="x", padx=4)
            ttk.Label(sub, text=f"  源: {acc.get('url', '')}", foreground="#999", font=("Microsoft YaHei", 8)).pack(anchor="w")
            # 最近更新(按天):IG 账户显示最新几张发布日期
            if acc.get("type") == "ig":
                meta = load_meta(acc)
                dates = sorted([d for d in meta.values() if d], reverse=True)[:5]
                if dates:
                    sub2 = ttk.Frame(self.acct_inner)
                    sub2.pack(fill="x", padx=4)
                    ttk.Label(sub2, text="  最近更新(按天): " + ", ".join(dates),
                              foreground="#888", font=("Microsoft YaHei", 8)).pack(anchor="w")

    def on_toggle(self, acc, var):
        name = acc["name"]
        sel = self.cfg.setdefault("selected", [])
        if var.get() and name not in sel:
            sel.append(name)
        elif not var.get() and name in sel:
            sel.remove(name)
        save_cfg(self.cfg)

    def _set_win(self, acc, key, val):
        acc[key] = val.strip()
        save_cfg(self.cfg)

    def _set_upscale(self, acc, var):
        acc["upscale"] = bool(var.get())
        save_cfg(self.cfg)

    # ---- 来源操作 ----
    def import_account(self):
        text = self.url_text.get("1.0", "end").strip()
        urls = [u.strip() for u in text.splitlines() if u.strip()]
        if not urls:
            messagebox.showerror("错误", "请输入至少一个 Instagram 链接,每行一个。")
            return
        added = 0
        for url in urls:
            if not re.search(r"instagram\.com/", url):
                self.log(f"跳过无效链接: {url}")
                continue
            sn = safe_name(url)
            if any(a.get("type") == "ig" and safe_name(a["url"]) == sn for a in self.cfg["accounts"]):
                self.log(f"已存在: {sn}")
                continue
            acc = {"name": sn, "type": "ig", "url": url, "dir": os.path.join(ACCOUNTS_DIR, sn)}
            self.cfg["accounts"].append(acc)
            self.cfg.setdefault("selected", []).append(sn)
            added += 1
            threading.Thread(target=self._fetch_thread, args=(acc,), daemon=True).start()
        save_cfg(self.cfg)
        self.url_text.delete("1.0", "end")
        self.refresh_account_list()
        self.log(f"已添加 {added} 个 IG 账户并开始抓取")

    def import_folder(self):
        d = filedialog.askdirectory(title="选择图片文件夹")
        if not d:
            return
        if any(a.get("type") == "folder" and a.get("folder") == d for a in self.cfg["accounts"]):
            messagebox.showinfo("提示", "该文件夹已导入。")
            return
        name = "folder_" + re.sub(r"\W+", "_", os.path.basename(d))[:24]
        acc = {"name": name, "type": "folder", "folder": d, "dir": d, "url": d}
        self.cfg["accounts"].append(acc)
        self.cfg.setdefault("selected", []).append(name)
        save_cfg(self.cfg)
        self.refresh_account_list()
        self.log(f"已导入文件夹: {d}")

    def import_single(self):
        f = filedialog.askopenfilename(
            title="选择一张图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp"), ("全部", "*.*")])
        if not f:
            return
        local = next((a for a in self.cfg["accounts"] if a.get("type") == "local"), None)
        if not local:
            d = os.path.join(ACCOUNTS_DIR, LOCAL_NAME)
            os.makedirs(d, exist_ok=True)
            local = {"name": LOCAL_NAME, "type": "local", "dir": d, "url": d}
            self.cfg["accounts"].append(local)
            self.cfg.setdefault("selected", []).append(LOCAL_NAME)
        os.makedirs(local["dir"], exist_ok=True)
        import shutil
        ext = os.path.splitext(f)[1].lower() or ".jpg"
        base = os.path.basename(f)
        dst = os.path.join(local["dir"], f"single_{int(time.time())}_{base}{ext}")
        try:
            shutil.copy2(f, dst)
            self.refresh_account_list()
            self.log(f"已导入单张图片: {base}")
        except Exception as e:
            self.log(f"复制失败: {e}")

    def refresh_one(self, acc):
        self.log(f"刷新账户 {acc['name']} ...")
        threading.Thread(target=self._fetch_thread, args=(acc,), daemon=True).start()

    def import_net(self):
        if any(a.get("type") == "net" for a in self.cfg["accounts"]):
            messagebox.showinfo("提示", "内置随机图来源已存在。")
            return
        name = "随机图_内置"
        d = os.path.join(ACCOUNTS_DIR, name)
        acc = {"name": name, "type": "net", "dir": d, "url": "内置免费API随机图"}
        self.cfg["accounts"].append(acc)
        self.cfg.setdefault("selected", []).append(name)
        save_cfg(self.cfg)
        self.refresh_account_list()
        threading.Thread(target=self._fetch_thread, args=(acc,), daemon=True).start()
        self.log("已添加内置随机图来源并开始抓取")

    def import_singer(self):
        name = self.singer_var.get().strip()
        if not name:
            messagebox.showerror("错误", "请输入歌手名(例如 Yorushika / 周杰伦)。")
            return
        sn = "singer_" + re.sub(r"\W+", "_", name)[:28]
        if any(a.get("type") == "singer" and a.get("artist") == name for a in self.cfg["accounts"]):
            messagebox.showinfo("提示", f"歌手「{name}」已导入。")
            return
        d = os.path.join(ACCOUNTS_DIR, sn)
        acc = {"name": sn, "type": "singer", "artist": name, "source": "netease",
               "dir": d, "url": "GD音乐台·" + name}
        self.cfg["accounts"].append(acc)
        self.cfg.setdefault("selected", []).append(sn)
        save_cfg(self.cfg)
        self.refresh_account_list()
        threading.Thread(target=self._fetch_thread, args=(acc,), daemon=True).start()
        self.log(f"已添加歌手来源「{name}」并开始抓取全部专辑封面")

    def refresh_all(self):
        """一次性刷新所有 IG 账户,各账户按 refresh_gap 错峰启动,避免服务器锁死。"""
        igs = [a for a in self.cfg["accounts"] if a.get("type") == "ig"]
        if not igs:
            self.log("没有可刷新的 IG 账户")
            return
        gap = max(0, int(self.cfg.get("refresh_gap", 20)))
        self.log(f"统一刷新 {len(igs)} 个 IG 账户,每隔 {gap} 秒错峰启动(防服务器锁死)…")
        for i, a in enumerate(igs):
            if i == 0:
                threading.Thread(target=self._fetch_thread, args=(a,), daemon=True).start()
            else:
                threading.Timer(gap * i, self._fetch_thread, args=(a,)).start()

    def import_images(self, acc):
        files = filedialog.askopenfilenames(
            title=f"为 {acc['name']} 选择图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp"), ("全部", "*.*")],
        )
        if not files:
            return
        os.makedirs(acc["dir"], exist_ok=True)
        import shutil
        copied = 0
        for i, src in enumerate(files, 1):
            ext = os.path.splitext(src)[1].lower() or ".jpg"
            dst = os.path.join(acc["dir"], f"manual_{int(time.time())}_{i:02d}{ext}")
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception as e:
                self.log(f"复制失败: {e}")
        self.refresh_account_list()
        self.log(f"已为 {acc['name']} 手动导入 {copied} 张图片")

    def _fetch_thread(self, acc):
        # 同账户同时只跑一个抓取:避免导入线程与(手动/自动)刷新线程并发,
        # 两个线程都清空并写入同一目录会互相覆盖、日志交错。
        name = acc["name"]
        if name in self._fetching:
            self.log(f"{name} 正在抓取中,跳过重复请求")
            return
        self._fetching.add(name)
        try:
            # 全局限速:两次抓取之间至少间隔 refresh_gap 秒,防止 igram.world 同时被打爆被锁死
            gap = max(0, int(self.cfg.get("refresh_gap", 20)))
            now = time.time()
            wait = gap - (now - self._last_fetch_start)
            if wait > 0:
                self.log(f"限速错峰中,约 {int(wait)} 秒后刷新 {acc['name']}…")
                time.sleep(wait)
            self._last_fetch_start = time.time()
            n = fetch_account(acc, self.log)
            self.root.after(0, self.refresh_account_list)
            self.log(f"账户 {acc['name']} 抓取完成,共 {n} 张")
        except Exception as e:
            self.log(f"抓取失败: {e}")
        finally:
            self._fetching.discard(name)

    def delete_account(self, acc):
        note = "\n(文件夹类型仅移除引用,不会删除你的原文件夹)" if acc.get("type") == "folder" else "\n及其已下载图片?"
        if not messagebox.askyesno("确认", f"删除来源 {acc['name']}?{note}"):
            return
        self.cfg["accounts"] = [a for a in self.cfg["accounts"] if a is not acc]
        self.cfg["selected"] = [s for s in self.cfg.get("selected", []) if s != acc["name"]]
        if acc.get("type") in ("ig", "local", "cover"):
            if os.path.isdir(acc["dir"]):
                import shutil
                shutil.rmtree(acc["dir"], ignore_errors=True)
        save_cfg(self.cfg)
        self.refresh_account_list()
        self.log(f"已删除来源 {acc['name']}")

    def open_cache(self):
        os.startfile(ACCOUNTS_DIR)

    def _music_html_path(self):
        """定位音乐播放器 HTML。
        打包后:优先用内嵌的 base64 数据(MUSIC_HTML_B64,来自 _music_html_data.py)直接写出到
        APP_DIR,这是最稳的方式,彻底绕开 PyInstaller --add-data 把同名文件误判成目录的坑。
        写出后仍兼容 MEIPASS / exe 同级的旧落点作为兜底。
        开发(未冻结)时:取脚本同级的 music_player.html(便于你随时改 HTML 即时生效)。"""
        if getattr(sys, "frozen", False):
            try:
                os.makedirs(APP_DIR, exist_ok=True)
            except Exception:
                pass
            dst = os.path.join(APP_DIR, "music_player.html")
            # ① 内嵌数据写出(最稳)
            if MUSIC_HTML_B64:
                try:
                    import base64
                    data = base64.b64decode(MUSIC_HTML_B64)
                    need = (not os.path.isfile(dst)) or os.path.getsize(dst) != len(data)
                    if need:
                        with open(dst, "wb") as f:
                            f.write(data)
                    return dst
                except Exception:
                    pass
            # ② 兜底:MEIPASS / exe 同级
            cands = []
            if hasattr(sys, "_MEIPASS"):
                mp = sys._MEIPASS
                cands = [
                    os.path.join(mp, "music_player.html"),
                    os.path.join(mp, "music_player.html", "music_player.html"),
                    os.path.join(mp, "assets", "music_player.html"),
                ]
            exedir = os.path.join(os.path.dirname(sys.executable), "music_player.html")
            for src in cands + [exedir]:
                if src and os.path.isfile(src) and (not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst)):
                    try:
                        import shutil
                        shutil.copy2(src, dst)
                    except Exception:
                        pass
            if os.path.isfile(dst):
                return dst
            for src in cands + [exedir]:
                if src and os.path.isfile(src):
                    return src
            return None
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_player.html")
        return local if os.path.isfile(local) else None

    # ---- 封面一体化:下载 + 写配置 ----
    def _gd_pic_bytes(self, pic_id, source, size=500, timeout=25):
        """下载 GD 音乐台专辑封面真实图片字节。
        注意:types=pic 返回的是 {"url":"..."} JSON,真正图片在 url 指向的 CDN 地址,需二次请求。"""
        if not pic_id:
            return None
        qs = urllib.parse.urlencode({"types": "pic", "source": source or "netease",
                                      "id": str(pic_id), "size": size})
        url = GD_API + "?" + qs
        hdr = {"User-Agent": "Mozilla/5.0"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=timeout) as r:
                data = r.read()
        except Exception:
            return None
        # 若为 JSON(含 url),则取真实图片地址再下
        if data[:1] == b"{":
            try:
                j = json.loads(data)
                real = j.get("url")
                if real:
                    with urllib.request.urlopen(urllib.request.Request(real, headers=hdr), timeout=timeout) as r2:
                        return r2.read()
            except Exception:
                return None
        return data

    def _add_cover_source(self, artist, source, covers, mode="single"):
        """由本地服务调用:把封面下载到 APP_DIR/covers/<歌手>/ 并 upsert 一个 cover 账户,
        自动加入 selected、刷新 UI,与 IG/歌手 来源同等待遇。失败自动回退不崩。"""
        if not artist:
            artist = "未知歌手"
        d = _cover_dir_for(artist)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        ok = fail = 0
        for c in (covers or []):
            pid = (c.get("pic_id") or "").strip()
            if not pid:
                fail += 1
                continue
            fn = "album_" + str(pid) + ".jpg"
            fp = os.path.join(d, fn)
            if os.path.isfile(fp):
                ok += 1
                continue  # 已存在,增量保留(与歌手来源一致)
            try:
                b = self._gd_pic_bytes(pid, source)
                if not b:
                    fail += 1
                    continue
                with open(fp, "wb") as f:
                    f.write(b)
                ok += 1
            except Exception as e:
                fail += 1
                self.log(f"[封面] 下载失败 {fn}: {e}")
        # upsert cover 账户
        safe = re.sub(r'[\\/:*?"<>|]', "_", artist.strip())[:60] or "未知歌手"
        name = "cover_" + safe
        acc = next((a for a in self.cfg["accounts"]
                    if a.get("type") == "cover" and a.get("artist") == artist), None)
        if acc is None:
            acc = {"name": name, "type": "cover", "artist": artist,
                   "source": source or "netease", "dir": d,
                   "url": "GD音乐台·封面·" + artist}
            self.cfg["accounts"].append(acc)
        else:
            acc["dir"] = d
            acc["source"] = source or acc.get("source", "netease")
        if name not in self.cfg.get("selected", []):
            self.cfg.setdefault("selected", []).append(name)
        save_cfg(self.cfg)
        self.root.after(0, self.refresh_account_list)
        self.log(f"[封面] {artist} 已加入壁纸:成功 {ok} 张"
                 + (f",失败 {fail} 张" if fail else "") + f"(目录 {d})")

    # ---- 桌面悬浮歌词(永远置顶 / 半透明 / 鼠标穿透) ----
    def update_desktop_lyric(self, line, trans=None):
        # 由 /lyric 端点(后台线程)调用。tkinter 不允许跨线程操作控件,
        # 所以把真正的绘制排到主线程(root.after)执行,避免崩溃。
        self.root.after(0, self._render_desk_lyric, line, trans)

    def _render_desk_lyric(self, line, trans):
        line = (line or "").strip()
        trans = (trans or "").strip()
        # 空行(句间停顿 / 关闭悬浮歌词)→ 隐藏窗口,不挡屏幕
        if not line:
            if self.desk_lyric_win is not None:
                try:
                    self.desk_lyric_win.withdraw()
                except Exception:
                    pass
            return
        if self.desk_lyric_win is None or not self.desk_lyric_win.winfo_exists():
            self._build_desk_lyric_win()
        if self.desk_lyric_win is None:
            return
        # 原句 + 可选译文(译文与原文相同则不重复)
        txt = line if not trans or trans == line else line + "\n" + trans
        try:
            self.desk_lyric_label.configure(text=txt)
            self.desk_lyric_win.attributes("-topmost", True)  # 重新置顶,防止被遮挡
            self._position_desk_lyric()
            self.desk_lyric_win.deiconify()
        except Exception:
            pass

    def _build_desk_lyric_win(self):
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)            # 去标题栏 / 边框
            win.attributes("-topmost", True)      # 永远最上层
            # 半透明深底:比 transparentcolor 抠字在高 DPI 下清晰得多(解决"分辨率低")
            # 透明度 / 字体 / 文字颜色均由主界面调节,并存于 cfg(默认已调淡,不那么黑)
            alpha = float(self.cfg.get("lyric_alpha", 0.7))
            fam = self.cfg.get("lyric_font", "Microsoft YaHei") or "Microsoft YaHei"
            fg = self.cfg.get("lyric_fg", "#ffffff")
            win.attributes("-alpha", alpha)
            win.configure(bg="#0b0e1a")
            # 平时鼠标穿透:不挡桌面操作
            try:
                win.wm_attributes("-disabled", True)
            except Exception:
                pass
            size = int(self.cfg.get("lyric_font_size", 22))
            lbl = tk.Label(win, text="", font=(fam, size, "bold"),
                           fg=fg, bg="#0b0e1a", justify="center",
                           padx=26, pady=14)
            lbl.pack()
            self.desk_lyric_win = win
            self.desk_lyric_label = lbl
            # 拖动支持:仅在「解锁歌词拖动」后的限时窗口内可拖动(防止误触);
            # 平时窗口 -disabled(鼠标穿透),不挡桌面操作。
            win.bind("<ButtonPress-1>", self._on_lyric_drag_start)
            win.bind("<B1-Motion>", self._on_lyric_drag_move)
            win.bind("<ButtonRelease-1>", self._on_lyric_drag_end)
            # 双击回到默认位置(底部居中)
            win.bind("<Double-Button-1>", self._on_lyric_reset_pos)
            # 右下角缩放手柄:拖动可放大/缩小歌词(同样仅在解锁窗口内生效)
            grip = tk.Label(win, text="◢", font=("Microsoft YaHei", 12),
                            fg="#5b8cff", bg="#0b0e1a", cursor="size_nw_se")
            grip.place(relx=1.0, rely=1.0, anchor="se", x=-1, y=-1)
            grip.bind("<ButtonPress-1>", self._on_lyric_resize_start)
            grip.bind("<B1-Motion>", self._on_lyric_resize_move)
            grip.bind("<ButtonRelease-1>", self._on_lyric_resize_end)
            self.desk_lyric_grip = grip
            # 恢复上次拖动保存的位置
            self._restore_lyric_pos()
            self._apply_lyric_drag_state()   # 默认锁定(鼠标穿透),解锁后由按钮改
            self.log("[桌面歌词] 悬浮歌词窗口已创建")
        except Exception as e:
            self.log(f"[桌面歌词] 创建窗口失败: {e}")

    def _on_lyric_drag_start(self, ev):
        # 仅当处于「拖动解锁」限时窗口才允许拖动,平时锁定防误触
        if not self._lyric_drag_unlocked:
            return
        try:
            self._drag_x = ev.x_root - self.desk_lyric_win.winfo_x()
            self._drag_y = ev.y_root - self.desk_lyric_win.winfo_y()
        except Exception:
            pass

    def _on_lyric_drag_move(self, ev):
        if not self._lyric_drag_unlocked or self.desk_lyric_win is None:
            return
        try:
            x = ev.x_root - self._drag_x
            y = ev.y_root - self._drag_y
            self.desk_lyric_win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _on_lyric_drag_end(self, ev):
        if not self._lyric_drag_unlocked or self.desk_lyric_win is None:
            return
        try:
            self._save_lyric_pos(self.desk_lyric_win.winfo_x(),
                                 self.desk_lyric_win.winfo_y())
        except Exception:
            pass

    def _on_lyric_reset_pos(self, ev):
        if not self._lyric_drag_unlocked:
            return
        try:
            self.cfg.pop("lyric_pos", None)
            save_cfg(self.cfg)
            self._position_desk_lyric(force_default=True)
        except Exception:
            pass

    # ---- 悬浮歌词缩放:右下角手柄拖动,改字号(需处于解锁窗口) ----
    def _on_lyric_resize_start(self, ev):
        if not self._lyric_drag_unlocked or self.desk_lyric_win is None:
            return
        try:
            self._resize_start_y = ev.y_root
            self._resize_start_size = int(self.cfg.get("lyric_font_size", 22))
        except Exception:
            pass

    def _on_lyric_resize_move(self, ev):
        if not self._lyric_drag_unlocked or self.desk_lyric_win is None:
            return
        try:
            dy = self._resize_start_y - ev.y_root      # 向上拖 = 放大
            new_size = self._resize_start_size + int(dy / 3.0)
            if new_size < 12: new_size = 12
            if new_size > 72: new_size = 72
            self.cfg["lyric_font_size"] = new_size
            save_cfg(self.cfg)
            self._apply_lyric_font_size()
        except Exception:
            pass

    def _on_lyric_resize_end(self, ev):
        if not self._lyric_drag_unlocked:
            return
        try:
            save_cfg(self.cfg)
        except Exception:
            pass

    # ---- 歌词拖动「限时解锁」:主界面按钮触发,20 秒后自动锁定防误触 ----
    def unlock_lyric_drag(self, seconds=20):
        """按下主界面按钮:解锁歌词拖动 seconds 秒,之后自动锁定。"""
        self._lyric_drag_unlocked = True
        self._lyric_drag_remaining = seconds
        self._apply_lyric_drag_state()
        if self._lyric_drag_after is not None:
            try:
                self.root.after_cancel(self._lyric_drag_after)
            except Exception:
                pass
            self._lyric_drag_after = None
        self._update_lyric_drag_btn()
        self._lyric_drag_after = self.root.after(1000, self._lyric_drag_tick)
        self.log(f"[桌面歌词] 拖动解锁,{seconds} 秒后自动锁定")

    def _lyric_drag_tick(self):
        self._lyric_drag_remaining -= 1
        self._update_lyric_drag_btn()
        if self._lyric_drag_remaining <= 0:
            self.lock_lyric_drag()
            return
        self._lyric_drag_after = self.root.after(1000, self._lyric_drag_tick)

    def lock_lyric_drag(self):
        self._lyric_drag_unlocked = False
        if self._lyric_drag_after is not None:
            try:
                self.root.after_cancel(self._lyric_drag_after)
            except Exception:
                pass
            self._lyric_drag_after = None
        self._apply_lyric_drag_state()
        self._update_lyric_drag_btn()
        self.log("[桌面歌词] 拖动已自动锁定")

    def _apply_lyric_drag_state(self):
        win = self.desk_lyric_win
        if win is None or not win.winfo_exists():
            return
        try:
            if self._lyric_drag_unlocked:
                # 解锁期:接收鼠标(可拖动/可缩放)+ 高亮边框提示,显示缩放手柄
                win.wm_attributes("-disabled", False)
                win.configure(highlightthickness=2, highlightbackground="#5b8cff")
                if self.desk_lyric_grip is not None:
                    self.desk_lyric_grip.place(relx=1.0, rely=1.0, anchor="se", x=-1, y=-1)
            else:
                # 锁定期:鼠标穿透,不挡桌面操作,隐藏缩放手柄
                win.wm_attributes("-disabled", True)
                win.configure(highlightthickness=0)
                if self.desk_lyric_grip is not None:
                    self.desk_lyric_grip.place_forget()
        except Exception:
            pass

    def _update_lyric_drag_btn(self):
        if self.lyric_drag_btn is None:
            return
        try:
            if self._lyric_drag_unlocked:
                self.lyric_drag_btn.configure(text=f"拖动中({self._lyric_drag_remaining}s)")
            else:
                self.lyric_drag_btn.configure(text="解锁歌词拖动")
        except Exception:
            pass

    # ---- 桌面歌词外观:透明度 / 字体 / 文字颜色(主界面可调,实时生效并存 cfg) ----
    @staticmethod
    def _register_font_file(path):
        """把字体文件注册进 Windows GDI(本进程可用),广播字体变更。失败静默。"""
        try:
            ctypes.windll.gdi32.AddFontResourceW(path)
            HWND_BROADCAST = 0xFFFF
            WM_FONTCHANGE = 0x001D
            ctypes.windll.user32.PostMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
        except Exception:
            pass

    @staticmethod
    def _font_family_name(path):
        """用 PIL 读取字体内部真实族名;读不到则退回文件名(去扩展名)。"""
        try:
            from PIL import ImageFont
            return ImageFont.truetype(path, 20).getname()[0]
        except Exception:
            return os.path.splitext(os.path.basename(path))[0]

    def _import_custom_font(self):
        """字体下拉选「导入字体…」时触发:选 .ttf/.otf/.ttc → 复制到 APP_DIR/fonts/
        并注册、提取族名、加入下拉、应用、存 cfg。"""
        path = filedialog.askopenfilename(
            title="选择字体文件（.ttf / .otf / .ttc）",
            filetypes=[("字体文件", "*.ttf;*.otf;*.ttc"), ("所有文件", "*.*")])
        if not path:
            # 用户取消:把下拉还原成已保存字体,避免卡在「导入字体…」
            self.lyric_font_var.set(self.cfg.get("lyric_font", "Microsoft YaHei"))
            return
        try:
            fonts_dir = os.path.join(APP_DIR, "fonts")
            os.makedirs(fonts_dir, exist_ok=True)
            dst = os.path.join(fonts_dir, os.path.basename(path))
            if os.path.abspath(path) != os.path.abspath(dst):
                import shutil as _sh
                _sh.copy2(path, dst)
            self._register_font_file(dst)
            fam = self._font_family_name(dst)
            self.cfg["lyric_font"] = fam
            self.cfg["lyric_font_path"] = dst
            save_cfg(self.cfg)
            # 加入下拉列表(去重,插在「导入字体…」之前)
            vals = list(self.lyric_font_cb["values"])
            if fam not in vals:
                vals.insert(-1, fam)
                self.lyric_font_cb.configure(values=vals)
            self.lyric_font_var.set(fam)
            self._apply_lyric_font()
            self._apply_global_font()
            self.log(f"[桌面歌词] 已导入字体: {fam}")
            messagebox.showinfo("导入成功", f"已导入字体:\n{fam}\n\n文件: {os.path.basename(dst)}")
        except Exception as e:
            self.log(f"[桌面歌词] 导入字体失败: {e}")
            messagebox.showerror("导入字体失败", str(e))
            self.lyric_font_var.set(self.cfg.get("lyric_font", "Microsoft YaHei"))

    def _register_custom_fonts(self):
        """启动时重新注册 cfg 里记录的自定义字体(进程重启后注册会丢失)。"""
        p = self.cfg.get("lyric_font_path", "")
        if p and os.path.exists(p):
            try:
                self._register_font_file(p)
                self.log(f"[桌面歌词] 已重新注册自定义字体: {os.path.basename(p)}")
            except Exception as e:
                self.log(f"[桌面歌词] 重新注册字体失败: {e}")

    def _on_lyric_alpha_change(self, val):
        try:
            a = float(val)
        except Exception:
            return
        if a < 0.2: a = 0.2
        if a > 1.0: a = 1.0
        self.cfg["lyric_alpha"] = a
        save_cfg(self.cfg)
        if self.desk_lyric_win is not None and self.desk_lyric_win.winfo_exists():
            try:
                self.desk_lyric_win.attributes("-alpha", a)
            except Exception:
                pass

    def _on_lyric_font_change(self, ev=None):
        fam = (self.lyric_font_var.get() if self.lyric_font_var else "").strip()
        if fam == "导入字体…":
            self._import_custom_font()
            return
        if not fam:
            fam = "Microsoft YaHei"
        self.cfg["lyric_font"] = fam
        save_cfg(self.cfg)
        self._apply_lyric_font()
        self._apply_global_font()

    def _apply_lyric_font(self):
        self._apply_lyric_font_size()

    def _apply_lyric_font_size(self):
        if self.desk_lyric_label is None:
            return
        try:
            fam = self.cfg.get("lyric_font", "Microsoft YaHei") or "Microsoft YaHei"
            size = int(self.cfg.get("lyric_font_size", 22))
            self.desk_lyric_label.configure(font=(fam, size, "bold"))
            if self.desk_lyric_win is not None and self.desk_lyric_win.winfo_exists():
                w = self.desk_lyric_win.winfo_width()
                if w > 0:
                    self.desk_lyric_label.configure(wraplength=max(200, w - 52))
        except Exception:
            pass

    def _choose_lyric_color(self):
        try:
            from tkinter import colorchooser
            cur = self.cfg.get("lyric_fg", "#ffffff")
            color = colorchooser.askcolor(title="选择歌词文字颜色", initialcolor=cur)
            if not color or not color[1]:
                return
            hexc = color[1]
            self.cfg["lyric_fg"] = hexc
            save_cfg(self.cfg)
            if self.desk_lyric_label is not None:
                self.desk_lyric_label.configure(fg=hexc)
        except Exception as e:
            self.log(f"[桌面歌词] 选择颜色失败: {e}")

    # ---------- 「字体同步到软件与网页」 ----------
    def _ui_font_family(self):
        """返回应同步到软件/网页的字体族名;未开启或仍是默认字体则返回空串。"""
        if not self.cfg.get("ui_font_sync"):
            return ""
        fam = (self.cfg.get("lyric_font", "") or "").strip()
        if not fam or fam == "Microsoft YaHei":
            return ""
        return fam

    def _on_ui_font_sync_change(self):
        on = bool(self.ui_font_sync_var.get())
        self.cfg["ui_font_sync"] = on
        save_cfg(self.cfg)
        self._apply_global_font()

    def _apply_global_font(self):
        """把歌词同款字体同步应用到整个软件界面(可选,ui_font_sync 开启时生效)。"""
        fam = self._ui_font_family()
        if not fam:
            return
        try:
            import tkinter.font as tkfont
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont",
                         "TkCaptionFont", "TkIconFont", "TkFixedFont"):
                try:
                    tkfont.nametofont(name).configure(family=fam)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            s = ttk.Style()
            for st in ("TButton", "TLabel", "TCheckbutton", "TRadiobutton", "TEntry",
                       "TCombobox", "TSpinbox", "TNotebook", "TNotebook.Tab", "TFrame"):
                try:
                    s.configure(st, font=(fam, 10))
                except Exception:
                    pass
            try:
                s.configure("Title.TLabel", font=(fam, 15, "bold"))
            except Exception:
                pass
        except Exception as e:
            self.log(f"[字体] 同步软件界面失败: {e}")

    # ---------- 天气(可选 · 非强制开启) ----------
    def _on_weather_toggle(self):
        on = bool(self.weather_on_var.get())
        self.cfg["weather_enabled"] = on
        save_cfg(self.cfg)
        if on:
            self._start_weather()
        else:
            self._stop_weather()
            try:
                self.weather_var.set("—")
            except Exception:
                pass

    def _on_weather_city_change(self):
        city = (self.weather_city_var.get() or "").strip()
        if not city:
            return
        self.cfg["weather_city"] = city
        save_cfg(self.cfg)
        if self.cfg.get("weather_enabled"):
            self._geo_cache.pop(city, None)
            self._fetch_weather()

    def _apply_weather_auto_state(self):
        """自动获取位置开启时,禁用手动城市输入;反之启用。"""
        auto = bool(self.weather_auto_var.get())
        state = "disabled" if auto else "normal"
        try:
            self.weather_city_lbl.configure(state=state)
            self.weather_city_entry.configure(state=state)
            self.weather_city_btn.configure(state=state)
            if auto:
                self.weather_loc_var.set("")
        except Exception:
            pass

    def _on_weather_auto_change(self):
        auto = bool(self.weather_auto_var.get())
        self.cfg["weather_auto"] = auto
        save_cfg(self.cfg)
        self._apply_weather_auto_state()
        if self.cfg.get("weather_enabled"):
            self._auto_geo = None   # 重新探测定位
            self._auto_city = ""
            self.weather_loc_var.set("")
            self._fetch_weather()

    def _start_show_thread(self):
        """单实例:另开线程等 '显示已有窗口' 事件,收到就把自己主窗口提到最前。"""
        if not (sys.platform.startswith("win") and ctypes.windll):
            return
        try:
            threading.Thread(target=_single_instance_show_thread, args=(self.root,), daemon=True).start()
        except Exception:
            pass

    def _start_weather(self):
        self._stop_weather()
        self._fetch_weather()
        self._schedule_weather()

    def _schedule_weather(self):
        try:
            self._weather_timer = self.root.after(30 * 60 * 1000, self._weather_tick)
        except Exception:
            self._weather_timer = None

    def _weather_tick(self):
        self._fetch_weather()
        self._schedule_weather()

    def _stop_weather(self):
        if self._weather_timer is not None:
            try:
                self.root.after_cancel(self._weather_timer)
            except Exception:
                pass
        self._weather_timer = None

    def _fetch_weather(self):
        try:
            self.weather_var.set("获取中…")
        except Exception:
            pass
        threading.Thread(target=self._fetch_weather_worker, daemon=True).start()

    def _fetch_weather_worker(self):
        try:
            auto = bool(self.cfg.get("weather_auto", True))
            city = None
            city_disp = ""
            if auto:
                if self._auto_city:
                    city = self._auto_city
                    city_disp = self._auto_city
                else:
                    det = self._detect_location()  # -> (lat, lon, city) 或 None
                    if det and det[2]:
                        city = det[2]
                        city_disp = det[2]
                        self._auto_city = city
            if not city:
                city = self.cfg.get("weather_city", "北京") or "北京"
            # 多数据源依次尝试(任一成功即显示);国内源优先,海外源兜底
            result = self._weather_from_cn(city)
            if not result:
                result = self._weather_from_openmeteo(city)
            if not result:
                result = self._weather_from_wttr(city)
            if not result:
                self.root.after(0, lambda: self.weather_var.set("天气获取失败(检查网络/防火墙)"))
                return
            temp, desc = result
            txt = "{}° {}".format(temp, desc)
            self.root.after(0, lambda t=txt: self.weather_var.set(t))
            # 自动定位到城市时显示标签;兜底默认城市不显示定位标签
            if auto and city_disp:
                self.root.after(0, lambda c=city_disp: self.weather_loc_var.set("（自动定位：" + c + "）"))
            else:
                self.root.after(0, lambda: self.weather_loc_var.set(""))
        except Exception as e:
            self.log("[天气] 获取失败: " + str(e))
            try:
                self.root.after(0, lambda: self.weather_var.set("天气获取失败(检查网络/防火墙)"))
            except Exception:
                pass

    def _weather_from_cn(self, city):
        """国内源(中国天气网):城市名 -> 城市代码 -> 实况温度+天气。免密、国内直连。"""
        try:
            code = self._cn_city_code(city)
            if not code:
                self.log("[天气] 中国天气网:未找到城市「" + str(city) + "」的代码")
                return None
            url = "https://d1.weather.com.cn/sk_2d/" + code + ".html"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "http://www.weather.com.cn/"})
            with urllib.request.urlopen(req, timeout=12) as r:
                txt = r.read().decode("utf-8", "ignore")
            m = re.search(r"var dataSK=(\{.*\})", txt)
            if not m:
                self.log("[天气] 中国天气网:返回格式异常")
                return None
            obj = json.loads(m.group(1))
            temp = obj.get("temp")
            weather = obj.get("weather")
            if temp is None or not weather:
                return None
            try:
                t = str(int(round(float(temp))))
            except Exception:
                t = str(temp)
            return (t, weather)
        except Exception as e:
            self.log("[天气] 中国天气网失败: " + str(e))
            return None

    def _cn_city_code(self, city):
        """用中国天气网城市搜索把中文城市名转成数字代码(免密);失败回退内置表。"""
        c = (city or "").strip()
        if not c:
            return None
        # 1) 官方接口(最准,含下级城市),偶发限流
        try:
            url = "http://toy1.weather.com.cn/search?cityname=" + urllib.parse.quote(c)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                txt = r.read().decode("utf-8", "ignore")
            m = re.search(r'"ref":"(\d+)~', txt)
            if m:
                return m.group(1)
        except Exception as e:
            self.log("[天气] 城市代码接口限流,改用内置表: " + str(e))
        # 2) 内置主要城市表兜底
        return _CN_CITY_CODES.get(c)

    def _weather_from_openmeteo(self, city):
        """海外源兜底:Open-Meteo 地理编码 + 实况(无需 key)。"""
        try:
            geo = self._geocode(city)
            if not geo:
                return None
            lat, lon = geo
            url = ("https://api.open-meteo.com/v1/forecast?latitude=" + str(lat) +
                   "&longitude=" + str(lon) +
                   "&current=temperature_2m,weather_code&timezone=auto")
            data = self._http_json(url, timeout=15)
            cur = (data or {}).get("current") or {}
            temp = cur.get("temperature_2m")
            code = cur.get("weather_code")
            if temp is None:
                return None
            return (str(round(float(temp))), WMO_DESC.get(code, "未知"))
        except Exception as e:
            self.log("[天气] Open-Meteo 失败: " + str(e))
            return None

    def _weather_from_wttr(self, city):
        """海外源兜底:wttr.in(按经纬度)。"""
        try:
            geo = self._geocode(city)
            if not geo:
                return None
            lat, lon = geo
            url = "https://wttr.in/" + str(lat) + "," + str(lon) + "?format=j1"
            j = self._http_json(url, timeout=15)
            cc = (j or {}).get("current_condition") or []
            if not cc:
                return None
            c = cc[0]
            temp = c.get("temp_C")
            desc = None
            wd = c.get("weatherDesc") or [{}]
            if wd and wd[0].get("value"):
                desc = wd[0]["value"]
            if temp is None:
                return None
            return (str(int(round(float(temp)))), desc or "未知")
        except Exception as e:
            self.log("[天气] wttr.in 失败: " + str(e))
            return None

    def _detect_location(self):
        """通过 IP 地理定位自动获取当前经纬度(无需 API key)。返回 (lat, lon, city)。
        优先用海外可用的 ipwho.is(直接给经纬度);国内环境常被墙,改用太平洋电脑网
        IP 库(返回中文省市)再经 Open-Meteo 地理编码取经纬度。都失败返回 None。"""
        # 1) ipwho.is:免费、无需 key、海外可用,直接返回经纬度
        try:
            j = self._http_json("https://ipwho.is/", timeout=8)
            if j and j.get("success") and j.get("latitude") is not None:
                return (float(j["latitude"]), float(j["longitude"]),
                        j.get("city") or j.get("region") or "")
        except Exception as e:
            self.log(f"[天气] ipwho.is 定位失败: {e}")
        # 2) 太平洋电脑网 IP 库(国内可访问,返回中文省市):直接取城市名即可
        #    (国内天气源只用城市名查代码,不依赖经纬度,故不再走 Open-Meteo 地理编码)
        try:
            req = urllib.request.Request("https://whois.pconline.com.cn/ipJson.jsp",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                txt = r.read().decode("gbk", "ignore")
            m = re.search(r"\{.*\}", txt, re.S)
            if m:
                obj = json.loads(m.group(0))
                city = (obj.get("city") or obj.get("pro") or "").strip()
                if city:
                    city = re.sub(r"(市|省|自治区|特别行政区|地区)$", "", city)
                    return (0.0, 0.0, city)
        except Exception as e:
            self.log(f"[天气] pconline 定位失败: {e}")
        # 3) ip-api.com 兜底(部分网络可用)
        try:
            j = self._http_json("https://ip-api.com/json/?fields=status,lat,lon,city", timeout=8)
            if j and j.get("status") == "success" and j.get("lat") is not None:
                return (float(j["lat"]), float(j["lon"]), j.get("city") or "")
        except Exception as e:
            self.log(f"[天气] ip-api 定位失败: {e}")
        return None

    def _geocode(self, city):
        """用 Open-Meteo 地理编码把城市名转成经纬度(无需 API key)。"""
        try:
            url = ("https://geocoding-api.open-meteo.com/v1/search?name=" +
                   urllib.parse.quote(city) + "&count=1&language=zh&format=json")
            j = self._http_json(url, timeout=15)
            res = (j or {}).get("results") or []
            if not res:
                return None
            r = res[0]
            return (float(r.get("latitude")), float(r.get("longitude")))
        except Exception as e:
            self.log(f"[天气] 地理编码失败: {e}")
            return None

    def _http_json(self, url, timeout=15):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))

    def _open_microsoft_weather(self):
        """点击天气数字:跳转微软天气(中国)。"""
        try:
            import webbrowser
            webbrowser.open(MS_WEATHER_URL)
        except Exception as e:
            self.log(f"[天气] 打开微软天气失败: {e}")

    def _restore_lyric_pos(self):
        try:
            p = self.cfg.get("lyric_pos")
            if p and isinstance(p, (list, tuple)) and len(p) == 2:
                self.desk_lyric_win.geometry(f"+{int(p[0])}+{int(p[1])}")
        except Exception:
            pass

    def _save_lyric_pos(self, x, y):
        try:
            self.cfg["lyric_pos"] = [int(x), int(y)]
            save_cfg(self.cfg)
        except Exception:
            pass

    def _position_desk_lyric(self, force_default=False):
        try:
            win = self.desk_lyric_win
            win.update_idletasks()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # 固定一个较宽的最小宽度,避免短句把窗口挤成"只一点点"
            target_w = max(640, int(sw * 0.62))
            w = win.winfo_width(); h = win.winfo_height()
            if w < target_w:
                win.geometry(f"{target_w}x{h}")
                win.update_idletasks()
                w = target_w
            # 文字随窗口宽度自动换行,确保完整显示
            self.desk_lyric_label.configure(wraplength=target_w - 52)
            # 位置:已拖动保存过 → 保持;否则底部居中
            saved = self.cfg.get("lyric_pos")
            if force_default or not saved:
                x = max(0, (sw - w) // 2)
                y = max(0, sh - h - 96)
                win.geometry(f"{w}x{h}+{x}+{y}")
            else:
                win.geometry(f"{w}x{h}+{int(saved[0])}+{int(saved[1])}")
        except Exception:
            pass

    def open_player(self, artist=""):
        # 用本程序自带的本地服务(http://127.0.0.1:PORT/music.html)托管播放器,
        # 这样"加封面做壁纸"能通过相对路径 /add_cover 一体化配置,无需手动导入。
        # v2.8.1:改用系统 Edge 应用模式(msedge --app)打开播放器,不弹系统浏览器标签页;
        # 也不再尝试 Electron(本构建环境拿不到完整的 Electron 内核)。
        # 改用系统 Edge 的「应用模式」(msedge --app=网址)打开播放器:
        #   无地址栏 / 无标签栏 / 无工具栏,就是一个纯净的播放器窗口,
        #   体验和"内嵌窗口"一致,且用你机器现成的 WebView2,100% 可用。
        url = f"http://{WALL_HOST}:{WALL_PORT}/music.html"
        if artist:
            url += "?artist=" + urllib.parse.quote(artist)
        # 单实例:若播放器窗口已经开着,直接聚焦到原窗口(不再新开,修复"托盘总开新界面")
        if self._focus_existing_player():
            self.log("音乐播放器已打开,已聚焦到现有窗口")
            return
        self.log("正在打开音乐播放器" + (f"（歌手：{artist}）" if artist else ""))
        threading.Thread(target=self._open_player_edge_app, args=(url,), daemon=True).start()

    def _focus_existing_player(self):
        """若音乐播放器窗口已存在,则把它提到前台并返回 True;否则返回 False。
        仅 Windows 有效;非 Windows 或任何异常都返回 False(退化为新开窗口)。"""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            EnumWindows = user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            GetWindowTextLength = user32.GetWindowTextLengthW
            GetWindowText = user32.GetWindowTextW
            IsWindowVisible = user32.IsWindowVisible
            SW_RESTORE = 9
            found = []
            def cb(hwnd, lparam):
                try:
                    if not IsWindowVisible(hwnd):
                        return True
                    length = GetWindowTextLength(hwnd)
                    if length <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buf, length + 1)
                    if "GD 音乐台" in buf.value:
                        found.append(hwnd)
                except Exception:
                    pass
                return True
            EnumWindows(EnumWindowsProc(cb), 0)
            if not found:
                return False
            hwnd = found[-1]
            user32.ShowWindow(hwnd, SW_RESTORE)            # 若最小化则还原
            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            # 兜底:置顶一下再取消,确保窗口可见且浮到最前
            try:
                user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 3)   # HWND_TOPMOST + NOSIZE+NOMOVE
                user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 3)   # HWND_NOTOPMOST
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _open_player_edge_app(self, url):
        """用系统 Edge 的「应用模式」打开播放器:纯净无地址栏窗口。
        兜底:若找不到 Edge,则尝试 Chrome;都找不到才弹窗提示(绝不自动开带标签的浏览器)。"""
        import subprocess, traceback
        dbg = os.path.join(APP_DIR, "player_debug.log")

        def L(msg):
            try:
                with open(dbg, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass

        L(f"[open_player] url={url}")
        # 候选浏览器(应用模式):优先 Edge,其次 Chrome
        candidates = []
        for base in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application",
            r"C:\Program Files\Microsoft\Edge\Application",
            r"C:\Program Files (x86)\Google\Chrome\Application",
            r"C:\Program Files\Google\Chrome\Application",
        ):
            for name in ("msedge.exe", "chrome.exe"):
                p = os.path.join(base, name)
                if os.path.isfile(p):
                    candidates.append(p)
        # 再用 PATH 试探
        import shutil
        for name in ("msedge.exe", "chrome.exe"):
            loc = shutil.which(name)
            if loc and os.path.isfile(loc):
                candidates.append(loc)
        # 去重保序
        seen, exe = set(), None
        for c in candidates:
            if c.lower() not in seen:
                seen.add(c.lower())
                exe = c
                break
        if not exe:
            L("[open_player] 未找到 Edge/Chrome")
            self.log("[播放器] 未找到 Edge/Chrome,无法打开播放器")
            self.root.after(0, lambda: messagebox.showerror(
                "无法打开播放器",
                "未在本机找到 Microsoft Edge 或 Google Chrome。\n请安装其中一个后再试。"))
            return
        L(f"[open_player] 使用 {exe}")
        try:
            # --app=网址:纯净应用窗口(无地址栏/标签栏);--window-size 给初始尺寸
            subprocess.Popen([exe, f"--app={url}", "--window-size=1180,760"])
            L("[open_player] Popen ok")
        except Exception as e:
            L("[open_player] Popen EXCEPTION:\n" + traceback.format_exc())
            self.log(f"[播放器] 启动失败：{e}")
            self.root.after(0, lambda: messagebox.showerror(
                "播放器启动失败", f"启动播放器窗口时出错：\n{e}"))

    # ---- 轮播 ----
    def gather(self, now=None):
        now = now or datetime.now()
        pool = []
        self._path_acc = {}                    # 路径 -> 所属账户(供按组决定 GPU 超分)
        sel = set(self.cfg.get("selected", []))
        span = int(self.cfg.get("span", 0))          # 0 = 永久
        cutoff = None
        if span > 0:
            cutoff = (now - timedelta(days=span)).strftime("%Y-%m-%d")
        for acc in self.cfg["accounts"]:
            if acc["name"] not in sel:
                continue
            if not in_window(acc, now):
                continue
            for p, date in account_items(acc):
                if cutoff and date and date < cutoff:
                    continue
                pool.append(p)
                self._path_acc[p] = acc
        return pool

    def _maybe_upscale(self, p):
        """按该图所属账户决定是否 GPU 超分;账户未单独设置时回退到全局默认。"""
        acc = getattr(self, "_path_acc", {}).get(p)
        on = bool(acc.get("upscale", False)) if acc else self.cfg.get("upscale", False)
        return _upscale(p) if on else p

    def date_for_path(self, path):
        """根据文件路径反查其发布日期(用于状态栏与烧录)。"""
        base = os.path.basename(path)
        d = os.path.dirname(path)
        for acc in self.cfg.get("accounts", []):
            if acc.get("dir") == d:
                return load_meta(acc).get(base)
        return None

    def start(self):
        if self.running:
            return
        self.cfg["interval"] = max(5, self.interval_var.get())
        self.cfg["order"] = self.order_var.get()
        self.cfg["fit"] = FIT_CN[self.fit_var.get()]
        self.cfg["refresh_gap"] = max(0, self.gap_var.get())
        self.cfg["max_photos"] = max(0, self.max_photos_var.get())
        self.cfg["span"] = SPAN_CN.get(self.span_var.get(), 0)
        self.cfg["auto_update"] = bool(self.auto_var.get())
        self.cfg["auto_hours"] = max(1, self.auto_hours_var.get())
        self.cfg["upscale"] = bool(self.upscale_var.get())
        # 模型固定 realesrgan-x4plus (4x),锁死画质最佳档,不再开放倍率
        self.cfg["collage_n"] = max(2, min(9, self.collage_n_var.get()))
        save_cfg(self.cfg)
        self._last_auto = 0.0
        pool = self.gather(datetime.now())
        if not pool:
            messagebox.showwarning("提示", "当前时段没有活跃的图片来源。\n请勾选来源;或把时段留空表示该来源始终参与轮播。")
            return
        self.running = True
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.thread = threading.Thread(target=self._rotate, daemon=True)
        self.thread.start()
        self.log(f"开始轮播,当前活跃 {len(pool)} 张,每 {self.cfg['interval']} 秒切换")

    def stop(self):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.log("已停止轮播")

    def _rotate(self):
        while self.running:
            now = datetime.now()
            # 自动更新:轮播中按设定间隔周期性刷新 IG 账户(与手动刷新共用错峰限速)
            if self.cfg.get("auto_update") and (time.time() - self._last_auto) >= self.cfg.get("auto_hours", 6) * 3600:
                self._last_auto = time.time()
                self.root.after(0, self.refresh_all)
                self.log("轮播中自动更新 IG 账户…")
            pool = self.gather(now)
            if not pool:
                self.root.after(0, lambda: self.status.set("当前时段无活跃来源,等待中…"))
                for _ in range(60):
                    if not self.running:
                        return
                    time.sleep(1)
                continue
            if self._frozen:
                # 定格:保持当前壁纸不动,仅空转等待;取消定格后下一轮自动换新
                for _ in range(self.cfg["interval"]):
                    if not self.running:
                        return
                    time.sleep(1)
                continue
            fit = self.cfg["fit"]
            if fit == "collage":
                # 拼贴:从池中取 K 张拼成 16:9 整图(无黑边、不变形)
                k = max(2, int(self.cfg.get("collage_n", 4)))
                k = min(k, len(pool))
                if self.cfg["order"] == "random":
                    picks = random.sample(pool, k)
                else:
                    picks = [pool[(self.idx + j) % len(pool)] for j in range(k)]
                    self.idx += k
                picks = [self._maybe_upscale(p) for p in picks]   # 按各组开关逐张决定
                wall = _compose_collage(picks)
                try:
                    set_wallpaper(wall, "collage", "")
                    self.root.after(0, lambda n=k: self.status.set(f"当前壁纸[拼贴]: {n} 张拼合 16:9"))
                except Exception as e:
                    self.log(f"设置壁纸失败: {e}")
            else:
                if self.cfg["order"] == "random":
                    path = random.choice(pool)
                else:
                    path = pool[self.idx % len(pool)]
                    self.idx += 1
                path = self._maybe_upscale(path)   # 按该图所属组的开关决定
                try:
                    date = self.date_for_path(path) or ""
                    set_wallpaper(path, fit, date)
                    sz = img_size(path)
                    tag = f" {sz}" if sz else ""
                    dt = f" · 发布 {date}" if date else ""
                    self.root.after(0, lambda p=path, t=tag, d=dt: self.status.set(f"当前壁纸: {os.path.basename(p)}{t}{d}"))
                except Exception as e:
                    self.log(f"设置壁纸失败: {e}")
            for _ in range(self.cfg["interval"]):
                if not self.running:
                    break
                time.sleep(1)

    # ---- 杂项 ----
    def save_settings(self):
        self.cfg["interval"] = max(5, self.interval_var.get())
        self.cfg["order"] = self.order_var.get()
        self.cfg["fit"] = FIT_CN[self.fit_var.get()]
        self.cfg["refresh_gap"] = max(0, self.gap_var.get())
        self.cfg["max_photos"] = max(0, self.max_photos_var.get())
        self.cfg["span"] = SPAN_CN.get(self.span_var.get(), 0)
        self.cfg["auto_update"] = bool(self.auto_var.get())
        self.cfg["auto_hours"] = max(1, self.auto_hours_var.get())
        self.cfg["upscale"] = bool(self.upscale_var.get())
        # 模型固定 realesrgan-x4plus (4x),锁死画质最佳档,不再开放倍率
        self.cfg["collage_n"] = max(2, min(9, self.collage_n_var.get()))
        save_cfg(self.cfg)
        self.log("设置已保存")

    def _restore_settings(self):
        self.interval_var.set(self.cfg.get("interval", 30))
        self.order_var.set(self.cfg.get("order", "random"))
        self.fit_var.set({v: k for k, v in FIT_CN.items()}.get(self.cfg.get("fit", "cover"), "铺满(不变形)"))
        self.gap_var.set(self.cfg.get("refresh_gap", 20))
        self.max_photos_var.set(self.cfg.get("max_photos", 0))
        self.span_var.set({v: k for k, v in SPAN_CN.items()}.get(self.cfg.get("span", 0), "永久"))
        self.auto_var.set(self.cfg.get("auto_update", True))
        self.auto_hours_var.set(self.cfg.get("auto_hours", 6))
        self.upscale_var.set(self.cfg.get("upscale", False))
        # 倍率不再开放给 UI,固定 4x(realesrgan-x4plus)
        self.collage_n_var.set(self.cfg.get("collage_n", 4))

    def log(self, msg):
        s = str(msg)
        self.log_lines.append(s)
        if len(self.log_lines) > 300:
            self.log_lines = self.log_lines[-300:]
        self.root.after(0, lambda: self.status.set(s))

    def show_errors(self):
        """F12 快捷键:打开报错查看窗口,显示 app_error.log 与本次运行日志。"""
        win = tk.Toplevel(self.root)
        win.title("报错查看 (F12)")
        win.geometry("720x440")
        txt = tk.Text(win, wrap="word", font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=8, pady=8)

        def load():
            txt.delete("1.0", "end")
            errf = os.path.join(APP_DIR, "app_error.log")
            if os.path.exists(errf):
                txt.insert("end", "==== app_error.log ====\n")
                try:
                    txt.insert("end", open(errf, encoding="utf-8", errors="replace").read())
                except Exception as e:
                    txt.insert("end", str(e))
            else:
                txt.insert("end", "(无 app_error.log,目前没有捕获到崩溃)\n")
            txt.insert("end", "\n==== 本次运行日志(最近) ====\n")
            txt.insert("end", "\n".join(self.log_lines[-200:]))
            txt.see("end")

        load()
        ttk.Button(win, text="刷新", command=load).pack(pady=4)

    # ---------- 系统托盘 ----------
    def _setup_tray(self):
        """创建系统托盘图标;关闭主窗口时默认最小化到托盘而非退出。"""
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception as e:
            self.log(f"[托盘] 缺少依赖,跳过系统托盘: {e}")
            return
        try:
            # 64x64 图标:深蓝圆底 + 白色双音符
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.ellipse((4, 4, 60, 60), fill=(30, 60, 120, 255))
            d.ellipse((20, 36, 32, 48), fill="white")    # 低音符头
            d.ellipse((40, 36, 52, 48), fill="white")    # 高音符头
            d.rectangle((29, 12, 33, 44), fill="white")  # 符干
            d.rectangle((49, 12, 53, 44), fill="white")
            d.line((33, 14, 53, 14), fill="white", width=4)  # 连音线
            icon = pystray.Icon("InsWallpaperTray", img, "INS 壁纸轮播器")
            # 注意:菜单项文字必须用静态字符串。曾用 callable 动态文字导致部分
            # pystray 版本构建托盘失败 -> tray_icon=None -> 点 X 退化成最小化且无法退出。
            icon.menu = pystray.Menu(
                pystray.MenuItem("打开主窗口", self._tray_show, default=True),
                pystray.MenuItem("打开音乐播放器", self._tray_open_player),
                pystray.MenuItem(f"定格/恢复壁纸轮播 ({self._hotkey_text()})", self._tray_toggle_freeze),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._tray_quit),
            )
            self.tray_icon = icon
            threading.Thread(target=self._tray_run, args=(icon,), daemon=True).start()
            self.log("[托盘] 系统托盘已启动")
        except Exception as e:
            self.log(f"[托盘] 启动失败: {e}")
            self.tray_icon = None

    def _tray_run(self, icon):
        """托盘线程入口:若 pystray 运行中崩溃,置空 tray_icon,
        让 _on_close 走『直接退出』分支,绝不出现关不掉的情况。"""
        try:
            icon.run()
        except Exception as e:
            try:
                self.log(f"[托盘] 托盘运行崩溃: {e}")
            except Exception:
                pass
            self.tray_icon = None

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, self._show_window)

    def _tray_open_player(self, icon=None, item=None):
        self.root.after(0, lambda: self.open_player(""))

    def _freeze_menu_label(self, icon=None):
        """托盘菜单『定格/恢复』项的动态文字。"""
        return (f"恢复壁纸轮播 ({self._hotkey_text()})" if self._frozen
                else f"定格壁纸轮播 ({self._hotkey_text()})")

    # ---- 定格快捷键:可自定义键组(须 >=2 键同时按) ----
    def _get_freeze_keys(self):
        """返回当前定格快捷键的按键名列表(经校验;非法/不足 2 键回退默认 F1+F2)。"""
        names = self.cfg.get("freeze_keys") or list(DEFAULT_FREEZE_KEYS)
        names = [n for n in names if n in _VK_NAME_TO_CODE]
        if len(names) < 2:
            names = list(DEFAULT_FREEZE_KEYS)
        return _hotkey_sort_names(names)

    def _get_freeze_codes(self):
        """返回当前定格快捷键的虚拟键码列表(热键线程每轮轮询调用,更换后即时生效)。"""
        return [_VK_NAME_TO_CODE[n] for n in self._get_freeze_keys()]

    def _hotkey_text(self):
        return "+".join(self._get_freeze_keys())

    def _change_hotkey(self):
        """弹出捕获窗口:用户同时按下 >=2 个键并全部松开后,设为新的定格快捷键。"""
        if not (sys.platform.startswith("win") and ctypes.windll):
            messagebox.showinfo("不支持", "自定义快捷键仅支持 Windows。")
            return
        win = tk.Toplevel(self.root)
        win.title("更换定格快捷键")
        win.geometry("460x210")
        win.resizable(False, False)
        try:
            win.transient(self.root)
            win.grab_set()
        except Exception:
            pass
        tk.Label(win, text="请同时按下 2 个及以上按键,然后全部松开即完成设置",
                 font=("Microsoft YaHei", 10)).pack(pady=(14, 2))
        tk.Label(win, text="支持: F1-F12 / Ctrl / Shift / Alt / 字母 / 数字 / 方向键 / Space 等",
                 fg="#999", font=("Microsoft YaHei", 8)).pack()
        cur_var = tk.StringVar(value="等待按键…")
        tk.Label(win, textvariable=cur_var, fg="#0066cc",
                 font=("Microsoft YaHei", 15, "bold")).pack(pady=8)
        hint_var = tk.StringVar(value=f"当前快捷键: {self._hotkey_text()}")
        tk.Label(win, textvariable=hint_var, fg="#cc3300",
                 font=("Microsoft YaHei", 9)).pack()
        ttk.Button(win, text="取消", command=win.destroy).pack(pady=8)

        state = {"session": set(), "done": False}
        GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
        # 打开瞬间可能还残留着点击按钮的键状态,先等所有键松开再开始捕获
        state["armed"] = False

        def poll():
            if state["done"]:
                return
            try:
                if not win.winfo_exists():
                    return
            except Exception:
                return
            try:
                pressed = {name for name, code in _VK_NAME_TO_CODE.items()
                           if GetAsyncKeyState(code) & 0x8000}
            except Exception:
                pressed = set()
            if not state["armed"]:
                if not pressed:
                    state["armed"] = True
                win.after(30, poll)
                return
            if pressed:
                state["session"] |= pressed
                cur_var.set(" + ".join(_hotkey_sort_names(state["session"])))
            elif state["session"]:
                # 全部松开 -> 本次按键会话结束,判定结果
                names = _hotkey_sort_names(state["session"])
                if len(names) < 2:
                    hint_var.set("至少需要 2 个按键同时按下,请重新按")
                    cur_var.set("等待按键…")
                    state["session"] = set()
                else:
                    state["done"] = True
                    self.cfg["freeze_keys"] = names
                    try:
                        save_cfg(self.cfg)
                    except Exception:
                        pass
                    self._apply_new_hotkey()
                    try:
                        win.destroy()
                    except Exception:
                        pass
                    messagebox.showinfo("快捷键已更换",
                                        f"新的定格快捷键: {'+'.join(names)}\n同时按住即可定格 / 恢复壁纸轮播")
                    return
            win.after(30, poll)

        win.after(150, poll)

    def _apply_new_hotkey(self):
        """更换快捷键后刷新界面显示与托盘菜单(热键线程通过 get_keys 即时读取,无需重启)。"""
        txt = self._hotkey_text()
        try:
            self.hotkey_label_var.set(txt)
        except Exception:
            pass
        self.log(f"[热键] 定格快捷键已更换为: {txt}")
        try:
            self.status.set(f"定格快捷键已更换为: 同时按住 {txt}")
        except Exception:
            pass
        # 重建托盘菜单文字(仍是静态字符串,避免动态 callable 导致 pystray 崩溃)
        try:
            if self.tray_icon is not None:
                self.tray_icon.menu = pystray.Menu(
                    pystray.MenuItem("打开主窗口", self._tray_show, default=True),
                    pystray.MenuItem("打开音乐播放器", self._tray_open_player),
                    pystray.MenuItem(f"定格/恢复壁纸轮播 ({txt})", self._tray_toggle_freeze),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("退出", self._tray_quit),
                )
                self.tray_icon.update_menu()
        except Exception:
            pass

    def _tray_toggle_freeze(self, icon=None, item=None):
        """托盘菜单点击:定格 / 恢复壁纸轮播(热键失效时的可靠兜底)。"""
        self._toggle_freeze()
        try:
            if self.tray_icon is not None:
                self.tray_icon.update_menu()
        except Exception:
            pass

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self._quit_app)

    def _show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(60, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def _toggle_freeze(self):
        """F1+F2 热键回调:切换壁纸定格(系统级钩子线程调用,经 root.after 回主线程刷新 UI)。"""
        self._frozen = not self._frozen
        try:
            self.root.after(0, self._update_freeze_ui)
        except Exception:
            pass

    def _on_hotkey_status(self, msg):
        """热键钩子安装结果回调:记录日志并短暂显示在状态栏,便于排查失效。"""
        self.log(f"[热键] {msg}")
        try:
            self.root.after(0, lambda: self.status.set(msg))
        except Exception:
            pass

    def _update_freeze_ui(self):
        try:
            if self._frozen:
                self.status.set(f"壁纸已定格（同时按 {self._hotkey_text()} 恢复轮播）")
                self.root.title("INS 壁纸轮播器【已定格】")
            else:
                self.status.set("已恢复壁纸轮播")
                self.root.title("INS 壁纸轮播器")
            if self.tray_icon is not None:
                try:
                    self.tray_icon.title = "INS 壁纸轮播器" + ("【已定格】" if self._frozen else "")
                except Exception:
                    pass
                try:
                    self.tray_icon.notify(
                        f"壁纸已定格，同时按 {self._hotkey_text()} 恢复轮播" if self._frozen else "已恢复壁纸轮播",
                        "INS 壁纸")
                except Exception:
                    pass
        except Exception:
            pass

    def _on_close(self):
        # 关闭(X):托盘可用 -> 隐藏到托盘,后台继续轮播;
        # 托盘不可用 -> 直接彻底退出(绝不能出现"最小化了却关不掉"的死局)。
        if self.tray_icon is not None:
            try:
                self.root.withdraw()
                try:
                    self.tray_icon.notify(
                        "已最小化到系统托盘\n壁纸轮播仍在继续,右键托盘图标可打开或退出",
                        "INS 壁纸轮播器")
                except Exception:
                    pass
                return
            except Exception:
                pass
        # 托盘不可用(启动失败/崩溃) -> 点 X 就是退出
        self._quit_app()

    def _quit_app(self):
        # 直接强制退出:所有后台线程(tray / 热键 / HTTP / 轮播)均为 daemon=True,
        # 会被 os._exit 一并强杀,保证 exe 一定能关掉,不依赖任何 stop() 是否阻塞
        # (pystray 的 stop() 个别版本可能 join 卡住,导致"关不掉")。
        try:
            release_single_instance()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        # 兜底:无论是否有线程/资源未释放,强制退出,确保 exe 能关掉
        try:
            os._exit(0)
        except Exception:
            pass

# ---------- 单实例:防止多开导致多个窗口 / 多个托盘图标 ----------
_INSTANCE_MUTEX = "Global\\InsWallpaper_SingleInstance_v1"
_INSTANCE_EVENT = "Global\\InsWallpaper_ShowEvent_v1"
_lock_file = os.path.join(APP_DIR, ".inswallpaper.lock")
_instance_handles = []   # 由主实例持有,退出时释放


def _pid_alive(pid):
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return True


def _read_lock_pid():
    try:
        with open(_lock_file, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _write_lock_pid():
    try:
        with open(_lock_file, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def _clear_lock_pid():
    try:
        os.remove(_lock_file)
    except Exception:
        pass


# ---- 全局快捷键: 定格 / 取消定格壁纸(GetAsyncKeyState 轮询,零钩子,可自定义键组) ----
# 重要教训:之前用 WH_KEYBOARD_LL 系统级键盘钩子实现,Python 回调慢(GIL),
# 全系统每次按键都要等本进程处理 -> 其他程序打字卡顿/打不出字。
# 现改为后台线程每 50ms 用 GetAsyncKeyState 轮询按键状态:
#   - 完全不介入系统键盘输入链,其他程序打字零影响
#   - 无需安装钩子,不会被安全软件拦截("热键安装失败"不再出现)
#   - 托盘模式 / 窗口失焦同样生效
# 键组可自定义(配置项 freeze_keys),但必须 >=2 个键同时按下才触发。

# 支持的按键名 -> Windows 虚拟键码(供轮询与"更换快捷键"捕获共用)
_VK_NAME_TO_CODE = {}
for _i in range(1, 13):                       # F1-F12
    _VK_NAME_TO_CODE[f"F{_i}"] = 0x6F + _i
for _i in range(10):                          # 0-9
    _VK_NAME_TO_CODE[str(_i)] = 0x30 + _i
for _i in range(26):                          # A-Z
    _VK_NAME_TO_CODE[chr(65 + _i)] = 0x41 + _i
_VK_NAME_TO_CODE.update({
    "Ctrl": 0x11, "Shift": 0x10, "Alt": 0x12,
    "Space": 0x20, "Tab": 0x09, "CapsLock": 0x14,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    "Home": 0x24, "End": 0x23, "PageUp": 0x21, "PageDown": 0x22,
    "Insert": 0x2D, "Delete": 0x2E,
})
_VK_CODE_TO_NAME = {v: k for k, v in _VK_NAME_TO_CODE.items()}

def _hotkey_sort_names(names):
    """修饰键(Ctrl/Shift/Alt)排前面,其余按名称排序,显示更符合习惯。"""
    order = {"Ctrl": 0, "Shift": 1, "Alt": 2}
    return sorted(names, key=lambda n: (order.get(n, 3), n))

DEFAULT_FREEZE_KEYS = ["F1", "F2"]

try:
    if not (sys.platform.startswith("win") and ctypes.windll):
        raise RuntimeError("not windows")

    class FreezeHotkey:
        """全局监听自定义键组(>=2 键):全部同时处于按下状态即触发 on_toggle()。
        触发一次后需全部松开才能再次触发(防连发)。
        get_keys() 每轮轮询时调用,返回虚拟键码列表 -> 用户更换快捷键后即时生效,无需重启线程。
        on_status(msg) 可选回调,用于把热键状态回报到界面/日志。"""

        def __init__(self, on_toggle, on_status=None, get_keys=None):
            self.on_toggle = on_toggle
            self.on_status = on_status
            self.get_keys = get_keys or (lambda: [0x70, 0x71])  # 默认 F1+F2
            self._running = True
            self._active = False

        def is_active(self):
            return bool(self._active)

        def _report(self, msg):
            if self.on_status:
                try:
                    self.on_status(msg)
                except Exception:
                    pass

        def _label(self):
            try:
                names = [_VK_CODE_TO_NAME.get(k, "?") for k in (self.get_keys() or [])]
                return "+".join(_hotkey_sort_names(names)) or "F1+F2"
            except Exception:
                return "F1+F2"

        def start(self):
            try:
                threading.Thread(target=self._run, daemon=True).start()
            except Exception as e:
                self._report(f"热键线程启动失败: {e}")

        def _run(self):
            try:
                GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
                self._active = True
                self._report(f"热键就绪: 同时按住 {self._label()} 定格 / 恢复壁纸轮播")
                fired = False
                while self._running:
                    try:
                        keys = self.get_keys() or []
                    except Exception:
                        keys = []
                    if len(keys) >= 2:
                        states = [bool(GetAsyncKeyState(k) & 0x8000) for k in keys]
                        if all(states):
                            if not fired:
                                fired = True
                                try:
                                    self.on_toggle()
                                except Exception:
                                    pass
                        elif not any(states):
                            fired = False
                    time.sleep(0.05)
            except Exception as e:
                self._active = False
                self._report(f"热键运行错误: {e}")

        def stop(self):
            self._running = False
except Exception:
    # 非 Windows / ctypes 不可用时的空实现,保证程序照常运行
    class FreezeHotkey:
        def __init__(self, on_toggle, on_status=None, get_keys=None):
            self.on_toggle = on_toggle
        def start(self):
            pass
        def is_active(self):
            return False
        def stop(self):
            pass


def ensure_single_instance():
    """返回 'primary' 或 'secondary'。
    primary  : 本进程是首个实例,调用方继续启动 GUI。
    secondary: 已有实例在运行 —— 已尝试把它窗口提到最前,调用方应直接退出。
    非 Windows 平台直接返回 'primary'(单实例锁依赖 Win32 内核对象)。
    """
    if not (sys.platform.startswith("win") and ctypes.windll):
        return "primary"
    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, 1, _INSTANCE_MUTEX)   # bInitialOwner=True
        err = kernel32.GetLastError()
        if err == 183:   # ERROR_ALREADY_EXISTS
            # 互斥量已存在:看锁文件里的进程是否还活着
            pid = _read_lock_pid()
            if pid and _pid_alive(pid):
                # 真有实例在跑 -> 唤醒它的窗口
                try:
                    ev = kernel32.OpenEventW(0x0002 | 0x0010, False, _INSTANCE_EVENT)  # MODIFY_STATE|SYNCHRONIZE
                    if ev:
                        kernel32.SetEvent(ev)
                        kernel32.CloseHandle(ev)
                except Exception:
                    pass
                return "secondary"
            # 锁文件进程已死(上次崩溃残留) -> 接管
        # primary:创建/复用 show 事件,记录 pid
        try:
            kernel32.CreateEventW(None, False, False, _INSTANCE_EVENT)
        except Exception:
            pass
        _write_lock_pid()
        _instance_handles.append(mutex)
        return "primary"
    except Exception:
        return "primary"


def release_single_instance():
    try:
        kernel32 = ctypes.windll.kernel32
        for h in _instance_handles:
            try:
                kernel32.ReleaseMutex(h)
                kernel32.CloseHandle(h)
            except Exception:
                pass
        _instance_handles.clear()
    except Exception:
        pass
    _clear_lock_pid()


def _single_instance_show_thread(root):
    """等待 '显示已有窗口' 事件,触发时把主窗口提到最前(配合托盘/最小化)。"""
    try:
        kernel32 = ctypes.windll.kernel32
        ev = kernel32.OpenEventW(0x0002 | 0x0010, False, _INSTANCE_EVENT)
        if not ev:
            return
        while True:
            kernel32.WaitForSingleObject(ev, 0x7FFFFFFF)
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
                try:
                    root.update()
                except Exception:
                    pass
            except Exception:
                pass
    except Exception:
        pass


def main():
    # 必须在创建任何 tkinter 窗口之前设置 DPI 感知,否则所有窗口被系统
    # DPI 虚拟化(逻辑像素渲染后再放大到物理像素),文字发虚——这是桌面歌词
    # "分辨率低得可怕"的根因。set_wallpaper 里也会再调一次(幂等,无害)。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    root = tk.Tk()
    app = App(root)
    # 启动即把音乐播放器 html 从 _MEIPASS 拷到 APP_DIR,避免点击时才发现找不到
    try:
        app._music_html_path()
    except Exception:
        pass
    # 启动本地 HTTP 服务(音乐播放器一体化:托管 music.html + 接收 /add_cover)
    try:
        srv = start_wall_server(app)
        if srv:
            app.log(f"本地服务已启动: http://{WALL_HOST}:{WALL_PORT}/music.html")
        else:
            app.log("⚠ 本地服务启动失败(端口被占),\"加封面做壁纸\"将回退为下载模式")
    except Exception as e:
        app.log(f"⚠ 本地服务异常: {e}")
    root.mainloop()

def _excepthook(etype, exc, tb):
    import traceback
    err = "".join(traceback.format_exception(etype, exc, tb))
    try:
        with open(os.path.join(APP_DIR, "app_error.log"), "w", encoding="utf-8") as f:
            f.write(err)
    except Exception:
        pass
    try:
        messagebox.showerror("程序出错", err)
    except Exception:
        pass

def _selftest():
    """隐藏自测: InsWallpaper.exe --selftest [ig_url] [out_dir]
    验证 frozen 环境下 Chromium 可被 playwright 加载并完成抓取,结果写 selftest_result.txt。
    """
    url = sys.argv[2] if len(sys.argv) > 2 else "https://www.instagram.com/kasumi_arimura.official/"
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ACCOUNTS_DIR, "selftest")
    acc = {"name": "selftest", "type": "ig", "url": url, "dir": out}
    res = {"url": url, "status": "OK"}
    try:
        n = fetch_account(acc, print)
        res["saved"] = n
        res["files"] = sorted(os.listdir(out)) if os.path.isdir(out) else []
    except Exception as e:
        import traceback
        res["status"] = "FAIL"
        res["error"] = str(e)
        res["trace"] = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    with open(os.path.join(APP_DIR, "selftest_result.txt"), "w", encoding="utf-8") as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=2))
    print("SELFTEST_DONE", json.dumps(res, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        sys.excepthook = _excepthook
        # 单实例:若已有一个在跑,把窗口提到最前并提示,本进程直接退出
        mode = ensure_single_instance()
        if mode == "secondary":
            try:
                _r = tk.Tk()
                _r.withdraw()
                messagebox.showinfo("InsWallpaper", "应用已在运行")
                _r.destroy()
            except Exception:
                pass
            sys.exit(0)
        atexit.register(release_single_instance)
        main()
