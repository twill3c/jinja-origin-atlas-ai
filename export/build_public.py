# -*- coding: utf-8 -*-
"""OSM × Wikidata を結合して公開アーティファクトを作る — SPEC F-03 / F-04 / F-08 / F-10 / D-06。

**属性ごとに出所を残す**(仕様書 §6.1 / RULE-02)。
**伝承年代と史料確認年代を分ける**(F-10 / RULE-04)。Wikidata の P571 は
「成立日」であって社伝の年代とは限らないので、`documented` ではなく
`structured` として別の欄に置く。

**決定 D-06 — 全カタログを公開物に置かない。** 全国 40,776 件では 33.7 MB になる。
配るのは都道府県ごとのチャンク(`public/data/shrines/NN.json`)と、ID から県を引く索引
(`public/data/shrines/index.json`)。神社詳細と類似の画面は、索引で県を引き、
その県のチャンクだけを読む。**AI の欄と類似の相手もチャンクに入れる** —— 詳細を開くのに
別のファイルを何本も引かせない。全カタログは検査と下流の ETL のために
`data/interim/catalog_full.json` に置く(配らない)。

    python -m export.build_public
"""
from __future__ import annotations

import json
import pathlib
from collections import defaultdict
from typing import Any

from etl.entity_resolution import MatchDecision, resolve, resolve_one_to_one
from export.dedupe import merge_same_name, part_suffix, same_name_pairs
from etl.prefectures import PREF_CODE_NAME
from etl.shrine_family import FAMILY_JA, classify, family_from_deities, family_from_name
from etl.wikidata_records import load_records
from export.build_geojson import JAPAN_BBOX, in_japan

CATALOG_IN = pathlib.Path("data/interim/catalog_osm.json")
OSM_REPORT_IN = pathlib.Path("data/interim/osm_report.json")
ELEVATION_IN = pathlib.Path("data/interim/elevation.json")
RIVER_IN = pathlib.Path("data/interim/river_distance.json")
AI_IN = pathlib.Path("public/data/ai/ai.min.json")
SIM_IN = pathlib.Path("public/data/ai/similarity.min.json")

FULL_OUT = pathlib.Path("data/interim/catalog_full.json")
CHUNK_DIR = pathlib.Path("public/data/shrines")
INDEX_OUT = CHUNK_DIR / "index.json"
#: 類似の相手は**県チャンクに入れない**。東京都のチャンクで測ると欄の 52.6%(1 件あたり
#: 3,548 バイト)を占めており、詳細を見るだけの人には要らない(2026-09-11 実測)。
SIMILAR_DIR = pathlib.Path("public/data/similar")
GEOJSON_OUT = pathlib.Path("public/data/osm/shrines.min.geojson")
BUILD_OUT = pathlib.Path("public/data/meta/build.json")
FAMILY_OUT = pathlib.Path("public/data/catalog/families.min.json")
#: D-06 以前に配っていた全カタログ。残っていると 33.7 MB を配り続けるので消す。
LEGACY_CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")

_COMPACT = {"ensure_ascii": False, "separators": (",", ":")}


