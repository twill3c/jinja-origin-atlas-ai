# -*- coding: utf-8 -*-
"""最寄り河川距離 — SPEC F-07 / T-084。

出典: 国土数値情報 W05(河川)。**CRS は .prj が無いので実測で確かめた** ——
メタデータ XML に `JGD2000 / (B, L)` とあるので EPSG:4612(地理座標)。
属性 `W05_004` が河川名であることも製品ページの属性表で確認した(2026-09-08)。

**緯度経度のまま測らない。** 都道府県ごとの平面直角座標系へ投影してから測る。
さらに**同じ問いを UTM でも解き**、選ばれた河川と距離が一致することを標本で確かめる
(投影の取り方に依る誤りを捕まえるため)。

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

from etl.geo_features import PREF_CRS, UTM_CRS

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
W05_DIR = pathlib.Path("data/raw/ksj/W05")
OUT = pathlib.Path("data/interim/river_distance.json")

#: W05 の座標参照系。**メタデータ XML の記述から確定させた**(推測ではない)。
W05_CRS = "EPSG:4612"  # JGD2000 / (B, L)

#: 属性の意味は製品ページの属性表による(2026-09-08 確認)。
COL_RIVER_NAME = "W05_004"
COL_RIVER_CODE = "W05_002"

#: 都道府県コード → 都道府県名(段階 1 の 3 件)。
PREF_NAME = {"13": "東京都", "26": "京都府", "19": "山梨県"}

#: これを超えたら「近くに川がある」という主張が嘘になる距離(m)。
#:
#: W05 には**島嶼部の河川がほとんど無い**。この上限を置かないと、硫黄島の社に 221 km、
#: 八丈島の社に伊豆大島の三原川まで 66 km、という値が付く。
#: 2026-09-08 実測: 10 km 超は 54 件で**全部が島嶼部**、本土で 10 km を超えるものは 0 件、
#: 5〜10 km はわずか 3 件。この谷間に上限を置く。
MAX_MEANINGFUL_M = 10_000.0

#: 二経路一致の許容。**距離に比例する量なので相対で置く。**
#: 平面直角座標系と UTM は縮尺係数が違うので、遠いほど差が開く。
#: 2026-09-08 実測: 相対差の最大は 1.27e-3(いずれも 24 km 以上の対象)。
TWO_PATH_REL_TOL = 2.0e-3
TWO_PATH_ABS_TOL = 1.0


def load_streams(code: str):
    import geopandas as gpd

    shps = sorted(glob.glob(str(W05_DIR / code / "*_Stream.shp")))
    if not shps:
        raise FileNotFoundError(f"{code}: Stream シェープファイルが無い。先に fetch_rivers を実行する")
    g = gpd.read_file(shps[0])
    if g.crs is None:
        # .prj が無い。メタデータに JGD2000 / (B, L) とあるのでそれを与える。
        g = g.set_crs(W05_CRS)
    if COL_RIVER_NAME not in g.columns:
        raise RuntimeError(f"{shps[0]}: 河川名の列 {COL_RIVER_NAME} が無い。属性の仕様が変わった疑い")
    return g


def compute(codes: tuple[str, ...], sample_check: int = 60) -> dict:
    import geopandas as gpd
    from shapely.geometry import Point

    recs = json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]
    shrines = gpd.GeoDataFrame(
        {"id": [r["id"] for r in recs]},
        geometry=[Point(r["location"]["lon"], r["location"]["lat"]) for r in recs],
        crs="EPSG:4326",
    )

    best: dict[str, dict] = {}
    per_pref: dict[str, int] = {}
    disagreements: list[dict] = []
    checked = 0

    for code in codes:
        pref = PREF_NAME[code]
        crs = PREF_CRS[pref]
        streams = load_streams(code)
        print(f"  {pref}: 流路 {len(streams)} 本 → {crs} で計算", file=sys.stderr)

        riv = streams.to_crs(crs)[[COL_RIVER_NAME, COL_RIVER_CODE, "geometry"]]
        pts = shrines.to_crs(crs)
        joined = gpd.sjoin_nearest(pts, riv, how="left", distance_col="dist_m")
        # sjoin_nearest は同点で複数返すことがある。id ごとに最小を決定的に採る。
        joined = joined.sort_values(["id", "dist_m", COL_RIVER_NAME]).drop_duplicates("id", keep="first")

        for row in joined.itertuples(index=False):
            d = getattr(row, "dist_m")
            if d is None or d != d:
                continue
            cur = best.get(row.id)
            if cur is None or d < cur["nearest_river_distance_m"]:
                best[row.id] = {
                    "nearest_river_distance_m": round(float(d), 1),
                    "nearest_river_name": getattr(row, COL_RIVER_NAME) or None,
                    "nearest_river_code": getattr(row, COL_RIVER_CODE) or None,
                    "crs": crs,
                    "prefecture_source": pref,
                }
        per_pref[pref] = int(len(streams))  # 流路の本数。結合した行数ではない

        # --- 二経路一致: 同じ問いを UTM でも解く(T-084) ---
        utm = UTM_CRS[crs]
        rng = random.Random(20260908)
        idx = rng.sample(range(len(pts)), min(sample_check, len(pts)))
        riv_u = streams.to_crs(utm)[[COL_RIVER_NAME, "geometry"]]
        pts_u = shrines.iloc[idx].to_crs(utm)
        j2 = gpd.sjoin_nearest(pts_u, riv_u, how="left", distance_col="dist_m")
        j2 = j2.sort_values(["id", "dist_m", COL_RIVER_NAME]).drop_duplicates("id", keep="first")
        ref = joined.set_index("id")
        for row in j2.itertuples(index=False):
            if row.id not in ref.index:
                continue
            a_name = ref.loc[row.id, COL_RIVER_NAME]
            a_d = float(ref.loc[row.id, "dist_m"])
            b_name, b_d = getattr(row, COL_RIVER_NAME), float(getattr(row, "dist_m"))
            checked += 1
            tol = max(TWO_PATH_ABS_TOL, TWO_PATH_REL_TOL * max(a_d, b_d))
            if a_name != b_name or abs(a_d - b_d) > tol:
                disagreements.append({"id": row.id, "pref": pref,
                                      "plane": [a_name, round(a_d, 2)],
                                      "utm": [b_name, round(b_d, 2)]})

    # 上限を超えたものは「川が無い」として理由つきで落とす。
    # **黙って捨てない** —— 何件をなぜ落としたかを数える。
    dropped = 0
    for k, v in list(best.items()):
        if v["nearest_river_distance_m"] > MAX_MEANINGFUL_M:
            best[k] = {
                "nearest_river_distance_m": None,
                "nearest_river_name": None,
                "nearest_river_code": None,
                "crs": None,
                "prefecture_source": None,
                "reason": f"最寄り河川が {MAX_MEANINGFUL_M:.0f} m を超える"
                          "(W05 に島嶼部の河川がほとんど無いため)",
            }
            dropped += 1

    got = sum(1 for v in best.values() if v["nearest_river_distance_m"] is not None)
    return {
        "river": best,
        "dropped_beyond_limit": dropped,
        "limit_m": MAX_MEANINGFUL_M,
        "shrines": len(recs),
        "with_river": got,
        "without_river": len(recs) - got,
        "streams_per_pref": per_pref,
        "two_path_checked": checked,
        "two_path_disagreements": disagreements,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="最寄り河川距離を計算する")
    ap.add_argument("--pref", action="append", help="都道府県コード")
    ap.add_argument("--sample", type=int, default=60, help="二経路一致を確かめる標本数")
    args = ap.parse_args(argv)
    codes = tuple(args.pref) if args.pref else tuple(PREF_NAME)

    t0 = time.time()
    d = compute(codes, sample_check=args.sample)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in d.items() if k != "river"}
    summary["秒"] = round(time.time() - t0, 1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
