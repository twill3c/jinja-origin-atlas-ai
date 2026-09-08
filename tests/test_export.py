# -*- coding: utf-8 -*-
"""T-030 / T-031: 公開アーティファクトの不変量。SPEC F-01 / G-01 / G-03 / G-04。

件数は定数で書かない。集合の一致と「違反 0」で書く。
実データが無い環境でも走るよう、合成フィクスチャからも同じ不変量を確かめる。
"""
import json
import pathlib

import pytest

from export.build_geojson import (
    JAPAN_BBOX,
    in_japan,
    shrine_id,
    to_records,
)

GEOJSON = pathlib.Path("public/data/osm/shrines.min.geojson")


@pytest.mark.unit
def test_t030_ids_are_deterministic_and_unique():
    """T-030: ID は OSM 要素から決定的に導かれ、型が違えば衝突しない。"""
    a = {"type": "way", "id": 123, "lat": 35.0, "lon": 135.0}
    b = {"type": "node", "id": 123, "lat": 35.0, "lon": 135.0}
    assert shrine_id(a) == shrine_id(dict(a)), "同じ入力から同じ ID が出ること"
    assert shrine_id(a) != shrine_id(b), "type が違えば ID も違うこと"
    assert shrine_id(a).startswith("jinja_")


@pytest.mark.unit
def test_t030b_bbox_rejects_outside_japan():
    """T-030: 外接矩形の判定。両端は含み、外は落とす。

    対照が成り立つ前提: 採用した矩形が実在の国土をすべて含むこと。
    与那国島・南鳥島・沖ノ鳥島・択捉島北端の公表座標で確かめる。
    """
    assert in_japan(122.93, 24.45), "与那国島(日本最西端)"
    assert in_japan(153.98, 24.28), "南鳥島(最東端)"
    assert in_japan(136.07, 20.42), "沖ノ鳥島(最南端)"
    assert in_japan(148.75, 45.55), "択捉島カムイワッカ岬(最北端)"
    # 外
    assert not in_japan(0.0, 0.0)
    assert not in_japan(139.7, 60.0)
    assert not in_japan(-139.7, 35.7)
    x0, y0, x1, y1 = JAPAN_BBOX
    assert not in_japan(x0 - 0.1, (y0 + y1) / 2)
    assert not in_japan((x0 + x1) / 2, y1 + 0.1)


@pytest.mark.unit
def test_t030c_records_drop_invalid_with_reasons():
    """T-030: 座標なし・矩形外・ID 重複は理由つきで落とす(黙って捨てない)。"""
    els = [
        {"type": "node", "id": 1, "lat": 35.0, "lon": 135.0, "tags": {"name": "有効神社"}},
        {"type": "node", "id": 2, "tags": {"name": "座標なし神社"}},                      # 座標なし
        {"type": "node", "id": 3, "lat": 51.5, "lon": -0.12, "tags": {"name": "London"}},  # 矩形外
        {"type": "node", "id": 1, "lat": 35.0, "lon": 135.0, "tags": {"name": "重複"}},    # 重複
    ]
    recs, dropped = to_records(els)
    assert [r["id"] for r in recs] == ["jinja_n1"]
    assert dropped == {"座標なし": 1, "日本の外接矩形外": 1, "ID 重複": 1}


@pytest.mark.unit
def test_t030d_way_uses_center():
    """T-030: way / relation は `out center` の center を座標に使う。"""
    els = [{"type": "way", "id": 9, "center": {"lat": 34.5, "lon": 135.5}, "tags": {"name": "社"}}]
    recs, dropped = to_records(els)
    assert recs[0]["location"] == {"lat": 34.5, "lon": 135.5, "prefecture": None, "municipality": None}
    assert sum(dropped.values()) == 0


@pytest.mark.unit
def test_t031_wikidata_tag_is_carried_but_flagged():
    """T-031: `wikidata` タグはカタログに載るが、GeoJSON の properties には出さない。

    SPEC §7 / D-02 — 名寄せの非循環オラクルなので、地図の描画属性として
    使えるところに置かない。
    """
    els = [{"type": "node", "id": 5, "lat": 35.0, "lon": 135.0,
            "tags": {"name": "八幡神社", "wikidata": "Q1"}}]
    recs, _ = to_records(els)
    assert recs[0]["external_ids"]["osm_wikidata_tag"] == "Q1"

    from export.build_geojson import feature

    props = feature(recs[0])["properties"]
    assert "osm_wikidata_tag" not in props
    assert "wikidata" not in props


@pytest.mark.validation
@pytest.mark.skipif(not GEOJSON.exists(), reason="公開 GeoJSON がまだ生成されていない")
def test_t031b_built_geojson_invariants():
    """T-031: 生成済み GeoJSON の構造と不変量(G-01 / G-03 / G-04)。"""
    fc = json.loads(GEOJSON.read_text(encoding="utf-8"))
    assert fc["type"] == "FeatureCollection"
    assert "OpenStreetMap contributors" in fc["attribution"], "F-02: 出典が付いていること"
    feats = fc["features"]
    assert feats, "走査対象が空でないこと"

    ids = [f["properties"]["id"] for f in feats]
    assert len(set(ids)) == len(ids), "G-03: 神社 ID が一意"

    for f in feats:
        assert f["type"] == "Feature"
        assert f["geometry"]["type"] == "Point"
        lon, lat = f["geometry"]["coordinates"]
        assert len(f["geometry"]["coordinates"]) == 2
        assert in_japan(lon, lat), f"G-04: 矩形外 {f['properties']['id']}"
