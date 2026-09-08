# -*- coding: utf-8 -*-
"""全神社の標高を国土地理院 DEM から取る — SPEC F-06 / G-14。

**タイルはディスクにキャッシュする。** 3 都府県 3,152 点で相異なるタイルは
dem5a(z15)で 1,659 枚・dem_png(z14)で 928 枚(2026-09-08 実測)。
再実行のたびに取り直すのは公共サービスへの無用な負荷である。

**取れなかったものを黙って `null` にしない。** 層ごとの内訳を数えて報告する。

    python -m etl.fetch_elevation
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from io import BytesIO

import httpx

from etl.gsi_dem import LAYER_ZOOM, TILE_URL, decode_rgb, lonlat_to_tile_pixel

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
CACHE_DIR = pathlib.Path("data/raw/gsi_dem")
OUT = pathlib.Path("data/interim/elevation.json")

USER_AGENT = "JinjaOriginAtlasAI/0.1 (+https://github.com/; contact via repository)"


class DiskTileCache:
    """タイルをディスクに置く。404 も「無い」という答えとして記録する(HC-221)。"""

    def __init__(self, client: httpx.Client, sleep: float = 0.05) -> None:
        self.client = client
        self.sleep = sleep
        self.fetched = 0
        self.from_cache = 0
        self.missing = 0

    def _path(self, layer: str, z: int, x: int, y: int) -> pathlib.Path:
        return CACHE_DIR / layer / str(z) / str(x) / f"{y}.png"

    def _absent(self, layer: str, z: int, x: int, y: int) -> pathlib.Path:
        return CACHE_DIR / layer / str(z) / str(x) / f"{y}.absent"

    def image(self, layer: str, z: int, x: int, y: int):
        from PIL import Image

        p = self._path(layer, z, x, y)
        a = self._absent(layer, z, x, y)
        if a.exists():
            self.from_cache += 1
            return None
        if p.exists():
            self.from_cache += 1
            return Image.open(p).convert("RGB")

        p.parent.mkdir(parents=True, exist_ok=True)
        r = self.client.get(TILE_URL.format(layer=layer, z=z, x=x, y=y))
        self.fetched += 1
        time.sleep(self.sleep)
        if r.status_code == 404:
            # 404 は障害ではなく「そこにタイルは無い」という答えである
            a.write_bytes(b"")
            self.missing += 1
            return None
        r.raise_for_status()
        p.write_bytes(r.content)
        return Image.open(BytesIO(r.content)).convert("RGB")


def elevation_for(lon: float, lat: float, cache: DiskTileCache) -> tuple[float | None, str | None]:
    for layer, z in LAYER_ZOOM.items():
        tx, ty, px, py = lonlat_to_tile_pixel(lon, lat, z)
        img = cache.image(layer, z, tx, ty)
        if img is None:
            continue
        h = decode_rgb(*img.getpixel((px, py)))
        if h is not None:
            return h, layer
    return None, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="神社の標高を DEM から取る")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 件だけ処理する(試走用)")
    ap.add_argument("--sleep", type=float, default=0.05)
    args = ap.parse_args(argv)

    recs = json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]
    if args.limit:
        recs = recs[: args.limit]

    out: dict[str, dict] = {}
    by_layer: dict[str, int] = {}
    t0 = time.time()
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        cache = DiskTileCache(client, sleep=args.sleep)
        for i, r in enumerate(recs, 1):
            h, layer = elevation_for(r["location"]["lon"], r["location"]["lat"], cache)
            out[r["id"]] = {"elevation_m": None if h is None else round(h, 2), "source": layer}
            by_layer[layer or "(取れず)"] = by_layer.get(layer or "(取れず)", 0) + 1
            if i % 250 == 0:
                print(f"  {i}/{len(recs)} 取得 {cache.fetched} / キャッシュ {cache.from_cache} "
                      f"/ 不在 {cache.missing}  ({time.time() - t0:.0f}s)", file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"elevation": out, "by_layer": by_layer,
                               "tiles_fetched": cache.fetched,
                               "tiles_from_cache": cache.from_cache,
                               "tiles_absent": cache.missing},
                              ensure_ascii=False), encoding="utf-8")
    got = sum(1 for v in out.values() if v["elevation_m"] is not None)
    print(json.dumps({"件数": len(out), "標高あり": got, "標高なし": len(out) - got,
                      "層別": by_layer, "取得タイル": cache.fetched,
                      "キャッシュ命中": cache.from_cache, "不在タイル": cache.missing,
                      "秒": round(time.time() - t0, 1)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
