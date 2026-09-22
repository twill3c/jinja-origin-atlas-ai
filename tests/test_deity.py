# -*- coding: utf-8 -*-
"""T-142〜T-150: 祭神の三面(共祀ネットワーク・リフト地図・習合対応表)。SPEC G-16〜G-19。

**リフトは総本社の表を入力に使わない**(G-16)。使えば循環し、一致はほぼ恒等式になる。
リフトは全国の祭神つき社の県分布だけから出し、総本社の表は答え合わせにだけ使う。

**件数は定数で書かない**(HC-016 / RULE-09)。県チャンクを数え直した値と突き合わせる。

**共起の最強の辺は同一視である**(八幡神と応神天皇など)。畳める辺は凍結表で
`identity` と分類した辺だけで、親族・総称と構成神・その他は畳まない。
"""
import json
import math
import pathlib
import random

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHUNK_DIR = ROOT / "public" / "data" / "shrines"
DEITY_DIR = ROOT / "public" / "data" / "deity"
HEAD_SHRINES = ROOT / "data" / "reference" / "head_shrines.json"
PAIR_LABELS = ROOT / "data" / "reference" / "deity_pair_labels.json"
CATALOG_FULL = ROOT / "data" / "interim" / "catalog_full.json"
WIKIDATA_CORE = ROOT / "data" / "raw" / "wikidata" / "core.json"

#: G-16 の合格線。**実装前に人間が承認して凍結した**(2026-09-21・loop_013)。
#: 偶然なら 47 分の 1 なので 26 柱で 0.55 件相当。測ってから書き換えてはならない。
G16_THRESHOLD = 13
#: G-17 の規則と閾値。こちらも測る前に書いた。**落ちてもよい** —— 落ちたら
#: 「共起の強さでは見分けられないので手で分類した」と画面に書く。
G17_THRESHOLD = 0.70
#: リフトの最上位県に選ぶための最小社数。自由に動かせる値なので、測る前に固定した。
MIN_PREF_SHRINES = 3
#: 帰無分布の試行数。
NULL_TRIALS = 200


