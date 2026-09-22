# -*- coding: utf-8 -*-
"""祭神の集計 — 共祀ネットワーク・県別リフト・習合の対応表。SPEC F-03 / F-14 / G-16〜G-19。

**リフトは総本社の表を入力に使わない。** 県ごとの期待値は「祭神つき社そのものの県分布」
から作る。総本社の表(`data/reference/head_shrines.json`)は答え合わせにだけ使い、
この計算の中には現れない —— 使えば一致はほぼ恒等式になる(G-16)。

**県の生の比率は使えない。** 祭神つき社は東京都・埼玉県・千葉県に偏っており、
生の比率で塗るとどの祭神も「東京の神」になる。期待値で割ったリフトを使う。

**配置は決定的でなければならない**(G-18)。乱数を使わず、Q-id の順で円周に置いてから
力学を回す。ブラウザで計算すると再現性が壊れて検品が書けないので、ここで計算して出荷する。

**畳める辺は同一視だけ**(`identity`)。親族・総称と構成神・その他は別の神格なので畳まない。
凍結表に無いペアは `unlabeled` にする —— 推測で型を付けない。
"""
from __future__ import annotations

import json
import math
import pathlib
from collections import Counter, defaultdict
from typing import Any, Iterable

#: ネットワークのノードに載せる最小社数。
MIN_NODE_SHRINES = 5
#: 辺に載せる最小の共起数。
MIN_EDGE_WEIGHT = 3
#: リフトの最上位県に選ぶために必要な社数。**測る前に決めた**(2026-09-21)。
#: 小さくすると 1 社だけの県が最上位に来てしまい、大きくすると小さな祭神が消える。
MIN_PREF_SHRINES = 3
#: 力学配置の反復回数と盤面の大きさ。乱数は使わない。
LAYOUT_ITERATIONS = 600
LAYOUT_SIZE = 1000.0
#: 出荷する座標の小数桁。丸めてから配ることで、環境差が座標に出ないようにする。
LAYOUT_DIGITS = 4

CHUNK_DIR = pathlib.Path("public/data/shrines")
PAIR_LABELS = pathlib.Path("data/reference/deity_pair_labels.json")

Row = dict[str, Any]


# --------------------------------------------------------------- 読み込み


