# -*- coding: utf-8 -*-
"""祭神の公開アーティファクトを作る — SPEC §7.14 / F-03 / F-14 / G-16〜G-20。

    python -m export.build_deity

出すもの(`public/data/deity/`):

- `index.json`  — 祭神 580 柱の一覧と総数(件数は数え直した値であって定数ではない)
- `points.json` — 祭神つき社の点(地図で光らせるためだけの最小限の欄)
- `detail.json` — 祭神ごとの県別リフトと、その祭神を祀る社の ID
- `network.json`— 共祀ネットワーク(ノード・辺・**ビルド時に決めた座標**)
- `pairs.json`  — 習合の対応表(凍結した手分類)
- `report.json` — G-16 / G-17 / G-20 の実測。**画面の文はここに従う**

**県を塗らない。** オオヤマツミの愛媛は 7 社である。7 社を県全体に塗ると、
リフト 11.8 倍という正しい数字が面積という嘘になる。点で出す。
"""
from __future__ import annotations

import gzip
import json
import pathlib
import random
from collections import Counter
from typing import Any

from etl import deity_stats as ds

OUT_DIR = pathlib.Path("public/data/deity")
HEAD_SHRINES = pathlib.Path("data/reference/head_shrines.json")

#: G-16 の合格線。**実装前に人間が承認して凍結した。測ってから書き換えない。**
G16_THRESHOLD = 13
#: G-17 の閾値。
G17_THRESHOLD = 0.70
#: 帰無分布の試行数と種。
NULL_TRIALS = 200
NULL_SEED = 20260921

_COMPACT = {"ensure_ascii": False, "separators": (",", ":")}


def _write(name: str, doc: Any) -> int:
    p = OUT_DIR / name
    p.write_text(json.dumps(doc, **_COMPACT), encoding="utf-8")
    return p.stat().st_size


def _load_head_shrines() -> dict[str, Any]:
    doc = json.loads(HEAD_SHRINES.read_text(encoding="utf-8"))
    if doc.get("_status") != "approved_frozen":
        raise ValueError("承認されていない総本社の表を使おうとしている")
    return doc


