# -*- coding: utf-8 -*-
"""T-060〜T-066: 名寄せ。SPEC F-04 / G-09 / D-02。

期待値の出所:
- 重みと閾値: 仕様書 §8.4(0.40 地理 / 0.30 名称 / 0.10 行政 / 0.10 外部 ID / 0.10 別名、
  ≥0.90 auto / 0.75–0.89 review / <0.75 separate)
- オラクル: Wikidata の P10689 / P11693 / P402 と OSM の `wikidata` タグ
  (SPEC M-11 / §7)。**マッチャーはこれを入力に使わない**(D-02)
"""
import pytest

from etl.entity_resolution import (
    AUTO_THRESHOLD,
    WEIGHTS,
    Candidate,
    MatchDecision,
    decide,
    haversine_m,
    match_score,
    resolve,
)


def _osm(sid, lon, lat, name, **extra):
    return {
        "id": sid,
        "name": {"ja": name, "kana": extra.get("kana"), "en": None},
        "aliases": extra.get("aliases", []),
        "location": {"lon": lon, "lat": lat, "prefecture": extra.get("pref"),
                     "municipality": extra.get("muni")},
        "external_ids": {"osm_type": "node", "osm_id": int(sid.split("n")[-1]),
                         "osm_wikidata_tag": extra.get("wd_tag")},
    }


def _wd(qid, lon, lat, label, **extra):
    return {
        "qid": qid,
        "label": label,
        "kana": extra.get("kana"),
        "official": extra.get("official"),
        "aliases": extra.get("aliases", []),
        "coord": (lon, lat),
        "admin_label": extra.get("pref"),
        "osm_ids": extra.get("osm_ids", []),
    }


@pytest.mark.unit
def test_t060_weights_sum_to_one_and_score_in_range():
    """T-060: 仕様書 §8.4 の重み。合計 1.0、値域 [0,1]。"""
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert set(WEIGHTS) == {"geo", "name", "admin", "external_id", "alias"}
    assert WEIGHTS["geo"] == pytest.approx(0.40)
    assert WEIGHTS["name"] == pytest.approx(0.30)

    pairs = [
        (_osm("jinja_n1", 135.0, 35.0, "八幡神社"), _wd("Q1", 135.0, 35.0, "八幡神社")),
        (_osm("jinja_n2", 135.0, 35.0, "八幡神社"), _wd("Q2", 139.0, 40.0, "全然別の社")),
        (_osm("jinja_n3", 135.0, 35.0, ""), _wd("Q3", 135.0, 35.0, "名無し対照")),
    ]
    for o, w in pairs:
        s = match_score(o, w)
        assert 0.0 <= s.total <= 1.0, s


@pytest.mark.unit
def test_t060b_identical_pair_scores_the_reachable_maximum():
    """T-060: 同じ場所・同じ名前・同じ行政区画のとき、到達可能な最大値になる。

    **0.90 にはならない。** D-02 で `external_id`(0.10)の材料を禁じており、
    別名も無いので、理想入力でも 0.40 + 0.30 + 0.10 = 0.80 が上限である(HC-229)。
    ここで 0.90 を期待すると、正しい実装のほうが落ちる。
    """
    o = _osm("jinja_n1", 135.7681, 35.0116, "八坂神社", pref="京都府")
    w = _wd("Q1", 135.7681, 35.0116, "八坂神社", pref="京都府")
    s = match_score(o, w)
    assert (s.geo, s.name, s.admin) == (1.0, 1.0, 1.0)
    assert s.total == pytest.approx(WEIGHTS["geo"] + WEIGHTS["name"] + WEIGHTS["admin"])
    assert decide(s.total) is MatchDecision.AUTO


