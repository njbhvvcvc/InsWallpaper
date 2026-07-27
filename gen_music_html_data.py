# -*- coding: utf-8 -*-
"""自动生成 _music_html_data.py:把 music_player.html 以 base64 编进 Python 源码,
这样打包进 exe 后 100% 能取到(彻底绕开 PyInstaller --add-data 的 DEST 路径坑:
当 DEST 基名 == SRC 基名时,PyInstaller 会把文件误判成目录,运行时按裸名去找就"找不到文件")。

重新改了 music_player.html 后,跑本脚本(或构建时自动跑)即可刷新内嵌副本。
"""
import os, base64

ROOT = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(ROOT, "music_player.html")
out = os.path.join(ROOT, "_music_html_data.py")

if not os.path.isfile(src):
    raise SystemExit(f"[错误] 找不到 {src}")

with open(src, "rb") as f:
    raw = f.read()
b64 = base64.b64encode(raw).decode("ascii")

with open(out, "w", encoding="utf-8") as f:
    f.write("# -*- coding: utf-8 -*-\n")
    f.write("# 自动生成,请勿手改。music_player.html 的 base64 副本(用于打包进 exe,运行时写出)。\n")
    f.write("MUSIC_HTML_B64 = (\n")
    # 每行 80 字符,便于阅读/排查
    for i in range(0, len(b64), 80):
        f.write('    "' + b64[i:i + 80] + '"\n')
    f.write(")\n")

print(f"[生成] {out}  ({len(raw)} 字节, base64 长度 {len(b64)})")
