#!/usr/bin/env python3
"""ミノムシだけのフォント(試作)。

元フォントの字を一切含まない。虫の字形だけを英数字に割り当てた、軽いフォント。
虫の描き方は build_font.py と同じ(一筆のぐしゃぐしゃ + 目玉)。

割り当て(全角の英数字も同じ字形)
  A〜Z  ふつうの虫(全角 1000)。26通りの形
  a〜z  小さい虫(全角 1000 の下寄せ。小書きのかな向け)。26通り
  0〜9  細い虫(半角 560)。10通り

太さは6ファイルに分ける(build_font.py の6書体と同じペン先)。
"""
import random
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.removeOverlaps import removeOverlaps

from build_font import BASES, MANUFACTURER, MIN_CELL, VENDOR_ID, bug_squeeze, draw_bug

OUT_DIR = Path(__file__).parent / "dist-solo"
VERSION = "1.000"
FAMILY, FAMILY_JA = "Minomushi Nomi", "ミノムシ のみ"
COPYRIGHT = "Copyright 2026 Pronama LLC"
LICENSE = "This Font Software is licensed under the SIL Open Font License, Version 1.1. This license is available with a FAQ at: https://openfontlicense.org"
SEED = "Minomushi Solo"   # 太さが違っても同じ字は同じ乱数の種を使う

# 太さの名前と OS/2 のウェイト。build_font.py の書体名の末尾で引く
STYLES = {
    "Gokuboso": ("ごくぼそ", 200), "Ballpen": ("ボールペン", 300), "Marumoji": ("まるもじ", 400),
    "Yurugaki": ("ゆるがき", 500), "Marker": ("マーカー", 700), "Gokubuto": ("ごくぶと", 900),
}

ASCENT, DESCENT = 1160, -288      # 6書体と同じ行の高さ
TOP, BOTTOM = 730, -90            # ふつうの虫の上下
SMALL_TOP, SMALL_WIDTH = 330, 420  # 小さい虫の上端と、消せる字の幅の目安
V_GAP = 60                        # 縦書きで、虫どうしのあいだに空ける量

# (文字, 字送り, 上, 下, 消せる字の幅)
KINDS = (
    [(chr(c), 1000, TOP, BOTTOM, None) for c in range(0x41, 0x5B)]
    + [(chr(c), 1000, SMALL_TOP, BOTTOM, SMALL_WIDTH) for c in range(0x61, 0x7B)]
    + [(chr(c), MIN_CELL, TOP, BOTTOM, None) for c in range(0x30, 0x3A)]
)


def build(style, nib, rough):
    ja, weight = STYLES[style]
    glyphs, hmtx, vmtx, cmap = {}, {}, {}, {}
    empty = TTGlyphPen(None).glyph()
    for name, advance in ((".notdef", 500), ("space", 500), ("uni3000", 1000)):
        glyphs[name], hmtx[name], vmtx[name] = empty, (advance, 0), (1000, 0)
    cmap[0x20], cmap[0x3000] = "space", "uni3000"

    for ch, cell, top, bottom, width in KINDS:
        name = f"bug.{ch}" if not ch.isdigit() else f"bug.n{ch}"
        if ch.islower():
            name = f"bug.s{ch}"
        pen = TTGlyphPen(None)
        draw_bug(TransformPen(pen, (1, 0, 0, 1, (cell - 1000) / 2, 0)), random.Random(f"{SEED}-{ch}"), nib, rough,
                 bug_squeeze(cell, nib, width), top, bottom)
        glyphs[name] = pen.glyph()
        hmtx[name] = (cell, 0)
        cmap[ord(ch)] = cmap[ord(ch) + 0xFEE0] = name  # 全角の英数字でも出す

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(hmtx)  # 輪郭の統合が字送りの表を読むので、先に仮の値で作る
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    removeOverlaps(fb.font, glyphNames=[n for n in glyphs if n.startswith("bug.")])
    glyf = fb.font["glyf"]
    for name in glyphs:
        g = glyf[name]
        if name.startswith("bug."):
            g.recalcBounds(glyf)
            hmtx[name] = (hmtx[name][0], g.xMin)
            # 縦書き: 虫の高さぶん送る。目が前の字に重ならないよう、上端を字送りの始点に合わせる
            height = g.yMax - g.yMin
            advance = max(1000, height + V_GAP)
            vmtx[name] = (advance, (advance - height) // 2 if height + V_GAP < 1000 else V_GAP // 2)
    fb.setupHorizontalMetrics(hmtx)
    fb.setupVerticalMetrics(vmtx)
    fb.setupVerticalHeader(ascent=500, descent=-500)
    psname = f"{FAMILY.replace(' ', '')}-{style}"
    fb.setupNameTable({
        "familyName": {"en": f"{FAMILY} {style}", "ja": f"{FAMILY_JA} {ja}"},
        "styleName": "Regular",
        "typographicFamily": {"en": FAMILY, "ja": FAMILY_JA},
        "typographicSubfamily": {"en": style, "ja": ja},
        "uniqueFontIdentifier": f"{VERSION};{VENDOR_ID};{psname}",
        "fullName": f"{FAMILY} {style}",
        "psName": psname,
        "version": f"Version {VERSION}",
        "copyright": COPYRIGHT,
        "manufacturer": MANUFACTURER,
        "licenseDescription": LICENSE,
        "licenseInfoURL": "https://openfontlicense.org",
    })
    fb.setupOS2(sTypoAscender=880, sTypoDescender=-120, sTypoLineGap=0, usWinAscent=ASCENT, usWinDescent=-DESCENT,
                usWeightClass=weight, achVendID=VENDOR_ID)
    fb.setupPost()
    fb.font["head"].fontRevision = float(VERSION)
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"{psname}.ttf"
    fb.save(path)
    return f"{path.name}: {len(glyphs)} 字形、{path.stat().st_size / 1024:.0f} KB"


if __name__ == "__main__":
    for base in BASES:
        print(build(base["family"].split()[-1], base["nib"], base["rough"]))