def _read(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mentions():
    """県チャンクを数え直した祭神の言及。テストの側で独立に組み立てる。"""
    if not CHUNK_DIR.exists():
        pytest.skip("県チャンクがまだ無い")
    out = []
    n_shrines = 0
    for p in sorted(CHUNK_DIR.glob("[0-9][0-9].json")):
        for r in _read(p)["shrines"]:
            n_shrines += 1
            ds = r.get("deities")
            if not ds:
                continue
            out.append({
                "id": r["id"],
                "pref": r["location"]["prefecture"],
                "qids": sorted({d["wikidata_id"] for d in ds}),
                "names": {d["wikidata_id"]: d["name"] for d in ds},
            })
    if not out:
        pytest.skip("祭神を持つ社が 1 件も無い")
    return {"rows": out, "shrines_total": n_shrines}


@pytest.fixture(scope="module")
def frozen_head_shrines():
    if not HEAD_SHRINES.exists():
        pytest.skip("総本社の凍結表がまだ無い")
    doc = _read(HEAD_SHRINES)
    assert doc["_status"] == "approved_frozen", "承認されていない表を正解に使わない"
    return doc


@pytest.fixture(scope="module")
def frozen_pairs():
    if not PAIR_LABELS.exists():
        pytest.skip("ペア分類の凍結表がまだ無い")
    doc = _read(PAIR_LABELS)
    assert doc["_status"] == "approved_frozen", "承認されていない表を正解に使わない"
    return doc


# ---------------------------------------------------------------- T-142


@pytest.mark.validation
def test_t142_deity_artifacts_preserve_the_mention_count(mentions):
    """T-142 / G-19: 公開した祭神アーティファクトの件数が、数え直した値と一致する。"""
    from etl import deity_stats

    index_path = DEITY_DIR / "index.json"
    if not index_path.exists():
        pytest.fail("public/data/deity/index.json がまだ作られていない")

    rows = mentions["rows"]
    want_mentions = sum(len(r["qids"]) for r in rows)
    want_deities = len({q for r in rows for q in r["qids"]})

    doc = _read(index_path)
    got = doc["totals"]
    assert got["mentions"] == want_mentions
    assert got["shrines_with_deities"] == len(rows)
    assert got["shrines_total"] == mentions["shrines_total"]
    assert got["deities"] == want_deities
    assert sum(d["n"] for d in doc["deities"]) == want_mentions
    assert len(doc["deities"]) == want_deities

    # 同じ数をモジュールからも出せること(出荷物とモジュールが別経路で一致する)
    counts = deity_stats.deity_counts(deity_stats.load_mentions(CHUNK_DIR))
    assert sum(c["n"] for c in counts.values()) == want_mentions
    assert len(counts) == want_deities


# ---------------------------------------------------------------- T-143


@pytest.mark.validation
def test_t143_head_shrine_prefectures_are_verifiable(frozen_head_shrines):
    """T-143: 凍結表の所在県を、総本社の Q-id から機械で引き直して確かめる。

    直接 OSM に結合されていない総本社は、Wikidata の座標から最寄りの社を取る。
    **表を信じない** —— 表が主張する県と、引き直した県が一致することを毎回確かめる。
    """
    import math
    import re

    if not CATALOG_FULL.exists() or not WIKIDATA_CORE.exists():
        pytest.skip("カタログか Wikidata の取得物がまだ無い")

    cat = _read(CATALOG_FULL)["shrines"]
    by_qid = {r["external_ids"]["wikidata"]: r for r in cat
              if r["external_ids"].get("wikidata")}

    coord: dict[str, tuple[float, float]] = {}
    for r in _read(WIKIDATA_CORE):
        q = r["item"]["value"].rsplit("/", 1)[-1]
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", r["coord"]["value"])
        if m:
            coord.setdefault(q, (float(m.group(2)), float(m.group(1))))

    def nearest_pref(lat: float, lon: float) -> tuple[str, float] | None:
        best = None
        for r in cat:
            dy = (r["location"]["lat"] - lat) * 111_320
            if abs(dy) > 3_000:
                continue
            dx = ((r["location"]["lon"] - lon) * 111_320
                  * math.cos(math.radians(lat)))
            d = math.hypot(dx, dy)
            if best is None or d < best[1]:
                best = (r["location"]["prefecture"], d)
        return best

    bad: list[str] = []
    checked = 0
    for e in frozen_head_shrines["entries"]:
        q = e["head_shrine_qid"]
        if q in by_qid:
            got = by_qid[q]["location"]["prefecture"]
        else:
            c = coord.get(q)
            if c is None:
                bad.append(f"{e['deity']}: {q} の座標が Wikidata に無い")
                continue
            near = nearest_pref(*c)
            if near is None:
                bad.append(f"{e['deity']}: {q} の 3 km 以内に社が無い")
                continue
            got, _d = near
        checked += 1
        if got != e["prefecture"]:
            bad.append(f"{e['deity']}: 表は {e['prefecture']} だが引き直すと {got}")

    assert checked == len(frozen_head_shrines["entries"]), "引き直せなかった行がある"
    assert bad == [], "総本社の所在県が引き直しと合わない: " + " / ".join(bad)


# ---------------------------------------------------------------- T-144


@pytest.mark.validation
def test_t144_lift_finds_head_shrines(mentions, frozen_head_shrines):
    """T-144 / G-16: 総本社の的中数を測り、レポートに残し、画面の文を結果に従わせる。

    **非循環**: リフトは祭神つき社の県分布だけから出す。総本社の表は
    この計算に入らない(入れれば恒等式になる)。

    **登録した予測 13/26 は 2026-09-21 に測って落ちた(7/26)。**
    閾値は動かさない。以後この検査が見るのは「測ったか」「レポートに載っているか」
    「画面の主張が結果と食い違っていないか」である(SPEC §7.14)。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    hit, total, detail = deity_stats.head_shrine_agreement(
        rows, frozen_head_shrines["entries"], floor=MIN_PREF_SHRINES)

    assert total == len(frozen_head_shrines["entries"])
    assert len(detail) == total
    assert all(d["hit"] == (d["top_pref"] == d["head_pref"]) for d in detail)

    report = DEITY_DIR / "report.json"
    if not report.exists():
        pytest.fail("public/data/deity/report.json がまだ作られていない")
    shipped = _read(report)["g16"]
    assert shipped["hit"] == hit, "レポートの的中数が計算し直した値と違う"
    assert shipped["total"] == total
    assert shipped["threshold"] == G16_THRESHOLD, "凍結した合格線が書き換えられている"
    assert shipped["pass"] is (hit >= G16_THRESHOLD)
    assert shipped["floor"] == MIN_PREF_SHRINES
    # 外れた祭神は消さずに残す(落ちた記録が資産である)
    assert len(shipped["rows"]) == total
    assert sum(1 for r in shipped["rows"] if not r["hit"]) == total - hit


@pytest.mark.validation
def test_t144b_lift_does_not_read_the_oracle():
    """T-144 / G-16: リフトの計算経路が総本社の表を読んでいないこと(循環の禁止)。

    結論だけでなく経路を見る(HC-065)。**言及と使用を分ける**(HC-074) ——
    docstring で「総本社の表は使わない」と書くのは違反ではない。見るのは
    識別子と文字列リテラル、つまり実際に走るコードだけである。
    """
    import ast

    def scan(fn: ast.FunctionDef) -> list[str]:
        """関数の中で総本社の表に**触れている**箇所を挙げる。docstring は除く。"""
        doc = (fn.body[0].value if fn.body and isinstance(fn.body[0], ast.Expr)
               and isinstance(fn.body[0].value, ast.Constant) else None)
        hits: list[str] = []
        for node in ast.walk(fn):
            if node is doc:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "head_shrine" in node.value:
                    hits.append(f"{fn.name}: 文字列 {node.value!r}")
            elif isinstance(node, ast.Name) and "head_shrine" in node.id:
                hits.append(f"{fn.name}: 名前 {node.id}")
            elif isinstance(node, ast.Attribute) and "head_shrine" in node.attr:
                hits.append(f"{fn.name}: 属性 {node.attr}")
            elif isinstance(node, ast.arg) and "head_shrine" in node.arg:
                hits.append(f"{fn.name}: 引数 {node.arg}")
        return hits

    src = (ROOT / "etl" / "deity_stats.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    lift_fns = {"prefecture_base", "lift_rows", "top_lift_pref"}
    found = [fn for fn in tree.body
             if isinstance(fn, ast.FunctionDef) and fn.name in lift_fns]
    assert {f.name for f in found} == lift_fns, "リフトを計算する関数を見つけられない"

    hits = [h for fn in found for h in scan(fn)]
    assert hits == [], "リフトの計算側が総本社の表を参照している: " + str(hits)

    # 引数でオラクルを受け取る道も塞ぐ —— 触れる引数を持っていないことを見る。
    for fn in found:
        names = {a.arg for a in fn.args.args}
        assert names <= {"rows", "qid", "floor", "base"}, (
            f"{fn.name} が想定外の引数を取る: {sorted(names)}。"
            "オラクルが引数で入ってくる道になっていないか確かめること")

    # 陽性対照: わざと循環させた実装を同じ検査に当てると、必ず撃つ。
    bad = ast.parse(
        "def lift_rows(rows, qid):\n"
        "    oracle = open('data/reference/head_shrines.json')\n"
        "    return oracle\n"
    ).body[0]
    assert scan(bad), "検査器が、あからさまに循環した実装すら捕まえない"


# ---------------------------------------------------------------- T-145


@pytest.mark.validation
def test_t145_lift_beats_shuffled_null(mentions, frozen_head_shrines):
    """T-145 / G-16: 祭神の割り当てを振り直すと的中が落ちる(偶然ではない)。

    陽性対照の裏返し。**帰無分布を作らない一致は、偶然と区別できない。**
    振り直しは社ごとの祭神の数と祭神の総出現数を保ったまま、どの社に付くかだけを崩す。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    entries = frozen_head_shrines["entries"]
    observed, _total, _d = deity_stats.head_shrine_agreement(
        rows, entries, floor=MIN_PREF_SHRINES)

    rng = random.Random(20260921)
    null = []
    prefs = [r["pref"] for r in rows]
    for _ in range(NULL_TRIALS):
        shuffled = prefs[:]
        rng.shuffle(shuffled)
        permuted = [{**r, "pref": p} for r, p in zip(rows, shuffled)]
        h, _t, _dd = deity_stats.head_shrine_agreement(
            permuted, entries, floor=MIN_PREF_SHRINES)
        null.append(h)

    null.sort()
    p95 = null[int(0.95 * len(null))]
    p_value = (sum(1 for x in null if x >= observed) + 1) / (len(null) + 1)
    assert observed > p95, f"実測 {observed} が帰無の 95 パーセンタイル {p95} を超えない"
    assert p_value < 0.05, f"p = {p_value:.4f}"


# ---------------------------------------------------------------- T-146


@pytest.mark.validation
def test_t146_syncretism_is_or_is_not_predictable(mentions, frozen_pairs):
    """T-146 / G-17: 共起の強さ(Jaccard)から同一視を当てられるかを測る。

    **落ちてよい検査である。** 合否はレポートに残し、画面の文はレポートに従う。
    ここで落とすのは「測っていない」ときだけ。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    result = deity_stats.syncretism_predictability(rows, frozen_pairs["pairs"])

    assert result["k"] == sum(1 for p in frozen_pairs["pairs"]
                              if p["type"] == "identity")
    assert 0.0 <= result["precision"] <= 1.0
    assert result["threshold"] == G17_THRESHOLD
    assert result["pass"] == (result["precision"] >= G17_THRESHOLD)

    report = DEITY_DIR / "report.json"
    if not report.exists():
        pytest.fail("public/data/deity/report.json がまだ作られていない")
    shipped = _read(report)["g17"]
    assert shipped["precision"] == pytest.approx(result["precision"])
    assert shipped["pass"] == result["pass"]


# ---------------------------------------------------------------- T-147


@pytest.mark.validation
def test_t147_pair_labels_match_the_measured_pairs(mentions, frozen_pairs):
    """T-147: 凍結したペア分類が「共起 N 回以上」の集合と完全に一致する。

    **件数で切らない。** 重み 9 のペアは 10 組あり、その同点の群が 42〜51 位に
    またがる。上位 50 件で切ると、どちらが 50 位に入るかが走査順で決まってしまう
    (2026-09-21 に実際に 応神天皇/菅原道真 が落ちていた)。境界は重みで置く。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    names = {q: n for r in rows for q, n in r["names"].items()}
    threshold = frozen_pairs["labeled_threshold"]
    measured = {k for k, w in deity_stats.pair_counts(rows).items()
                if w >= threshold}
    assert measured, "走査対象が空"

    frozen = {frozenset((p["a_qid"], p["b_qid"])) for p in frozen_pairs["pairs"]}
    assert len(frozen) == len(frozen_pairs["pairs"]), "凍結表に同じペアが二度ある"

    missing = [frozenset(k) for k in measured if frozenset(k) not in frozen]
    extra = [k for k in frozen if k not in {frozenset(m) for m in measured}]
    assert missing == [], "分類していない強い辺がある: " + ", ".join(
        "/".join(names.get(q, q) for q in k) for k in missing)
    assert extra == [], "実データに無いペアが凍結表にある: " + ", ".join(
        "/".join(names.get(q, q) for q in k) for k in extra)

    allowed = set(frozen_pairs["_types"])
    for entry in frozen_pairs["pairs"]:
        assert entry["type"] in allowed, f"{entry['type']} は列挙に無い型"
        assert names[entry["a_qid"]] == entry["a"]
        assert names[entry["b_qid"]] == entry["b"]


# ---------------------------------------------------------------- T-148


def _coords(net: dict) -> list:
    return [(q, n["qid"], n["x"], n["y"])
            for q, g in sorted(net["ego"].items()) for n in g["nodes"]]


@pytest.mark.validation
def test_t148_layout_is_deterministic(mentions):
    """T-148 / G-18: 同じ入力から配置を二度計算するとビット一致する。

    **ブラウザで配置を計算しない。** 計算し直すたびに図が変われば、
    「図が読めるか」も「要素が枠に収まるか」も測れなくなる。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    a = _coords(deity_stats.build_network(rows))
    b = _coords(deity_stats.build_network(rows))
    assert a and a == b, "同じ入力から二度計算した配置が一致しない"

    shipped_path = DEITY_DIR / "network.json"
    if not shipped_path.exists():
        pytest.fail("public/data/deity/network.json がまだ作られていない")
    assert _coords(_read(shipped_path)) == a, (
        "出荷した配置が、同じ入力から計算し直した配置と一致しない")


@pytest.mark.validation
def test_t148b_every_ring_node_sits_on_the_ring(mentions):
    """T-148 / G-18: 中心は原点、相手は半径 R の環の上にあり、重なっていない。

    図が読めるかは目視でしか分からないが(HC-041)、**環の上に等間隔で並ぶ**
    という性質は測れる。全体を力学配置した図では丸とラベルが重なっていたのに、
    `viewBox` の検査も要素数の検査も緑のままだった(2026-09-21)。
    """
    from etl import deity_stats

    net = deity_stats.build_network(mentions["rows"])
    r = deity_stats.EGO_RADIUS
    for qid, g in net["ego"].items():
        centre = [n for n in g["nodes"] if n["center"]]
        ring = [n for n in g["nodes"] if not n["center"]]
        assert len(centre) == 1 and centre[0]["qid"] == qid
        assert centre[0]["x"] == 0.0 and centre[0]["y"] == 0.0
        assert 1 <= len(ring) <= net["params"]["cap"]
        for n in ring:
            assert abs(math.hypot(n["x"], n["y"]) - r) < 0.01, (
                f"{qid} の {n['qid']} が環の上に無い")
        # 隣どうしの間合いが等しい(環が偏っていない)
        angles = sorted(math.atan2(n["y"], n["x"]) for n in ring)
        if len(angles) > 2:
            gaps = [angles[i + 1] - angles[i] for i in range(len(angles) - 1)]
            assert max(gaps) - min(gaps) < 1e-6, f"{qid} の環が等間隔でない"


# ---------------------------------------------------------------- T-149 / T-150


@pytest.mark.validation
def test_t149_only_identity_edges_collapse(mentions, frozen_pairs):
    """T-149: 畳めるのは `identity` の対だけ。陽性対照つき。"""
    from etl import deity_stats

    rows = mentions["rows"]
    net = deity_stats.build_network(rows)
    labeled = {frozenset((p["a_qid"], p["b_qid"])): p["type"]
               for p in frozen_pairs["pairs"]}

    for g in net["ego"].values():
        for e in g["edges"]:
            want = labeled.get(frozenset((e["a"], e["b"])), "unlabeled")
            assert e["type"] == want, f"辺 {e['a']}–{e['b']} の型が凍結表と違う"

    # 畳んだ群は、同一視の対だけから作られていること
    identity_pairs = {frozenset((p["a_qid"], p["b_qid"]))
                      for p in frozen_pairs["pairs"] if p["type"] == "identity"}
    assert identity_pairs, "同一視の対が 1 つも無い(対照が空振りしている)"
    assert net["merged_groups"], "畳んでも群が 1 つもできない"
    for members in net["merged_groups"].values():
        assert len(members) >= 2
        # 群の中は、同一視の対だけで繋がっていなければならない
        linked = {q: False for q in members}
        linked[members[0]] = True
        for _ in members:
            for a in members:
                for b in members:
                    if a != b and frozenset((a, b)) in identity_pairs:
                        linked[b] = linked[b] or linked[a]
        assert all(linked.values()), f"同一視でない繋がりで畳まれた群: {members}"

    # 陽性対照: 同一視の対が一つも無い表では、畳みが起きない。
    flat = {**frozen_pairs,
            "pairs": [{**p, "type": "other"} for p in frozen_pairs["pairs"]]}
    assert deity_stats.build_network(rows, labels=flat)["merged_groups"] == {}, (
        "同一視の対が無いのに畳まれた(畳みが型を見ていない)")


@pytest.mark.validation
def test_t150_unlabeled_edges_are_not_guessed(mentions, frozen_pairs):
    """T-150: 凍結表の外の辺は `unlabeled` のまま。推測で型を埋めない。

    データが更新されて新しいペアが閾値に達したら、その数を**画面とレポートに出す**
    (黙って型を付けない)。ここではその数が数え直しと一致することを確かめる。
    """
    from etl import deity_stats

    rows = mentions["rows"]
    net = deity_stats.build_network(rows)
    labeled = {frozenset((p["a_qid"], p["b_qid"])) for p in frozen_pairs["pairs"]}
    outside = [e for g in net["ego"].values() for e in g["edges"]
               if frozenset((e["a"], e["b"])) not in labeled]
    assert outside, "凍結表の外の辺が 1 本も無い(検査が空振りしている)"
    assert all(e["type"] == "unlabeled" for e in outside), (
        "分類していない辺に型が付いている")

    threshold = frozen_pairs["labeled_threshold"]
    want_strong = sum(1 for k, w in deity_stats.pair_counts(rows).items()
                      if w >= threshold and frozenset(k) not in labeled)
    report = DEITY_DIR / "report.json"
    if not report.exists():
        pytest.fail("public/data/deity/report.json がまだ作られていない")
    assert _read(report)["pairs"]["unlabeled_at_threshold"] == want_strong


# ---------------------------------------------------------------- T-152


@pytest.mark.validation
def test_t152_deity_artifacts_fit_the_size_budget():
    """T-152 / G-06: 祭神アーティファクトが gzip 5 MB を超えない(N-02)。"""
    import gzip

    if not DEITY_DIR.exists():
        pytest.fail("public/data/deity/ がまだ無い")
    files = sorted(DEITY_DIR.glob("*.json"))
    assert files, "走査対象が空"
    over = [(p.name, len(gzip.compress(p.read_bytes())))
            for p in files if len(gzip.compress(p.read_bytes())) > 5_000_000]
    assert over == [], f"gzip 5 MB 超: {over}"
