# -*- coding: utf-8 -*-
"""T-050〜T-053: Wikidata の取得と畳み込み。SPEC F-03。

期待値の出所:
- T-050: 2026-09-08 実測。OPTIONAL を 7 本重ねたクエリが Blazegraph の
  `java.util.concurrent.TimeoutException` で打ち切られたが、HTTP 200 /
  content-type `application/sparql-results+json` のまま、途中で切れた JSON の末尾に
  Java のスタックトレースが付いて返ってきた(30,069,925 バイト)
- T-051: `P31/P279*` は経路が複数あると同じ item を複数回返す。実測で
  座標つき日本の神社は COUNT(DISTINCT) 16,917 に対し行数 29,233
- T-053: Wikidata の時間値は `+0927-00-00T00:00:00Z` の形と `precision` を持つ
"""
import json

import pytest

from etl.fetch_wikidata import (
    fold_rows,
    parse_time_value,
    parse_wkt_point,
    verify_sparql_body,
)


@pytest.mark.unit
def test_t050_truncated_body_raises_even_on_http_200():
    """T-050: HTTP 200 でも本文が JSON でなければ例外にする(HC-075)。

    黙って通る道を残さない。打ち切りは「壊れたデータ」ではなく「取れなかった」である。
    """
    good = json.dumps({"results": {"bindings": [{"item": {"value": "Q1"}}]}}).encode()
    assert verify_sparql_body(good)["results"]["bindings"][0]["item"]["value"] == "Q1"

    # 実測した壊れ方: 途中で切れた JSON + Java のスタックトレース
    broken = (
        b'{\n  "results" : {\n    "bindings" : [ {\n      "admin" : {\n        "type" : '
        b"SPARQL-QUERY: queryStr=\nSELECT ?item WHERE { }\n"
        b"java.util.concurrent.TimeoutException\n\tat java.util.concurrent.FutureTask.get\n"
    )
    with pytest.raises(RuntimeError, match="打ち切"):
        verify_sparql_body(broken)


@pytest.mark.unit
def test_t050b_positive_control_detector_reads_the_body():
    """T-050 陽性対照: 検算が本文を実際に見ていること。

    対照が成り立つ前提 —— 正常な本文と壊れた本文が実際に違うこと。
    """
    good = json.dumps({"results": {"bindings": []}}).encode()
    assert verify_sparql_body(good) == {"results": {"bindings": []}}
    with pytest.raises(RuntimeError):
        verify_sparql_body(good[:-5])  # 末尾を削るだけで落ちること


@pytest.mark.unit
def test_t051_folds_duplicate_paths_into_one_record():
    """T-051: 同じ item が複数行で返っても 1 レコードに畳む。"""
    rows = [
        {"item": {"value": "http://www.wikidata.org/entity/Q1"},
         "itemLabel": {"value": "八幡神社"}, "coord": {"value": "Point(135.0 35.0)"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q1"},
         "itemLabel": {"value": "八幡神社"}, "coord": {"value": "Point(135.0 35.0)"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q2"},
         "itemLabel": {"value": "稲荷神社"}, "coord": {"value": "Point(136.0 36.0)"}},
    ]
    folded = fold_rows(rows)
    assert set(folded) == {"Q1", "Q2"}
    assert folded["Q1"]["label"] == "八幡神社"


@pytest.mark.unit
def test_t052_multi_valued_fold_is_deterministic():
    """T-052: 多値は決定的に畳む。行の並びを変えても同じ結果になる。

    「たまたま最初に来た値」を採ると、再実行のたびに属性が入れ替わる。
    """
    rows = [
        {"item": {"value": ".../Q1"}, "itemLabel": {"value": "諏訪大社"},
         "coord": {"value": "Point(138.1 36.0)"}},
        {"item": {"value": ".../Q1"}, "itemLabel": {"value": "諏訪大社"},
         "coord": {"value": "Point(138.2 35.9)"}},
    ]
    a = fold_rows(rows)
    b = fold_rows(list(reversed(rows)))
    assert a == b, "行の並びで結果が変わってはならない"
    assert len(a["Q1"]["coords"]) == 2, "捨てずに全部持つ"
    # 代表値も決定的であること
    assert a["Q1"]["coord"] == b["Q1"]["coord"]


@pytest.mark.unit
def test_t052b_parse_wkt_point():
    """T-052: WKT の Point は (lon, lat) の順である。"""
    assert parse_wkt_point("Point(135.7681 35.0116)") == (135.7681, 35.0116)
    assert parse_wkt_point("Point(139.702028 35.71775)") == (139.702028, 35.71775)
    assert parse_wkt_point("これは点ではない") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,precision,expected",
    [
        ("+0927-00-00T00:00:00Z", 9, (927, 927)),        # 年精度
        ("+1868-10-00T00:00:00Z", 10, (1868, 1868)),      # 年月精度
        ("+2001-04-01T00:00:00Z", 11, (2001, 2001)),      # 日精度
        ("+0700-00-00T00:00:00Z", 8, (700, 709)),         # 10 年紀
        ("+0700-00-00T00:00:00Z", 7, (700, 799)),         # 世紀
        ("-0660-00-00T00:00:00Z", 9, (-660, -660)),       # 紀元前
    ],
)
def test_t053_parse_time_value(value, precision, expected):
    """T-053: 精度を落とさずに年の範囲へ変換する。

    精度 7(世紀)を年として読むと「700 年創建」という嘘になる。
    Wikidata の precision の意味は https://www.wikidata.org/wiki/Help:Dates による。
    """
    assert parse_time_value(value, precision) == expected


@pytest.mark.unit
def test_t053b_unknown_precision_is_not_guessed():
    """T-053: 解釈できない精度は None を返す(もっともらしい値を作らない)。"""
    assert parse_time_value("+0927-00-00T00:00:00Z", 3) is None
    assert parse_time_value("よくわからない値", 9) is None
