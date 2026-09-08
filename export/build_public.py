# -*- coding: utf-8 -*-
"""OSM × Wikidata を結合して公開アーティファクトを作る — SPEC F-03 / F-04 / F-08 / F-10。

**属性ごとに出所を残す**(仕様書 §6.1 / RULE-02)。
**伝承年代と史料確認年代を分ける**(F-10 / RULE-04)。Wikidata の P571 は
「成立日」であって社伝の年代とは限らないので、`documented` ではなく
`structured` として別の欄に置く。

    python -m export.build_public
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from etl.entity_resolution import AUTO_THRESHOLD, MatchDecision, resolve
from etl.shrine_family import FAMILY_JA, Basis, classify, family_from_deities, family_from_name
from etl.wikidata_records import load_records
from export.build_geojson import JAPAN_BBOX, in_japan

CATALOG_IN = pathlib.Path("public/data/catalog/shrines.min.json")
ELEVATION_IN = pathlib.Path("data/interim/elevation.json")
RIVER_IN = pathlib.Path("data/interim/river_distance.json")
CATALOG_OUT = pathlib.Path("public/data/catalog/shrines.min.json")
GEOJSON_OUT = pathlib.Path("public/data/osm/shrines.min.geojson")
BUILD_OUT = pathlib.Path("public/data/meta/build.json")
FAMILY_OUT = pathlib.Path("public/data/catalog/families.min.json")


def load_geo() -> tuple[dict[str, Any], dict[str, Any]]:
    """標高と河川距離の中間成果を読む。無ければ空(仮の値を作らない)。"""
    ele = (json.loads(ELEVATION_IN.read_text(encoding="utf-8"))["elevation"]
           if ELEVATION_IN.exists() else {})
    riv = (json.loads(RIVER_IN.read_text(encoding="utf-8"))["river"]
           if RIVER_IN.exists() else {})
    return ele, riv


def merge(osm: list[dict[str, Any]], wd: dict[str, dict[str, Any]]) -> dict[str, Any]:
    wd_list = [r for r in wd.values() if r.get("coord")]
    matches = {m.osm_id: m for m in resolve(osm, wd_list)}

    elevation, rivers = load_geo()
    stats = {
        "matched_auto": 0, "matched_review": 0, "unmatched": 0,
        "with_deities": 0, "with_rank": 0, "with_inception": 0,
        "with_parent": 0, "with_ja_wikipedia": 0,
        "with_elevation": 0, "without_elevation": 0,
        "with_river_distance": 0, "without_river_distance": 0,
    }
    elevations: list[float] = []
    river_distances: list[float] = []
    family_counts: dict[str, int] = {}
    basis_counts: dict[str, int] = {}
    # T-073: 二つの独立な信号(祭神 / 名称)の一致率
    agree = {"both_known": 0, "agree": 0, "disagree": 0, "examples": []}

    out: list[dict[str, Any]] = []
    for r in osm:
        m = matches.get(r["id"])
        w = wd.get(m.qid) if (m and m.qid and m.decision is MatchDecision.AUTO) else None
        if m and m.decision is MatchDecision.AUTO:
            stats["matched_auto"] += 1
        elif m and m.decision is MatchDecision.REVIEW:
            stats["matched_review"] += 1
        else:
            stats["unmatched"] += 1

        deities = (w or {}).get("deities") or []
        ranks = (w or {}).get("ranks") or []
        orgs = (w or {}).get("orgs") or []
        deity_names = [d["name"] for d in deities]

        fam = classify(name=r["name"]["ja"], deities=deity_names, ranks=ranks, orgs=orgs)
        family_counts[fam.label] = family_counts.get(fam.label, 0) + 1
        basis_counts[str(fam.basis)] = basis_counts.get(str(fam.basis), 0) + 1

        # 独立な二信号の突き合わせ(どちらも決まったものだけ数える)
        f_d = family_from_deities(deity_names)[0]
        f_n = family_from_name(r["name"]["ja"])[0]
        if f_d != "unknown" and f_n != "unknown":
            agree["both_known"] += 1
            if f_d == f_n:
                agree["agree"] += 1
            else:
                agree["disagree"] += 1
                if len(agree["examples"]) < 25:
                    agree["examples"].append(
                        {"id": r["id"], "name": r["name"]["ja"],
                         "by_deity": f_d, "by_name": f_n, "deities": deity_names[:5]}
                    )

        rec = dict(r)
        rec["shrine_family"] = {
            "label": fam.label, "label_ja": FAMILY_JA[fam.label],
            "basis": str(fam.basis), "confidence": fam.confidence,
            "alternatives": list(fam.alternatives),
        }
        if w:
            rec["external_ids"] = dict(r["external_ids"], wikidata=w["qid"])
            rec["sources"] = sorted(set(r.get("sources", []) + ["src_wikidata"]))
            rec["match"] = {"score": round(m.score, 4), "distance_m": round(m.distance_m or 0, 1),
                            "name_similarity": round(m.name_sim or 0, 4), "decision": str(m.decision)}
            if deities:
                rec["deities"] = [
                    {"name": d["name"], "wikidata_id": d["wikidata_id"],
                     "source_ids": ["src_wikidata"]} for d in deities
                ]
                stats["with_deities"] += 1
            if ranks:
                rec["shrine_rank"] = {"labels": ranks, "source_ids": ["src_wikidata"]}
                stats["with_rank"] += 1
            if w.get("inception"):
                # **伝承年代ではない。** Wikidata の「成立日」であることを名前で示す。
                rec["foundation"] = {
                    "traditional": {"year_min": None, "year_max": None, "text": None},
                    "documented": {"year_min": None, "year_max": None},
                    "structured": dict(w["inception"], source_ids=["src_wikidata"]),
                }
                stats["with_inception"] += 1
            if w.get("parents"):
                # 文献上の分祀関係(SPEC §43 の「実線」)
                rec["documented_parents"] = {"qids": w["parents"], "source_ids": ["src_wikidata"]}
                stats["with_parent"] += 1
            if w.get("ja_wikipedia"):
                rec["ja_wikipedia"] = w["ja_wikipedia"]
                stats["with_ja_wikipedia"] += 1
            for key in ("kana", "official", "site"):
                if w.get(key) and not rec.get(key):
                    rec[key] = w[key]
        # --- 地理特徴量(F-06 / F-07)。属性ごとに出所を残す ---
        geo: dict[str, Any] = {}
        e = elevation.get(r["id"])
        if e and e.get("elevation_m") is not None:
            geo["elevation_m"] = e["elevation_m"]
            geo["elevation_source"] = e.get("source")
            geo["elevation_source_ids"] = ["src_gsi_dem"]
            elevations.append(e["elevation_m"])
            stats["with_elevation"] += 1
        else:
            stats["without_elevation"] += 1
        v = rivers.get(r["id"])
        if v and v.get("nearest_river_distance_m") is not None:
            geo["nearest_river_distance_m"] = v["nearest_river_distance_m"]
            geo["nearest_river_name"] = v["nearest_river_name"]
            geo["river_source_ids"] = ["src_ksj_w05"]
            river_distances.append(v["nearest_river_distance_m"])
            stats["with_river_distance"] += 1
        else:
            stats["without_river_distance"] += 1
            if v and v.get("reason"):
                geo["nearest_river_note"] = v["reason"]
        # 海岸距離は V1.0 では測らない(C23 の非商用条項。SPEC F-15)
        geo["coast_distance_m"] = None
        if geo:
            rec["geography"] = geo
            if "elevation_m" in geo or "nearest_river_distance_m" in geo:
                rec["sources"] = sorted(set(rec.get("sources", []) +
                                            (["src_gsi_dem"] if "elevation_m" in geo else []) +
                                            (["src_ksj_w05"] if "nearest_river_distance_m" in geo else [])))
        out.append(rec)

    def quantiles(xs: list[float]) -> dict[str, float] | None:
        if not xs:
            return None
        v = sorted(xs)
        q = lambda p: round(v[min(len(v) - 1, int(len(v) * p))], 1)
        return {"min": round(v[0], 1), "p25": q(0.25), "median": q(0.5),
                "p75": q(0.75), "p95": q(0.95), "max": round(v[-1], 1)}

    # T-082: DEM 由来の標高を、OSM の ele タグ(独立な出所)と突き合わせる。
    # **ele はここでしか読まない。** 標高の計算には使っていないので循環しない。
    diffs = []
    for r in out:
        a = r.get("osm_ele")
        b = (r.get("geography") or {}).get("elevation_m")
        if a is not None and b is not None:
            diffs.append(abs(a - b))
    diffs.sort()
    ele_oracle = None
    if diffs:
        ele_oracle = {
            "n": len(diffs),
            "median_abs_diff_m": round(diffs[len(diffs) // 2], 2),
            "within_1m": sum(1 for d in diffs if d <= 1.0),
            "within_5m": sum(1 for d in diffs if d <= 5.0),
            "within_10m": sum(1 for d in diffs if d <= 10.0),
            "max_abs_diff_m": round(diffs[-1], 2),
        }

    return {"shrines": out, "stats": stats, "family_counts": family_counts,
            "elevation_oracle": ele_oracle,
            "elevation_quantiles": quantiles(elevations),
            "river_distance_quantiles": quantiles(river_distances),
            "basis_counts": basis_counts, "signal_agreement": agree}


def feature(rec: dict[str, Any]) -> dict[str, Any]:
    fam = rec.get("shrine_family") or {}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [rec["location"]["lon"], rec["location"]["lat"]]},
        "properties": {
            "id": rec["id"],
            "name": rec["name"]["ja"],
            "prefecture": rec["location"]["prefecture"],
            "family": fam.get("label", "unknown"),
            "ai": False,
        },
    }


def main() -> int:
    osm = json.loads(CATALOG_IN.read_text(encoding="utf-8"))["shrines"]
    wd = load_records()
    merged = merge(osm, wd)
    recs = merged["shrines"]

    # 不変量(G-03 / G-04)。黙って壊れた出力を配らない。
    ids = [r["id"] for r in recs]
    assert len(set(ids)) == len(ids), "神社 ID が重複している"
    for r in recs:
        assert in_japan(r["location"]["lon"], r["location"]["lat"]), r["id"]
        assert r.get("sources"), r["id"]

    fc = {"type": "FeatureCollection",
          "attribution": "© OpenStreetMap contributors (ODbL) / Wikidata (CC0)",
          "features": [feature(r) for r in recs]}
    for p in (CATALOG_OUT, GEOJSON_OUT, BUILD_OUT, FAMILY_OUT):
        p.parent.mkdir(parents=True, exist_ok=True)
    GEOJSON_OUT.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    CATALOG_OUT.write_text(json.dumps({"shrines": recs}, ensure_ascii=False, separators=(",", ":")),
                           encoding="utf-8")
    FAMILY_OUT.write_text(json.dumps(
        {"labels": FAMILY_JA, "counts": merged["family_counts"], "basis": merged["basis_counts"]},
        ensure_ascii=False, indent=1), encoding="utf-8")

    named = sum(1 for r in recs if r["name"]["ja"])
    agree = merged["signal_agreement"]
    report = {
        "shrines": len(recs),
        "with_name": named,
        "without_name": len(recs) - named,
        "with_osm_wikidata_tag": sum(1 for r in recs if r["external_ids"].get("osm_wikidata_tag")),
        "wikidata_records_with_coord": sum(1 for r in wd.values() if r.get("coord")),
        **merged["stats"],
        "family_counts": merged["family_counts"],
        "family_basis": merged["basis_counts"],
        "elevation_oracle": merged["elevation_oracle"],
        "elevation_quantiles": merged["elevation_quantiles"],
        "river_distance_quantiles": merged["river_distance_quantiles"],
        "signal_agreement": {
            "both_known": agree["both_known"], "agree": agree["agree"],
            "disagree": agree["disagree"],
            "rate": round(agree["agree"] / agree["both_known"], 4) if agree["both_known"] else None,
        },
        "bytes_geojson": GEOJSON_OUT.stat().st_size,
        "bytes_catalog": CATALOG_OUT.stat().st_size,
        "japan_bbox": list(JAPAN_BBOX),
    }
    BUILD_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    pathlib.Path("data/reports").mkdir(parents=True, exist_ok=True)
    pathlib.Path("data/reports/signal_disagreements.json").write_text(
        json.dumps(agree["examples"], ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