def _read(p: pathlib.Path, default: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def load_geo() -> tuple[dict[str, Any], dict[str, Any]]:
    """標高と河川距離の中間成果を読む。無ければ空(仮の値を作らない)。"""
    return (_read(ELEVATION_IN, {"elevation": {}})["elevation"],
            _read(RIVER_IN, {"river": {}})["river"])


def top_motifs(percentiles: dict[str, float], n: int = 3) -> list[str]:
    """**順位で**上位を取る(D-05)。生スコアで取ると 66% の神社で同じモチーフが 1 位になる。"""
    return [k for k, _ in sorted(percentiles.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def merge(osm: list[dict[str, Any]], wd: dict[str, dict[str, Any]],
          ai_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    wd_list = [r for r in wd.values() if r.get("coord")]
    # D-08: 同じ社を指す地物を先に一つにまとめ、名寄せは一対一で行う。
    # 多対一の結果は「別の項目どうしだから統合しない」の判定にだけ使う。
    many = {m.osm_id: m for m in resolve(osm, wd_list)}
    per_item: dict[str, int] = {}
    for m in many.values():
        if m.qid and m.decision is MatchDecision.AUTO:
            per_item[m.qid] = per_item.get(m.qid, 0) + 1
    osm_features = len(osm)
    dd = merge_same_name(osm, many)
    osm = dd.survivors
    matches = {m.osm_id: m for m in resolve_one_to_one(osm, wd_list)}

    elevation, rivers = load_geo()
    # AI の対象(§59 —— 位置レイヤーと分けて数える)。スコアはチャンクに入れる
    ai_by_id = {x["id"]: x for x in (ai_doc or {}).get("shrines", [])}

    stats = {
        "matched_auto": 0, "matched_review": 0, "unmatched": 0,
        "with_deities": 0, "with_rank": 0, "with_inception": 0,
        "with_parent": 0, "with_ja_wikipedia": 0,
        "with_elevation": 0, "without_elevation": 0,
        "with_river_distance": 0, "without_river_distance": 0,
        "suspected_parts": 0, "ai_without_article": 0,
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
        # T-128: 社殿・境内の部分を指す語で終わる名前。**統合はしない**(D-08)
        suf = part_suffix(r["name"]["ja"])
        if suf:
            rec["suspected_part"] = {"suffix": suf,
                                     "note": "名前が社殿・境内の部分を指す語で終わる。本社とは別に数えている"}
            stats["suspected_parts"] += 1
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
        rec["geography"] = geo
        if "elevation_m" in geo or "nearest_river_distance_m" in geo:
            rec["sources"] = sorted(set(rec.get("sources", []) +
                                        (["src_gsi_dem"] if "elevation_m" in geo else []) +
                                        (["src_ksj_w05"] if "nearest_river_distance_m" in geo else [])))

        # --- AI(F-09)。**配るのはスコアと帰属だけ**(D-01) ---
        a = ai_by_id.get(r["id"])
        if a is not None and not rec.get("ja_wikipedia"):
            # 名寄せが変わって記事を持たなくなった神社に、前回の AI 結果を付けない
            stats["ai_without_article"] += 1
            a = None
        rec["ai"] = a is not None
        if a is not None:
            rec["ai_scores"] = {
                "motif_percentiles": a["motif_percentiles"],
                "cluster": a["cluster"],
                "source": {k: a["source"][k] for k in ("title", "revid", "url", "license")},
            }
        out.append(rec)

    def quantiles(xs: list[float]) -> dict[str, float] | None:
        if not xs:
            return None
        s = sorted(xs)
        q = lambda p: round(s[min(len(s) - 1, int(len(s) * p))], 1)
        return {"min": round(s[0], 1), "p25": q(0.25), "median": q(0.5),
                "p75": q(0.75), "p95": q(0.95), "max": round(s[-1], 1)}

    # T-082: DEM 由来の標高を、OSM の ele タグ(独立な出所)と突き合わせる。
    # **ele はここでしか読まない。** 標高の計算には使っていないので循環しない。
    diffs = sorted(abs(r["osm_ele"] - r["geography"]["elevation_m"])
                   for r in out
                   if r.get("osm_ele") is not None and r["geography"].get("elevation_m") is not None)
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
            "basis_counts": basis_counts, "signal_agreement": agree,
            "aliases": dd.aliases,
            "dedupe": {
                "osm_features": osm_features,
                "merged_features": len(dd.aliases),
                "merged_components": dd.merged_components,
                "guarded_pairs": dd.guarded_pairs,
                "guarded_components": dd.guarded_components,
                "items_matched_to_multiple_features_before": sum(1 for n in per_item.values() if n > 1),
                "suspected_parts": stats["suspected_parts"],
            }}


def attach_similar(recs: list[dict[str, Any]], neighbors: dict[str, list]) -> int:
    """類似の相手をチャンクに入れる。**相手の名前・県・系統・上位モチーフも書き込む** ——
    相手は別の県のチャンクにいることが多く、詳細を開くたびに何本も引かせないため。

    :returns: カタログに見つからなかった相手の数(0 のはず。数えて報告する)
    """
    by_id = {r["id"]: r for r in recs}
    missing = 0
    for r in recs:
        lst = neighbors.get(r["id"])
        if not lst:
            continue
        sim = []
        for other, score in lst:
            o = by_id.get(other)
            if o is None:
                missing += 1
                continue
            sim.append({
                "id": other,
                "score": score,
                "name": o["name"]["ja"],
                "p": o["location"]["pref_code"],
                "prefecture": o["location"]["prefecture"],
                "family_ja": o["shrine_family"]["label_ja"],
                "top3": top_motifs(o["ai_scores"]["motif_percentiles"]) if o.get("ai_scores") else [],
                "cluster": o["ai_scores"]["cluster"]["id"] if o.get("ai_scores") else None,
            })
        r["similar"] = sim
    return missing


def feature(rec: dict[str, Any]) -> dict[str, Any]:
    fam = rec.get("shrine_family") or {}
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [rec["location"]["lon"], rec["location"]["lat"]]},
        "properties": {
            "id": rec["id"],
            "name": rec["name"]["ja"],
            "prefecture": rec["location"]["prefecture"],
            # 詳細画面が索引を引かずに済むよう、県コードも持たせる
            "p": rec["location"]["pref_code"],
            "family": fam.get("label", "unknown"),
            "ai": bool(rec.get("ai")),
        },
    }


def write_chunks(recs: list[dict[str, Any]], ai_doc: dict[str, Any] | None,
                 aliases: dict[str, str] | None = None) -> dict[str, Any]:
    """都道府県ごとのチャンクと索引を書く(D-06)。"""
    no_pref = [r["id"] for r in recs if not r["location"].get("pref_code")]
    if no_pref:
        # 県別に取得していれば起きない。起きたら全国ファイルが混じった疑い
        raise RuntimeError(f"県コードの無いレコードが {len(no_pref)} 件ある(例 {no_pref[:3]})")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in recs:
        groups[r["location"]["pref_code"]].append(r)

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    # 前回のビルドで作ったが今回は無い県のチャンクを残さない
    for stale in CHUNK_DIR.glob("[0-9][0-9].json"):
        if stale.stem not in groups:
            stale.unlink()

    # 詳細画面が索引を引かずに済むよう、表示に要る小さな付帯情報は各チャンクにも持たせる
    ai_count = sum(1 for r in recs if r.get("ai"))
    motif_labels = (ai_doc or {}).get("motif_labels", {})
    sizes = {}
    for code in sorted(groups):
        p = CHUNK_DIR / f"{code}.json"
        # `similar` はここに入れない(別ファイル。write_similar を見よ)
        slim = [{k: v for k, v in r.items() if k != "similar"} for r in groups[code]]
        p.write_text(json.dumps({"pref_code": code, "prefecture": PREF_CODE_NAME[code],
                                 "ai_count": ai_count, "motif_labels": motif_labels,
                                 "shrines": slim}, **_COMPACT), encoding="utf-8")
        sizes[code] = p.stat().st_size

    INDEX_OUT.write_text(json.dumps({
        "ids": {r["id"]: r["location"]["pref_code"] for r in recs},
        # D-08: 統合で消えた ID → 残った ID。旧 URL はこれで残った神社を開く(T-127)
        "aliases": aliases or {},
        "prefectures": {c: {"name": PREF_CODE_NAME[c], "count": len(groups[c])} for c in sorted(groups)},
        "ai_count": sum(1 for r in recs if r.get("ai")),
        "motif_labels": (ai_doc or {}).get("motif_labels", {}),
    }, **_COMPACT), encoding="utf-8")

    return {"chunks": len(groups), "bytes_chunks": sum(sizes.values()),
            "bytes_chunk_max": max(sizes.values()), "bytes_index": INDEX_OUT.stat().st_size}


def write_similar(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """類似の相手を県ごとの別ファイルに書く。

    **詳細を開くだけの人に配らない。** 東京都のチャンクでは `similar` が欄の 52.6% を
    占めていた(2026-09-11 実測)。類似の画面だけがこのファイルを引く。
    """
    groups: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in recs:
        if r.get("similar"):
            groups[r["location"]["pref_code"]][r["id"]] = r["similar"]

    SIMILAR_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SIMILAR_DIR.glob("[0-9][0-9].json"):
        if stale.stem not in groups:
            stale.unlink()

    total = 0
    for code in sorted(groups):
        p = SIMILAR_DIR / f"{code}.json"
        p.write_text(json.dumps({"pref_code": code, "similar": groups[code]}, **_COMPACT),
                     encoding="utf-8")
        total += p.stat().st_size
    return {"similar_files": len(groups), "bytes_similar": total,
            "shrines_with_similar": sum(len(g) for g in groups.values())}


def main() -> int:
    osm = json.loads(CATALOG_IN.read_text(encoding="utf-8"))["shrines"]
    osm_report = _read(OSM_REPORT_IN, {})
    ai_doc = _read(AI_IN, None)
    wd = load_records()
    merged = merge(osm, wd, ai_doc)
    recs = merged["shrines"]
    missing_neighbors = attach_similar(recs, _read(SIM_IN, {"neighbors": {}})["neighbors"])

    # 不変量(G-03 / G-04)。黙って壊れた出力を配らない。
    ids = [r["id"] for r in recs]
    assert len(set(ids)) == len(ids), "神社 ID が重複している"
    for r in recs:
        assert in_japan(r["location"]["lon"], r["location"]["lat"]), r["id"]
        assert r.get("sources"), r["id"]

    for p in (FULL_OUT, GEOJSON_OUT, BUILD_OUT, FAMILY_OUT):
        p.parent.mkdir(parents=True, exist_ok=True)
    FULL_OUT.write_text(json.dumps({"shrines": recs}, **_COMPACT), encoding="utf-8")
    chunk_report = write_chunks(recs, ai_doc, merged["aliases"])
    chunk_report |= write_similar(recs)
    if LEGACY_CATALOG.exists():
        LEGACY_CATALOG.unlink()

    fc = {"type": "FeatureCollection",
          "attribution": "© OpenStreetMap contributors (ODbL) / Wikidata (CC0)",
          "features": [feature(r) for r in recs]}
    GEOJSON_OUT.write_text(json.dumps(fc, **_COMPACT), encoding="utf-8")
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
        "with_ai": sum(1 for r in recs if r.get("ai")),
        "without_ai": sum(1 for r in recs if not r.get("ai")),
        "similar_missing_neighbors": missing_neighbors,
        "dedupe": {**merged["dedupe"], "guarded_pairs_remaining": len(same_name_pairs(recs))},
        "osm_dropped": osm_report.get("dropped", {}),
        "elevation_oracle": merged["elevation_oracle"],
        "elevation_quantiles": merged["elevation_quantiles"],
        "river_distance_quantiles": merged["river_distance_quantiles"],
        "signal_agreement": {
            "both_known": agree["both_known"], "agree": agree["agree"],
            "disagree": agree["disagree"],
            "rate": round(agree["agree"] / agree["both_known"], 4) if agree["both_known"] else None,
        },
        "bytes_geojson": GEOJSON_OUT.stat().st_size,
        # 配っているカタログの総量(チャンクの合計)。D-06 以前の単一ファイルとは意味が違う
        "bytes_catalog": chunk_report["bytes_chunks"],
        **chunk_report,
        "japan_bbox": list(JAPAN_BBOX),
    }
    BUILD_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    pathlib.Path("data/reports").mkdir(parents=True, exist_ok=True)
    pathlib.Path("data/reports/signal_disagreements.json").write_text(
        json.dumps(agree["examples"], ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({k: v for k, v in report.items() if k not in ("family_counts",)},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
