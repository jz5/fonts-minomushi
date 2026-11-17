#!/usr/bin/env python3
"""書き損じミノムシ フォント(試作)。

ベースの手書き風フォント(いずれも SIL OFL 1.1)の字形と機能をすべて残したまま、
書き損じミノムシの字形を追加する。

合字(文字を打つだけで出る。発動には必ず ✕ U+2715 が入る)
  字✕✕  → その字の上に虫(一筆のぐしゃぐしゃ + 目玉)を重ねる
  字✕○  → 直前の文字の上に、その字の吹き出しを重ねる(幅ゼロ)
  ●✕✕  → 虫だけ(下の字なし)
  例: あ✕✕い✕○ … 「あ」を虫で消して、上に「い」の吹き出し

スタイルセット(テキストは元の文字のまま。読み上げ・コピーに記号が混ざらない)
  ss01 → 字に虫を重ねる
  ss02 → 虫 + その字の吹き出し
  ss03 → 吹き出しのみ(幅ゼロ)

替え字形(かなと「虫だけ」は形を3種類持つ)
  虫が続けて出ると、直前の虫と違う形に順に切り替わる(同じ字を並べても同じ形が続かない)。
  幅ゼロの吹き出し(字✕○、ss03)も、虫とは別に同じ仕組みで切り替わる。
  間に挟まる文字が GAP 字を超えるか、かなと漢字の境目をまたぐと、最初の形に戻る。

大きさの決め方
  虫の上下   … 書体ごとに、かな(小書きを除く)の高さから決める。小書きの字はその字の高さまで。
  虫の幅     … 虫にした字の字送り × BUG_FILL。字送り 1000 で元の大きさ。
  虫の字送り … 字幅固定の書体は元のまま。字幅が不揃いな書体は CELL_GROW 倍に広げ、MIN_CELL を下限にする。
  吹き出し   … 書体ごとに同じ大きさ。幅の広いかなの字送りに収まるよう縮める(字送り 1000 で元の大きさ)。
  ss02 の字送り … 字幅が不揃いな書体では、吹き出しの幅近くまで広げる。
  幅ゼロの吹き出しの位置 … 標準の字送りの字の上に描き、GPOS の dist で直前の字の中央・高さへずらす。

✕ はどのベースにも無い記号なので、発動用に使っても元の表示を失わない。× ○ ● は元のまま使える。
記号を後置にするのは、記号が直前の文字と同じスクリプトのランに入るため。
前置だと「かな✕漢字」でランが分かれて合字にならない。

縦書き(かな・英数字・記号・「字」)
  虫は横書きと同じ字形を使い、縦の字送りを長くして目が前の字に重ならないようにする。
  吹き出しは虫の右に出す字形を別に持つ。吹き出しは直前の虫と同じ始点から描き、虫のほうを字送りゼロの写し(.pre)に
  替える(Illustrator は字送りの始点より上にはみ出す字形を切り落とすので、虫のあとから上へ戻して描く作りは不可)。
  縦書きの入口でかなを同じ形の写し(.vert)に替え、写しから縦書き用の字形を直接出す。
  Safari は縦書きで「1文字ずつ vert → 横書き用の liga・ss」の順にしか当てないため、
  合字のあとで縦用に替える作りでは効かない。HarfBuzz は逆に縦書きで liga を使わないので、
  合字と順送りは liga と vert の両方に登録してある。
  元のフォントが縦用の字形を持つ字(小書きの字、長音など)は、縦用の字形に重ねた虫も作る。
  縦の字送りの表(vmtx)が無い書体(Darumadrop One)には、全角の標準の値で表を足す。

注意: 吹き出しは行の高さ(ascent 1160)を大きく超えて、上端が 2000 前後まで出る。行間を広げて使う。
"""
import collections
import copy
import math
import multiprocessing
import random
from pathlib import Path

from fontTools.otlLib import builder as otl
from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.removeOverlaps import removeOverlaps
from fontTools.ttLib.tables import otTables as ot

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "dist"


def nib_round(d, n=10):
    return [(d / 2 * math.cos(2 * math.pi * i / n), d / 2 * math.sin(2 * math.pi * i / n)) for i in range(n)]


def nib_rect(w, h, c):
    """角を落とした四角いペン先(マーカー・クレヨン)。横に動くと細く、縦に動くと太い。"""
    x, y = w / 2, h / 2
    return [(x - c, y), (x, y - c), (x, -y + c), (x - c, -y), (-x + c, -y), (-x, -y + c), (-x, y - c), (-x + c, y)]


# ベースごとのペン先。太さは「ー」「い」などの実測に合わせた。
#   nib: ペン先の輪郭 / rough: 輪郭のがたつき
#   family・ja: 新しい名前。元の書体名は含めない(作者の README が派生名への使用を禁じている書体がある)
#   seed: 字形の乱数の種。名前を変えても形が変わらないよう固定する
BASES = [
    dict(file="Yomogi-Regular", family="Minomushi Gokuboso", ja="ミノムシ ごくぼそ", based_on="Yomogi", seed="Minomushi Yomogi", nib=nib_round(40), rough=0),
    dict(file="HachiMaruPop-Regular", family="Minomushi Marumoji", ja="ミノムシ まるもじ", based_on="Hachi Maru Pop", seed="Minomushi HachiMaru", nib=nib_round(60), rough=0),
    dict(file="ZenKurenaido-Regular", family="Minomushi Ballpen", ja="ミノムシ ボールペン", based_on="Zen Kurenaido", seed="Minomushi Kurenaido", nib=nib_round(48), rough=0),
    dict(file="YuseiMagic-Regular", family="Minomushi Marker", ja="ミノムシ マーカー", based_on="Yusei Magic", seed="Minomushi Yusei", nib=nib_rect(108, 58, 16), rough=0),
    dict(file="DarumadropOne-Regular", family="Minomushi Gokubuto", ja="ミノムシ ごくぶと", based_on="Darumadrop One", seed="Minomushi Daruma", nib=nib_rect(140, 130, 36), rough=9),
    dict(file="SlacksideOne-Regular", family="Minomushi Yurugaki", ja="ミノムシ ゆるがき", based_on="Slackside One", seed="Minomushi Slackside", nib=nib_round(66), rough=4),
]

# 対応文字: ひらがな・カタカナ全部と長音、英数字(半角・全角)、よく使う記号、試作から使っている漢字1字。
# フォントに無い字は飛ばす
KANA = "".join(chr(c) for c in [*range(0x3041, 0x3097), *range(0x30A1, 0x30FB), 0x30FC])
ALNUM = "".join(chr(base + c) for base in (0, 0xFEE0) for c in [*range(0x30, 0x3A), *range(0x41, 0x5B), *range(0x61, 0x7B)])
PUNCT = "、。！？・「」（）.,!?()"
CHARS = KANA + "字" + ALNUM + PUNCT
SYMBOLS = "○●"            # 記号そのものにも虫・吹き出しを付けられるようにする
MARK, CIRCLE, BLOT, TIMES = 0x2715, 0x25CB, 0x25CF, 0x00D7  # ✕ ○ ● ×

VERSION = "1.000"
VENDOR_ID = "prnm"                        # OS/2 のベンダー ID
MANUFACTURER = "Pronama LLC"              # name テーブルの製造元

# ---- 替え字形 ----
VARIANTS = 3                              # かなと「虫だけ」に用意する形の数
GAP = 20                                  # 直前の虫・吹き出しを探しにいく字数の上限

# ---- 虫(1000 UPM。字送り 1000 のときの大きさが基準) ----
SCRIBBLE_TOP, SCRIBBLE_BOTTOM = 730, -90   # 虫の上下の目安。実際は書体ごとに、かなの高さから決める
BUG_FILL = 0.84                           # 字送りに対する虫の幅。残りが隣の虫とのすき間になる
CELL_GROW = 1.1                           # 字幅が不揃いな書体で、虫にした字の字送りを広げる倍率
FIT_MIN_HEIGHT, FIT_MIN_WIDTH = 380, 420   # 英数字・記号に合わせた虫の、高さと幅の下限
MIN_CELL = 560                            # 虫にした字の字送りの下限。これより狭い字は虫のときだけ広げる
SMALL_KANA = "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"  # 小書きの字は虫も小さくする
EYE_PEN_MAX, BUBBLE_PEN_MAX = 62, 90      # 極太ペンでも目と吹き出しが潰れない上限

# ---- 吹き出し ----
BUBBLE_FILL = 0.97                        # 字送りに対する吹き出しの幅の上限
CHAR_SCALE = 0.62                         # 吹き出しの中の字の縮小率(字送り 1000 のとき)
CHAR_FILL = 0.7                           # 吹き出しの内側に対する、中の字の大きさの下限
CHAR_CLEARANCE = 18  # 吹き出しの中の字と枠の線のあいだに空けるすき間
CHAR_STROKE_MAX = 75  # 吹き出しの中の字を太らせる上限
LOW_STEP = 100  # 横書きで、小さい虫に合わせて吹き出しを下げる刻み
SIDE_STEP = 50  # 縦書きで、虫の目の位置に合わせて右吹き出しをずらす刻み(横)
SIDE_KEEP = 8  # 漢字のある書体で残す、縦のずらしの組の数。字形数の上限に収めるため、使う虫の少ない組は近い組に寄せる
SIDE_STEP_Y = 100  # 同、縦の刻み。字形数を抑えるため横より粗くする
KANJI_BUGS, KANJI_FRAMES = 12, 8  # 漢字で使い回す、虫と吹き出しの枠の種類
KANJI_BUG_CELL = 1090
SPREAD_REACH = 24  # Safari の縦書きで、後ろのかなから漢字へ縦書きを伝える範囲(字形数。✕ や ○ も数える)  # 漢字の虫の幅を決める字送り(かなは 1000。虫の幅はこの 0.84 倍)
VERTICAL_OVERHANG = 0  # 縦書きで、字送りの始点より上にはみ出してよい量(Illustrator は 30 でも上端がわずかに切れた)


