# -*- coding: utf-8 -*-
"""前回の地理特徴量を再利用する — SPEC D-09(T-133)。

月次の自動更新はランナーのキャッシュが毎回消えた状態で走る(GitHub のキャッシュは 7 日アクセスが
無いと消える)。そのまま全件を測ると、国土地理院の標高タイル約 2.8 万枚と国土数値情報 W05 約 1 GB を
毎月取り直すことになる。**ID と位置が変わっていない地物は前回の値を引き継ぎ、新しい地物・動いた地物・
前回取れていなかった地物だけを測る。**

前回の値は `data/state/geo_state.jsonl`(git で追跡する)に地物ごとに一行ずつ置く。県チャンクには
統合で残った神社しか無いので、統合で消えた地物(loop_009 で 467)の値を持てないためである。
ID の昇順に並べるので、月ごとの差分は変わった行だけになる。

    python -m etl.reuse_geography --write-state   # いまの標高・河川距離から状態ファイルを作る
"""
from __future__ import annotations

import argparse
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from etl.entity_resolution import haversine_m

STATE = pathlib.Path("data/state/geo_state.jsonl")
CATALOG = pathlib.Path("data/interim/catalog_osm.json")
ELEVATION = pathlib.Path("data/interim/elevation.json")
RIVER = pathlib.Path("data/interim/river_distance.json")

#: これ以上動いた地物は測り直す。OSM の座標は小数 7 桁(約 1 cm)で、同じ地物なら変わらない。
#: 標高タイルの画素は z15 で約 4 m なので、1 m 未満の移動は値を変えない
MOVE_TOLERANCE_M = 1.0

_GEO_KEYS = ("elevation_m", "elevation_source", "nearest_river_distance_m",
             "nearest_river_name", "nearest_river_note")


@dataclass
class Plan:
    elevation_reuse: dict[str, dict[str, Any]] = field(default_factory=dict)
    elevation_todo: list[str] = field(default_factory=list)
    river_reuse: dict[str, dict[str, Any]] = field(default_factory=dict)
    river_todo: list[str] = field(default_factory=list)


def load_previous(path: pathlib.Path = STATE) -> dict[str, dict[str, Any]]:
    """状態ファイルを {id: {lat, lon, geography}} にする。無ければ空(= 全件を測る)。"""
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    # **splitlines() を使わない。** NEL(U+0085)や U+2028 でも行を割るので、値にそれが入った行が
    # 途中で切れる(loop_012 の試走で、化けた河川名に入っていた U+0085 で JSON が壊れた)。改行は LF だけ
    for line in path.read_text(encoding="utf-8").split(chr(10)):
        if not line.strip():
            continue
        row = json.loads(line)
        out[row["id"]] = {"lat": row["lat"], "lon": row["lon"],
                          "geography": {k: row[k] for k in _GEO_KEYS if row.get(k) is not None}}
    return out


def plan(catalog: Sequence[Mapping[str, Any]], previous: Mapping[str, Mapping[str, Any]],
         tol_m: float = MOVE_TOLERANCE_M) -> Plan:
    """どの地物の標高・河川距離を引き継ぎ、どれを測るかを決める(カタログの並び順を保つ)。"""
    p = Plan()
    for r in catalog:
        sid = r["id"]
        prev = previous.get(sid)
        loc = r["location"]
        same = prev is not None and haversine_m(prev["lon"], prev["lat"], loc["lon"], loc["lat"]) < tol_m
        g = prev["geography"] if same else {}

        if g.get("elevation_m") is not None:
            p.elevation_reuse[sid] = {"elevation_m": g["elevation_m"], "source": g.get("elevation_source")}
        else:
            p.elevation_todo.append(sid)

        if g.get("nearest_river_distance_m") is not None:
            p.river_reuse[sid] = {"nearest_river_distance_m": g["nearest_river_distance_m"],
                                  "nearest_river_name": g.get("nearest_river_name"),
                                  "nearest_river_code": None, "crs": None, "reused": True}
        elif g.get("nearest_river_note"):
            # 島嶼部などの「理由つきの空欄」は、理由ごと引き継ぐ(D-04)
            p.river_reuse[sid] = {"nearest_river_distance_m": None, "nearest_river_name": None,
                                  "nearest_river_code": None, "crs": None,
                                  "reason": g["nearest_river_note"], "reused": True}
        else:
            p.river_todo.append(sid)
    return p


def write_state(catalog_path: pathlib.Path = CATALOG, elevation_path: pathlib.Path = ELEVATION,
                river_path: pathlib.Path = RIVER, out: pathlib.Path = STATE) -> dict[str, int]:
    recs = json.loads(pathlib.Path(catalog_path).read_text(encoding="utf-8"))["shrines"]
    ele = json.loads(pathlib.Path(elevation_path).read_text(encoding="utf-8"))["elevation"]
    riv = json.loads(pathlib.Path(river_path).read_text(encoding="utf-8"))["river"]
    rows = []
    for r in sorted(recs, key=lambda x: x["id"]):
        e = ele.get(r["id"]) or {}
        v = riv.get(r["id"]) or {}
        rows.append({
            "id": r["id"], "lat": r["location"]["lat"], "lon": r["location"]["lon"],
            "elevation_m": e.get("elevation_m"), "elevation_source": e.get("source"),
            "nearest_river_distance_m": v.get("nearest_river_distance_m"),
            "nearest_river_name": v.get("nearest_river_name"),
            "nearest_river_note": v.get("reason"),
        })
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) + "\n" for x in rows),
                   encoding="utf-8", newline="\n")
    return {"rows": len(rows),
            "with_elevation": sum(1 for x in rows if x["elevation_m"] is not None),
            "with_river_or_note": sum(1 for x in rows if x["nearest_river_distance_m"] is not None
                                      or x["nearest_river_note"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="地理特徴量の状態ファイル")
    ap.add_argument("--write-state", action="store_true", help="いまの標高・河川距離から状態ファイルを作る")
    args = ap.parse_args(argv)
    if not args.write_state:
        ap.error("--write-state を指定する")
    print(json.dumps(write_state(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
