#!/usr/bin/env python3
"""README と GitHub のソーシャルプレビューに使う画像を images/ に作る。

  python3 make_images.py          全部
  python3 make_images.py social   名前を指定したものだけ

字形をパスにした SVG を組み、macOS の sips で PNG にする。hb-shape（HarfBuzz）が要る。
先に build_font.py と build_solo.py でフォントを作っておくこと。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).parent
OUT = ROOT / "images"
BG, FG, SUB = "#fffdf5", "#1a1a1a", "#8a8478"
X, O, DOT = "✕", "○", "●"

FONTS = {  # 書体名: （ファイル, 日本語名）
    "Gokuboso": ("dist/MinomushiGokuboso-Regular.ttf", "ミノムシ ごくぼそ"),
    "Marumoji": ("dist/MinomushiMarumoji-Regular.ttf", "ミノムシ まるもじ"),
    "Ballpen": ("dist/MinomushiBallpen-Regular.ttf", "ミノムシ ボールペン"),
    "Marker": ("dist/MinomushiMarker-Regular.ttf", "ミノムシ マーカー"),
    "Gokubuto": ("dist/MinomushiGokubuto-Regular.ttf", "ミノムシ ごくぶと"),
    "Yurugaki": ("dist/MinomushiYurugaki-Regular.ttf", "ミノムシ ゆるがき"),
}
NOMI = ["Gokuboso", "Ballpen", "Marumoji", "Yurugaki", "Marker", "Gokubuto"]
_cache = {}


def load(key):
    """書体名（FONTS のキー、または Nomi-太さ）から、ファイルの場所と字形の集まりを返す。"""
    if key not in _cache:
        path = ROOT / (f"dist-solo/Minomushi{key}.ttf" if key.startswith("Nomi-") else FONTS[key][0])
        _cache[key] = (path, TTFont(path).getGlyphSet())
    return _cache[key]


def shape(key, text, vertical=False, features=None):
    """hb-shape で組み、（字形名, x, y） の並びと送りの合計を返す。単位はフォントの単位。"""
    path, _ = load(key)
    cmd = ["hb-shape", "--output-format=json"]
    if vertical:
        cmd.append("--direction=ttb")
    if features:
        cmd.append(f"--features={features}")
    out = subprocess.run(cmd + [str(path), text], capture_output=True, text=True, check=True,
                         env={**os.environ, "LC_ALL": "en_US.UTF-8"}).stdout
    x = y = 0
    placed = []
    for g in json.loads(out):
        placed.append((g["g"], x + g["dx"], y + g["dy"]))
        x, y = x + g["ax"], y + g["ay"]
    return placed, x, y


class Canvas:
    def __init__(self, width, height):
        self.w, self.h, self.items = width, height, []

    def text(self, key, text, x, y, size, color=FG, vertical=False, features=None, split=False, align="left"):
        """(x, y) を始点に組む。横書きは y がベースライン、縦書きは x が行の中心で y が上端。
        split は1字ずつ別に組む（合字にせず、打った記号のまま見せる）。送った長さ（px）を返す。"""
        k = size / 1000
        if split:
            placed, ax, ay = [], 0, 0
            for ch in text:
                p, dx, dy = shape(key, ch, vertical, features)
                placed += [(n, gx + ax, gy + ay) for n, gx, gy in p]
                ax, ay = ax + dx, ay + dy
        else:
            placed, ax, ay = shape(key, text, vertical, features)
        if align == "center":
            x -= ax * k / 2
        gs = load(key)[1]
        for name, gx, gy in placed:
            self.items.append((gs, name, (k, 0, 0, -k, x + gx * k, y - gy * k), color))
        return abs(ay if vertical else ax) * k

    def center(self):
        """置いたもの全体を、画像の上下左右の中央へ寄せる。"""
        boxes = []
        for gs, name, t, _ in self.items:
            bp = BoundsPen(gs)  # 部品を重ねた字形があるので、書体ごとの字形の集まりを渡す
            gs[name].draw(TransformPen(bp, t))
            if bp.bounds:
                boxes.append(bp.bounds)
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
        dx, dy = (self.w - x0 - x1) / 2, (self.h - y0 - y1) / 2
        self.items = [(gs, n, t[:4] + (t[4] + dx, t[5] + dy), c) for gs, n, t, c in self.items]

    def save(self, name):
        by_color = {}
        for gs, glyph, t, color in self.items:
            pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
            gs[glyph].draw(TransformPen(pen, t))
            by_color.setdefault(color, []).append(pen.getCommands())
        paths = "".join(f'<path fill="{c}" d="{" ".join(d)}"/>' for c, d in by_color.items())
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
               f'viewBox="0 0 {self.w} {self.h}"><rect width="{self.w}" height="{self.h}" fill="{BG}"/>{paths}</svg>')
        OUT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"{name}.svg"
            src.write_text(svg)
            subprocess.run(["sips", "-s", "format", "png", str(src), "--out", str(OUT / f"{name}.png")],
                           check=True, capture_output=True)
        print(f"images/{name}.png  {self.w}×{self.h}  {(OUT / f'{name}.png').stat().st_size // 1024} KB")


def social():
    """GitHub のソーシャルプレビュー（1280×640）。"""
    c = Canvas(1280, 640)
    c.text("Marker", f"書き存{X}{X}損{X}{O}じミノムシ", 640, 330, 106, align="center")
    c.text("Marumoji", "打つだけで出せる、書き損じミノムシのフォント", 640, 475, 36, color=SUB, align="center")
    c.center()
    c.save("social")


def howto():
    """打ち方と出るもの。左が打つ字、右が出る形。"""
    c = Canvas(1600, 860)
    rows = [(f"天{X}{X}", "字を虫にする"), (f"天{X}{X}点{X}{O}気", "正しい字を言わせる"), (f"{DOT}{X}{X}", "虫だけ")]
    for i, (typed, note) in enumerate(rows):
        y = 250 + i * 250
        c.text("Marumoji", note, 80, y - 130, 30, color=SUB)
        c.text("Marumoji", typed, 80, y, 96, split=True)
        c.text("Marumoji", "→", 820, y, 96, color=SUB)
        c.text("Marumoji", typed, 1000, y, 96)
    c.save("howto")


def styles():
    """6書体の見本。"""
    c = Canvas(1600, 960)
    for i, (key, (_, ja)) in enumerate(FONTS.items()):
        x, y = 80 + (i % 2) * 780, 250 + (i // 2) * 300
        kanji = i < 4
        c.text(key, ja, x, y + 75, 30, color=SUB)  # 吹き出しに重ならないよう、見本の下に置く
        c.text(key, f"良い天{X}{X}点{X}{O}気です" if kanji else f"よいで{X}{X}て{X}{O}んきです", x, y, 92)
    c.save("styles")


def vertical():
    """縦書きの見本。"""
    c = Canvas(1600, 900)
    lines = [("Marumoji", f"今日は猫{X}{X}犬{X}{O}と遊んだ。"), ("Ballpen", f"明日は雨{X}{X}晴{X}{O}れるはず。"),
             ("Marker", f"漢字の間{X}{X}違{X}{O}いを直す。"), ("Gokubuto", f"かきそこ{X}{X}ん{X}{O}じた。")]
    for i, (key, text) in enumerate(lines):
        c.text(key, text, 1340 - i * 340, 90, 76, vertical=True)
    c.center()
    c.save("vertical")


def nomi():
    """虫だけのフォント「ミノムシ のみ」の6つの太さ。"""
    c = Canvas(1600, 940)
    for i, weight in enumerate(NOMI):
        y = 170 + i * 130
        c.text("Marumoji", FONTS[weight][1].split()[1], 80, y - 20, 30, color=SUB)
        c.text(f"Nomi-{weight}", "ABCDEFGH abcde 01234", 330, y, 68)
    c.save("nomi")


if __name__ == "__main__":
    todo = sys.argv[1:] or ["social", "howto", "styles", "vertical", "nomi"]
    for name in todo:
        globals()[name]()
