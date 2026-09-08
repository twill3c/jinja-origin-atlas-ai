# -*- coding: utf-8 -*-
"""T-073 / T-074: 結合後の公開カタログ。SPEC F-03 / F-04 / F-08 / G-03 / G-04。

T-073 は**二つの独立な信号の一致率**を測る。祭神(Wikidata P825)由来の系統と、
名称規則由来の系統は互いを参照していないので、この一致は循環しない。

**率だけを見ない**(HC-231)。食い違いは `data/reports/signal_disagreements.json` に
残し、こちらの欠陥・本物の曖昧さ・データの誤りに分けて読む。
"""
import json
import pathlib

import pytest

from export.build_geojson import in_japan

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
BUILD = pathlib.Path("public/data/meta/build.json")
GEOJSON = pathlib.Path("public/data/osm/shrines.min.geojson")

pytestmark = pytest.mark.skipif(not BUILD.exists(), reason="公開アーティファクトが未生成")


@pytest.fixture(scope="module")
def artifacts():
    return {
        "catalog": json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"],
        "build": json.loads(BUILD.read_text(encoding="utf-8")),
        "geojson": json.loads(GEOJSON.read_text(encoding="utf-8")),
    }


#: 較正ではなく**観測の記録**。2026-09-08 の実測は 340/343 = 0.9913。
#: 床は余裕を見て 0.95。下回ったら、率ではなく食い違いの中身を読むこと。
SIGNAL_AGREEMENT_FLOOR = 0.95
SIGNAL_MIN_SAMPLE = 100


@pytest.mark.validation
def test_t073_two_independent_signals_agree(artifacts):
    """T-073: 祭神由来と名称由来の系統の一致率。**循環しない照合**。"""
    a = artifacts["build"]["signal_agreement"]
    assert a["both_known"] >= SIGNAL_MIN_SAMPLE, (
        f"両方が決まった件数が {a['both_known']} 件しかない。"
        "標本が小さすぎる照合は、緑でも何も言っていない"
    )
    assert a["rate"] >= SIGNAL_AGREEMENT_FLOOR, (
        f"一致率 {a['rate']} < {SIGNAL_AGREEMENT_FLOOR}。"
        "率だけを見ず data/reports/signal_disagreements.json を読むこと"
    )


@pytest.mark.validation
def test_t073b_disagreements_are_recorded_not_hidden(artifacts):
    """T-073: 食い違いを黙って捨てないこと。

    一致率が高いほど「残りの数件」が重要になる。件数と実物の両方を残す。
    """
    a = artifacts["build"]["signal_agreement"]
    assert a["agree"] + a["disagree"] == a["both_known"]
    p = pathlib.Path("data/reports/signal_disagreements.json")
    if a["disagree"]:
        assert p.exists(), "食い違いがあるのに記録が無い"
        assert len(json.loads(p.read_text(encoding="utf-8"))) > 0


@pytest.mark.validation
def test_t073c_positive_control_signals_are_actually_independent(artifacts):
    """T-073 陽性対照: 二つの信号が本当に別物であること。

    片方がもう片方から導かれていたら、一致は恒等式になる(HC-045)。
    実データに「祭神で決まったが名称では決まらない」「名称で決まったが祭神では決まらない」
    レコードが両方あることを確かめる。
    """
    basis = artifacts["build"]["family_basis"]
    assert basis.get("deity", 0) > 0, "祭神で決まったレコードが無い"
    assert basis.get("name", 0) > 0, "名称で決まったレコードが無い"
    # 両方が決まったレコード数より、片方だけで決まったレコードのほうが多いこと
    a = artifacts["build"]["signal_agreement"]
    assert basis["deity"] + basis["name"] > a["both_known"], "二信号が同じ集合しか覆っていない"


@pytest.mark.validation
def test_t074_merged_catalog_invariants(artifacts):
    """T-074 / G-03 / G-04: 結合後も ID 一意・座標が矩形内・出所が空でない。"""
    recs = artifacts["catalog"]
    assert recs, "走査対象が空"
    ids = [r["id"] for r in recs]
    assert len(set(ids)) == len(ids)
    for r in recs:
        assert in_japan(r["location"]["lon"], r["location"]["lat"]), r["id"]
        assert r.get("sources"), r["id"]
        fam = r.get("shrine_family")
        assert fam and fam["label"], r["id"]
        assert 0.0 <= fam["confidence"] <= 1.0, r["id"]
        if fam["label"] == "unknown":
            assert fam["basis"] == "none", f"{r['id']}: unknown なのに根拠がある"


@pytest.mark.validation
def test_t074b_wikidata_attributes_only_on_matched_records(artifacts):
    """T-074: 結合していないレコードに Wikidata 由来の属性が付いていないこと。

    出所の無い属性を作らない(RULE-02 / RULE-10)。
    """
    for r in artifacts["catalog"]:
        has_wd = r["external_ids"].get("wikidata")
        for key in ("deities", "shrine_rank", "documented_parents", "ja_wikipedia"):
            if r.get(key):
                assert has_wd, f"{r['id']}: {key} があるのに Wikidata に結合されていない"
                assert "src_wikidata" in r["sources"], r["id"]


