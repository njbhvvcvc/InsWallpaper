# -*- coding: utf-8 -*-
"""生成 InsWallpaper 文档所需的中文流程图 (PNG)。"""
import os, math
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = "C:/Windows/Fonts"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doc_assets")
os.makedirs(OUT, exist_ok=True)

def reg(size):  return ImageFont.truetype(os.path.join(FONT_DIR, "msyh.ttc"), size)
def bold(size): return ImageFont.truetype(os.path.join(FONT_DIR, "msyhbd.ttc"), size)

PALE = "#2F6FB0"
PALE2 = "#3A9B7E"
ORG = "#E8743B"
RED = "#C0504D"
PUR = "#9B6FC9"
GREY = "#4F6D7A"
BLU = "#5B8FD9"
GRN = "#7FA650"
YEL = "#D9A441"

def rr(d, box, r, fill, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

def tcenter(d, box, text, font, fill, line_h=None):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    if line_h is None:
        line_h = font.getbbox("中")[3] + 5
    total = line_h * len(lines)
    cy = (y0 + y1) / 2 - total / 2
    for i, ln in enumerate(lines):
        bb = d.textbbox((0, 0), ln, font=font)
        w = bb[2] - bb[0]
        cx = (x0 + x1) / 2 - w / 2
        d.text((cx, cy + i * line_h), ln, font=font, fill=fill)

def tleft(d, box, text, font, fill, pad=8, line_h=None):
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    if line_h is None:
        line_h = font.getbbox("中")[3] + 5
    cy = y0 + pad
    for i, ln in enumerate(lines):
        d.text((x0 + pad, cy + i * line_h), ln, font=font, fill=fill)

def wrap(s, maxw, font, d):
    lines = []; cur = ""
    for ch in s:
        if d.textlength(cur + ch, font=font) > maxw and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines

def arrow(d, p1, p2, color="#5A5A5A", width=3):
    d.line([p1, p2], fill=color, width=width)
    x1, y1 = p1; x2, y2 = p2
    ang = math.atan2(y2 - y1, x2 - x1)
    L = 13
    a1 = ang + math.radians(155)
    a2 = ang - math.radians(155)
    d.polygon([(x2, y2), (x2 + L * math.cos(a1), y2 + L * math.sin(a1)),
               (x2 + L * math.cos(a2), y2 + L * math.sin(a2))], fill=color)

# -------------------- Fig 1: 功能总览（卡片网格） --------------------
def fig1():
    W, H = 1040, 760
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.text((30, 22), "INS 壁纸轮播器 — 功能总览", font=bold(30), fill="#1F3A56")
    d.text((32, 62), "一个把社交平台 / 网络图源 / 本地照片变成自动轮播桌面的 Windows 小工具", font=reg(16), fill="#666")

    cards = [
        ("多来源导入", "Instagram 账号\n必应每日壁纸\n本地文件夹", PALE),
        ("智能轮播", "自定义间隔\n顺序 / 随机\n每来源每日时段", PALE2),
        ("一键定格", "双键热键\n随时固定\n当前壁纸", ORG),
        ("实时天气", "可选组件\n桌面天气\n自动更新", BLU),
        ("内置音乐", "网页播放器\n后台播放\n不占界面", PUR),
        ("运行日志", "底部常驻\n实时滚动\n一键清空", RED),
        ("AI 超分", "Real-ESRGAN\n低清变高清", YEL),
        ("托盘驻留", "单实例\n后台运行\n右键管理", GREY),
    ]
    margin, gap = 30, 22
    cw = (W - 2 * margin - 3 * gap) // 4
    ch = 165
    y0 = 110
    for i, (title, body, col) in enumerate(cards):
        col_i = i % 4; row_i = i // 4
        x = margin + col_i * (cw + gap)
        y = y0 + row_i * (ch + gap)
        rr(d, (x, y, x + cw, y + ch), 14, "#F3F7FC", outline="#D5E2F0", width=2)
        rr(d, (x, y, x + cw, y + 40), 14, col)
        d.rectangle((x, y + 20, x + cw, y + 40), fill=col)
        tcenter(d, (x, y, x + cw, y + 40), title, bold(19), "#FFFFFF")
        tcenter(d, (x, y + 48, x + cw, y + ch), body, reg(15), "#333333", line_h=24)
    p = os.path.join(OUT, "fig1_overview.png")
    img.save(p, "PNG"); print("saved", p)

# -------------------- Fig 2: 工作流程 --------------------
def fig2():
    W, H = 1040, 440
    img = Image.new("RGB", (W, H), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.text((30, 18), "工作流程：从添加图源到一键定格", font=bold(28), fill="#1F3A56")

    steps = ["添加图片来源", "抓取 / 同步图片", "缓存到本地", "定时轮播设壁纸", "随时一键定格"]
    margin = 24
    n = len(steps)
    bw = 178; bh = 92
    gap = (W - 2 * margin - n * bw) // (n - 1)
    y = 120
    boxes = []
    for i, s in enumerate(steps):
        x = margin + i * (bw + gap)
        col = [PALE, BLU, PALE2, ORG, RED][i]
        rr(d, (x, y, x + bw, y + bh), 12, col)
        tcenter(d, (x, y, x + bw, y + bh), s, bold(16), "#FFFFFF", line_h=24)
        boxes.append((x, y, x + bw, y + bh))
    for i in range(n - 1):
        x2 = boxes[i][2]; y2 = y + bh // 2
        x1 = boxes[i + 1][0]; y1 = y + bh // 2
        arrow(d, (x2 + 2, y2), (x1 - 4, y1))

    # 底部：运行日志 / 托盘管理
    lw, lh = 320, 92
    lx = (W - lw) // 2; ly = 300
    rr(d, (lx, ly, lx + lw, ly + lh), 12, "#FBEAE6", outline=ORG, width=2)
    tcenter(d, (lx, ly, lx + lw, ly + lh), "运行日志 / 托盘右键管理", bold(17), ORG, line_h=26)
    # 反馈箭头：轮播、定格 -> 日志
    arrow(d, (boxes[3][0] + bw // 2, y + bh), (lx + 70, ly), color="#B5582E")
    arrow(d, (boxes[4][0] + bw // 2, y + bh), (lx + lw - 70, ly), color="#B5582E")
    # 日志 -> 抓取（虚线反馈，文字）
    ax1, ay1 = lx + lw // 2, ly
    ax2, ay2 = boxes[1][0] + bw // 2, y + bh
    # 画虚线
    dash = []
    steps_n = 40
    for k in range(steps_n):
        t0 = k / steps_n; t1 = (k + 0.5) / steps_n
        x0 = ax1 + (ax2 - ax1) * t0; y0 = ay1 + (ay2 - ay1) * t0
        x1 = ax1 + (ax2 - ax1) * t1; y1 = ay1 + (ay2 - ay1) * t1
        dash.append((x0, y0, x1, y1))
    for (a, b, c, e) in dash:
        d.line([(a, b), (c, e)], fill="#C9A06A", width=2)
    d.text((lx - 6, ly - 26), "运行日志实时反馈", font=reg(14), fill="#9A7B3F")
    p = os.path.join(OUT, "fig2_workflow.png")
    img.save(p, "PNG"); print("saved", p)

# -------------------- Fig 3: 界面布局示意 --------------------
def fig3():
    W = 780
    img = Image.new("RGB", (W, 900), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.text((24, 16), "主界面布局示意（重点：底部常驻日志区）", font=bold(22), fill="#1F3A56")

    x0, x1 = 30, W - 30
    sections = [
        ("标题：INS 壁纸轮播器", 44, "#E8F0FA"),
        ("天气组件（可选）", 70, "#F4F8FC"),
        ("导入来源 / 刷新 / 歌词外观", 64, "#F4F8FC"),
        ("来源列表（勾选 + 每日时段，可滚动）", 150, "#EEF4FA"),
        ("轮播设置（间隔 / 顺序 / 定格快捷键）", 120, "#F4F8FC"),
        ("控制按钮（开始 / 暂停 / 退出）", 60, "#F4F8FC"),
        ("状态栏 + 免责声明", 56, "#F4F8FC"),
    ]
    y = 60
    for label, h, bg in sections:
        rr(d, (x0, y, x1, y + h), 10, bg, outline="#D5E2F0", width=1)
        tleft(d, (x0, y, x1, y + h), label, reg(15), "#444")
        y += h + 10

    # 底部常驻日志区（高亮）
    h = 150
    rr(d, (x0, y, x1, y + h), 10, "#2B2B2B", outline=ORG, width=3)
    d.text((x0 + 12, y + 8), "常驻日志区（钉在窗口底部，始终可见）", font=bold(15), fill="#FFD9C2")
    sample = ["[12:01] 已加载来源 6 个", "[12:02] 开始轮播，间隔 30s",
              "[12:03] 已设置壁纸：hikaru_001.jpg", "[12:05] 抓取完成，共 78 张",
              "[12:06] 用户定格当前壁纸 ✓"]
    fy = y + 34
    for s in sample:
        d.text((x0 + 14, fy), s, font=reg(13), fill="#D6F5D6")
        fy += 20
    # 清空按钮示意
    d.rounded_rectangle((x1 - 86, y + 8, x1 - 12, y + 30), 6, "#555")
    d.text((x1 - 74, y + 12), "清空日志", font=reg(12), fill="#FFF")
    p = os.path.join(OUT, "fig3_ui.png")
    img.save(p, "PNG"); print("saved", p)

if __name__ == "__main__":
    fig1(); fig2(); fig3()
    print("ALL_IMAGES_DONE")
