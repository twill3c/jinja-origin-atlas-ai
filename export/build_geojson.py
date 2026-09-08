# -*- coding: utf-8 -*-
"""生の Overpass 応答 → 公開用 GeoJSON / カタログ — SPEC F-01 / G-01 / G-03 / G-04。

神社 ID は **OSM の要素 ID から決定的に導く**(`jinja_w123456789`)。
仕様書 §7.1 の `jinja_000001` は例示であって形式の規定ではない。連番にすると
データが動くたびに ID が入れ替わり、`/shrine/[id]` の URL が壊れる。

**`wikidata` タグは GeoJSON にも カタログにも出すが、名寄せの入力には使わない**
(SPEC §7 / D-02)。この対応は名寄せの非循環オラクルであり、入力に混ぜると
オラクルが恒等式になる。
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
from typing import Any, Iterable

from etl.normalize import normalize_name

RAW_GLOB = "data/raw/osm/shrines_overpass_*.json"
OUT_GEOJSON = pathlib.Path("public/data/osm/shrines.min.geojson")
OUT_CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
OUT_BUILD = pathlib.Path("public/data/meta/build.json")

#: 日本の外接矩形(G-04)。与那国島(東経 122.9)〜南鳥島(153.98)、
#: 沖ノ鳥島(北緯 20.42)〜択捉島北端(45.55)を含む。
JAPAN_BBOX = (122.0, 20.2, 154.1, 45.8)

_ID_PREFIX = {"node": "n", "way": "w", "relation": "r"}

_ELE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)")


def _parse_ele(value: Any) -> float | None:
    """OSM の `ele` タグを数値にする。解釈できなければ None(推測で埋めない)。"""
    if value is None:
        return None
    m = _ELE.match(str(value))
    return float(m.group(1)) if m else None


def shrine_id(el: dict[str, Any]) -> str:
    return f"jinja_{_ID_PREFIX[el['type']]}{el['id']}"


def coordinates(el: dict[str, Any]) -> tuple[float, float] | None:
    """(lon, lat)。node は lat/lon、way/relation は out center の center を使う。"""
    if "lat" in el and "lon" in el:
        return float(el["lon"]), float(el["lat"])
    c = el.get("center")
    if c:
        return float(c["lon"]), float(c["lat"])
    return None


def in_japan(lon: float, lat: float) -> bool:
    x0, y0, x1, y1 = JAPAN_BBOX
    return x0 <= lon <= x1 and y0 <= lat <= y1


def load_raw(pattern: str = RAW_GLOB) -> list[dict[str, Any]]:
    els: list[dict[str, Any]] = []
    for p in sorted(glob.glob(pattern)):
        els += json.loads(pathlib.Path(p).read_text(encoding="utf-8"))["elements"]
    return els


def to_records(elements: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """OSM 要素 → 神社レコード。落としたものは理由ごとに数える。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    dropped = {"座標なし": 0, "日本の外接矩形外": 0, "ID 重複": 0}

    for el in elements:
        xy = coordinates(el)
        if xy is None:
            dropped["座標なし"] += 1
            continue
        lon, lat = xy
        if not in_japan(lon, lat):
            dropped["日本の外接矩形外"] += 1
            continue
        sid = shrine_id(el)
        if sid in seen:
            dropped["ID 重複"] += 1
            continue
        seen.add(sid)

        t = el.get("tags") or {}
        name_ja = normalize_name(t.get("name:ja") or t.get("name"))
        out.append(
            {
                "id": sid,
                "name": {
                    "ja": name_ja or None,
                    "kana": normalize_name(t.get("name:ja-Hira") or t.get("name:ja_kana")) or None,
                    "en": normalize_name(t.get("name:en")) or None,
                },
                "aliases": [
                    a for a in (normalize_name(t.get("alt_name")), normalize_name(t.get("official_name")))
                    if a and a != name_ja
                ],
                "location": {
                    "lat": round(lat, 7),
                    "lon": round(lon, 7),
                    "prefecture": t.get("addr:province"),
                    "municipality": t.get("addr:city"),
                },
                "external_ids": {
                    "osm_type": el["type"],
                    "osm_id": el["id"],
                    # 名寄せの入力に使ってはならない(D-02)。オラクルとして別経路で読む
                    "osm_wikidata_tag": t.get("wikidata"),
                    "wikipedia": t.get("wikipedia"),
                },
                # **標高のオラクル専用**(T-082)。OSM 投稿者が記録した標高であり、
                # DEM から求める標高の計算には一切使わない。使えば循環する。
                "osm_ele": _parse_ele(t.get("ele")),
                "website": t.get("website"),
                "sources": ["src_osm"],
            }
        )
    return out, dropped


def feature(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [rec["location"]["lon"], rec["location"]["lat"]]},
        "properties": {
            "id": rec["id"],
            "name": rec["name"]["ja"],
            "prefecture": rec["location"]["prefecture"],
            # 系統・年代・AI は後続ループで結合する。まだ測っていないので出さない
            "ai": False,
        },
    }


def build(pattern: str = RAW_GLOB) -> dict[str, Any]:
    elements = load_raw(pattern)
    records, dropped = to_records(elements)
    fc = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "features": [feature(r) for r in records],
    }
    for p in (OUT_GEOJSON, OUT_CATALOG, OUT_BUILD):
        p.parent.mkdir(parents=True, exist_ok=True)
    OUT_GEOJSON.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT_CATALOG.write_text(
        json.dumps({"shrines": records}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    named = sum(1 for r in records if r["name"]["ja"])
    with_wd_tag = sum(1 for r in records if r["external_ids"]["osm_wikidata_tag"])
    with_ele = sum(1 for r in records if r.get("osm_ele") is not None)
    report = {
        "osm_elements_read": len(elements),
        "shrines": len(records),
        "with_name": named,
        "without_name": len(records) - named,
        "with_osm_wikidata_tag": with_wd_tag,
        "with_osm_ele_tag": with_ele,
        "dropped": dropped,
        "bytes_geojson": OUT_GEOJSON.stat().st_size,
        "bytes_catalog": OUT_CATALOG.stat().st_size,
    }
    OUT_BUILD.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OSM 生データ → 公開 GeoJSON")
    ap.add_argument("--pattern", default=RAW_GLOB)
    args = ap.parse_args(argv)
    rep = build(args.pattern)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