def signed_area(pts):
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2


def draw_poly(pen, pts):
    """塗りの向き(時計回り)に揃えて描く。"""
    pts = [(round(x), round(y)) for x, y in pts]
    area = signed_area(pts)
    if abs(area) < 1:
        return
    if area > 0:
        pts.reverse()
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.closePath()


def convex_hull(pts):
    pts = sorted(set(pts))
    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out[:-1]
    return half(pts) + half(pts[::-1])


def round_corners(pts):
    """折れ線の角を丸める(両端は保つ)。1回目は浅く切って振れ幅を残す。"""
    for q in (0.1, 0.25):
        out = [pts[0]]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            out.append((x0 * (1 - q) + x1 * q, y0 * (1 - q) + y1 * q))
            out.append((x0 * q + x1 * (1 - q), y0 * q + y1 * (1 - q)))
        out.append(pts[-1])
        pts = out
    return pts


class FlattenPen(BasePen):
    """輪郭を折れ線にする。"""
    def __init__(self):
        super().__init__(None)
        self.contours = []

    def _moveTo(self, pt):
        self.contours.append([pt])

    def _lineTo(self, pt):
        self.contours[-1].append(pt)

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        for t in (1 / 3, 2 / 3, 1):
            u = 1 - t
            self.contours[-1].append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                                      u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        for t in (0.25, 0.5, 0.75, 1):
            u = 1 - t
            self.contours[-1].append(tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d
                                           for a, b, c, d in zip(p0, p1, p2, p3)))


def draw_stroke(pen, rng, pts, nib, rough=0):
    """ペン先を線に沿って動かした跡を描く。線の端はペン先の形がそのまま出る。"""
    def stamp(x, y):
        return [(x + nx + rng.uniform(-rough, rough), y + ny + rng.uniform(-rough, rough)) for nx, ny in nib]
    prev = stamp(*pts[0])
    for x, y in pts[1:]:
        cur = stamp(x, y)
        draw_poly(pen, convex_hull(prev + cur))
        prev = cur


def scale_nib(nib, limit):
    size = max(max(x for x, _ in nib) - min(x for x, _ in nib), max(y for _, y in nib) - min(y for _, y in nib))
    k = min(1, limit / size)
    return [(x * k, y * k) for x, y in nib]


def nib_size(nib):
    return (max(x for x, _ in nib) - min(x for x, _ in nib), max(y for _, y in nib) - min(y for _, y in nib))


def bug_squeeze(cell, nib, glyph_width=None):
    """字送り cell に虫が収まるよう、横の振れ幅に掛ける倍率。字送り 1000 で 1。
    glyph_width を渡すと、その幅の字を消せる大きさまでさらに縮める(小書きの字・英数字・記号用)。"""
    nib_w = nib_size(nib)[0]
    width = cell * BUG_FILL
    if glyph_width is not None:
        width = min(width, max(glyph_width + 140, FIT_MIN_WIDTH))
    return (width - nib_w) / (1000 * BUG_FILL - nib_w)


def scribble_path(rng, nib_h, squeeze=1.0, top=SCRIBBLE_TOP, bottom=SCRIBBLE_BOTTOM):
    """一筆でぐしゃぐしゃと消した線。上が太く下へ細るミノ形が多め。squeeze で横幅を縮める。"""
    height = top - bottom
    # 一往復で下がる量はペンの太さ以下に抑える(線どうしが重なって密になる)。太いペンでも9回は振る
    turns = max(9, min(26, round(height / (nib_h * rng.uniform(0.72, 0.98)))))
    full = rng.uniform(430, 490) * squeeze
    kind = rng.choices(("taper", "shoulder", "even"), weights=(65, 22, 13))[0]
    power = rng.uniform(0.7, 1.6)
    end = rng.uniform(0.18, 0.36)
    peak = rng.uniform(0.15, 0.3)

    def half_width(t):
        if kind == "taper":      # 上が最大で下へ細る
            return full * (1 - (1 - end) * t ** power)
        if kind == "shoulder":   # 少し下に肩があり、そこから細る
            if t < peak:
                return full * (0.72 + 0.28 * t / peak)
            return full * (1 - (1 - end) * ((t - peak) / (1 - peak)) ** power)
        return full * (0.85 - 0.22 * t)  # ほぼ同じ幅

    steps = [rng.uniform(0.75, 1.3) for _ in range(turns)]  # 下への移動量のばらつきは控えめ
    total = sum(steps)
    sway, drift = rng.uniform(-40, 40) * squeeze, rng.uniform(-60, 60) * squeeze
    overshoot = {rng.randrange(2, turns + 1) for _ in range(rng.choice((0, 1, 1, 2)))}  # 最上段は目の横に飛び出すので除く
    side = rng.choice((-1, 1))
    pts, acc = [], 0.0
    for i in range(turns + 1):
        t = acc / total
        cx = 500 + sway * math.sin(t * math.pi * rng.uniform(0.8, 1.2)) + drift * t * t
        reach = half_width(t) * rng.uniform(0.86, 1.08) * (1.12 if i in overshoot else 1)
        if i < 2:  # 書き出しは控えめに。最上段が目の横へ一本飛び出して見えるのを防ぐ
            reach *= (0.5, 0.82)[i]
        y = top - height * t + side * rng.uniform(0, 24) + rng.uniform(-8, 8)
        pts.append((cx + side * reach, y))
        side = -side
        if i < turns:
            acc += steps[i]
    # 最後に下へ払う、しっぽ
    lx, ly = pts[-1]
    pts.append((lx + side * rng.uniform(40, 130) * squeeze, ly - rng.uniform(25, 70)))
    return round_corners(pts)


def loop_path(rng, cx, cy, rx, ry, n, wobble, tilt=0.0, pull=None):
    """手で描いた輪。閉じ際が少しずれて重なる。pull=(角度, 先端, 半角) でしっぽを付ける。"""
    p1, p2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    start = rng.uniform(0, 2 * math.pi)
    drift = rng.uniform(-0.05, 0.05)       # 一周するうちに半径がずれる
    extra = rng.uniform(0.15, 0.5)         # 閉じ際の重なり
    angles = [start + (2 * math.pi + extra) * i / n for i in range(n + 1)]
    if pull:
        t0 = pull[0]
        k = math.ceil((start - t0) / (2 * math.pi))
        angles = sorted(angles + [t0 + 2 * math.pi * k])
    ct, st = math.cos(tilt), math.sin(tilt)
    out = []
    for a in angles:
        prog = (a - start) / (2 * math.pi)
        k = 1 + wobble * math.sin(2 * a + p1) + wobble * 0.7 * math.sin(3 * a + p2) + drift * prog
        x, y = rx * k * math.cos(a), ry * k * math.sin(a)
        x, y = cx + x * ct - y * st, cy + x * st + y * ct
        if pull:
            d = abs((a - pull[0] + math.pi) % (2 * math.pi) - math.pi)
            if d < pull[2]:
                w = (1 - d / pull[2]) ** 1.5
                x += (pull[1][0] - x) * w
                y += (pull[1][1] - y) * w
        out.append((x, y))
    return out


def eye_radius(eye_line):
    return 68 + eye_line * 0.35


def nominal_eye_top(nib, top=SCRIBBLE_TOP):
    """吹き出しだけの字形が、しっぽの先を合わせる高さ。"""
    eye_line = max(nib_size(scale_nib(nib, EYE_PEN_MAX)))
    r = eye_radius(eye_line)
    return top + nib_size(nib)[1] * 0.3 + r * 1.2 + r * 1.15 + eye_line / 2


def draw_bug(pen, rng, nib, rough, squeeze=1.0, top=SCRIBBLE_TOP, bottom=SCRIBBLE_BOTTOM):
    """虫: 一筆のぐしゃぐしゃと、その上に乗る目玉。(目の中心x, 目の上端y) を返す。"""
    nib_h = nib_size(nib)[1]
    draw_stroke(pen, rng, scribble_path(rng, nib_h, squeeze, top, bottom), nib, rough)

    eye_nib = scale_nib(nib, EYE_PEN_MAX)
    eye_line = max(nib_size(eye_nib))
    eye_cx = 500 + rng.uniform(-45, 45) * squeeze
    look = rng.uniform(0.7, 1.7)
    eye_top = 0
    rights, mids = [], []
    for sign in (-1, 1):
        r = eye_radius(eye_line) * rng.uniform(0.9, 1.12)
        ex = eye_cx + sign * (r + eye_line / 2 + rng.uniform(-8, 12))
        ey = top + nib_h * 0.3 + r * rng.uniform(1.05, 1.35)  # 目の下端がぐしゃぐしゃの上端に触れる程度
        rights.append(ex + r + eye_line / 2)
        mids.append(ey)
        draw_stroke(pen, rng, loop_path(rng, ex, ey, r, r * rng.uniform(1.0, 1.15), 14, 0.04), eye_nib, rough * 0.5)
        pr = r * 0.4
        dot = [(ex + math.cos(look) * r * 0.3 + pr * math.cos(a) * rng.uniform(0.9, 1.1),
                ey + math.sin(look) * r * 0.3 + pr * math.sin(a) * rng.uniform(0.9, 1.1))
               for a in (2 * math.pi * i / 12 for i in range(12))]
        draw_poly(pen, dot)
        eye_top = max(eye_top, ey + r * 1.15 + eye_line / 2)
    draw_bug.last = (max(rights), sum(mids) / 2)  # 目の右端と高さ。縦書きの右吹き出しを合わせるのに使う
    return eye_cx, eye_top


def bubble_fit(cell, line):
    """字送り cell に合わせて吹き出しを縮める倍率(字送り 1000 では 1)。"""
    return min(1, (cell * BUBBLE_FILL - line) / 2 / ((370 + line * 0.5) * 1.07))


