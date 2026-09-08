# -*- coding: utf-8 -*-
"""T-080〜T-086: 地理特徴量。SPEC F-06 / F-07 / G-14。

期待値の出所:
- 平面直角座標系の系番号: 国土交通省告示による第 I〜XIX 系の適用範囲。
  東京都(島嶼部を除く)= 第 IX 系 EPSG:6677、京都府 = 第 VI 系 EPSG:6674、
  山梨県 = 第 VIII 系 EPSG:6676
- 二経路一致: 平面直角座標系と UTM は別の投影なので、同じ答えが出れば
  投影の取り方に依らないと言える(HC-065 は「結論だけでなく経路も比べる」を求める。
  ここでは**選ばれた河川**という経路も比べている)
"""
import math

import pytest

from etl.geo_features import (
    PREF_CRS,
    UTM_CRS,
    nearest_river,
    prefecture_crs,
)

shapely = pytest.importorskip("shapely")
from shapely.geometry import LineString, Point  # noqa: E402


@pytest.mark.unit
def test_t083_prefecture_crs_table():
    """T-083: 都道府県 → 平面直角座標系。"""
    assert prefecture_crs("東京都") == "EPSG:6677"
    assert prefecture_crs("京都府") == "EPSG:6674"
    assert prefecture_crs("山梨県") == "EPSG:6676"
    # 表に無い県は None を返す。**適当な系を当てない**(距離が静かにずれる)
    assert prefecture_crs("架空県") is None
    assert prefecture_crs(None) is None
    # 対照が成り立つ前提 —— 表が空でなく、47 都道府県を覆っていること
    assert len(PREF_CRS) == 47, f"{len(PREF_CRS)} 件しかない"
    # **系が 1 つに潰れていないこと**が対照の狙いである。
    # 相異なる系の数は 2026-09-08 の実測で 12(平面直角座標系 I〜XV の一部を使う)。
    # ここに「15 以上」と書いていたのは観測前の思い込みだった。
    assert len(set(PREF_CRS.values())) >= 10, "系が少なすぎる(潰れている疑い)"
    # 出荷している 3 都府県が互いに違う系に載っていること(検算が効く配置か)
    assert len({PREF_CRS["東京都"], PREF_CRS["京都府"], PREF_CRS["山梨県"]}) == 3


@pytest.mark.unit
def test_t084_two_projections_agree():
    """T-084 二経路一致: 平面直角座標系と UTM で同じ河川・同じ距離になる。

    投影が違えば数値の丸め方も歪み方も違う。それでも一致するなら、
    答えは投影の取り方に依らない。
    """
    shrine = (139.7000, 35.7000)
    rivers = [
        ("近い川", LineString([(139.7050, 35.6980), (139.7050, 35.7020)])),
        ("遠い川", LineString([(139.7400, 35.6900), (139.7400, 35.7100)])),
    ]
    a = nearest_river(shrine, rivers, "EPSG:6677")
    b = nearest_river(shrine, rivers, UTM_CRS["EPSG:6677"])
    assert a.name == b.name == "近い川"
    assert abs(a.distance_m - b.distance_m) <= 1.0, (a, b)
    # 距離の桁が妥当であること(経度 0.005 度 ≒ 450 m)
    assert 400 <= a.distance_m <= 500, a


@pytest.mark.unit
def test_t085_positive_control_degrees_are_not_metres():
    """T-085 陽性対照: 緯度経度のまま測る実装は T-084 の一致を壊す。

    これが落ちないなら、T-084 は投影を見ていない。
    """
    shrine = (139.7000, 35.7000)
    rivers = [("近い川", LineString([(139.7050, 35.6980), (139.7050, 35.7020)]))]
    good = nearest_river(shrine, rivers, "EPSG:6677")
    bad = nearest_river(shrine, rivers, "EPSG:4326")  # 度のまま
    assert abs(good.distance_m - bad.distance_m) > 100.0, (good, bad)
    # 対照が成り立つ前提 —— 正しい側が妥当な値であること
    assert 400 <= good.distance_m <= 500


@pytest.mark.unit
def test_t086_distance_is_non_negative_and_named():
    """T-086: 距離は非負、河川名は空でない。"""
    shrine = (135.7681, 35.0116)
    rivers = [("鴨川", LineString([(135.7700, 35.0000), (135.7700, 35.0300)]))]
    r = nearest_river(shrine, rivers, "EPSG:6674")
    assert r.distance_m >= 0.0
    assert r.name == "鴨川"
    # 線の上に乗っている点は距離 0
    on = nearest_river((135.7700, 35.0116), rivers, "EPSG:6674")
    assert on.distance_m == pytest.approx(0.0, abs=0.5)


@pytest.mark.unit
def test_no_rivers_returns_none_not_zero():
    """河川が 1 本も無いときに 0 を返さない。

    0 は「川の上にある」を意味する。「川が無い」を 0 で表すと嘘になる。
    """
    assert nearest_river((139.7, 35.7), [], "EPSG:6677") is None


@pytest.mark.unit
def test_distance_matches_closed_form_on_a_meridian():
    """検算: 子午線に沿った距離は緯度差からほぼ直に出る。

    出所 —— 海里の定義(緯度 1 分 ≒ 1,852 m)。投影の歪みぶんの余裕を 0.5% とる。
    """
    lat0 = 35.0
    dlat = 1.0 / 60.0  # 1 分
    rivers = [("東西の川", LineString([(135.0 - 0.05, lat0 + dlat), (135.0 + 0.05, lat0 + dlat)]))]
    r = nearest_river((135.0, lat0), rivers, "EPSG:6674")
    assert 1852.0 * 0.995 <= r.distance_m <= 1852.0 * 1.005, r.distance_m
    assert not math.isnan(r.distance_m)
