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
import re

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


@pytest.mark.validation
def test_t120_elevation_coverage_is_complete_and_losses_are_counted():
    """T-120: 標高が全カタログを覆い、取れなかったものを数えていること。

    河川では `except: continue` のせいで 2 県がまるごと欠けたまま通っていた(HC-263)。
    標高には同じ握りつぶしは無いが、**検査が無ければ同じことが起きても気づけない**ので、
    こちらにも被覆の検査を置く。**県ごとに 1 件も取れていない県が無いこと**まで見る。
    """
    import json
    import pathlib

    p = pathlib.Path("data/interim/elevation.json")
    cat = pathlib.Path("data/interim/catalog_osm.json")
    if not (p.exists() and cat.exists()):
        pytest.skip("標高かカタログがまだ無い")
    d = json.loads(p.read_text(encoding="utf-8"))
    recs = json.loads(cat.read_text(encoding="utf-8"))["shrines"]
    ele = d["elevation"]

    assert set(ele) == {r["id"] for r in recs}, (
        f"標高の件数がカタログと合わない(標高 {len(ele)} / カタログ {len(recs)})"
    )
    # 取れなかったものは黙って null にせず、層別の内訳として数えられていること
    assert sum(d["by_layer"].values()) == len(ele)
    for sid, v in ele.items():
        if v["elevation_m"] is None:
            assert v["source"] is None, f"{sid}: 標高が無いのに層が付いている"

    # 県ごとに 1 件も取れていない県が無いこと(地域がまるごと欠ける故障を捕まえる)
    got_by_pref: dict[str, int] = {}
    total_by_pref: dict[str, int] = {}
    for r in recs:
        c = r["location"]["pref_code"]
        total_by_pref[c] = total_by_pref.get(c, 0) + 1
        if ele[r["id"]]["elevation_m"] is not None:
            got_by_pref[c] = got_by_pref.get(c, 0) + 1
    empty = sorted(c for c in total_by_pref if got_by_pref.get(c, 0) == 0)
    assert empty == [], f"標高が 1 件も取れていない県がある: {empty}"


@pytest.mark.validation
def test_t119_river_coverage_is_complete_and_losses_are_counted():
    """T-119: 河川の読み込みが 47 県すべてを覆い、落としたものを数えていること。

    **県がまるごと欠けても、下流からは「近くに川が無かった」と区別が付かない。**
    実際、`except FileNotFoundError: continue` のせいで北海道と島根の河川が
    黙って欠けたまま通っていた(2026-09-12)。被覆そのものを検査する。
    """
    import json
    import pathlib

    p = pathlib.Path("data/interim/river_distance.json")
    if not p.exists():
        pytest.skip("河川距離がまだ計算されていない")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("mode") == "incremental":
        pytest.skip("増分で計算した報告(T-134 が見る)")

    from etl.prefectures import PREF_CODE_NAME

    assert set(d["streams_per_pref"]) == set(PREF_CODE_NAME), (
        "河川を読めていない県がある: "
        f"{sorted(set(PREF_CODE_NAME) - set(d['streams_per_pref']))}"
    )
    for code, n in d["streams_per_pref"].items():
        assert n > 0, f"{code}: 流路が 0 本"
    # 落としたものは黙って消さず、欄として残っていること(0 件でも欄はある)
    assert isinstance(d["invalid_geometries_dropped"], dict)
    assert d["shrines_without_pref"] == 0, f"県コードの無い神社が {d['shrines_without_pref']} 件"


@pytest.mark.unit
def test_t083b_utm_table_matches_plane_origins():
    """T-083: 平面直角座標系 → UTM の表を、pyproj の定義(原点経度・帯番号)と突き合わせる。

    **番号を記憶で書いた表は、隣の番号も実在するので黙って動く。** 最初の版は注記が
    1 帯ずれ、II 系を 53N に割り当てていた(2026-09-10)。表の値を実物に当てて確かめる。
    """
    from pyproj import CRS

    for plane, utm in UTM_CRS.items():
        lon0 = CRS.from_user_input(plane).to_dict()["lon_0"]
        want_zone = int((lon0 + 180.0) // 6.0) + 1
        got_zone = CRS.from_user_input(utm).to_dict()["zone"]
        assert got_zone == want_zone, f"{plane}(原点 {lon0}E)→ {utm} は {got_zone} 帯。正しくは {want_zone}"


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


#: 日本語の河川名に現れるはずのない字(Latin-1 補助)。Shift_JIS を ISO-8859-1 で読むとここに落ちる
LATIN1 = re.compile("[" + chr(0x80) + "-" + chr(0xFF) + "]")


def garbled_names(names):
    return [n for n in names if n and LATIN1.search(n)]


@pytest.mark.unit
def test_t137_positive_control_detects_shift_jis_read_as_latin1():
    """T-137 陽性対照: Shift_JIS のバイト列を ISO-8859-1 で読んだ名前を検出する。正しい名前は通す。"""
    wrong = "亀田川".encode("cp932").decode("latin-1")
    assert garbled_names([wrong, "亀田川", "名称不明", None]) == [wrong]


@pytest.mark.validation
def test_t137_river_names_are_not_garbled():
    """T-137: 河川名に符号化の取り違えが無い(河川距離の報告と、出荷した県チャンクの両方)。

    W05 には .cpg が無く、読み手が dbf から符号化を推定する。北海道だけ ISO-8859-1 と推定され、
    1,159 社の河川名が化けたまま、うち 1,130 社が本番の詳細画面に出ていた(loop_012 で発見)。
    """
    import glob
    import json
    import pathlib

    p = pathlib.Path("data/interim/river_distance.json")
    if not p.exists():
        pytest.skip("河川距離がまだ計算されていない")
    riv = json.loads(p.read_text(encoding="utf-8"))["river"]
    names = [v.get("nearest_river_name") for v in riv.values()]
    assert sum(1 for n in names if n) > 1000, "走査対象が少なすぎる"
    bad = garbled_names(names)
    assert bad == [], f"河川距離の報告に化けた河川名が {len(bad)} 件。例 {bad[:3]}"

    shipped = []
    for f in sorted(glob.glob("public/data/shrines/[0-9][0-9].json")):
        for r in json.loads(pathlib.Path(f).read_text(encoding="utf-8"))["shrines"]:
            shipped.append((r.get("geography") or {}).get("nearest_river_name"))
    bad = garbled_names(shipped)
    assert bad == [], f"出荷した県チャンクに化けた河川名が {len(bad)} 件。例 {bad[:3]}"