def draw_bubble(pen, rng, glyph_set, base_name, nib, rough, eye_cx, eye_top, dx=0, cell=1000, mid=340, boost=1.0, typical_size=None, clear=None):
    """吹き出し: 同じペンで一周描く。位置・大きさ・傾き・しっぽを毎回ばらつかせる。
    clear を渡すと縦書き用。虫の右(x が clear より右)に置き、しっぽを目のほうへ向ける。"""
    bubble_nib = scale_nib(nib, BUBBLE_PEN_MAX)
    line = max(nib_size(bubble_nib))
    # 字送りが狭い書体では、隣の吹き出しと重ならないよう小さくする(字送り 1000 では元の大きさ)
    fit = bubble_fit(cell, line)
    rx = (370 + line * 0.5) * rng.uniform(0.95, 1.07) * fit
    ry = (335 + line * 0.5) * rng.uniform(0.95, 1.07) * fit
    tip = (dx + eye_cx + rng.uniform(-70, 90) * fit, eye_top + line / 2 + rng.uniform(15, 45))
    cx = dx + 500 + rng.uniform(-70, 80) * fit
    cy = tip[1] + rng.uniform(95, 150) + ry
    if clear is not None:
        eye_line = max(nib_size(scale_nib(nib, EYE_PEN_MAX)))
        r = eye_radius(eye_line)
        eye_mid = eye_top - r * 1.15 - eye_line / 2
        # しっぽの先は目のすぐ右。虫ごとに目の位置が少し揺れるので、触れないだけのすき間を取る
        tip = (dx + eye_cx + 2 * r + eye_line + line / 2 + rng.uniform(40, 60), eye_mid + rng.uniform(-40, -20))
        cx = max(tip[0] + rng.uniform(95, 150), dx + clear + line / 2 + 20) + rx
        # 吹き出しは目とほぼ同じ高さに置く。目より低いと、しっぽが上を向いて不自然になる。
        # 高くしすぎると、Illustrator で上端が切れる(build の VERTICAL_OVERHANG を参照)
        cy = eye_mid + rng.uniform(-60, -30)
    t0 = math.atan2((tip[1] - cy) / ry, (tip[0] - cx) / rx) + rng.uniform(-0.2, 0.2)
    path = loop_path(rng, cx, cy, rx, ry, 44, rng.uniform(0.018, 0.04), rng.uniform(-0.12, 0.12),
                     pull=(t0, tip, rng.uniform(0.13, 0.2)))
    draw_stroke(pen, rng, path, bubble_nib, rough * 0.6)
    if base_name is None:  # 枠だけ(漢字用の部品)。中の字を置くための中心・大きさを返す
        return cx, cy, rx, ry, line, fit

    # 正しい字。縮小で細くなるぶん、輪郭を丸ペンでなぞって太らせる
    rec = DecomposingRecordingPen(glyph_set)
    glyph_set[base_name].draw(rec)
    s = CHAR_SCALE * fit ** 0.75  # 吹き出しを小さくしたぶん、中の字も縮める
    if typical_size:  # 字の小さい書体では余白が空きすぎるので、吹き出しの内側に対する割合で下限を設ける
        s = max(s, CHAR_FILL * (2 * (370 + line * 0.5) * fit - line) / typical_size)
    s *= boost  # boost は小書きの字用
    # 字の見た目の中心を吹き出しの中心に合わせる(字幅が一定でない書体でもずれない)。
    # 縦は小書きの字などが浮きすぎないよう、その書体の字の中心 mid と半々にする
    bounds = BoundsPen(glyph_set)
    rec.replay(bounds)
    x0, y0, x1, y1 = bounds.bounds or (0, 0, 1000, 680)
    # 濁点・半濁点の付く字などは標準の字より大きい。字の四隅(濁点のある右上など)が枠の内側に収まる大きさを上限にする
    inner_x, inner_y = rx - line / 2 - CHAR_CLEARANCE, ry - line / 2 - CHAR_CLEARANCE
    # 縦書き用の吹き出しでは、字を枠の真ん中に置く。縦用の小書きの字は字面の右上に寄っているので、
    # 書体の字の中心と半々にすると枠の上に寄りすぎる
    anchor = (y0 + y1) / 2 if clear is not None else ((y0 + y1) / 2 + mid) / 2
    lean = abs((y0 + y1) / 2 - anchor)  # 字の見た目の中心が枠の中心からずれる量
    s = min(s, 1 / math.hypot((x1 - x0) / 2 / inner_x, ((y1 - y0) / 2 + lean) / inner_y))
    transform = (s, 0, 0, s, cx - s * (x0 + x1) / 2, cy - s * anchor)
    rec.replay(TransformPen(pen, transform))
    pen_size = sum(nib_size(nib)) / 2
    extra = min(pen_size * 0.9, CHAR_STROKE_MAX) - pen_size * s
    if extra >= 4:
        flat = FlattenPen()
        rec.replay(TransformPen(flat, transform))
        fattener = nib_round(extra, 6)
        for contour in flat.contours:
            kept = [contour[0]]
            for q in contour[1:]:
                if math.dist(q, kept[-1]) >= extra * 0.5:
                    kept.append(q)
            draw_stroke(pen, rng, kept + [kept[0]], fattener)


def finish(pen):
    return pen.glyph()  # 重なったままの輪郭。あとでまとめて統合する


def glyph_combined(glyph_set, base_name, seed, nib, rough, cell, squeeze, top, bottom, mid, bubble_cell, boost, typical_size, bug_dx=0):
    """虫 + その字の吹き出し(ss02)。字送り cell の中央に置く。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    shift = (cell - 1000) / 2
    eye_cx, eye_top = draw_bug(TransformPen(pen, (1, 0, 0, 1, shift + bug_dx, 0)), rng, nib, rough, squeeze, top, bottom)
    draw_bubble(pen, rng, glyph_set, base_name, nib, rough, eye_cx + bug_dx, eye_top, dx=shift, cell=bubble_cell, mid=mid, boost=boost, typical_size=typical_size)
    return finish(pen)


def glyph_struck(glyph_set, base_name, seed, nib, rough, cell, advance, squeeze, top, bottom, bug_dx=0):
    """元の字の上に虫を重ねる(あ×)。base_name が None なら虫だけ(●×)。
    字送り cell の中央に、元の字(字幅 advance)と虫を置く。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    if base_name:
        rec = DecomposingRecordingPen(glyph_set)
        glyph_set[base_name].draw(rec)
        rec.replay(TransformPen(pen, (1, 0, 0, 1, (cell - advance) / 2, 0)))
    draw_bug(TransformPen(pen, (1, 0, 0, 1, (cell - 1000) / 2 + bug_dx, 0)), rng, nib, rough, squeeze, top, bottom)
    return finish(pen)


def glyph_combined_vertical(glyph_set, char_name, seed, nib, rough, cell, squeeze, top, bottom, mid, bubble_cell, boost, typical_size, bug_dx=0):
    """縦書き用の「虫 + 吹き出し」。吹き出しは虫の右に出す。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    shift = (cell - 1000) / 2
    eye_cx, eye_top = draw_bug(TransformPen(pen, (1, 0, 0, 1, shift + bug_dx, 0)), rng, nib, rough, squeeze, top, bottom)
    draw_bubble(pen, rng, glyph_set, char_name, nib, rough, eye_cx + bug_dx, eye_top, dx=shift, cell=bubble_cell, mid=mid,
                boost=boost, typical_size=typical_size, clear=500 + cell * BUG_FILL / 2)
    return finish(pen)


def glyph_bubble_vertical(glyph_set, char_name, seed, nib, rough, prev_cell, top, mid, boost, bubble_cell, typical_size):
    """縦書き用の幅ゼロの吹き出し(い○)。直前(上)の虫の右に出す。
    縦書きでは字形の x=0 が行の中央に来るので、虫の中央(500)を 0 に合わせて描く。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    draw_bubble(pen, rng, glyph_set, char_name, nib, rough, 500, nominal_eye_top(nib, top), dx=-500, cell=bubble_cell, mid=mid,
                boost=boost, typical_size=typical_size, clear=500 + prev_cell * BUG_FILL / 2)
    return finish(pen)