def null_distribution(rows: list[ds.Row], entries: list[dict[str, Any]],
                      observed: int) -> dict[str, Any]:
    """祭神の割り当てを社のあいだで振り直した帰無分布(G-20)。

    社ごとの祭神の数と、祭神の総出現数は保ったまま、**どの社に付くかだけ**を崩す。
    """
    rng = random.Random(NULL_SEED)
    prefs = [r["pref"] for r in rows]
    hits: list[int] = []
    for _ in range(NULL_TRIALS):
        shuffled = prefs[:]
        rng.shuffle(shuffled)
        permuted = [{**r, "pref": p} for r, p in zip(rows, shuffled)]
        hits.append(ds.head_shrine_agreement(
            permuted, entries, floor=ds.MIN_PREF_SHRINES)[0])
    hits.sort()
    p = (sum(1 for h in hits if h >= observed) + 1) / (NULL_TRIALS + 1)
    return {
        "trials": NULL_TRIALS, "seed": NULL_SEED, "observed": observed,
        "mean": round(sum(hits) / len(hits), 3),
        "p95": hits[int(0.95 * len(hits))], "max": hits[-1],
        "p_value": round(p, 4), "pass": observed > hits[int(0.95 * len(hits))],
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = ds.load_mentions()
    if not rows:
        print("祭神を持つ社が 1 件も無い。何も作らない(空の出荷物を作らない)")
        return 1

    shrines_total = ds.count_all_shrines()
    counts = ds.deity_counts(rows)
    base = ds.prefecture_base(rows)
    labels = ds.load_pair_labels()
    head = _load_head_shrines()

    # ---- 一覧
    deities = sorted(counts.values(), key=lambda d: (-d["n"], d["qid"]))
    mentions = sum(len(r["qids"]) for r in rows)
    index = {
        "totals": {
            "mentions": mentions,
            "shrines_with_deities": len(rows),
            "shrines_total": shrines_total,
            "deities": len(counts),
        },
        "deities": deities,
    }

    # ---- 点(地図で光らせるための最小限。座標は小数 5 桁で十分)
    points = {"shrines": [{
        "id": r["id"], "name": r["name"], "pref": r["pref"],
        "lat": round(r["lat"], 5), "lon": round(r["lon"], 5),
    } for r in sorted(rows, key=lambda r: r["id"])]}

    # ---- 祭神ごとの県別リフトと社
    by_deity: dict[str, dict[str, Any]] = {}
    ids_by_deity: dict[str, list[str]] = {}
    for r in rows:
        for q in r["qids"]:
            ids_by_deity.setdefault(q, []).append(r["id"])
    for q in counts:
        by_deity[q] = {
            "prefs": ds.lift_rows(rows, q, base=base),
            "ids": sorted(ids_by_deity[q]),
        }
    detail = {"floor": ds.MIN_PREF_SHRINES, "deities": by_deity}

    # ---- 祭神ごとの「まわりの図」(畳む前と畳んだ後)
    network = ds.build_network(rows, labels=labels)

    # ---- 習合の対応表
    pair_n = ds.pair_counts(rows)
    threshold = labels["labeled_threshold"]
    labeled_keys = {frozenset((p["a_qid"], p["b_qid"])) for p in labels["pairs"]}
    pairs_doc = {
        "threshold": threshold,
        "types": labels["_types"],
        "pairs": sorted(
            [{**{k: p[k] for k in ("a", "a_qid", "b", "b_qid", "type")},
              "note": p.get("note"),
              "w": pair_n.get(tuple(sorted((p["a_qid"], p["b_qid"]))), 0)}
             for p in labels["pairs"]],
            key=lambda d: (-d["w"], d["a_qid"], d["b_qid"])),
    }
    unlabeled_at_threshold = sorted(
        ({"a": counts[a]["name"], "b": counts[b]["name"], "w": w}
         for (a, b), w in pair_n.items()
         if w >= threshold and frozenset((a, b)) not in labeled_keys),
        key=lambda d: (-d["w"], d["a"], d["b"]))

    # ---- G-16(測って落ちた予測) / G-20(帰無分布) / G-17(同一視の予測可能性)
    hit, total, detail_rows = ds.head_shrine_agreement(
        rows, head["entries"], floor=ds.MIN_PREF_SHRINES)
    for row, entry in zip(detail_rows, head["entries"]):
        # 外れた理由を数で残す —— 総本社の県にその祭神が何社あるか
        mine = Counter(r["pref"] for r in rows if entry["deity_qid"] in r["qids"])
        row["head_pref_n"] = mine.get(entry["prefecture"], 0)
        row["head_pref_base"] = base[entry["prefecture"]]
        row["below_floor"] = row["head_pref_n"] < ds.MIN_PREF_SHRINES
        # 地図に総本社のピンを置くための座標(凍結表が持っている検証済みの値)
        row["lat"] = entry["lat"]
        row["lon"] = entry["lon"]

    g16 = {
        "threshold": G16_THRESHOLD, "floor": ds.MIN_PREF_SHRINES,
        "hit": hit, "total": total, "pass": hit >= G16_THRESHOLD,
        "rows": detail_rows,
        "misses_below_floor": sum(1 for r in detail_rows
                                  if not r["hit"] and r["below_floor"]),
    }
    g20 = null_distribution(rows, head["entries"], hit)
    g17 = ds.syncretism_predictability(rows, labels["pairs"],
                                       threshold=G17_THRESHOLD)

    report = {
        "g16": g16,
        "g20": g20,
        "g17": g17,
        "pairs": {
            "labeled": len(labels["pairs"]),
            "threshold": threshold,
            "unlabeled_at_threshold": len(unlabeled_at_threshold),
            "unlabeled_examples": unlabeled_at_threshold[:10],
            "by_type": dict(sorted(Counter(
                p["type"] for p in labels["pairs"]).items())),
        },
        "network": {
            "cap": ds.EGO_MAX_NEIGHBOURS,
            "deities_with_ego": len(network["ego"]),
            "deities_total": len(counts),
            "merged_groups": len(network["merged_groups"]),
            "merged_deities": sum(len(m) for m in
                                  network["merged_groups"].values()),
            "pairs_total": len(pair_n),
            "by_type": {
                **dict(sorted(Counter(p["type"] for p in labels["pairs"]).items())),
                "unlabeled": len(pair_n) - len(labels["pairs"]),
            },
        },
    }

    written = {
        "index.json": _write("index.json", index),
        "points.json": _write("points.json", points),
        "detail.json": _write("detail.json", detail),
        "network.json": _write("network.json", network),
        "pairs.json": _write("pairs.json",
                             {**pairs_doc,
                              "unlabeled_at_threshold": unlabeled_at_threshold}),
        "report.json": _write("report.json", report),
    }
    sizes = {name: {"bytes": n,
                    "gzip": len(gzip.compress((OUT_DIR / name).read_bytes()))}
             for name, n in written.items()}

    print(json.dumps({
        "totals": index["totals"],
        "network": report["network"],
        "pairs": report["pairs"],
        "g16": {k: g16[k] for k in
                ("hit", "total", "threshold", "pass", "misses_below_floor")},
        "g20": {k: g20[k] for k in ("observed", "mean", "p95", "p_value", "pass")},
        "g17": {k: g17[k] for k in ("k", "correct", "precision", "pass")},
        "bytes": sizes,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