def load_mentions(chunk_dir: pathlib.Path | str = CHUNK_DIR) -> list[Row]:
    """県チャンクから祭神を持つ社だけを取り出す。

    同じ社に同じ Q-id が二度書かれていることがあるので集合にする
    (延べ言及数は「社 × 異なり祭神」で数える)。
    """
    chunk_dir = pathlib.Path(chunk_dir)
    rows: list[Row] = []
    for p in sorted(chunk_dir.glob("[0-9][0-9].json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        for r in doc["shrines"]:
            ds = r.get("deities")
            if not ds:
                continue
            rows.append({
                "id": r["id"],
                "name": r["name"]["ja"],
                "pref": r["location"]["prefecture"],
                "lat": r["location"]["lat"],
                "lon": r["location"]["lon"],
                "qids": sorted({d["wikidata_id"] for d in ds}),
                "names": {d["wikidata_id"]: d["name"] for d in ds},
            })
    return rows


def count_all_shrines(chunk_dir: pathlib.Path | str = CHUNK_DIR) -> int:
    """祭神の有無によらない全社数(画面に割合を出すための分母)。"""
    chunk_dir = pathlib.Path(chunk_dir)
    return sum(len(json.loads(p.read_text(encoding="utf-8"))["shrines"])
               for p in sorted(chunk_dir.glob("[0-9][0-9].json")))


# --------------------------------------------------------------- 集計


def deity_counts(rows: Iterable[Row]) -> dict[str, dict[str, Any]]:
    """Q-id ごとの鎮座社数。名前は最初に見たものを採る(Q-id が識別子)。"""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        for q in r["qids"]:
            e = out.setdefault(q, {"qid": q, "name": r["names"][q], "n": 0})
            e["n"] += 1
    return out


def pair_counts(rows: Iterable[Row]) -> Counter:
    """同じ社に並ぶ祭神ペアの数。キーは Q-id の昇順の組。"""
    out: Counter = Counter()
    for r in rows:
        qs = r["qids"]
        for i in range(len(qs)):
            for j in range(i + 1, len(qs)):
                out[(qs[i], qs[j])] += 1
    return out


def prefecture_base(rows: Iterable[Row]) -> Counter:
    """期待値の分母 —— 祭神つき社そのものの県分布。**これがリフトの土台**。"""
    return Counter(r["pref"] for r in rows)


def lift_rows(rows: list[Row], qid: str,
              base: Counter | None = None) -> list[dict[str, Any]]:
    """ある祭神の県別リフト。リフト降順、同点は県名の昇順で決定的に並べる。"""
    base = prefecture_base(rows) if base is None else base
    total = sum(base.values())
    mine = Counter(r["pref"] for r in rows if qid in r["qids"])
    n = sum(mine.values())
    out = []
    for pref, c in mine.items():
        expected = n * base[pref] / total
        out.append({
            "pref": pref, "n": c,
            "expected": round(expected, 3),
            "lift": round(c / expected, 3) if expected else None,
        })
    out.sort(key=lambda d: (-(d["lift"] or 0.0), d["pref"]))
    return out


def top_lift_pref(rows: list[Row], qid: str, floor: int = MIN_PREF_SHRINES,
                  base: Counter | None = None) -> dict[str, Any] | None:
    """該当社が `floor` 件以上ある県のうち、リフト最大の県。無ければ None。"""
    for row in lift_rows(rows, qid, base=base):
        if row["n"] >= floor:
            return row
    return None


# --------------------------------------------------------------- G-16


def head_shrine_agreement(rows: list[Row], entries: list[dict[str, Any]],
                          floor: int = MIN_PREF_SHRINES
                          ) -> tuple[int, int, list[dict[str, Any]]]:
    """リフト最上位の県が総本社の県と一致する数を数える(G-16 の答え合わせ)。

    **この関数より上に総本社の表は現れない。** リフトの計算は `lift_rows` が
    県分布だけから行い、ここで初めて表と突き合わせる(循環しない)。
    """
    base = prefecture_base(rows)
    hit = 0
    detail: list[dict[str, Any]] = []
    for e in entries:
        top = top_lift_pref(rows, e["deity_qid"], floor=floor, base=base)
        ok = bool(top and top["pref"] == e["prefecture"])
        hit += ok
        detail.append({
            "deity": e["deity"], "deity_qid": e["deity_qid"],
            "head_shrine": e["head_shrine"], "head_pref": e["prefecture"],
            "top_pref": top["pref"] if top else None,
            "top_lift": top["lift"] if top else None,
            "top_n": top["n"] if top else None,
            "hit": ok,
        })
    return hit, len(entries), detail


# --------------------------------------------------------------- G-17


def syncretism_predictability(rows: list[Row],
                              labeled: list[dict[str, Any]],
                              threshold: float = 0.70) -> dict[str, Any]:
    """共起の強さ(Jaccard)から同一視を当てられるかを測る。**落ちてよい検査**。

    規則: 凍結表のペアのうち Jaccard 上位 k 件を同一視と予測する。
    k は手分類の同一視の件数に合わせるので、適合率と再現率は同じ値になる。
    """
    counts = deity_counts(rows)
    pairs = pair_counts(rows)
    truth = {frozenset((p["a_qid"], p["b_qid"])): p["type"] for p in labeled}
    k = sum(1 for t in truth.values() if t == "identity")

    scored = []
    for p in labeled:
        a, b = p["a_qid"], p["b_qid"]
        w = pairs.get(tuple(sorted((a, b))), 0)
        union = counts[a]["n"] + counts[b]["n"] - w
        scored.append({
            "a": p["a"], "b": p["b"], "a_qid": a, "b_qid": b,
            "w": w, "jaccard": round(w / union, 4) if union else 0.0,
            "truth": p["type"],
        })
    # 同点は Q-id の昇順で決める(走査順に依存させない)
    scored.sort(key=lambda d: (-d["jaccard"], d["a_qid"], d["b_qid"]))
    predicted = scored[:k]
    correct = sum(1 for d in predicted if d["truth"] == "identity")
    precision = correct / k if k else 0.0
    return {
        "rule": "jaccard_top_k",
        "k": k,
        "correct": correct,
        "precision": round(precision, 4),
        "threshold": threshold,
        "pass": precision >= threshold,
        "predicted": predicted,
        "missed": [d for d in scored[k:] if d["truth"] == "identity"],
    }


# --------------------------------------------------------------- ネットワーク


def load_pair_labels(path: pathlib.Path | str = PAIR_LABELS) -> dict[str, Any]:
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if doc.get("_status") != "approved_frozen":
        raise ValueError("承認されていないペア分類表を使おうとしている")
    return doc


#: 一柱のまわりに描く相手の上限。天照大神は 30 柱と並ぶが、環に 30 の名前を
#: 並べるとラベルが重なって読めない。上限を超えたぶんは数で書く(隠さない)。
EGO_MAX_NEIGHBOURS = 14
#: 環の半径と、中心から見た最初の相手の角度。
EGO_RADIUS = 320.0
EGO_START_ANGLE = -math.pi / 2
#: 環の上での並び順。**型でまとめてから重みで並べる** —— 同じ種類の関係が
#: 隣り合うと、図は「どの向きに何があるか」を言えるようになる。
#: `mixed` は畳んだあとにだけ現れる(型の違う辺が一本に束ねられた場合)。
TYPE_ORDER = {"identity": 0, "kin": 1, "partof": 2, "mixed": 3, "other": 4,
              "unlabeled": 5}


def edge_type(labels: dict[str, Any]) -> dict[frozenset, str]:
    """凍結表から「ペア → 型」を引く辞書。表に無いペアは呼び出し側で unlabeled。"""
    return {frozenset((p["a_qid"], p["b_qid"])): p["type"] for p in labels["pairs"]}


def neighbours_of(pairs: Counter, qid: str) -> list[tuple[str, int]]:
    """ある祭神と同じ社に並ぶ相手と、その回数。重み降順・同点は Q-id 昇順。"""
    out = [(b if a == qid else a, w)
           for (a, b), w in pairs.items() if a == qid or b == qid]
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


def ego_graph(counts: dict[str, dict[str, Any]], pairs: Counter,
              types: dict[frozenset, str], qid: str,
              cap: int = EGO_MAX_NEIGHBOURS) -> dict[str, Any] | None:
    """一柱を中心に置いた図。**環なので、次数がいくつでも必ず読める。**

    全体を一枚に描くと 73 柱の中心部でラベルが重なる(2026-09-21 に二度試した)。
    問いは「この祭神は誰と並ぶか」なので、中心を決めた図のほうが答えになる。
    """
    nb = neighbours_of(pairs, qid)
    if not nb:
        return None
    ranked = sorted(
        nb,
        key=lambda t: (TYPE_ORDER[types.get(frozenset((qid, t[0])), "unlabeled")],
                       -t[1], t[0]),
    )[:cap]
    ring = [q for q, _w in ranked]

    nodes = [{"qid": qid, "name": counts[qid]["name"], "n": counts[qid]["n"],
              "x": 0.0, "y": 0.0, "center": True}]
    for i, q in enumerate(ring):
        a = EGO_START_ANGLE + 2 * math.pi * i / len(ring)
        nodes.append({
            "qid": q, "name": counts[q]["name"], "n": counts[q]["n"],
            "x": round(EGO_RADIUS * math.cos(a), LAYOUT_DIGITS),
            "y": round(EGO_RADIUS * math.sin(a), LAYOUT_DIGITS),
            "center": False,
        })

    edges = []
    members = [qid, *ring]
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            w = pairs.get(tuple(sorted((a, b))), 0)
            if not w:
                continue
            edges.append({"a": a, "b": b, "w": w,
                          "type": types.get(frozenset((a, b)), "unlabeled")})
    edges.sort(key=lambda e: (-e["w"], e["a"], e["b"]))
    return {"center": qid, "nodes": nodes, "edges": edges,
            "neighbours_total": len(nb), "neighbours_shown": len(ring)}


def _identity_groups(pairs: Counter, types: dict[frozenset, str]
                     ) -> dict[str, str]:
    """同一視の辺だけで併合したときの「代表」を Q-id ごとに返す。"""
    parent: dict[str, str] = {}

    def find(q: str) -> str:
        parent.setdefault(q, q)
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q

    for (a, b) in pairs:
        if types.get(frozenset((a, b))) != "identity":
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))  # 併合の向きも Q-id で決める
            parent[hi] = lo
    return {q: find(q) for q in {x for pair in pairs for x in pair}}


