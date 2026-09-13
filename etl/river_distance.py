# -*- coding: utf-8 -*-
"""最寄り河川距離 — SPEC F-07 / T-084 / D-06(全国)。

出典: 国土数値情報 W05(河川)。**CRS は .prj が無いので実測で確かめた** ——
メタデータ XML に `JGD2000 / (B, L)` とあるので EPSG:4612(地理座標)。
属性 `W05_004` が河川名であることも製品ページの属性表で確認した(2026-09-08)。

**緯度経度のまま測らない。** 神社の県の平面直角座標系へ投影してから測る。
**県境を越えて探す** —— 県境近くの神社の最寄りの川は隣の県にあることがある。
その県の神社を囲む矩形を 10 km 強ひろげ、それに掛かる県の川をすべて候補に入れる。

**第二の経路で確かめる。** 標本について、経度から決めた UTM 帯(WGS84 / EPSG:326zz)でも
同じ問いを解き、選ばれた川と距離が一致することを見る。平面直角座標系の表を引かない
別の投影なので、表の誤り(系の割り当て違い)も捕まえる。

    python -m etl.river_distance
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import random
import sys
import time
from collections import defaultdict

from etl.geo_features import PREF_CRS
from etl.prefectures import PREF_CODE_NAME

CATALOG = pathlib.Path("data/interim/catalog_osm.json")  # D-06: 全カタログは公開物に置かない
W05_DIR = pathlib.Path("data/raw/ksj/W05")
OUT = pathlib.Path("data/interim/river_distance.json")

#: W05 の座標参照系。**メタデータ XML の記述から確定させた**(推測ではない)。
W05_CRS = "EPSG:4612"  # JGD2000 / (B, L)

#: 属性の意味は製品ページの属性表による(2026-09-08 確認)。
COL_RIVER_NAME = "W05_004"
COL_RIVER_CODE = "W05_002"

#: これを超えたら「近くに川がある」という主張が嘘になる距離(m)。
#:
#: W05 には**島嶼部の河川がほとんど無い**。この上限を置かないと、硫黄島の社に 221 km、
#: 八丈島の社に伊豆大島の三原川まで 66 km、という値が付く。
#: 2026-09-08 実測(3 都府県 3,152 件): 10 km 超は 54 件で**全部が島嶼部**、
#: 本土で 10 km を超えるものは 0 件、5〜10 km はわずか 3 件。この谷間に上限を置く。
#: **全国で測り直すこと**(3 都府県の実測を全国へ持ち込んでいる)。
MAX_MEANINGFUL_M = 10_000.0

#: 県の神社を囲む矩形をこれだけ広げて、候補の川を集める(度)。
#: 10 km は緯度で約 0.09 度、北緯 45 度の経度で約 0.13 度。余裕を見て 0.15 度。
SEARCH_PAD_DEG = 0.15

#: 二経路一致の許容。**距離に比例する量なので相対で置く。**
#: 2026-09-08 実測(3 都府県・180 標本): 相対差の最大は 1.27e-3。
TWO_PATH_REL_TOL = 2.0e-3
TWO_PATH_ABS_TOL = 1.0


def load_streams(code: str):
    """その県の流路を読む。:returns: (GeoDataFrame, 落とした退化幾何の数)

    **再帰で探す。** 47 県に広げたとき、北海道(01)と島根(32)だけ zip の中が
    `W05-09_01-g_GML/` と一階層深い作りだった(2026-09-12 実測)。非再帰の glob では
    見つからず、しかも呼び手が FileNotFoundError を握りつぶしていたため、
    **その 2 県の河川が黙って欠けたまま通っていた。**

    **退化した幾何がある。** 三重県(24)の 7,527 本に 1 本だけ、点が 1 個しかない線が
    入っており、素直に読むと GEOSException で全体が落ちる。落とすが、**数えて報告する**。
    """
    import pyogrio

    shps = sorted(glob.glob(str(W05_DIR / code / "**" / "*_Stream.shp"), recursive=True))
    if not shps:
        raise FileNotFoundError(f"{code}: Stream シェープファイルが無い。先に fetch_rivers を実行する")
    g = pyogrio.read_dataframe(shps[0], on_invalid="ignore")
    n_bad = int(g.geometry.isna().sum())
    if n_bad:
        g = g[g.geometry.notna()].copy()
    if g.crs is None:
        # .prj が無い。メタデータに JGD2000 / (B, L) とあるのでそれを与える。
        g = g.set_crs(W05_CRS)
    if COL_RIVER_NAME not in g.columns:
        raise RuntimeError(f"{shps[0]}: 河川名の列 {COL_RIVER_NAME} が無い。属性の仕様が変わった疑い")
    return g[[COL_RIVER_NAME, COL_RIVER_CODE, "geometry"]], n_bad


def utm_epsg(lon: float) -> str:
    """経度から UTM 帯を決める(WGS84 / 北半球)。第二の経路は表を引かない。"""
    zone = int((lon + 180.0) // 6.0) + 1
    return f"EPSG:{32600 + zone}"


def _bbox_hit(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def compute(sample_per_pref: int = 20) -> dict:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point

    recs = json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]
    by_pref: dict[str, list[dict]] = defaultdict(list)
    no_pref = 0
    for r in recs:
        c = r["location"].get("pref_code")
        if c:
            by_pref[c].append(r)
        else:
            no_pref += 1

    # 川は全県ぶん一度だけ読み、県ごとの外接矩形(地理座標)を持っておく
    t0 = time.time()
    streams = {}
    stream_bbox = {}
    invalid_dropped: dict[str, int] = {}
    for code in PREF_CODE_NAME:
        # **例外を握りつぶさない。** 県を飛ばすと、その県の神社に河川が付かないまま
        # 「距離なし」として通ってしまう(2026-09-12 に北海道と島根で実際に起きた)。
        g, n_bad = load_streams(code)
        streams[code] = g
        if n_bad:
            invalid_dropped[code] = n_bad
        stream_bbox[code] = tuple(g.to_crs("EPSG:4326").total_bounds)
    print(f"  W05: {len(streams)} 県 {sum(len(g) for g in streams.values())} 本 "
          f"/ 退化した幾何を落とした {sum(invalid_dropped.values())} 本 "
          f"({time.time() - t0:.0f}s)", file=sys.stderr)

    best: dict[str, dict] = {}
    candidates_used: dict[str, list[str]] = {}
    disagreements: list[dict] = []
    checked = 0
    rng = random.Random(20260910)

    for code in sorted(by_pref):
        rs = by_pref[code]
        crs = PREF_CRS[PREF_CODE_NAME[code]]
        pts4326 = gpd.GeoDataFrame(
            {"id": [r["id"] for r in rs]},
            geometry=[Point(r["location"]["lon"], r["location"]["lat"]) for r in rs],
            crs="EPSG:4326",
        )
        x0, y0, x1, y1 = pts4326.total_bounds
        box = (x0 - SEARCH_PAD_DEG, y0 - SEARCH_PAD_DEG, x1 + SEARCH_PAD_DEG, y1 + SEARCH_PAD_DEG)
        cand = [c for c, bb in stream_bbox.items() if _bbox_hit(box, bb)]
        candidates_used[code] = cand
        if not cand:
            continue
        riv4326 = pd.concat([streams[c] for c in cand], ignore_index=True)
        riv = gpd.GeoDataFrame(riv4326, geometry="geometry", crs=streams[cand[0]].crs).to_crs(crs)

        joined = gpd.sjoin_nearest(pts4326.to_crs(crs), riv, how="left", distance_col="dist_m")
        # sjoin_nearest は同点で複数返すことがある。id ごとに最小を決定的に採る。
        joined = joined.sort_values(["id", "dist_m", COL_RIVER_NAME]).drop_duplicates("id", keep="first")
        for row in joined.itertuples(index=False):
            d = getattr(row, "dist_m")
            if d is None or d != d:
                continue
            best[row.id] = {
                "nearest_river_distance_m": round(float(d), 1),
                "nearest_river_name": getattr(row, COL_RIVER_NAME) or None,
                "nearest_river_code": getattr(row, COL_RIVER_CODE) or None,
                "crs": crs,
            }

        # --- 第二の経路: 経度から決めた UTM 帯で同じ問いを解く(T-084) ---
        ref = joined.set_index("id")
        sample = rng.sample(range(len(rs)), min(sample_per_pref, len(rs)))
        for i in sample:
            r = rs[i]
            if r["id"] not in ref.index:
                continue
            utm = utm_epsg(r["location"]["lon"])
            pt = gpd.GeoDataFrame({"id": [r["id"]]},
                                  geometry=[Point(r["location"]["lon"], r["location"]["lat"])],
                                  crs="EPSG:4326").to_crs(utm)
            j2 = gpd.sjoin_nearest(pt, riv.to_crs(utm), how="left", distance_col="dist_m")
            j2 = j2.sort_values(["dist_m", COL_RIVER_NAME]).iloc[0]
            a_name = ref.loc[r["id"], COL_RIVER_NAME]
            a_d = float(ref.loc[r["id"], "dist_m"])
            b_name, b_d = j2[COL_RIVER_NAME], float(j2["dist_m"])
            checked += 1
            tol = max(TWO_PATH_ABS_TOL, TWO_PATH_REL_TOL * max(a_d, b_d))
            if a_name != b_name or abs(a_d - b_d) > tol:
                disagreements.append({"id": r["id"], "pref": code, "plane": [a_name, round(a_d, 2), crs],
                                      "utm": [b_name, round(b_d, 2), utm]})
        print(f"  {code} {PREF_CODE_NAME[code]}: 神社 {len(rs)} / 候補の県 {len(cand)} "
              f"({time.time() - t0:.0f}s)", file=sys.stderr)

    # 上限を超えたものは「川が無い」として理由つきで落とす。**黙って捨てない。**
    beyond = sorted((v["nearest_river_distance_m"], k) for k, v in best.items()
                    if v["nearest_river_distance_m"] > MAX_MEANINGFUL_M)
    for _, k in beyond:
        best[k] = {
            "nearest_river_distance_m": None, "nearest_river_name": None,
            "nearest_river_code": None, "crs": None,
            "reason": f"最寄り河川が {MAX_MEANINGFUL_M:.0f} m を超える(W05 に島嶼部の河川がほとんど無いため)",
        }

    got = sum(1 for v in best.values() if v["nearest_river_distance_m"] is not None)
    return {
        "river": best,
        "shrines": len(recs),
        "shrines_without_pref": no_pref,
        "with_river": got,
        "without_river": len(recs) - got,
        "dropped_beyond_limit": len(beyond),
        "limit_m": MAX_MEANINGFUL_M,
        "beyond_limit_examples": [{"id": k, "distance_m": d} for d, k in beyond[:30]],
        "streams_per_pref": {c: int(len(g)) for c, g in streams.items()},
        "invalid_geometries_dropped": invalid_dropped,
        "candidate_prefs": candidates_used,
        "two_path_checked": checked,
        "two_path_disagreements": disagreements,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="最寄り河川距離を計算する(全国)")
    ap.add_argument("--sample", type=int, default=20, help="県ごとに二経路一致を確かめる標本数")
    args = ap.parse_args(argv)

    t0 = time.time()
    d = compute(sample_per_pref=args.sample)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in d.items() if k not in ("river", "candidate_prefs", "streams_per_pref")}
    summary["秒"] = round(time.time() - t0, 1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
