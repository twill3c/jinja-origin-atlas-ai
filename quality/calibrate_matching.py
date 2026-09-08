# -*- coding: utf-8 -*-
"""名寄せの閾値を非循環オラクルから較正する — SPEC G-09 / HC-229。

**較正に使った標本で報告しない。** オラクルのペアを QID のハッシュで決定的に半分に割り、
片方(calibration)で閾値を決め、もう片方(holdout)で数字を出す。
同じ標本で決めて同じ標本で報告すると、何も分からない。

オラクルの出所は二方向:
  - OSM 側: 要素の `wikidata=Q…` タグ
  - Wikidata 側: P10689(way)/ P11693(node)/ P402(relation)

**マッチャーはどちらも入力に使わない**(D-02)。

    python -m quality.calibrate_matching
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

from etl.entity_resolution import match_score, resolve
from etl.wikidata_records import load_oracle_pairs, load_records

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
REPORT = pathlib.Path("data/reports/matching_calibration.json")


def load_osm() -> list[dict[str, Any]]:
    return json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]


def build_oracle(osm: list[dict[str, Any]], wd: dict[str, Any]) -> dict[str, dict[str, str]]:
    """OSM の神社 ID → {qid, direction}。両方向から作る。

    衝突(両方向が違う QID を指す)は、どちらも信じずに落とす。
    """
    by_osm_key = {(r["external_ids"]["osm_type"], r["external_ids"]["osm_id"]): r for r in osm}
    wd_side = load_oracle_pairs()

    pairs: dict[str, dict[str, str]] = {}
    conflicts = 0

    for r in osm:  # OSM 側のタグ
        qid = r["external_ids"].get("osm_wikidata_tag")
        if qid and qid in wd:
            pairs[r["id"]] = {"qid": qid, "direction": "osm_tag"}

    for key, qid in wd_side.items():  # Wikidata 側の ID
        r = by_osm_key.get(key)
        if not r or qid not in wd:
            continue
        prev = pairs.get(r["id"])
        if prev and prev["qid"] != qid:
            conflicts += 1
            pairs.pop(r["id"], None)
            continue
        pairs[r["id"]] = {"qid": qid, "direction": "both" if prev else "wd_id"}

    return {"pairs": pairs, "conflicts": conflicts}


def split(osm_id: str) -> str:
    """決定的な 50/50 分割。QID ではなく OSM ID で割る(片側に寄らないように)。"""
    h = hashlib.sha256(osm_id.encode("utf-8")).digest()[0]
    return "calibration" if h % 2 == 0 else "holdout"


def main() -> int:
    osm = load_osm()
    wd = load_records()
    wd_list = [r for r in wd.values() if r.get("coord")]

    built = build_oracle(osm, wd)
    oracle = built["pairs"]
    print(f"OSM {len(osm)} 件 / Wikidata(座標あり) {len(wd_list)} 件")
    print(f"オラクルのペア {len(oracle)} 組(衝突で落としたもの {built['conflicts']} 組)")
    dirs: dict[str, int] = {}
    for v in oracle.values():
        dirs[v["direction"]] = dirs.get(v["direction"], 0) + 1
    print("  方向の内訳:", dirs)

    matches = {m.osm_id: m for m in resolve(osm, wd_list)}

    # オラクルの各組について「正解の相手」に付いたスコアと、実際に選ばれた相手を見る
    wd_by_qid = {r["qid"]: r for r in wd_list}
    osm_by_id = {r["id"]: r for r in osm}
    rows = []
    for osm_id, info in oracle.items():
        truth = info["qid"]
        m = matches.get(osm_id)
        w = wd_by_qid.get(truth)
        truth_score = match_score(osm_by_id[osm_id], w).total if w else 0.0
        rows.append({
            "osm_id": osm_id,
            "split": split(osm_id),
            "truth_qid": truth,
            "picked_qid": m.qid if m else None,
            "picked_score": m.score if m else 0.0,
            "truth_score": truth_score,
            "correct_top1": bool(m and m.qid == truth),
        })

    def report(rs: list[dict[str, Any]], name: str, threshold: float | None = None) -> dict[str, Any]:
        n = len(rs)
        top1 = sum(1 for r in rs if r["correct_top1"])
        d = {"split": name, "n": n, "top1_correct": top1,
             "top1_rate": round(top1 / n, 4) if n else None}
        if threshold is not None:
            kept = [r for r in rs if r["picked_score"] >= threshold]
            tp = sum(1 for r in kept if r["correct_top1"])
            d |= {
                "threshold": threshold,
                "auto_merged": len(kept),
                "auto_correct": tp,
                "precision": round(tp / len(kept), 4) if kept else None,
                "recall": round(tp / n, 4) if n else None,
            }
        return d

    cal = [r for r in rows if r["split"] == "calibration"]
    hold = [r for r in rows if r["split"] == "holdout"]
    print(f"\n較正 {len(cal)} 組 / 取り置き {len(hold)} 組")
    print("較正側 top-1 一致:", report(cal, "calibration"))

    # 較正側で閾値の候補を掃く
    print("\n較正側の閾値掃き(この結果だけを見て閾値を決める):")
    sweep = []
    for t in [round(x * 0.01, 2) for x in range(50, 91, 2)]:
        d = report(cal, "calibration", t)
        sweep.append(d)
        print(f"  {t:.2f}  自動 {d['auto_merged']:4d}  適合率 {d['precision']}  再現率 {d['recall']}")

    # 正解に付いたスコアの分布(閾値をどこに置けるかの目安)
    ts = sorted(r["truth_score"] for r in cal)
    if ts:
        def pct(p):
            return round(ts[int(len(ts) * p)], 4)
        print(f"\n較正側・正解ペアのスコア分布: 最小 {ts[0]:.4f} / 5% {pct(0.05)} / "
              f"25% {pct(0.25)} / 中央 {pct(0.5)} / 最大 {ts[-1]:.4f}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "osm_records": len(osm),
        "wikidata_records_with_coord": len(wd_list),
        "oracle_pairs": len(oracle),
        "oracle_conflicts": built["conflicts"],
        "oracle_directions": dirs,
        "calibration_n": len(cal),
        "holdout_n": len(hold),
        "calibration_sweep": sweep,
        "rows": rows,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