def collapse_pairs(counts: dict[str, dict[str, Any]], pairs: Counter,
                   types: dict[frozenset, str]
                   ) -> tuple[dict[str, dict[str, Any]], Counter,
                              dict[frozenset, str], dict[str, list[str]]]:
    """同一視の対を一柱に畳んだ世界を作る(数え直しではなく、名前の統合)。

    畳んだ柱の社数は構成柱の**最大**を採る。八幡神 495 と応神天皇 294 は
    同じ社を二つの名で数えているので、和は社数ではない。
    """
    rep = _identity_groups(pairs, types)
    groups: dict[str, list[str]] = defaultdict(list)
    for q in counts:
        groups[rep.get(q, q)].append(q)

    new_counts: dict[str, dict[str, Any]] = {}
    for root, members in groups.items():
        members = sorted(members, key=lambda q: (-counts[q]["n"], q))
        new_counts[root] = {
            "qid": root,
            "name": "・".join(counts[q]["name"] for q in members),
            "n": max(counts[q]["n"] for q in members),
            "members": members,
        }

    new_pairs: Counter = Counter()
    new_types: dict[frozenset, str] = {}
    for (a, b), w in pairs.items():
        ra, rb = rep.get(a, a), rep.get(b, b)
        if ra == rb:
            continue
        key = tuple(sorted((ra, rb)))
        new_pairs[key] += w
        t = types.get(frozenset((a, b)), "unlabeled")
        cur = new_types.get(frozenset(key))
        new_types[frozenset(key)] = t if cur in (None, t) else "mixed"
    return new_counts, new_pairs, new_types, {r: groups[r] for r in groups}