@pytest.mark.unit
def test_t061b_spec_threshold_is_unreachable_under_d02():
    """T-061 / HC-229: 仕様書 §8.4 の 0.90 が到達不能であることを検査で固定する。

    逸脱を「そういうことにした」で済ませず、**なぜ逸脱したかを機械で確かめる**。
    もし将来 external_id の材料が非循環に手に入るようになれば、この検査が落ちて
    「仕様の閾値に戻せる」と教えてくれる。
    """
    from etl.entity_resolution import SPEC_AUTO_THRESHOLD

    # D-02 のもとで実際に埋まりうる項だけを最大にした値
    reachable_max = WEIGHTS["geo"] + WEIGHTS["name"] + WEIGHTS["admin"] + WEIGHTS["alias"]
    assert reachable_max < SPEC_AUTO_THRESHOLD + 1e-9
    assert AUTO_THRESHOLD < SPEC_AUTO_THRESHOLD, "置き直した閾値は仕様値より低いこと"
    # 別名まで一致する理想の組でも、仕様の閾値には届かないこと
    o = _osm("jinja_n1", 135.0, 35.0, "八幡神社", pref="京都府", aliases=["八幡社"])
    w = _wd("Q1", 135.0, 35.0, "八幡神社", pref="京都府", aliases=["八幡社"])
    assert match_score(o, w).total < SPEC_AUTO_THRESHOLD


@pytest.mark.unit
def test_t061_decision_boundaries():
    """T-061: 判定の境界。閾値そのものではなく**境界の振る舞い**を確かめる。

    仕様書 §8.4 は「>= 0.90 / 0.75-0.89 / < 0.75」と書いていたが、その値は
    到達不能だった(HC-229)。ここで数値を直書きすると、較正で閾値を動かすたびに
    このテストが「正しい実装を落とす」側に回る。
    """
    from etl.entity_resolution import REVIEW_THRESHOLD

    assert REVIEW_THRESHOLD < AUTO_THRESHOLD
    eps = 1e-4
    assert decide(1.0) is MatchDecision.AUTO
    assert decide(AUTO_THRESHOLD) is MatchDecision.AUTO
    assert decide(AUTO_THRESHOLD - eps) is MatchDecision.REVIEW
    assert decide(REVIEW_THRESHOLD) is MatchDecision.REVIEW
    assert decide(REVIEW_THRESHOLD - eps) is MatchDecision.SEPARATE
    assert decide(0.0) is MatchDecision.SEPARATE


@pytest.mark.unit
def test_t061c_calibrated_thresholds_are_the_measured_ones():
    """T-061: 較正で決めた閾値を実測値として固定する。

    出所 —— オラクル 825 組の**較正半分 411 組だけ**を見た閾値掃き(2026-09-08)。
    0.58 → 適合率 0.9975 / 再現率 0.9708、**0.60 → 適合率 1.0000 / 再現率 0.9611**、
    0.62 → 適合率 1.0000 / 再現率 0.9173。適合率が 1.0 になる最小の閾値を採った。
    """
    from etl.entity_resolution import REVIEW_THRESHOLD

    assert AUTO_THRESHOLD == pytest.approx(0.60)
    assert REVIEW_THRESHOLD == pytest.approx(0.50)


@pytest.mark.unit
def test_t062_matcher_ignores_direct_links():
    """T-062 / D-02 循環の禁止: 直リンクを与えても与えなくても結果が同じ。

    仕様書 §8.3 は補助特徴に「OSM wikidata tag」を挙げているが、これはオラクルの
    裏返しなので入力に混ぜるとオラクルが恒等式になる(HC-045)。

    対照が成り立つ前提 —— 与えるリンクが実際に「正解」を指していること。
    指していないリンクを与えても、何も証明できない。
    """
    o_plain = _osm("jinja_n1", 135.0, 35.0, "八幡神社")
    o_linked = _osm("jinja_n1", 135.0, 35.0, "八幡神社", wd_tag="Q1")
    w_plain = _wd("Q1", 135.0, 35.0, "八幡神社")
    w_linked = _wd("Q1", 135.0, 35.0, "八幡神社", osm_ids=["node/1"])

    assert o_linked["external_ids"]["osm_wikidata_tag"] == w_plain["qid"], "リンクが正解を指していること"

    base = match_score(o_plain, w_plain)
    assert match_score(o_linked, w_plain) == base
    assert match_score(o_plain, w_linked) == base
    assert match_score(o_linked, w_linked) == base


