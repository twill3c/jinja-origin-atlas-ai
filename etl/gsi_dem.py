# -*- coding: utf-8 -*-
"""国土地理院 標高タイルからの標高取得 — SPEC F-06 / G-14。

復号式の出所: https://maps.gsi.go.jp/development/demtile.html

    x = 2^16 R + 2^8 G + B
    x <  2^23 : h = x * 0.01
    x == 2^23 : 無効値(NA)
    x >  2^23 : h = (x - 2^24) * 0.01

**層ごとに配信ズームが違う。** 仕様書 §5.5 のフォールバック連鎖は各層の
最大ズームを書いていなかった。全層を同一 z で叩くと dem_png が 404 になり、
「標高なし」に見える(2026-09-08 実測 / SPEC M-17)。
"""
from __future__ import annotations

import math
from io import BytesIO
from typing import Iterable

#: 層 → 配信ズーム。順序が解決順である。最後の dem_png(DEM10B)が全国を覆う。
#: 2026-09-08 実測: dem5a_png は z15 で 200、dem_png は z15 で 404 / z14 で 200。
LAYER_ZOOM: dict[str, int] = {
    "dem5a_png": 15,
    "dem5b_png": 15,
    "dem5c_png": 15,
    "dem_png": 14,
}

TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png"

_NA = 2 ** 23


def decode_rgb(r: int, g: int, b: int) -> float | None:
    """標高タイルの 1 画素を標高(m)へ復号する。無効値は None。"""
    x = 65536 * r + 256 * g + b
    if x == _NA:
        return None
    if x > _NA:
        return (x - 2 ** 24) * 0.01
    return x * 0.01


def lonlat_to_tile_pixel(lon: float, lat: float, z: int) -> tuple[int, int, int, int]:
    """経緯度 → (タイル x, タイル y, タイル内画素 x, タイル内画素 y)。

    Web メルカトル(EPSG:3857)・256px タイル。
    """
    n = 2.0 ** z
    ex = (lon + 180.0) / 360.0 * n
    ey = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    tx, ty = int(ex), int(ey)
    return tx, ty, int((ex % 1) * 256), int((ey % 1) * 256)


class TileCache:
    """タイルをメモリに持つ。1 つの神社群は同じタイルに何度も当たる。"""

    def __init__(self, client=None, max_entries: int = 4096) -> None:
        self._client = client
        self._cache: dict[tuple[str, int, int, int], object | None] = {}
        self._max = max_entries

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                timeout=60.0,
                headers={"User-Agent": "JinjaOriginAtlasAI/0.1 (+https://github.com/)"},
            )
        return self._client

    def image(self, layer: str, z: int, x: int, y: int):
        key = (layer, z, x, y)
        if key in self._cache:
            return self._cache[key]
        from PIL import Image

        r = self._get_client().get(TILE_URL.format(layer=layer, z=z, x=x, y=y))
        img = None
        if r.status_code == 200:
            img = Image.open(BytesIO(r.content)).convert("RGB")
        if len(self._cache) >= self._max:
            self._cache.clear()
        self._cache[key] = img
        return img


_DEFAULT_CACHE = TileCache()


def elevation_at(
    lon: float,
    lat: float,
    layers: Iterable[str] | None = None,
    cache: TileCache | None = None,
) -> tuple[float | None, str | None, int | None]:
    """標高を返す。

    :returns: (標高 m, 使った層, 使った zoom)。どの層でも取れなければ (None, None, None)。
    """
    cache = cache or _DEFAULT_CACHE
    for layer in layers or LAYER_ZOOM:
        z = LAYER_ZOOM[layer]
        tx, ty, px, py = lonlat_to_tile_pixel(lon, lat, z)
        img = cache.image(layer, z, tx, ty)
        if img is None:
            continue
        h = decode_rgb(*img.getpixel((px, py)))
        if h is not None:
            return h, layer, z
    return None, None, None