def glyph_frame(glyph_set, seed, nib, rough, prev_cell, top, mid, bubble_cell, vertical):
    """吹き出しの枠だけの字形(漢字用の部品)と、中に字を置くための (中心x, 中心y, 横半径, 縦半径, 線の太さ, 縮小率)。
    横書き用は幅ゼロで左隣の字の上、縦書き用は虫の右。位置の決め方はかなの吹き出しと同じ。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    if vertical:
        info = draw_bubble(pen, rng, glyph_set, None, nib, rough, 500, nominal_eye_top(nib, top), dx=-500, cell=bubble_cell,
                           mid=mid, clear=500 + prev_cell * BUG_FILL / 2)
    else:
        info = draw_bubble(pen, rng, glyph_set, None, nib, rough, 500, nominal_eye_top(nib, top), dx=-prev_cell / 2 - 500,
                           cell=bubble_cell, mid=mid)
    return finish(pen), info


def is_kanji(code):
    return 0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF


def glyph_bubble(glyph_set, base_name, seed, nib, rough, prev_advance, top, mid, boost, bubble_cell, typical_size):
    """直前の文字の上に出す吹き出し(い○)。幅ゼロで、左隣の字の中央に合わせて描く。"""
    rng, pen = random.Random(seed), TTGlyphPen(None)
    draw_bubble(pen, rng, glyph_set, base_name, nib, rough, 500, nominal_eye_top(nib, top), dx=-prev_advance / 2 - 500, cell=bubble_cell, mid=mid, boost=boost, typical_size=typical_size)
    return finish(pen)


def add_feature(gsub, tag, lookup_index):
    records = gsub.FeatureList.FeatureRecord
    # 同じタグの feature が既にあるならそこへ足す(同タグを2つ並べても片方しか使われない)
    existing = [r for r in records if r.FeatureTag == tag]
    if existing:
        for r in existing:
            r.Feature.LookupListIndex = sorted(set(r.Feature.LookupListIndex) | {lookup_index})
            r.Feature.LookupCount = len(r.Feature.LookupListIndex)
        return
    rec = ot.FeatureRecord()
    rec.FeatureTag = tag
    rec.Feature = ot.Feature()
    rec.Feature.FeatureParams = None
    rec.Feature.LookupListIndex = [lookup_index]
    rec.Feature.LookupCount = 1
    # FeatureRecord はタグ順を保つ必要があるので、挿入後に既存の参照を付け替える
    old_ids = [id(r) for r in records]
    records.append(rec)
    records.sort(key=lambda r: r.FeatureTag)
    new_ids = [id(r) for r in records]
    remap = {old: new_ids.index(i) for old, i in enumerate(old_ids)}
    new_index = new_ids.index(id(rec))
    gsub.FeatureList.FeatureCount = len(records)
    for script in gsub.ScriptList.ScriptRecord:
        langs = [script.Script.DefaultLangSys] + [l.LangSys for l in script.Script.LangSysRecord]
        for lang in filter(None, langs):
            if lang.ReqFeatureIndex != 0xFFFF:
                lang.ReqFeatureIndex = remap[lang.ReqFeatureIndex]
            lang.FeatureIndex = sorted([remap[i] for i in lang.FeatureIndex] + [new_index])
            lang.FeatureCount = len(lang.FeatureIndex)


def build(file, family, ja, based_on, seed, nib, rough):
    font = TTFont(ROOT / "base" / f"{file}.ttf")
    assert font["head"].unitsPerEm == 1000
    cmap = font.getBestCmap()
    glyph_set = font.getGlyphSet()
    glyf, hmtx = font["glyf"], font["hmtx"]
    circle, blot = cmap[CIRCLE], cmap[BLOT]
    added = []

    # 縦の字送りの表が無い書体(Darumadrop One)には足す。無いままだと縦書きの字送りがアプリ任せになり、
    # 虫の字送りも右吹き出しの位置も決められない。全角の標準どおり、字送り 1000・仮想ボディの上端を原点にする
    if "vmtx" not in font:
        top_edge = font["OS/2"].sTypoAscender
        vmtx = font["vmtx"] = newTable("vmtx")
        vmtx.metrics = {name: (1000, top_edge - getattr(glyf[name], "yMax", top_edge)) for name in font.getGlyphOrder()}
        vhea = font["vhea"] = newTable("vhea")
        vhea.tableVersion = 0x00011000
        vhea.ascent, vhea.descent, vhea.lineGap = 500, -500, 0
        vhea.advanceHeightMax, vhea.minTopSideBearing, vhea.minBottomSideBearing, vhea.yMaxExtent = 1000, 0, 0, 0
        vhea.caretSlopeRise, vhea.caretSlopeRun, vhea.caretOffset = 0, 1, 0
        vhea.reserved1 = vhea.reserved2 = vhea.reserved3 = vhea.reserved4 = 0
        vhea.metricDataFormat, vhea.numberOfVMetrics = 0, len(vmtx.metrics)

    # 発動用の ✕ を追加する。× を全角の大きさに拡大して作る
    assert MARK not in cmap
    mark = "uni2715"
    rec = DecomposingRecordingPen(glyph_set)
    glyph_set[cmap[TIMES]].draw(rec)
    bounds = BoundsPen(glyph_set)
    rec.replay(bounds)
    x0, y0, x1, y1 = bounds.bounds
    k = 640 / max(x1 - x0, y1 - y0)
    pen = TTGlyphPen(None)
    rec.replay(TransformPen(pen, (k, 0, 0, k, 500 - k * (x0 + x1) / 2, 340 - k * (y0 + y1) / 2)))
    glyf[mark] = pen.glyph()
    glyf[mark].recalcBounds(glyf)
    hmtx[mark] = (1000, glyf[mark].xMin)
    font["vmtx"][mark] = (1000, 0)
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap[MARK] = mark

    def add(name, glyph, advance):
        glyf[name] = glyph
        glyph.recalcBounds(glyf)
        hmtx[name] = (advance, getattr(glyph, "xMin", 0))
        font["vmtx"][name] = (1000, 0)
        added.append(name)

    # プロポーショナルな書体では字幅が1000でないので、虫と吹き出しを字の中央に合わせる
    advances = sorted(hmtx[cmap[ord(ch)]][0] for ch in KANA if ord(ch) in cmap)
    typical = advances[len(advances) // 2]
    # 字幅が不揃いな書体は字が字送りいっぱいに描かれているので、虫にした字の字送りを少し広げて
    # 「字と同じ幅の虫」と「隣の虫とのすき間」を両立させる
    grow = CELL_GROW if advances[0] != advances[-1] else 1
    bug_cell = max(round(typical * grow), MIN_CELL) if grow > 1 else 1000  # 虫だけの字形の字送り
    # 虫の上下は、その書体のかな(小書きを除く)の高さに合わせる
    full_size = [glyf[cmap[ord(ch)]] for ch in KANA if ord(ch) in cmap and ch not in SMALL_KANA and ch != "ー"]
    tops, bottoms = sorted(g.yMax for g in full_size), sorted(g.yMin for g in full_size)
    box_top, box_bottom = tops[len(tops) // 2] - 30, bottoms[len(bottoms) // 10] - 10
    mid = (box_top + box_bottom) / 2 + 20
    # 吹き出しは書体の標準の字送りに合わせた大きさに揃える(狭い字でも小さくしない。隣と重なるのは許す)
    wide = sorted(hmtx[cmap[ord(ch)]][0] for ch in KANA if ord(ch) in cmap and ch not in SMALL_KANA)
    bubble_floor = max(bug_cell, round(wide[len(wide) * 4 // 5] * grow))  # 幅の広い字(上位2割)の字送りが基準
    # 吹き出し付き(ss02)の字送りは、吹き出しの幅近くまで広げる(隣とは軽く触れる程度)。
    # 字幅固定の書体のかなは元から足りているので変わらず、半角の英数字などに効く
    line = max(nib_size(scale_nib(nib, BUBBLE_PEN_MAX)))
    bubble_width = 2 * (370 + line * 0.5) * bubble_fit(bubble_floor, line) + line
    mino_floor = round(bubble_width * 0.95)
    # 小書きの字は吹き出しの中で潰れやすいので、普通の字の8割の大きさになるまで拡大する(最大1.5倍)
    sizes = sorted(max(g.xMax - g.xMin, g.yMax - g.yMin) for g in full_size)
    typical_size = sizes[len(sizes) // 2]

    struck, combined, bubble, liga = {}, {}, {}, {}
    # 元のフォントが縦書きで置き換える字形(小書きの字、長音など)
    vert_map = {}
    for record in font["GSUB"].table.FeatureList.FeatureRecord:
        if record.FeatureTag == "vert":
            for index in record.Feature.LookupListIndex:
                for subtable in font["GSUB"].table.LookupList.Lookup[index].SubTable:
                    vert_map.update(getattr(subtable, "mapping", {}))
    # 縦書きの入口。Safari は縦書きで、まず1文字ずつ vert の字形に替え、そのあと横書き用の機能(liga・ss)
    # だけを当てる。合字やスタイルセットのあとで縦用の字形に替える作りは Safari では効かないので、
    # 縦用の字形を持たないかなに同じ形の写しを作って vert で替え、写しからは縦書き用の字形が直接出るようにする。
    # (✕ にも写しを作る案は不可。Safari は ✕ を縦用の字形に替えないので、合字が成り立たなくなる)
    def twin(name):
        glyf[name + ".vert"] = copy.deepcopy(glyf[name])
        hmtx[name + ".vert"] = hmtx[name]
        font["vmtx"][name + ".vert"] = font["vmtx"][name]
        return name + ".vert"
    entry = {}
    for ch in CHARS:
        name = cmap.get(ord(ch))
        if name and name not in vert_map:
            assert name + ".vert" not in glyf.glyphs
            entry[name] = twin(name)
    # Safari は、漢字だけのページ(文字コード 256 個の区切り)の字を縦用の字形に替えない。漢字は vert が
    # 効かないまま横書き用の合字に進み、吹き出しが横書きの形で出てしまう。そこで「縦用の字形の隣にある
    # 漢字は縦用の写しに替える」規則を合字の前に置き、同じ行のかな・句読点から縦書きであることを伝える。
    # ✕ ○ ● と空白は、伝えるあいだだけ目印の写しに替え、合字の前に元へ戻す。横書きには縦用の字形が
    # 出ないので、この規則は働かない
    carriers = {}
    for code in (MARK, CIRCLE, BLOT, 0x20, 0x3000):
        name = cmap.get(code)
        if name and name not in vert_map and name not in entry:
            glyf[name + ".vcarry"] = copy.deepcopy(glyf[name])
            hmtx[name + ".vcarry"] = hmtx[name]
            font["vmtx"][name + ".vcarry"] = font["vmtx"][name]
            carriers[name] = name + ".vcarry"
    # 替え字形: tiers[n] は「n 番目の形」の字形の集合、step[n] は n 番目 → n+1 番目の置き換え表
    # 虫と、幅ゼロの吹き出しとで、別々に順送りする
    def new_cycle():
        return [set() for _ in range(VARIANTS)], [{} for _ in range(VARIANTS - 1)]
    bug_cycle, bubble_cycle = new_cycle(), new_cycle()

    eye_info = {}  # 虫の字形 → 描いたときの目の右端 x と目の高さ y(字送り 1000 の中央に描いた座標)

    def add_variants(name, make, advance, count, cycle=bug_cycle):
        """name を最初の形として count 種類の字形を作り、切り替え表に登録する。"""
        tiers, step = cycle
        names = [name] + [f"{name}.v{n + 1}" for n in range(1, count)]
        for n, variant in enumerate(names):
            add(variant, make("" if n == 0 else f"-v{n + 1}"), advance)
            eye_info[variant] = getattr(draw_bug, "last", None)
            tiers[n].add(variant)
        for n in range(count - 1):
            step[n][names[0]] = names[n + 1]

    pending_bubbles = []
    nudge = {}  # 字形名 → 直後の幅ゼロの吹き出しをずらす量 (横, 縦)
    add_variants("mino.bug", lambda v: glyph_struck(glyph_set, None, f"{seed}-bug{v}", nib, rough, bug_cell, bug_cell, bug_squeeze(bug_cell, nib), box_top, box_bottom), bug_cell, VARIANTS)
    def fit(ch, name, vertical=False):
        """字 ch(字形 name)に重ねる虫の大きさと位置。"""
        advance, glyph = hmtx[name][0], glyf[name]
        cell = max(round(advance * grow), MIN_CELL)  # 狭い字は虫にしたときだけ字送りを下限まで広げる
        squeeze, top, bottom, boost, bug_dx = bug_squeeze(cell, nib), box_top, box_bottom, 1.0, 0
        width, size = glyph.xMax - glyph.xMin, max(glyph.xMax - glyph.xMin, glyph.yMax - glyph.yMin)
        if ch in SMALL_KANA and not vertical:  # 小書きの字は、字の大きさに合わせて虫を低く・細くする
            squeeze = bug_squeeze(cell, nib, width)
            top = min(box_top, glyph.yMax - 40)
            boost = max(1.0, min(1.5, 0.8 * typical_size / size))
        elif ch in ALNUM + PUNCT or ch in SMALL_KANA:
            # 英数字・記号と、縦書き用の小書きの字(右上に寄っている)は、その字の大きさと位置に虫を合わせる
            squeeze = bug_squeeze(cell, nib, width)
            top, bottom = min(box_top, glyph.yMax - 30), glyph.yMin - 30
            lack = FIT_MIN_HEIGHT - (top - bottom)
            if lack > 0:
                top, bottom = top + lack / 2, bottom - lack / 2
            # 字送りの中央に無い字は、字の見た目の中央に虫を寄せる(字送りからはみ出さない範囲で)
            reach = (cell - min(cell * BUG_FILL, max(width + 140, FIT_MIN_WIDTH))) / 2
            bug_dx = max(-reach, min(reach, (glyph.xMin + glyph.xMax) / 2 - advance / 2))
            boost = max(1.0, min(1.5, 0.8 * typical_size / size))
        return advance, cell, squeeze, top, bottom, boost, bug_dx

    def variant_names(name, count):
        return [name] + [f"{name}.v{n + 1}" for n in range(1, count)]

    # 縦書きの右吹き出しは「標準の位置に目のある虫」の右・目の高さに描いてある。虫ごとの実際の目との差(横, 縦)。
    # 目の位置は虫ごとに少し揺らしてあるので、描いたときの位置(eye_info)から求める
    eye_line = max(nib_size(scale_nib(nib, EYE_PEN_MAX)))
    eye_r = eye_radius(eye_line)
    nominal_right = 500 + 2 * eye_r + eye_line
    nominal_mid = nominal_eye_top(nib, box_top) - eye_r * 1.15 - eye_line / 2
    def side_shift(source, bug_dx):
        right, mid = eye_info[source]
        return round(bug_dx + right - nominal_right), min(0, round(mid - nominal_mid))  # 上へはずらさない(縦の字送りが伸びるため)
    pre_sources = [(name, side_shift(name, 0)) for name in variant_names("mino.bug", VARIANTS)]  # 直後に右吹き出しが来うる虫

    pending_vertical, vertical_bugs, vertical_twins = [], [], []
    for ch in CHARS + SYMBOLS:
        base = cmap.get(ord(ch))
        if base is None:
            continue
        advance, cell, squeeze, top, bottom, boost, bug_dx = fit(ch, base)
        mino_cell = max(cell, mino_floor)
        count = VARIANTS if ch in KANA else 1  # かなだけ複数。漢字・英数字・記号は1種類
        add_variants(base + ".mino", lambda v: glyph_combined(glyph_set, base, f"{seed}-{ch}{v}", nib, rough, mino_cell, squeeze, top, bottom, mid, max(cell, bubble_floor), boost, typical_size, bug_dx), mino_cell, count)
        add_variants(base + ".struck", lambda v: glyph_struck(glyph_set, base, f"{seed}-{ch}-x{v}", nib, rough, cell, advance, squeeze, top, bottom, bug_dx), cell, count)
        pending_bubbles.append((base, ch, boost, count))
        # 幅ゼロの吹き出しは「字送り bug_cell・高さ box_top の虫」の上に描いてある。実際の字との差を記録する
        nudge[base] = (round((bug_cell - advance) / 2), 0)
        for name in variant_names(base + ".struck", count):
            nudge[name] = (round((bug_cell - cell) / 2 + bug_dx), round(top - box_top))
        struck[base] = base + ".struck"
        combined[base] = base + ".mino"
        bubble[base] = base + ".bubble"
        liga[(base, mark, mark)] = base + ".struck"
        liga[(base, mark, circle)] = base + ".bubble"
        # 元のフォントが縦用の字形を持つ字(かっこ、句読点など)からも、横書きと同じ字形を出す
        other = vert_map.get(base, base)
        liga[(other, mark, mark)] = base + ".struck"
        liga[(other, mark, circle)] = base + ".bubble"
        if ch in SYMBOLS:  # ○ ● は発動用の記号でもあるので、縦用の写しは作らない(横書きと同じ字形を出す)
            pre_sources += [(name, side_shift(name, bug_dx)) for name in variant_names(base + ".struck", count)]
            continue
        # ---- 縦書き ----
        # 縦書きでは元のフォントの vert が先に効いて、小書きの字や長音が縦用の字形に替わる。
        # 縦用の字形からも同じ合字・スタイルセットが出るようにし、縦用の字形に重ねた虫を作る
        vbase, vstruck, vdraw = vert_map.get(base), base + ".struck", base
        vfit = (cell, squeeze, top, bottom, boost, bug_dx)
        if vbase:
            vadvance, *vfit = fit(ch, vbase, vertical=True)
            vcell, vsqueeze, vtop, vbottom, vboost, vdx = vfit
            add_variants(vbase + ".struck", lambda v: glyph_struck(glyph_set, vbase, f"{seed}-{ch}-vx{v}", nib, rough, vcell, vadvance, vsqueeze, vtop, vbottom, vdx), vcell, count)
            vstruck, vdraw = vbase + ".struck", vbase
            vertical_bugs += variant_names(vstruck, count)
            pre_sources += [(name, side_shift(name, vdx)) for name in variant_names(vstruck, count)]
        else:
            vbase, vstruck = entry[base], base + ".struck.vert"  # 形は横書きの虫と同じ。あとで写しを作る
            vertical_twins.append((base + ".struck", vstruck, count))
            pre_sources += [(name, side_shift(source, bug_dx))
                            for name, source in zip(variant_names(vstruck, count), variant_names(base + ".struck", count))]
        struck[vbase] = vstruck
        combined[vbase] = base + ".mino.vert"
        bubble[vbase] = base + ".bubble.vert"
        liga[(vbase, mark, mark)] = vstruck
        liga[(vbase, mark, circle)] = base + ".bubble.vert"
        pending_vertical.append((base, ch, count, vdraw, vfit))
    # 縦書き用の「虫 + 右吹き出し」。虫の仲間なので、ほかの虫の字形と続けて並べる(下の注を参照)
    for base, ch, count, char_name, (vcell, vsqueeze, vtop, vbottom, vboost, vdx) in pending_vertical:
        add_variants(base + ".mino.vert", lambda v: glyph_combined_vertical(glyph_set, char_name, f"{seed}-{ch}-vm{v}", nib, rough, vcell, vsqueeze, vtop, vbottom, mid, bubble_floor, vboost, typical_size, vdx), vcell, count)
        vertical_bugs += variant_names(base + ".mino.vert", count)
    # ---- 漢字 ----
    # 漢字は数千字あるので、1字ずつ描くと字形数の上限(65,535)もファイルサイズも超える。
    # 虫と吹き出しの枠を何種類か描いておき、漢字ごとの字形は「元の漢字 + 部品」を参照するだけにする。
    # 吹き出しの中の漢字の大きさと位置は、1字ずつ合わせる(下の「漢字の吹き出し」)
    kanji = [code for code in sorted(cmap) if is_kanji(code) and chr(code) not in CHARS
             and getattr(glyf[cmap[code]], "numberOfContours", 0) != 0]
    kbugs, kframes, kvframes, frame_info = [], [], [], {}
    if kanji:
        for n in range(KANJI_BUGS):
            name = f"mino.kbug.{n + 1}"
            # 漢字はかなより字面が大きいので、虫の幅を広げる(高さは変えない。目の高さが変わると吹き出しがずれる)
            add(name, glyph_struck(glyph_set, None, f"{seed}-kbug{n}", nib, rough, 1000, 1000, bug_squeeze(KANJI_BUG_CELL, nib), box_top, box_bottom), 1000)
            eye_info[name] = draw_bug.last
            kbugs.append(name)
    # 吹き出しの字形は最後にまとめて並べる。順送りの規則は「虫以外」「吹き出し以外」の字形の一覧を
    # 何百回も参照するので、虫と吹き出しが字形の並びの中で混ざっていると一覧が細切れになり、
    # HarfBuzz の検査の上限を超えて機能全体が無効になる(小さいフォントほど上限が低い)
    for base, ch, boost, count in pending_bubbles:
        add_variants(base + ".bubble", lambda v: glyph_bubble(glyph_set, base, f"{seed}-{ch}-o{v}", nib, rough, bug_cell, box_top, mid, boost, bubble_floor, typical_size), 0, count, bubble_cycle)
    # 縦書き用の、虫の右に出す幅ゼロの吹き出し
    vertical_bubbles = []
    for base, ch, count, char_name, (vcell, vsqueeze, vtop, vbottom, vboost, vdx) in pending_vertical:
        add_variants(base + ".bubble.vert", lambda v: glyph_bubble_vertical(glyph_set, char_name, f"{seed}-{ch}-vo{v}", nib, rough, bug_cell, box_top, mid, vboost, bubble_floor, typical_size), 0, count, bubble_cycle)
        vertical_bubbles += variant_names(base + ".bubble.vert", count)
    liga[(blot, mark, mark)] = "mino.bug"  # ●✕✕ は「●に虫」ではなく虫だけにする
    if kanji:
        for n in range(KANJI_FRAMES):
            for vertical, names in ((False, kframes), (True, kvframes)):
                name = f"mino.kframe{'.vert' if vertical else ''}.{n + 1}"
                glyph, frame_info[name] = glyph_frame(glyph_set, f"{seed}-kframe{'v' if vertical else ''}{n}", nib, rough,
                                                      KANJI_BUG_CELL if vertical else bug_cell, box_top, mid, bubble_floor, vertical)
                add(name, glyph, 0)
                names.append(name)
    font["maxp"].numGlyphs = len(font.getGlyphOrder())

    # 輪郭の統合: 重ねて描いた多角形をつなげて外周だけにする(点数が減り、重なりによる表示崩れも防ぐ)
    raw_points = sum(len(glyf[n].coordinates) for n in added)
    removeOverlaps(font, glyphNames=added)
    for name in added:
        glyf[name].recalcBounds(glyf)
        hmtx[name] = (hmtx[name][0], getattr(glyf[name], "xMin", 0))

    # 縦書きの字送り。虫は目が上に出るぶん 1000 より長くし、どの虫も目の高さが同じ位置に来るようにする。
    # 縦書きでは字形の「上端 + 上の余白」が字送りの始まりに来る。右吹き出しは直前の虫と同じ座標で描いてあるので、
    # 虫の字送りの終わり(= 吹き出しの位置)がその座標のどこに当たるかから、上の余白を逆算する
    vmtx = font["vmtx"]
    origin = round(nominal_eye_top(nib, box_top) + 20)
    v_advance = origin - round(box_bottom - 100)
    def compose(name, parts, advance):
        """ほかの字形を参照するだけの字形。parts は (字形名, x, y, 倍率) の並び。"""
        pen = TTGlyphPen({part[0]: None for part in parts})
        for part, x, y, scale in parts:
            pen.addComponent(part, (scale, 0, 0, scale, round(x), round(y)))
        glyph = pen.glyph()
        glyph.components[0].flags |= 0x0400  # 部品どうしが重なる(OVERLAP_COMPOUND)
        glyf[name] = glyph
        glyph.recalcBounds(glyf)
        hmtx[name], vmtx[name] = (advance, glyph.xMin), (1000, 0)

    # 漢字の虫(元の漢字 + 使い回しの虫)と、縦書きの入口になる写し
    # ss02: 横書きは虫+吹き出しを1字形にまとめる(Illustrator は、1字を2字形に分ける置き換えを ss で当てない)。
    # 縦書きは字形数が足りないので「虫」と「吹き出し」の2字形に分ける
    multi = {}
    for code in kanji:
        base, bug = cmap[code], kbugs[code % KANJI_BUGS]
        advance = hmtx[base][0]
        hit, twin_name = base + ".struck", base + ".vert"
        compose(hit, [(base, 0, 0, 1), (bug, (advance - 1000) / 2, 0, 1)], advance)
        vmtx[hit] = (v_advance, origin - glyf[hit].yMax)
        compose(twin_name, [(base, 0, 0, 1)], advance)
        vmtx[twin_name] = vmtx[base]
        entry[base] = twin_name
        nudge[base] = nudge[hit] = (round((bug_cell - advance) / 2), 0)
        pre_sources.append((hit, side_shift(bug, 0)))
        struck[base] = struck[twin_name] = hit
        bubble[base], bubble[twin_name] = base + ".bubble", base + ".bubble.vert"
        liga[(base, mark, mark)] = liga[(twin_name, mark, mark)] = hit
        liga[(base, mark, circle)], liga[(twin_name, mark, circle)] = base + ".bubble", base + ".bubble.vert"
        multi[twin_name] = [hit + ".pre", base + ".bubble.vert"]
        combined[base] = base + ".mino"

    # Safari は縦書きの字送りに、置き換えたあとの字形の「横の字送り」を使う。縦書きでしか出ない虫には、
    # 縦の字送りと同じ横の字送りを持たせる(縦書きでは字形が横の字送りの中央に置かれるので、輪郭も中央へずらす)。
    # 横書きと形が同じ虫は、そのための写しを作る
    for source, target, count in vertical_twins:
        names = variant_names(target, count)
        for n, (old, new) in enumerate(zip(variant_names(source, count), names)):
            glyf[new] = copy.deepcopy(glyf[old])
            hmtx[new] = hmtx[old]
            bug_cycle[0][n].add(new)
            if n:
                bug_cycle[1][n - 1][names[0]] = new
        vertical_bugs += names
    # Illustrator は縦書きで、字送りの始点より大きく上に出た部分を切り落とす。右吹き出しは目の高さから上へ
    # はみ出すので、吹き出しの付く字形だけ始点を rise だけ上に取り(字送りも rise だけ長くする)、
    # はみ出しを VERTICAL_OVERHANG までに収める
    tall = [name for name in vertical_bugs if ".mino.vert" in name]
    # 虫の大きさ・位置に合わせて吹き出しをずらす量(LOW_STEP 刻み)。上へずらすぶんも、はみ出しに数える
    snap = lambda value, step: round(value / step) * step
    side_of = {name + ".pre": (snap(dx, SIDE_STEP), snap(dy, SIDE_STEP_Y)) for name, (dx, dy) in pre_sources}
    if kanji:
        usage = collections.Counter(side_of.values())
        kept = [(0, 0)] + [shift for shift, _ in usage.most_common() if shift != (0, 0)][:SIDE_KEEP]
        side_of = {name: min(kept, key=lambda k: math.hypot(k[0] - shift[0], k[1] - shift[1])) for name, shift in side_of.items()}
    lift = max(0, max(dy for dx, dy in side_of.values()))
    rise = max(0, round(max(glyf[name].yMax for name in tall + vertical_bubbles + kvframes) + lift - origin - VERTICAL_OVERHANG))
    side_advance = v_advance + rise
    for name in vertical_bugs:
        advance = side_advance if name in tall else v_advance
        shift = round((advance - hmtx[name][0]) / 2)
        glyf[name].coordinates.translate((shift, 0))
        glyf[name].recalcBounds(glyf)
        hmtx[name] = (advance, glyf[name].xMin)
    for name in set().union(*bug_cycle[0]):
        vmtx[name] = (v_advance, origin - glyf[name].yMax)
    for name in tall:
        vmtx[name] = (side_advance, origin + rise - glyf[name].yMax)
    # 右吹き出しは、直前の虫と同じ始点から描く。虫のあとに置いて上へ戻して描くと、Illustrator は
    # 字送りの始点より上にはみ出した字形を切り落とすので、吹き出しが消える。
    # そこで、直後に右吹き出しが来る虫を「字送りゼロの写し(.pre)」に替え、字送りは吹き出しのほうに持たせる
    for name in vertical_bubbles:
        glyf[name].coordinates.translate((round(side_advance / 2), 0))
        glyf[name].recalcBounds(glyf)
        hmtx[name] = (side_advance, glyf[name].xMin)
        vmtx[name] = (side_advance, origin + rise - glyf[name].yMax)
    pre, pre_shift = {}, {}
    for name, shift in pre_sources:
        new = name + ".pre"
        if glyf[name].isComposite():  # 漢字の虫
            compose(new, [(name, -round(hmtx[name][0] / 2), 0, 1)], 0)
        else:
            glyf[new] = copy.deepcopy(glyf[name])
            glyf[new].coordinates.translate((-round(hmtx[name][0] / 2), 0))
            glyf[new].recalcBounds(glyf)
        hmtx[new] = (0, glyf[new].xMin)
        vmtx[new] = (0, vmtx[name][1] + rise)
        pre[name], pre_shift[new] = new, shift
    # 縦書き: 虫の大きさ・位置に合わせてずらした右吹き出し。Illustrator は既定の設定では位置合わせ(GPOS)を
    # 読まないので、横書きと同じく字形の置き換えで合わせる。ずらした吹き出しは、元の吹き出しを参照するだけの字形
    shifted = {shift: {} for shift in sorted(set(side_of.values()) - {(0, 0)})}
    for index, ((dx, dy), table) in enumerate(shifted.items()):
        for name in vertical_bubbles:
            pen = TTGlyphPen({name: None})
            pen.addComponent(name, (1, 0, 0, 1, dx, dy))
            new = f"{name}.s{index + 1}"
            glyf[new] = pen.glyph()
            glyf[new].recalcBounds(glyf)
            hmtx[new] = (hmtx[name][0], glyf[new].xMin)
            vmtx[new] = (vmtx[name][0], vmtx[name][1] - dy)
            table[name] = new
    # 漢字の吹き出し(枠の部品 + 縮小した漢字)。中の字の大きさと位置は、かなと同じ決め方で1字ずつ合わせる。
    # 縮小した線は太らせない(太らせるには1字ずつ描く必要がある)
    kanji_bubbles, kanji_side, kanji_whole = [], [], []
    for code in kanji:
        base = cmap[code]
        shape = glyf[base]
        width, height, middle = shape.xMax - shape.xMin, shape.yMax - shape.yMin, (shape.yMin + shape.yMax) / 2
        for vertical in (False, True):
            frame = (kvframes if vertical else kframes)[(code // KANJI_BUGS) % KANJI_FRAMES]
            cx, cy, rx, ry, line, fit = frame_info[frame]
            scale = max(CHAR_SCALE * fit ** 0.75, CHAR_FILL * (2 * (370 + line * 0.5) * fit - line) / typical_size)
            anchor = middle if vertical else (middle + mid) / 2
            inner_x, inner_y = rx - line / 2 - CHAR_CLEARANCE, ry - line / 2 - CHAR_CLEARANCE
            scale = min(scale, 1 / math.hypot(width / 2 / inner_x, (height / 2 + abs(middle - anchor)) / inner_y))
            shift = side_advance / 2 if vertical else 0
            name = base + (".bubble.vert" if vertical else ".bubble")
            compose(name, [(frame, shift, 0, 1), (base, cx + shift - scale * (shape.xMin + shape.xMax) / 2, cy - scale * anchor, scale)],
                    side_advance if vertical else 0)
            if vertical:
                vmtx[name] = (side_advance, origin + rise - glyf[name].yMax)
            else:
                kanji_whole.append((code, base, frame, cx - scale * (shape.xMin + shape.xMax) / 2, cy - scale * anchor, scale))
            (kanji_side if vertical else kanji_bubbles).append(name)
    # ss02 用の、虫と吹き出しを1つにまとめた字形(横書き)。吹き出しは、虫のすぐあとに置いたときと同じ位置。
    # 吹き出しの字形が字形順で続くよう、あとからまとめて作る
    for code, base, frame, x, y, scale in kanji_whole:
        advance, hit = hmtx[base][0], base + ".struck"
        at = advance + nudge[hit][0]
        compose(base + ".mino", [(base, 0, 0, 1), (kbugs[code % KANJI_BUGS], (advance - 1000) / 2, 0, 1), (frame, at, 0, 1), (base, at + x, y, scale)], advance)
        vmtx[base + ".mino"] = vmtx[hit]
        nudge[base + ".mino"] = nudge[hit]
    # 横書き: 小さい虫(小書きの字、英数字など)のあとの吹き出しは、虫の高さに合わせて下げる。
    # Illustrator は横書きで位置合わせ(GPOS)を読まないので、高さは字形の置き換えで合わせる。
    # 下げた吹き出しは、元の吹き出しを参照するだけの字形(LOW_STEP 刻み)
    order = font.getReverseGlyphMap(rebuild=True)
    flat_bubbles = sorted(set().union(*bubble_cycle[0]) - set(vertical_bubbles), key=order.get)
    drop_of = {name: round(dy / LOW_STEP) * LOW_STEP for name, (dx, dy) in nudge.items()}
    lowered = {drop: {} for drop in sorted(set(drop_of.values()) - {0})}
    for drop, table in lowered.items():
        for name in flat_bubbles:
            pen = TTGlyphPen({name: None})
            pen.addComponent(name, (1, 0, 0, 1, 0, drop))
            new = f"{name}.{'d' if drop < 0 else 'u'}{abs(drop)}"
            glyf[new] = pen.glyph()
            glyf[new].recalcBounds(glyf)
            hmtx[new], vmtx[new] = (0, glyf[new].xMin), vmtx[name]
            table[name] = new
    font["maxp"].numGlyphs = len(font.getGlyphOrder())

    gsub = font["GSUB"].table

    def add_lookup(subtables):
        gsub.LookupList.Lookup.append(otl.buildLookup(subtables))
        gsub.LookupList.LookupCount = len(gsub.LookupList.Lookup)
        return gsub.LookupList.LookupCount - 1

    # 縦書きの入口(かなを縦用の写しへ)。合字より先に効かせるので、最初に足す
    if entry:  # かな全部に縦用の字形がある書体(Yusei Magic)では要らない
        entry_lookup = add_lookup([otl.buildSingleSubstSubtable(entry)])
        for tag in ("vert", "vrt2"):
            add_feature(gsub, tag, entry_lookup)

    if kanji:
        spread = {**entry, **carriers}
        order_now = font.getReverseGlyphMap(rebuild=True)
        upright = otl.buildCoverage(set(entry.values()) | set(vert_map.values()) | set(carriers.values()), order_now)
        targets = otl.buildCoverage(set(spread), order_now)
        swap = add_lookup([otl.buildSingleSubstSubtable(spread)])
        forward = ot.ChainContextSubst()
        forward.Format = 3
        forward.BacktrackCoverage, forward.BacktrackGlyphCount = [upright], 1
        forward.InputCoverage, forward.InputGlyphCount = [targets], 1
        forward.LookAheadCoverage, forward.LookAheadGlyphCount = [], 0
        record = ot.SubstLookupRecord()
        record.SequenceIndex, record.LookupListIndex = 0, swap
        forward.SubstLookupRecord, forward.SubstCount = [record], 1
        # 後ろにあるかな・句読点からも伝える。右から左へたどる規則(逆順の文脈置換)は Illustrator が読めず、
        # 合字ごと無効になるので使わない。「SPREAD_REACH 字形先までに縦用の字形がある」規則を並べる
        between = otl.buildCoverage(set(spread) | set(upright.glyphs), order_now)
        backward = []
        for gap in range(SPREAD_REACH):
            rule = ot.ChainContextSubst()
            rule.Format = 3
            rule.BacktrackCoverage, rule.BacktrackGlyphCount = [], 0
            rule.InputCoverage, rule.InputGlyphCount = [targets], 1
            rule.LookAheadCoverage, rule.LookAheadGlyphCount = [between] * gap + [upright], gap + 1
            record = ot.SubstLookupRecord()
            record.SequenceIndex, record.LookupListIndex = 0, swap
            rule.SubstLookupRecord, rule.SubstCount = [record], 1
            backward.append(rule)
        for subtable in ([forward], backward, [otl.buildSingleSubstSubtable({v: k for k, v in carriers.items()})]):
            add_feature(gsub, "liga", add_lookup(subtable))

    def pieces(table, first, size):
        """大きな表を、1つ 64KB の枠に収まるよう先頭の字形ごとに分ける。"""
        keys = sorted({first(key) for key in table})
        for start in range(0, len(keys), size):
            chunk = set(keys[start:start + size])
            yield {key: value for key, value in table.items() if first(key) in chunk}

    ligature_tables = [otl.buildLigatureSubstSubtable(piece) for piece in pieces(liga, lambda key: key[0], 1200)]
    for tag, subtables in (("liga", ligature_tables),
                           ("ss01", [otl.buildSingleSubstSubtable(struck)]),
                           ("ss02", [otl.buildSingleSubstSubtable(combined)]),
                           ("ss03", [otl.buildSingleSubstSubtable(bubble)])):
        index = add_lookup(subtables)
        add_feature(gsub, tag, index)
        if tag == "liga":
            # 縦書きでは liga が使われない(HarfBuzz の既定)。縦書きで必ず効く vert にも同じ合字を登録する。
            # Safari は逆に、縦書きでも liga のほうを当てる
            for vertical_tag in ("vert", "vrt2"):
                add_feature(gsub, vertical_tag, index)

    if multi:
        index = add_lookup([otl.buildMultipleSubstSubtable(piece) for piece in pieces(multi, lambda key: key, 3000)])
        add_feature(gsub, "ss02", index)

    # 虫が続くとき形を切り替える。置き換えは左から順に進むので、
    # 「いちばん近い直前の虫が n 番目の形なら、自分は n+1 番目にする」だけで順送りになる。
    # 直前の虫が最後の形なら何もしない(最初の形に戻る)。
    # 吹き出しも同じ仕組みで、直前の吹き出しと違う形にする。
    glyph_map = font.getReverseGlyphMap(rebuild=True)

    def add_cycle(cycle, tags):
        tiers, step = cycle
        members = set().union(*tiers)
        others = otl.buildCoverage(set(glyph_map) - members, glyph_map)
        swaps = [add_lookup([otl.buildSingleSubstSubtable(table)]) for table in step]
        rules = []
        for gap in range(GAP + 1):
            for n, swap in enumerate(swaps):
                rule = ot.ChainContextSubst()
                rule.Format = 3
                rule.BacktrackCoverage = [others] * gap + [otl.buildCoverage(tiers[n], glyph_map)]  # 近い順に並べる
                rule.BacktrackGlyphCount = gap + 1
                rule.InputCoverage = [otl.buildCoverage(set(step[n]), glyph_map)]
                rule.InputGlyphCount = 1
                rule.LookAheadCoverage = []
                rule.LookAheadGlyphCount = 0
                record = ot.SubstLookupRecord()
                record.SequenceIndex, record.LookupListIndex = 0, swap
                rule.SubstLookupRecord = [record]
                rule.SubstCount = 1
                rules.append(rule)
        lookup = add_lookup(rules)
        for tag in tags:
            add_feature(gsub, tag, lookup)

    add_cycle(bug_cycle, ("liga", "ss01", "ss02", "vert", "vrt2"))
    add_cycle(bubble_cycle, ("liga", "ss03", "vert", "vrt2"))

    # 縦書き: 直後に右吹き出しが来る虫を、字送りゼロの写しに替える
    rule = ot.ChainContextSubst()
    rule.Format = 3
    rule.BacktrackCoverage, rule.BacktrackGlyphCount = [], 0
    rule.InputCoverage, rule.InputGlyphCount = [otl.buildCoverage(set(pre), glyph_map)], 1
    rule.LookAheadCoverage, rule.LookAheadGlyphCount = [otl.buildCoverage(set(vertical_bubbles) | set(kanji_side), glyph_map)], 1
    record = ot.SubstLookupRecord()
    record.SequenceIndex, record.LookupListIndex = 0, add_lookup([otl.buildSingleSubstSubtable(pre)])
    rule.SubstLookupRecord, rule.SubstCount = [record], 1
    pre_lookup = add_lookup([rule])
    for tag in ("liga", "vert", "vrt2"):
        add_feature(gsub, tag, pre_lookup)

    # 縦書き: 虫の大きさ・位置に合わせて、ずらした右吹き出しに替える
    rules = []
    for shift, table in shifted.items():
        rule = ot.ChainContextSubst()
        rule.Format = 3
        rule.BacktrackCoverage = [otl.buildCoverage({name for name, value in side_of.items() if value == shift}, glyph_map)]
        rule.BacktrackGlyphCount = 1
        rule.InputCoverage, rule.InputGlyphCount = [otl.buildCoverage(set(table), glyph_map)], 1
        rule.LookAheadCoverage, rule.LookAheadGlyphCount = [], 0
        record = ot.SubstLookupRecord()
        record.SequenceIndex, record.LookupListIndex = 0, add_lookup([otl.buildSingleSubstSubtable(table)])
        rule.SubstLookupRecord, rule.SubstCount = [record], 1
        rules.append(rule)
    if rules:
        side_lookup = add_lookup(rules)
        for tag in ("liga", "vert", "vrt2"):
            add_feature(gsub, tag, side_lookup)

    # 横書き: 小さい虫の直後の吹き出しを、下げた字形に替える
    rules = []
    for drop, table in lowered.items():
        rule = ot.ChainContextSubst()
        rule.Format = 3
        rule.BacktrackCoverage = [otl.buildCoverage({name for name, value in drop_of.items() if value == drop}, glyph_map)]
        rule.BacktrackGlyphCount = 1
        rule.InputCoverage, rule.InputGlyphCount = [otl.buildCoverage(set(table), glyph_map)], 1
        rule.LookAheadCoverage, rule.LookAheadGlyphCount = [], 0
        record = ot.SubstLookupRecord()
        record.SequenceIndex, record.LookupListIndex = 0, add_lookup([otl.buildSingleSubstSubtable(table)])
        rule.SubstLookupRecord, rule.SubstCount = [record], 1
        rules.append(rule)
    if rules:
        low_lookup = add_lookup(rules)
        for tag in ("liga", "vert", "vrt2"):
            add_feature(gsub, tag, low_lookup)

    # 幅ゼロの吹き出しを、直前の字の中央と虫の高さに合わせる(GPOS)。
    # kern は切られることがあるので、常に効く dist に入れる
    if "GPOS" not in font:
        gpos = ot.GPOS()
        gpos.Version = 0x00010000
        gpos.ScriptList, gpos.FeatureList, gpos.LookupList = ot.ScriptList(), ot.FeatureList(), ot.LookupList()
        gpos.ScriptList.ScriptRecord, gpos.FeatureList.FeatureRecord, gpos.LookupList.Lookup = [], [], []
        for script in gsub.ScriptList.ScriptRecord:  # GSUB と同じスクリプトを用意する
            record = ot.ScriptRecord()
            record.ScriptTag, record.Script = script.ScriptTag, ot.Script()
            record.Script.LangSysRecord, record.Script.DefaultLangSys = [], ot.LangSys()
            record.Script.DefaultLangSys.ReqFeatureIndex = 0xFFFF
            record.Script.DefaultLangSys.FeatureIndex, record.Script.DefaultLangSys.LookupOrder = [], None
            gpos.ScriptList.ScriptRecord.append(record)
        font["GPOS"] = newTable("GPOS")
        font["GPOS"].table = gpos
    gpos = font["GPOS"].table
    # 高さは上の字形の置き換えで合わせてあるので、ここでは横と、刻みの端数だけ合わせる
    bubbles = tuple(sorted(flat_bubbles + [new for table in lowered.values() for new in table.values()], key=glyph_map.get))
    groups = {}
    for glyph_name, (dx, dy) in nudge.items():
        shift = (dx, dy - drop_of[glyph_name])
        if shift != (0, 0):
            groups.setdefault(shift, []).append(glyph_name)
    if groups:
        pairs = {(tuple(sorted(names, key=glyph_map.get)), bubbles): (None, otl.buildValue({"XPlacement": dx, "YPlacement": dy}))
                 for (dx, dy), names in groups.items()}
        gpos.LookupList.Lookup.append(otl.buildLookup([otl.buildPairPosClassesSubtable(pairs, glyph_map)]))
        gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)
        add_feature(gpos, "dist", gpos.LookupList.LookupCount - 1)
        # Illustrator は dist を使わないので kern にも登録する(同じルックアップは1回しか適用されない)
        add_feature(gpos, "kern", gpos.LookupList.LookupCount - 1)
    def add_pairs(table, targets, tags):
        """targets(吹き出し)が table の字形の直後に来たとき、その量だけずらす。"""
        groups = {}
        for glyph_name, shift in table.items():
            if shift != (0, 0):
                groups.setdefault(shift, []).append(glyph_name)
        if groups and targets:
            second = tuple(sorted(targets, key=glyph_map.get))
            pairs = {(tuple(sorted(names, key=glyph_map.get)), second): (None, otl.buildValue({"XPlacement": dx, "YPlacement": dy}))
                     for (dx, dy), names in groups.items()}
            gpos.LookupList.Lookup.append(otl.buildLookup([otl.buildPairPosClassesSubtable(pairs, glyph_map)]))
            gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)
            for tag in tags:
                add_feature(gpos, tag, gpos.LookupList.LookupCount - 1)

    # 漢字の吹き出しには、下げた字形・ずらした字形を用意していない(字形数が足りない)。位置合わせだけで寄せる
    add_pairs(nudge, kanji_bubbles, ("dist", "kern"))
    add_pairs(pre_shift, kanji_side, ("dist", "vkrn", "mark"))
    # 縦書きの右吹き出しも、直前の虫の大きさと位置に合わせてずらす(小さい虫では左下へ寄せる)
    groups = {}
    for glyph_name, (dx, dy) in pre_shift.items():  # 字形の置き換えで合わせた残り(刻みの端数)だけ
        shift = (dx - side_of[glyph_name][0], dy - side_of[glyph_name][1])
        if shift != (0, 0):
            groups.setdefault(shift, []).append(glyph_name)
    if groups:
        side = tuple(sorted(vertical_bubbles + [new for table in shifted.values() for new in table.values()], key=glyph_map.get))
        pairs = {(tuple(sorted(names, key=glyph_map.get)), side): (None, otl.buildValue({"XPlacement": dx, "YPlacement": dy}))
                 for (dx, dy), names in groups.items()}
        gpos.LookupList.Lookup.append(otl.buildLookup([otl.buildPairPosClassesSubtable(pairs, glyph_map)]))
        gpos.LookupList.LookupCount = len(gpos.LookupList.Lookup)
        add_feature(gpos, "dist", gpos.LookupList.LookupCount - 1)
        add_feature(gpos, "vkrn", gpos.LookupList.LookupCount - 1)  # Illustrator の縦書きはこちらを使う
        # HarfBuzz は縦書きで dist も vkrn も使わない。縦書きでも必ず使う mark にも登録する
        add_feature(gpos, "mark", gpos.LookupList.LookupCount - 1)

    # OFL に従い、元フォントとは別の名前にする。日本語名も併せて登録する
    psname = family.replace(" ", "") + "-Regular"
    name = font["name"]
    # 著作権表示(0)とデザイナー(9、12)は元のまま残す。改変したことは説明(10)に書く。
    # 製造元(8)はこのファイルを作った側にし、元の製造元の URL(11)は外す
    name.names = [rec for rec in name.names if rec.langID == 0x409 and rec.nameID not in (8, 11)]
    for rec in name.names:
        if rec.nameID in (1, 16):
            rec.string = family
        elif rec.nameID == 4:
            rec.string = family + " Regular"
        elif rec.nameID == 6:
            rec.string = psname
        elif rec.nameID == 3:
            rec.string = f"{VERSION};{VENDOR_ID};{psname}"
        elif rec.nameID == 5:
            rec.string = f"Version {VERSION}"
    name.setName(f"Based on {based_on} (SIL OFL 1.1). Adds kakisonji-minomushi glyphs.", 10, 3, 1, 0x409)
    name.setName(MANUFACTURER, 8, 3, 1, 0x409)
    name.setName(ja, 1, 3, 1, 0x411)
    name.setName(ja, 4, 3, 1, 0x411)

    font["head"].fontRevision = float(VERSION)  # name テーブルのバージョン表記と揃える
    font["OS/2"].achVendID = VENDOR_ID
    font["OS/2"].recalcAvgCharWidth(font)  # 字形を足したぶん平均字幅を計算し直す

    OUT_DIR.mkdir(exist_ok=True)
    font.save(OUT_DIR / f"{psname}.ttf")
    points = [len(glyf[n].coordinates) for n in added]
    return (f"字形数 {len(font.getGlyphOrder())}、漢字 {len(kanji)} 字、縦のずらし {len(shifted)} 通り、" +
            f"{psname}.ttf: 虫の上下 {box_top}〜{box_bottom}、追加 {len(added)} 字形、点数 統合前 {raw_points} → 統合後 {sum(points)}"
            f"(1字形あたり平均 {sum(points) // len(points)}、最大 {max(points)})")


def build_one(base):
    return build(**base)


if __name__ == "__main__":
    import sys
    targets = [base for base in BASES if not sys.argv[1:] or base["family"].split()[-1] in sys.argv[1:]]  # 例: build_font.py Gokuboso
    with multiprocessing.Pool(len(targets)) as pool:
        for line in pool.imap(build_one, targets):
            print(line, flush=True)