@pytest.mark.unit
def test_t062b_resolve_output_is_unchanged_by_links():
    """T-062: 経路まで含めて同じであること(結論だけの一致では足りない / HC-065)。"""
    osm_plain = [_osm("jinja_n1", 135.0, 35.0, "八幡神社"), _osm("jinja_n2", 136.0, 36.0, "稲荷神社")]
    osm_linked = [_osm("jinja_n1", 135.0, 35.0, "八幡神社", wd_tag="Q1"),
                  _osm("jinja_n2", 136.0, 36.0, "稲荷神社", wd_tag="Q2")]
    wds = [_wd("Q1", 135.0, 35.0, "八幡神社"), _wd("Q2", 136.0, 36.0, "稲荷神社")]

    a = resolve(osm_plain, wds)
    b = resolve(osm_linked, [dict(w, osm_ids=["node/1"]) for w in wds])
    assert [(m.osm_id, m.qid, m.decision, round(m.score, 9)) for m in a] == \
           [(m.osm_id, m.qid, m.decision, round(m.score, 9)) for m in b]


@pytest.mark.unit
def test_t064_negative_control_same_name_far_apart():
    """T-064 陰性対照: 同名でも 100 km 離れていれば結合しない。

    「八幡神社」は全国にある。名前だけで寄せると別の神社が融合する。
    """
    o = _osm("jinja_n1", 135.0, 35.0, "八幡神社")
    w = _wd("Q1", 136.2, 35.0, "八幡神社")  # 経度 1.2 度 ≒ 109 km
    d = haversine_m(135.0, 35.0, 136.2, 35.0)
    assert d > 100_000, f"対照が成り立つ前提: 実距離 {d:.0f} m"
    assert decide(match_score(o, w).total) is MatchDecision.SEPARATE


@pytest.mark.unit
def test_haversine_against_external_authority():
    """距離計算の検算。**外部権威と別式の二重**で確かめる。

    出所 1(外部権威): 海里の定義。子午線に沿った緯度 1 分は約 1,852 m である。
    球面(半径 6,371,008.8 m)では πR/(180×60) = 1,853.2 m なので、
    0.5% の幅で押さえる。これは実装から独立に決まる値である。

    出所 2(別式): 球面三角法の余弦定理。haversine とは別の式なので、
    実装の写し間違いを捕まえられる。
    """
    import math

    # 緯度 1 分 ≒ 1 海里
    one_arcmin = haversine_m(0.0, 35.0, 0.0, 35.0 + 1.0 / 60.0)
    assert 1852.0 * 0.995 <= one_arcmin <= 1853.2 * 1.005, one_arcmin

    # 極 → 赤道の子午線弧長は約 10,002 km(球面近似)
    quarter = haversine_m(0.0, 0.0, 0.0, 90.0)
    assert 9_995_000 <= quarter <= 10_010_000, quarter

    # 別式(余弦定理)と一致すること
    def law_of_cosines(lon1, lat1, lon2, lat2):
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl = math.radians(lon2 - lon1)
        c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
        return 6371008.8 * math.acos(max(-1.0, min(1.0, c)))

    for a in [(139.767125, 35.681236, 135.758767, 34.985849),
              (130.4, 33.6, 141.35, 43.06),
              (135.0, 35.0, 135.01, 35.0)]:
        assert haversine_m(*a) == pytest.approx(law_of_cosines(*a), rel=1e-6), a

    assert haversine_m(135.0, 35.0, 135.0, 35.0) == pytest.approx(0.0)


@pytest.mark.unit
def test_haversine_tokyo_kyoto_measured_value():
    """実測の記録。東京駅 — 京都駅の大円距離。

    2026-09-08 に本実装で測った値は 371,710.6 m(半径 6,371,008.8 m の球面)。
    これは**外部権威ではなく実測**なので、上の test_haversine_against_external_authority が
    正しさの根拠であり、こちらは回帰の見張りである。
    """
    d = haversine_m(139.767125, 35.681236, 135.758767, 34.985849)
    assert d == pytest.approx(371_710.6, abs=1.0)


@pytest.mark.unit
def test_candidate_is_hashable_and_ordered():
    """候補は決定的に並ぶこと(同点で順序が揺れると再実行で結果が変わる)。"""
    c1 = Candidate(osm_id="jinja_n1", qid="Q1", score=0.9, distance_m=10.0, name_sim=1.0)
    c2 = Candidate(osm_id="jinja_n1", qid="Q2", score=0.9, distance_m=10.0, name_sim=1.0)
    assert sorted([c2, c1])[0].qid == "Q1", "同点は qid で決定的に決める"
