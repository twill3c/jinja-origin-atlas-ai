# -*- coding: utf-8 -*-
"""地理特徴量 — SPEC F-06(標高)/ F-07(最寄り河川距離)。

**緯度経度のまま距離を測らない**(仕様書 §13.2)。日本の平面直角座標系(第 I〜XIX 系)へ
投影してから測る。系の割り当ては国土交通省告示の適用範囲による。

**投影を一つしか使わないと、投影の取り方に依る誤りに気づけない。** 同じ問いを
平面直角座標系と UTM の二つで解き、選ばれた河川と距離が一致することを確かめる(T-084)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

#: 都道府県 → 平面直角座標系(JGD2011)。国土交通省告示の適用範囲による。
#: 東京都・鹿児島県・沖縄県は島嶼で系が分かれるが、本土側の系を代表とする。
PREF_CRS: dict[str, str] = {
    "北海道": "EPSG:6680",      # XII 系(道央)。道東・道北は XIII/XIV 系
    "青森県": "EPSG:6678", "岩手県": "EPSG:6678", "宮城県": "EPSG:6678",
    "秋田県": "EPSG:6678", "山形県": "EPSG:6678", "福島県": "EPSG:6678",
    "茨城県": "EPSG:6677", "栃木県": "EPSG:6677", "群馬県": "EPSG:6677",
    "埼玉県": "EPSG:6677", "千葉県": "EPSG:6677", "東京都": "EPSG:6677",
    "神奈川県": "EPSG:6677", "山梨県": "EPSG:6676", "長野県": "EPSG:6676",
    "新潟県": "EPSG:6676", "富山県": "EPSG:6675", "石川県": "EPSG:6675",
    "福井県": "EPSG:6674", "岐阜県": "EPSG:6675", "静岡県": "EPSG:6676",
    "愛知県": "EPSG:6675", "三重県": "EPSG:6674", "滋賀県": "EPSG:6674",
    "京都府": "EPSG:6674", "大阪府": "EPSG:6674", "兵庫県": "EPSG:6673",
    "奈良県": "EPSG:6674", "和歌山県": "EPSG:6674", "鳥取県": "EPSG:6673",
    "島根県": "EPSG:6671", "岡山県": "EPSG:6673", "広島県": "EPSG:6671",
    "山口県": "EPSG:6669", "徳島県": "EPSG:6672", "香川県": "EPSG:6672",
    "愛媛県": "EPSG:6672", "高知県": "EPSG:6672", "福岡県": "EPSG:6670",
    "佐賀県": "EPSG:6670", "長崎県": "EPSG:6669", "熊本県": "EPSG:6670",
    "大分県": "EPSG:6670", "宮崎県": "EPSG:6670", "鹿児島県": "EPSG:6670",
    "沖縄県": "EPSG:6683",     # XV 系(沖縄本島)
}

#: 平面直角座標系 → 突き合わせ用の UTM。**別の投影で解き直して一致を見る**(T-084)。
#: 日本は UTM 51〜55N に跨がるが、二経路一致の検算には概ねの帯で足りる。
UTM_CRS: dict[str, str] = {
    "EPSG:6669": "EPSG:6689",  # I 系  → UTM 51N
    "EPSG:6670": "EPSG:6690",  # II 系 → UTM 52N
    "EPSG:6671": "EPSG:6690",
    "EPSG:6672": "EPSG:6690",
    "EPSG:6673": "EPSG:6690",
    "EPSG:6674": "EPSG:6690",
    "EPSG:6675": "EPSG:6690",
    "EPSG:6676": "EPSG:6691",  # VIII 系 → UTM 53N
    "EPSG:6677": "EPSG:6691",  # IX 系
    "EPSG:6678": "EPSG:6691",
    "EPSG:6680": "EPSG:6691",
    "EPSG:6683": "EPSG:6689",
}


def prefecture_crs(pref: str | None) -> str | None:
    """都道府県名 → 平面直角座標系。**表に無ければ None**。

    適当な系を当ててはならない。系を間違えると距離が静かにずれるだけで、
    例外にならない。
    """
    if not pref:
        return None
    return PREF_CRS.get(pref.strip())


@dataclass(frozen=True)
class RiverHit:
    name: str
    distance_m: float


def _project(lon: float, lat: float, crs: str):
    from pyproj import Transformer

    if crs == "EPSG:4326":
        return lon, lat
    tf = _transformer(crs)
    return tf.transform(lon, lat)


_TF_CACHE: dict[str, object] = {}


def _transformer(crs: str):
    if crs not in _TF_CACHE:
        from pyproj import Transformer

        _TF_CACHE[crs] = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return _TF_CACHE[crs]


def nearest_river(
    shrine_lonlat: tuple[float, float],
    rivers: Sequence[tuple[str, object]],
    crs: str,
) -> RiverHit | None:
    """指定の座標系へ投影してから最寄り河川を求める。

    :param rivers: (河川名, shapely の LineString/MultiLineString) の列
    :returns: 河川が 1 本も無ければ **None**。
        「川が無い」を 0 で表さない —— 0 は「川の上にある」を意味する。
    """
    if not rivers:
        return None
    from shapely.geometry import Point
    from shapely.ops import transform as shp_transform

    lon, lat = shrine_lonlat
    if crs == "EPSG:4326":
        pt = Point(lon, lat)
        geoms = [(name, g) for name, g in rivers]
    else:
        tf = _transformer(crs)
        pt = Point(*tf.transform(lon, lat))
        geoms = [(name, shp_transform(lambda x, y, t=tf: t.transform(x, y), g)) for name, g in rivers]

    best_name, best_d = None, float("inf")
    for name, g in geoms:
        d = pt.distance(g)
        if d < best_d:
            best_name, best_d = name, d
    return RiverHit(best_name or "", float(best_d))


def nearest_river_both_ways(
    shrine_lonlat: tuple[float, float],
    rivers: Sequence[tuple[str, object]],
    crs: str,
) -> tuple[RiverHit | None, RiverHit | None]:
    """平面直角座標系と UTM の二つで解く。呼び手が一致を確かめる。"""
    a = nearest_river(shrine_lonlat, rivers, crs)
    utm = UTM_CRS.get(crs)
    b = nearest_river(shrine_lonlat, rivers, utm) if utm else None
    return a, b


def japan_bbox_of(geoms: Iterable[object]) -> tuple[float, float, float, float]:
    xs0, ys0, xs1, ys1 = [], [], [], []
    for g in geoms:
        x0, y0, x1, y1 = g.bounds
        xs0.append(x0); ys0.append(y0); xs1.append(x1); ys1.append(y1)
    return min(xs0), min(ys0), max(xs1), max(ys1)
