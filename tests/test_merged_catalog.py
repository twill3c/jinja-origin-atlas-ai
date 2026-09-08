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
