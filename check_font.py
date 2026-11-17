#!/usr/bin/env python3
"""ベースのフォントと dist のフォントを照合し、元の内容が変わっていないことを確かめる。

  - 元からある全グリフの輪郭・字幅が一致する
  - 元の文字コード割り当てがすべて残っている(追加だけ)
  - 元の GSUB のルックアップと機能が残っている(追加だけ)
  - 元の GPOS のルックアップと機能が残っている(追加だけ)
  - 触っていないテーブルがバイト単位で一致する

あわせて、追加した機能が実際に効くことを hb-shape で確かめる(元の内容が無事でも、
機能テーブルが HarfBuzz の検査に落ちると合字もスタイルセットも全部効かなくなる)。
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fontTools.misc.testTools import getXML
from fontTools.ttLib import TTFont

from build_font import BASES, OUT_DIR, ROOT

# ビルドで書き換わるのが正しいテーブル。個別に中身を照合する
REBUILT = {"glyf", "loca", "hmtx", "vmtx", "cmap", "GSUB", "GPOS", "name", "maxp", "head", "hhea", "vhea", "post", "OS/2", "GlyphOrder"}


def check(file, family, **_):
    base = TTFont(ROOT / "base" / f"{file}.ttf")
    out = TTFont(OUT_DIR / f"{family.replace(' ', '')}-Regular.ttf")
    problems = []
    base_order, out_order = base.getGlyphOrder(), out.getGlyphOrder()

    if out_order[:len(base_order)] != base_order:
        problems.append("元のグリフの並び順が変わっている")

    for table, label in (("glyf", "輪郭"), ("hmtx", "横の字幅"), ("vmtx", "縦の字幅")):
        if table not in base:
            continue
        if table == "glyf":
            diff = [g for g in base_order if base["glyf"][g] != out["glyf"][g]]
        else:
            diff = [g for g in base_order if base[table][g] != out[table][g]]
        if diff:
            problems.append(f"{label}が変わったグリフ {len(diff)} 個: {diff[:8]}")

    for b, o in zip(base["cmap"].tables, out["cmap"].tables):
        changed = {hex(u) for u, g in b.cmap.items() if o.cmap.get(u) != g}
        if changed:
            problems.append(f"文字コードの割り当てが変わった: {sorted(changed)[:8]}")
    base_map, out_map = base.getBestCmap(), out.getBestCmap()
    added_codes = sorted(set(out_map) - set(base_map))

    def dump(lookup, font):
        return getXML(lookup.toXML, font)

    def features(t):
        return {(r.FeatureTag, tuple(r.Feature.LookupListIndex)) for r in t.FeatureList.FeatureRecord}

    added_features = {}
    for table in ("GSUB", "GPOS"):
        if table not in base:
            if table in out:
                added_features[table] = sorted({t for t, _ in features(out[table].table)})
            continue
        bg, og = base[table].table, out[table].table
        n = len(bg.LookupList.Lookup)
        changed_lookups = [i for i in range(n) if dump(bg.LookupList.Lookup[i], base) != dump(og.LookupList.Lookup[i], out)]
        if changed_lookups:
            problems.append(f"元の {table} ルックアップが変わった: {changed_lookups[:8]}")
        for tag, lookups in features(bg):
            if not any(t == tag and set(lookups) <= set(l) for t, l in features(og)):
                problems.append(f"元の {table} の機能 {tag} が失われた")
        added_features[table] = sorted({t for t, _ in features(og)} - {t for t, _ in features(bg)})

    for tag in base.keys():
        if tag in REBUILT:
            continue
        if tag not in out or base.reader[tag] != out.reader[tag]:
            problems.append(f"テーブル {tag} が変わった")
    # OS/2 はベンダー ID と平均字幅だけ書き換える。ほかの項目は元のまま
    for field, value in vars(base["OS/2"]).items():
        if field not in ("achVendID", "xAvgCharWidth") and vars(out["OS/2"]).get(field) != value and field != "panose":
            problems.append(f"OS/2.{field} が変わった")
    if vars(base["OS/2"].panose) != vars(out["OS/2"].panose):
        problems.append("OS/2.panose が変わった")
    for tag, fields in (("hhea", ("ascent", "descent", "lineGap")),
                        ("head", ("unitsPerEm",)),
                        ("post", ("underlinePosition", "underlineThickness", "isFixedPitch"))):
        for field in fields:
            if getattr(base[tag], field) != getattr(out[tag], field):
                problems.append(f"{tag}.{field} が変わった")

    print(f"{family}: 元のグリフ {len(base_order)} 個を照合、追加グリフ {len(out_order) - len(base_order)} 個、"
          f"追加した文字コード {[hex(c) for c in added_codes]}、追加した機能 {added_features}、ベンダー ID {out['OS/2'].achVendID!r}")
    for line in problems:
        print("  NG:", line)
    if not problems:
        print("  OK: 元の内容は変わっていない")
    behaviour = check_behaviour(out, OUT_DIR / f"{family.replace(' ', '')}-Regular.ttf")
    for line in behaviour:
        print("  NG:", line)
    if not behaviour:
        print("  OK: 合字・スタイルセット・順送り・吹き出しの位置が効いている")
    return not problems and not behaviour


def apply_horizontal(font, glyphs, feature):
    """字形の並びに、liga(と指定の ss)のルックアップだけを順に当てる。置き換えと合字のみ対応。"""
    gsub = font["GSUB"].table
    tags = {"liga", feature} - {""}
    indices = sorted({i for r in gsub.FeatureList.FeatureRecord if r.FeatureTag in tags for i in r.Feature.LookupListIndex})
    for index in indices:
        for subtable in gsub.LookupList.Lookup[index].SubTable:
            subtable = getattr(subtable, "ExtSubTable", subtable)  # 大きな表は拡張形式に包まれる
            if hasattr(subtable, "mapping"):
                glyphs = [subtable.mapping.get(name, name) for name in glyphs]
            elif type(subtable).__name__ == "ChainContextSubst" and subtable.Format == 3 and subtable.InputGlyphCount == 1:
                # 前後の字形を見て1字形を替える規則。左から順に、替えた結果を次の判定に使う
                swaps = [gsub.LookupList.Lookup[r.LookupListIndex].SubTable[0] for r in subtable.SubstLookupRecord]
                swaps = [getattr(getattr(t, "ExtSubTable", t), "mapping", {}) for t in swaps]
                back = [set(c.glyphs) for c in subtable.BacktrackCoverage]
                ahead = [set(c.glyphs) for c in subtable.LookAheadCoverage]
                glyphs = list(glyphs)
                for i, name in enumerate(glyphs):
                    if (name in subtable.InputCoverage[0].glyphs and i >= len(back) and i + len(ahead) < len(glyphs)
                            and all(glyphs[i - 1 - n] in c for n, c in enumerate(back))
                            and all(glyphs[i + 1 + n] in c for n, c in enumerate(ahead))):
                        for mapping in swaps:
                            glyphs[i] = mapping.get(glyphs[i], glyphs[i])
            elif type(subtable).__name__ == "ReverseChainSingleSubst":
                # 右から順にたどる規則
                table = dict(zip(subtable.Coverage.glyphs, subtable.Substitute))
                ahead = [set(c.glyphs) for c in subtable.LookAheadCoverage]
                glyphs = list(glyphs)
                for i in range(len(glyphs) - 1, -1, -1):
                    if glyphs[i] in table and i + len(ahead) < len(glyphs) and all(glyphs[i + 1 + n] in c for n, c in enumerate(ahead)):
                        glyphs[i] = table[glyphs[i]]
            elif hasattr(subtable, "ligatures"):
                out, i = [], 0
                while i < len(glyphs):
                    for lig in subtable.ligatures.get(glyphs[i], []):
                        if glyphs[i + 1:i + 1 + len(lig.Component)] == lig.Component:
                            out.append(lig.LigGlyph)
                            i += 1 + len(lig.Component)
                            break
                    else:
                        out.append(glyphs[i])
                        i += 1
                glyphs = out
    return glyphs


def shape(path, text, features="", direction=""):
    """hb-shape の結果を [(字形名, 横のずれ, 縦のずれ, 字送り)] で返す。"""
    args = ["hb-shape", "--no-clusters", "-u", ",".join(f"{ord(c):X}" for c in text)]
    if features:
        args.append(f"--features={features}")
    if direction:
        args.append(f"--direction={direction}")
    out = subprocess.run([*args, str(path)], capture_output=True, text=True, check=True).stdout.strip()
    glyphs = []
    for item in out.strip("[]").split("|"):
        m = re.fullmatch(r"([^@+]+)(?:@(-?\d+),(-?\d+))?(?:\+(-?\d+)(?:,-?\d+)?)?", item)
        glyphs.append((m[1], int(m[2] or 0), int(m[3] or 0), int(m[4] or 0)))
    return glyphs


def check_behaviour(font, path):
    """追加した機能が実際に効くか。"""
    cmap, glyf = font.getBestCmap(), font["glyf"]
    g = lambda ch: cmap[ord(ch)]
    # 小さい虫のあとの吹き出しは、下げた字形(.d300 など)に替わる。字の照合では区別しない
    level = lambda name: re.sub(r"\.([du]|s)\d+$", "", name)
    names = lambda text, features="": [level(name) for name, *_ in shape(path, text, features)]
    problems = []

    def expect(label, got, want):
        if got != want:
            problems.append(f"{label}: {got}(期待 {want})")

    expect("合字", names("て✕✕で✕○"), [g("て") + ".struck", g("で") + ".bubble"])
    expect("虫だけ", names("●✕✕"), ["mino.bug"])
    expect("記号はそのまま", names("×○●✕"), [g("×"), g("○"), g("●"), g("✕")])
    expect("虫の順送り", names("の✕✕" * 4), [g("の") + s for s in (".struck", ".struck.v2", ".struck.v3", ".struck")])
    expect("吹き出しの順送り", names("あ✕✕の✕○" * 4)[1::2], [g("の") + s for s in (".bubble", ".bubble.v2", ".bubble.v3", ".bubble")])
    expect("英数字・記号", names("a✕✕B✕○1✕✕。✕✕?✕○"), [g("a") + ".struck", g("B") + ".bubble", g("1") + ".struck", g("。") + ".struck", g("?") + ".bubble"])
    if ord("Ｂ") in cmap:  # 全角英数字はかなのみの書体には無い
        expect("全角英数字", names("Ｂ✕✕１✕○"), [g("Ｂ") + ".struck", g("１") + ".bubble"])
    expect("ss01", names("ああ", "ss01"), [g("あ") + ".struck", g("あ") + ".struck.v2"])
    expect("ss02", names("ああ", "ss02"), [g("あ") + ".mino", g("あ") + ".mino.v2"])
    expect("ss03", names("ああ", "ss03"), [g("あ") + ".bubble", g("あ") + ".bubble.v2"])
    # 縦書き: 合字が効き、吹き出しが右に出す字形に替わり、順送りも進む
    vertical = [name for name, *_ in shape(path, "て✕✕で✕○て✕✕で✕○", "", "ttb")]
    expect("縦書きの合字", [level(n).replace(".vert", "").replace(".pre", "") for n in vertical],
           [g("て") + ".struck", g("で") + ".bubble", g("て") + ".struck.v2", g("で") + ".bubble.v2"])
    if not vertical[0].endswith(".pre"):
        problems.append(f"縦書きで、右吹き出しの前の虫が字送りゼロの写しに替わっていない: {vertical}")
    if not (".bubble.vert" in vertical[1] and ".bubble.vert" in vertical[3]):
        problems.append(f"縦書きで吹き出しが右用の字形に替わっていない: {vertical}")
    # 小さい虫のあとの右吹き出しは、虫に合わせて寄る(位置合わせが縦書きでも効いているか)。
    # 縦用の小書きの字は右上にあるので、下がらず横にだけ寄る書体もある
    plain, low = shape(path, "て✕✕あ✕○", "", "ttb")[1], shape(path, "っ✕✕あ✕○", "", "ttb")[1]
    if low[1:3] == plain[1:3] and low[0] == plain[0]:
        problems.append(f"縦書きで、小さい虫のあとの右吹き出しが寄っていない: {plain} / {low}")
    # 位置合わせ(GPOS)が効かないアプリでも寄るよう、ずらした字形に替わっているか
    if not re.search(r"\.s\d+$", low[0]):
        problems.append(f"縦書きで、小さい虫のあとの右吹き出しが、ずらした字形に替わっていない: {low}")
    small = [name for name, *_ in shape(path, "っ✕✕", "", "ttb")]
    if len(small) != 1 or ".struck" not in small[0]:
        problems.append(f"縦書きで小書きの字に虫が重ならない: {small}")
    expect("縦書きの ss02", [name for name, *_ in shape(path, "ああ", "ss02", "ttb")], [g("あ") + ".mino.vert", g("あ") + ".mino.vert.v2"])
    expect("縦書きの ss03", [name for name, *_ in shape(path, "ああ", "ss03", "ttb")], [g("あ") + ".bubble.vert", g("あ") + ".bubble.vert.v2"])
    expect("縦書きの英数字・記号", [level(name).replace(".vert", "").replace(".pre", "") for name, *_ in shape(path, "a✕✕1✕○", "", "ttb")], [g("a") + ".struck", g("1") + ".bubble"])
    # Safari は縦書きで、1文字ずつ vert の字形に替えたあと横書き用の機能だけを当てる。その順でも縦用の字形が出るか
    vert = {}
    for record in font["GSUB"].table.FeatureList.FeatureRecord:
        if record.FeatureTag == "vert":
            for index in record.Feature.LookupListIndex:
                for subtable in font["GSUB"].table.LookupList.Lookup[index].SubTable:
                    vert.update(getattr(getattr(subtable, "ExtSubTable", subtable), "mapping", {}))
    # (✕ は Safari では縦用の字形に替わらない)
    entry = vert.get(g("て"))
    if entry != g("て") + ".vert" or g("✕") in vert or None in font["GSUB"].table.LookupList.Lookup:
        problems.append(f"縦書きの入口の字形が想定と違う: {entry}, ✕ → {vert.get(g('✕'))}")
    for label, glyphs, feature, want in (("合字", [entry, g("✕"), g("✕"), entry, g("✕"), g("○")], "", [".struck", ".bubble.vert"]),
                                         ("ss02", [entry], "ss02", [".mino.vert"]),
                                         ("ss03", [entry], "ss03", [".bubble.vert"])):
        # hb-shape は字形の並びを直接は受け取れないので、liga・ss の表を自前でたどる
        got = apply_horizontal(font, glyphs, feature)
        if len(got) != len(want) or not all(w in name for name, w in zip(got, want)):
            problems.append(f"Safari の順序での縦書きの{label}: {got}")
    # 小さい虫のあとの吹き出しは、位置合わせ(GPOS)を切っても下がっているか(Illustrator の横書き用)
    after_small = shape(path, "っ✕✕あ✕○", "-dist,-kern")[1][0]
    if not re.search(r"\.d\d+$", after_small):
        problems.append(f"小さい虫のあとの吹き出しが、下げた字形に替わっていない: {after_small}")
    # 漢字(漢字のある書体だけ)。虫と吹き出しは部品を参照する字形で、ss02 は虫と吹き出しの2字形に分かれる
    if ord("漢") in cmap:
        k, n = g("漢"), g("猫")
        expect("漢字の合字", names("漢✕✕猫✕○"), [k + ".struck", n + ".bubble"])
        expect("漢字の ss01〜03", names("漢", "ss01") + names("漢", "ss02") + names("漢", "ss03"), [k + ".struck", k + ".mino", k + ".bubble"])
        expect("縦書きの漢字", [name for name, *_ in shape(path, "漢✕✕猫✕○っ✕✕猫✕○", "", "ttb")],
               [k + ".struck.pre", n + ".bubble.vert", g("っ") + ".vert.struck.pre" if g("っ") + ".vert.struck" in glyf.glyphs else g("っ") + ".struck.vert.pre", n + ".bubble.vert"])
        expect("縦書きの漢字の ss02", [name for name, *_ in shape(path, "漢", "ss02", "ttb")], [k + ".struck.pre", k + ".bubble.vert"])
        # Safari は漢字を縦用の字形に替えない。同じ行のかな(縦用の字形)から縦書きが伝わって、
        # 漢字の吹き出しが縦書き用になるか。かなが前にある場合と後ろにある場合
        for label, glyphs in (("前", [entry, k, g("✕"), g("✕"), n, g("✕"), g("○")]), ("後ろ", [k, g("✕"), g("✕"), n, g("✕"), g("○"), k, entry])):
            got = apply_horizontal(font, glyphs, "")
            if n + ".bubble.vert" not in got or k + ".struck.pre" not in got or g("✕") in got or any(".vcarry" in x for x in got):
                problems.append(f"Safari の縦書きで、かなが{label}にあるときの漢字: {got}")
        if any(".vert" in x for x in apply_horizontal(font, [k, g("✕"), g("✕"), n, g("✕"), g("○")], "")):
            problems.append("横書きの漢字が縦書き用の字形になっている")
        # 右から左へたどる規則(ルックアップの種類 8)が1つでもあると、Illustrator は合字をすべて無効にする
        if any(getattr(t, "ExtSubTable", t).LookupType == 8 for lookup in font["GSUB"].table.LookupList.Lookup for t in lookup.SubTable):
            problems.append("Illustrator が読めない種類の規則(逆順の文脈置換)が入っている")
        if not glyf[k + ".struck"].isComposite() or not glyf[k + ".mino"].isComposite() or not glyf[n + ".bubble"].isComposite():
            problems.append("漢字の字形が部品の参照になっていない")
    # 幅ゼロの吹き出しが、直前の虫の中央に来ているか(吹き出しは左右に 80 ほど揺らしてある)。
    # 句読点やかっこの虫は字に寄せてあるので、字送りの中央ではなく虫を重ねた字形の中央と比べる
    for ch in "あいしくっゃのーai1。「":
        (struck, _, _, advance), (bubble, dx, _, _) = shape(path, ch + "✕✕" + "あ✕○")
        center = advance + dx + (glyf[bubble].xMin + glyf[bubble].xMax) / 2
        target = (glyf[struck].xMin + glyf[struck].xMax) / 2 if ch in "。「" else advance / 2
        if abs(center - target) > 120:
            problems.append(f"「{ch}」の虫の上の吹き出しが横に {center - target:.0f} ずれている")
    return problems


if __name__ == "__main__":
    if not shutil.which("hb-shape"):
        sys.exit("hb-shape が見つからない(HarfBuzz のコマンドラインツールが必要)")
    results = [check(**base) for base in BASES]
    sys.exit(0 if all(results) else 1)
