# -*- coding: utf-8 -*-
"""INS 壁纸轮播器 v2.5
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
仅供个人将图片设为自己的桌面壁纸;图片版权归原作者所有,请勿用于分发或商业用途。
"""
import os, sys
# 冻结为 EXE 后,把 Playwright 浏览器目录指向打包内自带的一份
if getattr(sys, "frozen", False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(sys._MEIPASS, "ms-playwright")

import json, time, random, re, threading, glob, subprocess
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

        root.title("INS 壁纸轮播器  v2.5")
        root.geometry("840x690")
        try:
            root.iconbitmap()
        except Exception:
            pass
        self._style()
        self._build()
        self.refresh_account_list()
        self._restore_settings()
        self.root.bind("<F12>", lambda e: self.show_errors())

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
        ttk.Label(row0c, text="(抓该歌手全部专辑封面当壁纸;播放器用 GD 音乐台 API,数据仅供学习)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

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
        ttk.Checkbutton(r5, text="AI 超分(显卡,4×)", variable=self.upscale_var).pack(side="left")
        ttk.Label(r5, text="(本地 Real-ESRGAN/NCNN-Vulkan 跑显卡,固定 4× 最佳画质;需显卡支持 Vulkan,失败自动回退原图)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

        r7 = ttk.Frame(f2)
        r7.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(r7, text="拼贴张数:").pack(side="left")
        self.collage_n_var = tk.IntVar(value=4)
        ttk.Spinbox(r7, from_=2, to=9, increment=1, textvariable=self.collage_n_var, width=4).pack(side="left", padx=4)
        ttk.Label(r7, text="(填充方式选「拼贴(16:9)」时,把这么多张图拼满屏幕)", foreground="#999", font=("Microsoft YaHei", 8)).pack(side="left", padx=2)

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
            if acc.get("type") == "singer":
                ttk.Button(row, text="打开播放器", command=lambda a=acc: self.open_player(a.get("artist", ""))).pack(side="left", padx=2)
            if acc.get("type") in ("ig", "local"):
                ttk.Button(row, text="导入图片", command=lambda a=acc: self.import_images(a)).pack(side="left", padx=2)
            ttk.Button(row, text="删除", command=lambda a=acc: self.delete_account(a)).pack(side="left", padx=2)
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
        if acc.get("type") in ("ig", "local"):
            if os.path.isdir(acc["dir"]):
                import shutil
                shutil.rmtree(acc["dir"], ignore_errors=True)
        save_cfg(self.cfg)
        self.refresh_account_list()
        self.log(f"已删除来源 {acc['name']}")

    def open_cache(self):
        os.startfile(ACCOUNTS_DIR)

    def _music_html_path(self):
        """定位音乐播放器 HTML:打包后从 MEIPASS 拷到 APP_DIR,开发时取脚本同级。"""
        if getattr(sys, "frozen", False):
            src = os.path.join(sys._MEIPASS, "music_player.html")
            dst = os.path.join(APP_DIR, "music_player.html")
            if os.path.isfile(src) and (not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst)):
                try:
                    import shutil
                    shutil.copy2(src, dst)
                except Exception:
                    pass
            return dst if os.path.isfile(dst) else (src if os.path.isfile(src) else None)
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music_player.html")
        return local if os.path.isfile(local) else None

    def open_player(self, artist=""):
        html = self._music_html_path()
        if not html:
            messagebox.showerror("错误", "未找到音乐播放器 music_player.html(请确保它和本程序在一起)。")
            return
        url = "file:///" + html.replace("\\", "/")
        if artist:
            from urllib.parse import quote
            url += "?artist=" + quote(artist)
        import webbrowser
        webbrowser.open(url)
        self.log("已打开音乐播放器" + (f"(歌手: {artist})" if artist else ""))

    # ---- 轮播 ----
    def gather(self, now=None):
        now = now or datetime.now()
        pool = []
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
        return pool

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
            fit = self.cfg["fit"]
            upscale = self.cfg.get("upscale", False)
            if fit == "collage":
                # 拼贴:从池中取 K 张拼成 16:9 整图(无黑边、不变形)
                k = max(2, int(self.cfg.get("collage_n", 4)))
                k = min(k, len(pool))
                if self.cfg["order"] == "random":
                    picks = random.sample(pool, k)
                else:
                    picks = [pool[(self.idx + j) % len(pool)] for j in range(k)]
                    self.idx += k
                if upscale:
                    picks = [_upscale(p) for p in picks]
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
                if upscale:
                    path = _upscale(path)
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

def main():
    root = tk.Tk()
    App(root)
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
        main()
