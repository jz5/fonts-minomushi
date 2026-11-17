#!/usr/bin/env python3
"""書体ラボの記事「書き損じミノムシ」のアイキャッチ（1280×640）。字形をパスにした SVG を書き出す。"""
import json, subprocess, sys, os
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen

style = sys.argv[1] if len(sys.argv) > 1 else "Marker"
TEXT = "書き存✕✕損✕○じミノムシ"
W, H, BG, FG = 1280, 640, "#fffdf5", "#1a1a1a"
WIDTH = 1060  # 文字列の幅（px）
path = Path(__file__).parent / "dist" / f"Minomushi{style}-Regular.ttf"
out = subprocess.run(["hb-shape", "--output-format=json", str(path), TEXT], capture_output=True, text=True,
                     env={**os.environ, "LC_ALL": "en_US.UTF-8"}).stdout
font = TTFont(path); gs = font.getGlyphSet()
x, placed = 0, []
for g in json.loads(out):
    placed.append((g["g"], x + g["dx"], g["dy"])); x += g["ax"]
bp = BoundsPen(gs)
for name, gx, gy in placed:
    gs[name].draw(TransformPen(bp, (1, 0, 0, 1, gx, gy)))
x0, y0, x1, y1 = bp.bounds
k = WIDTH / (x1 - x0)
ox, oy = (W - (x1 - x0) * k) / 2 - x0 * k, (H + (y1 + y0) * k) / 2   # 絵全体を上下左右の中央に
d = []
for name, gx, gy in placed:
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    gs[name].draw(TransformPen(pen, (k, 0, 0, -k, ox + gx * k, oy - gy * k)))
    d.append(pen.getCommands())
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
       f'<rect width="{W}" height="{H}" fill="{BG}"/><path fill="{FG}" d="{" ".join(d)}"/></svg>')
dest = Path.home() / "Downloads/kakisonji-eyecatch" / f"kakisonji-eyecatch-{style.lower()}.svg"
dest.write_text(svg)
print(dest, f"{len(svg)//1024} KB", "bbox", [round(v) for v in bp.bounds], font["name"].getDebugName(5))