def build_network(rows: list[Row],
                  labels: dict[str, Any] | None = None,
                  cap: int = EGO_MAX_NEIGHBOURS) -> dict[str, Any]:
    """祭神ごとの「まわりの図」を、畳む前と畳んだ後の二通り作る。

    **座標はここで決めて出荷する**(G-18)。ブラウザで計算すると、同じ入力から
    同じ図が出るとは限らなくなり、検品で図の性質を測れなくなる。
    """
    labels = load_pair_labels() if labels is None else labels
    counts = deity_counts(rows)
    pairs = pair_counts(rows)
    types = edge_type(labels)

    ego = {q: g for q in sorted(counts)
           if (g := ego_graph(counts, pairs, types, q, cap=cap)) is not None}

    c_counts, c_pairs, c_types, groups = collapse_pairs(counts, pairs, types)
    c_ego_by_root = {r: g for r in sorted(c_counts)
                     if (g := ego_graph(c_counts, c_pairs, c_types, r,
                                        cap=cap)) is not None}
    # 畳んだあとも、**どの構成柱を選んでも同じ図に着く**ようにする。
    # 図の実体は代表に 1 つだけ置き、構成柱からは代表の Q-id で引く ——
    # 構成柱ごとに図を複製すると、出荷する JSON が倍近くに膨れる。
    collapsed_of = {q: root for root, members in groups.items()
                    if root in c_ego_by_root for q in members}
    # 畳んでも図が変わらない祭神(まわりに同一視の対が一つも無い)は、
    # 畳んだ側を持たない。同じ図を二度配ることになるため。
    changed = {q for q, root in collapsed_of.items()
               if q not in ego or ego[q] != c_ego_by_root[root]}
    collapsed_of = {q: r for q, r in collapsed_of.items() if q in changed}
    c_ego_by_root = {r: g for r, g in c_ego_by_root.items()
                     if r in set(collapsed_of.values())}

    merged = {root: m["members"] for root, m in c_counts.items()
              if len(m["members"]) > 1}
    return {
        "params": {
            "cap": cap, "radius": EGO_RADIUS, "digits": LAYOUT_DIGITS,
            "labeled_threshold": labels["labeled_threshold"],
        },
        "ego": ego,
        "collapsed_ego": c_ego_by_root,
        "collapsed_of": collapsed_of,
        "merged_groups": {r: sorted(m) for r, m in sorted(merged.items())},
        "names": {q: c["name"] for q, c in sorted(counts.items())},
    }
