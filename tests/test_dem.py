# -*- coding: utf-8 -*-
"""T-010〜T-014: 国土地理院 DEM タイルの復号とタイル座標。SPEC F-06 / G-14。

期待値の出所:
- 復号式: 標高タイル仕様 https://maps.gsi.go.jp/development/demtile.html
- 層ごとの配信ズーム: 2026-09-08 実測(SPEC M-17)。dem_png を z15 で叩くと HTTP 404
- 諏訪湖湖面 759.0 m: 公表標高 759 m。dem_png z14 から復号して完全一致(2026-09-08 実測)

富士山頂は**オラクルにしない**。剣ヶ峰の座標で復号すると 3,756.03 m(dem5a z15)/
3,760.89 m(dem_png z14)で公表 3,776 m と 15〜20 m ずれる(2026-09-08 実測)。
急斜面では水平方向のわずかなずれが標高差に化ける。
"""
import math

import pytest

from etl.gsi_dem import LAYER_ZOOM, decode_rgb, elevation_at, lonlat_to_tile_pixel


@pytest.mark.unit
def test_t010_decode_three_branches():
    """T-010: 仕様の 3 分岐。x < 2^23 / x == 2^23(無効値) / x > 2^23(負の標高)。"""
    # x < 2^23: 高さ = x * 0.01
    assert decode_rgb(0, 0, 0) == pytest.approx(0.0)
    assert decode_rgb(0, 1, 0) == pytest.approx(2.56)
    assert decode_rgb(1, 0, 0) == pytest.approx(655.36)
    # x == 2^23 → 無効値
    assert decode_rgb(128, 0, 0) is None
    # x > 2^23: 高さ = (x - 2^24) * 0.01(負の標高。八郎潟干拓地など)
    assert decode_rgb(255, 255, 255) == pytest.approx(-0.01)
    assert decode_rgb(255, 255, 0) == pytest.approx(-2.56)


@pytest.mark.unit
def test_t010b_decode_matches_closed_form():
    """T-010: 総当たりに近い標本で閉形式と一致する。"""
    for r in range(0, 256, 17):
        for g in range(0, 256, 17):
            for b in range(0, 256, 17):
                x = 65536 * r + 256 * g + b
                got = decode_rgb(r, g, b)
                if x == 2 ** 23:
                    assert got is None
                elif x > 2 ** 23:
                    assert got == pytest.approx((x - 2 ** 24) * 0.01)
                else:
                    assert got == pytest.approx(x * 0.01)


@pytest.mark.unit
def test_t014_positive_control_broken_decoder_is_caught():
    """T-014 陽性対照: 係数を 1 つ壊した実装は T-010 の期待値を満たさない。

    これが落ちないなら、T-010 は復号式を見ていない。
    """
    def broken(r, g, b):
        x = 65536 * r + 256 * g + b  # 256 を 255 に壊す
        x = 65535 * r + 256 * g + b
        if x == 2 ** 23:
            return None
        return (x - 2 ** 24) * 0.01 if x > 2 ** 23 else x * 0.01

    assert broken(1, 0, 0) != pytest.approx(655.36)
    assert decode_rgb(1, 0, 0) == pytest.approx(655.36)


@pytest.mark.unit
def test_t011_layer_zoom_constants():
    """T-011: 層ごとの配信ズーム。2026-09-08 実測(SPEC M-17)。"""
    assert LAYER_ZOOM["dem5a_png"] == 15
    assert LAYER_ZOOM["dem5b_png"] == 15
    assert LAYER_ZOOM["dem5c_png"] == 15
    assert LAYER_ZOOM["dem_png"] == 14
    # 全国を覆う最後の砦は dem_png(DEM10B)であること
    assert list(LAYER_ZOOM)[-1] == "dem_png"


@pytest.mark.unit
def test_t012_tile_pixel_closed_form():
    """T-012: 緯度経度 → タイル座標・タイル内画素。閉形式で検算する。"""
    # z=0 はタイル 1 枚しか無い
    tx, ty, px, py = lonlat_to_tile_pixel(139.7, 35.7, 0)
    assert (tx, ty) == (0, 0)
    assert 0 <= px < 256 and 0 <= py < 256

    # 経度 0・緯度 0 は z=1 でタイル境界の角に来る
    tx, ty, px, py = lonlat_to_tile_pixel(0.0, 0.0, 1)
    assert (tx, ty, px, py) == (1, 1, 0, 0)

    # Web メルカトルの定義から独立に再計算して一致を見る
    for lon, lat, z in [(139.767, 35.681, 15), (135.768, 35.011, 12), (141.35, 43.06, 9)]:
        n = 2.0 ** z
        ex = (lon + 180.0) / 360.0 * n
        ey = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
        tx, ty, px, py = lonlat_to_tile_pixel(lon, lat, z)
        assert (tx, ty) == (int(ex), int(ey))
        assert px == int((ex % 1) * 256)
        assert py == int((ey % 1) * 256)


@pytest.mark.network
def test_t013_suwa_lake_surface_elevation():
    """T-013 [network]: 諏訪湖湖面の標高。公表 759 m。

    平坦な水面なので水平方向の誤差に鈍く、オラクルとして安定する。
    2026-09-08 実測では dem_png z14 から 759.0 が返った。
    """
    h, layer, z = elevation_at(138.083, 36.049)
    assert h is not None
    assert h == pytest.approx(759.0, abs=0.5)
    assert layer == "dem_png"
    assert z == LAYER_ZOOM[layer]