@pytest.mark.validation
def test_t074c_geojson_and_catalog_agree(artifacts):
    """T-074: GeoJSON とカタログが同じ集合を指していること。"""
    cat_ids = {r["id"] for r in artifacts["catalog"]}
    geo_ids = {f["properties"]["id"] for f in artifacts["geojson"]["features"]}
    assert cat_ids == geo_ids
    fams_cat = {r["id"]: r["shrine_family"]["label"] for r in artifacts["catalog"]}
    for f in artifacts["geojson"]["features"]:
        assert f["properties"]["family"] == fams_cat[f["properties"]["id"]]


#: T-082 の床。2026-09-08 実測は 54 件・中央差 0.14 m・1 m 以内 47 件。
#: 床は余裕を見て置く。**下回ったら、率ではなく差の大きい個体を読むこと。**
ELE_ORACLE_MIN_N = 20
ELE_ORACLE_MEDIAN_MAX_M = 2.0
ELE_ORACLE_WITHIN_10M_RATE = 0.90


@pytest.mark.validation
def test_t081_elevation_counts_are_reported(artifacts):
    """T-081: 標高が付いた件数・付かなかった件数を数える。黙って null にしない。"""
    b = artifacts["build"]
    assert b["with_elevation"] + b["without_elevation"] == b["shrines"]
    assert b["with_elevation"] > 0, "標高が 1 件も付いていない"
    q = b["elevation_quantiles"]
    assert q is not None
    # 日本の陸地の標高としてありえない値が混じっていないこと
    assert -20.0 <= q["min"] <= q["median"] <= q["max"] <= 3800.0, q


@pytest.mark.validation
def test_t082_elevation_against_osm_ele_oracle(artifacts):
    """T-082 / G-14 非循環オラクル: DEM 由来の標高 vs OSM の `ele` タグ。

    `ele` は OSM の投稿者が記録した標高で、DEM からの計算には**使っていない**。
    したがってこの一致は循環しない。

    2026-09-08 実測: 54 件、差の中央値 0.14 m、1 m 以内 47 件、10 m 以内 53 件。
    外れた 1 件(59.56 m)は名称タグの無い地物で `ele=600.0` という丸い値だった。
    """
    o = artifacts["build"]["elevation_oracle"]
    assert o is not None, "オラクルの突き合わせが行われていない"
    assert o["n"] >= ELE_ORACLE_MIN_N, f"照合できたのが {o['n']} 件しかない"
    assert o["median_abs_diff_m"] <= ELE_ORACLE_MEDIAN_MAX_M, o
    assert o["within_10m"] / o["n"] >= ELE_ORACLE_WITHIN_10M_RATE, o


@pytest.mark.validation
def test_t082b_osm_ele_is_not_used_to_compute_elevation(artifacts):
    """T-082 循環の禁止: `ele` タグを持つ神社の標高が、タグの値そのままではないこと。

    そのまま写していたら差は常に 0 になり、オラクルは恒等式になる(HC-045)。
    """
    exact = 0
    n = 0
    for r in artifacts["catalog"]:
        a = r.get("osm_ele")
        b = (r.get("geography") or {}).get("elevation_m")
        if a is None or b is None:
            continue
        n += 1
        if a == b:
            exact += 1
    assert n >= ELE_ORACLE_MIN_N
    assert exact < n, "標高が ele タグの写しになっている(オラクルが循環している)"


@pytest.mark.validation
def test_t086_river_distances_are_sane(artifacts):
    """T-086: 河川距離は非負・上限内、河川名が空でない。落としたものは理由つき。"""
    b = artifacts["build"]
    assert b["with_river_distance"] + b["without_river_distance"] == b["shrines"]
    q = b["river_distance_quantiles"]
    assert q is not None and q["min"] >= 0.0
    # 上限を超えたものは null にしてあるはず(SPEC の MAX_MEANINGFUL_M)
    from etl.river_distance import MAX_MEANINGFUL_M

    assert q["max"] <= MAX_MEANINGFUL_M, q

    for r in artifacts["catalog"]:
        g = r.get("geography") or {}
        if g.get("nearest_river_distance_m") is not None:
            assert g["nearest_river_distance_m"] >= 0.0, r["id"]
            assert g.get("nearest_river_name"), f"{r['id']}: 距離はあるのに河川名が空"
            assert "src_ksj_w05" in r["sources"], r["id"]
        elif "nearest_river_note" in g:
            assert g["nearest_river_note"], r["id"]


@pytest.mark.validation
def test_t087_coast_distance_is_explicitly_null(artifacts):
    """T-087 / F-15: 海岸距離は V1.0 では測らない。**欄を作って null と言う。**

    欄ごと無いと「測ったが 0 だった」と区別できない。
    """
    with_geo = [r for r in artifacts["catalog"] if r.get("geography")]
    assert with_geo
    for r in with_geo:
        assert "coast_distance_m" in r["geography"], r["id"]
        assert r["geography"]["coast_distance_m"] is None, r["id"]
