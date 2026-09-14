# -*- coding: utf-8 -*-
"""T-124〜T-128: 名寄せの一対一と、同じ社を指す地物の統合。SPEC D-08。

loop_009 の実測(2026-09-14):
- マッチャーは多対一を許していた。自動結合 6,409 件のうち 222 項目に 2 件以上(485 件)
- 同名で 150 m 以内の組が 498(距離の中央 8 m)。OSM の wikidata タグが両方にある 12 組は
  12 組とも同じタグ、両方が自動結合された 120 組は 117 組が同じ項目
- 「佐紀神社」のように、同名で 135 m しか離れていない**実在の別社**がある(別の Wikidata 項目)

期待値の出所:
- 距離: 緯度 1 度 = πR/180(R = 6,371,008.8 m)= 111,194.9 m。前提の距離は haversine_m で
  確かめてから使う(記憶の数値で書かない)
"""
import json
import pathlib

import pytest

from etl.entity_resolution import Match, MatchDecision, haversine_m, resolve, resolve_one_to_one
from export.dedupe import merge_same_name, part_suffix

M_PER_DEG_LAT = 111_194.9


def _rec(sid, name, lat, lon=135.0, typ="node"):
    return {"id": sid, "name": {"ja": name, "kana": None, "en": None}, "aliases": [],
            "location": {"lon": lon, "lat": lat, "prefecture": None, "municipality": None},
            "external_ids": {"osm_type": typ, "osm_id": int(sid.split("_")[-1][1:]),
                             "osm_wikidata_tag": None}}


def _m(sid, qid=None, decision=MatchDecision.AUTO, score=0.7):
    if qid is None:
        return Match(sid, None, 0.0, MatchDecision.SEPARATE, None, None)
    return Match(sid, qid, score, decision, 0.0, 1.0)


def _wd(qid, lon, lat, label):
    return {"qid": qid, "label": label, "kana": None, "official": None, "aliases": [],
            "coord": (lon, lat), "admin_label": None, "osm_ids": []}


def _lat_for(metres):
    return metres / M_PER_DEG_LAT


# ---------------------------------------------------------------- T-125 統合の規則

@pytest.mark.unit
def test_t125_same_name_within_150m_is_merged_and_151m_is_not():
    near = _lat_for(145.0)
    far = _lat_for(151.5)
    assert haversine_m(135.0, 35.0, 135.0, 35.0 + near) < 150.0, "前提: 近いほうは 150 m 未満"
    assert haversine_m(135.0, 35.0, 135.0, 35.0 + far) > 150.0, "前提: 遠いほうは 150 m 超"

    recs = [_rec("jinja_n1", "八幡神社", 35.0), _rec("jinja_w2", "八幡神社", 35.0 + near, typ="way")]
    r = merge_same_name(recs, {x["id"]: _m(x["id"]) for x in recs})
    assert [x["id"] for x in r.survivors] == ["jinja_w2"]
    assert r.aliases == {"jinja_n1": "jinja_w2"}

    recs = [_rec("jinja_n1", "八幡神社", 35.0), _rec("jinja_w2", "八幡神社", 35.0 + far, typ="way")]
    r = merge_same_name(recs, {x["id"]: _m(x["id"]) for x in recs})
    assert sorted(x["id"] for x in r.survivors) == ["jinja_n1", "jinja_w2"]
    assert r.aliases == {}


@pytest.mark.unit
def test_t125_different_wikidata_items_are_not_merged():
    """実在の別社(佐紀神社の型): 両方が別の項目に自動結合されていれば統合しない。"""
    d = _lat_for(100.0)
    recs = [_rec("jinja_n1", "佐紀神社", 35.0), _rec("jinja_n2", "佐紀神社", 35.0 + d)]
    r = merge_same_name(recs, {"jinja_n1": _m("jinja_n1", "Q1"), "jinja_n2": _m("jinja_n2", "Q2")})
    assert len(r.survivors) == 2 and r.aliases == {}
    assert r.guarded_pairs == 1

    # 片方だけ結合 / 同じ項目 なら統合する
    r = merge_same_name(recs, {"jinja_n1": _m("jinja_n1", "Q1"), "jinja_n2": _m("jinja_n2")})
    assert len(r.survivors) == 1
    r = merge_same_name(recs, {"jinja_n1": _m("jinja_n1", "Q1"), "jinja_n2": _m("jinja_n2", "Q1")})
    assert len(r.survivors) == 1


@pytest.mark.unit
def test_t125_chain_with_two_items_is_left_unmerged():
    """A—B—C と連鎖し、A と C が別の項目なら、成分ごと統合しない(推移で別社を融合させない)。"""
    d = _lat_for(100.0)
    recs = [_rec("jinja_n1", "稲荷神社", 35.0), _rec("jinja_n2", "稲荷神社", 35.0 + d),
            _rec("jinja_n3", "稲荷神社", 35.0 + 2 * d)]
    assert haversine_m(135.0, 35.0, 135.0, 35.0 + 2 * d) > 150.0, "前提: A と C は直接には近くない"
    ms = {"jinja_n1": _m("jinja_n1", "Q1"), "jinja_n2": _m("jinja_n2"), "jinja_n3": _m("jinja_n3", "Q2")}
    r = merge_same_name(recs, ms)
    assert len(r.survivors) == 3 and r.aliases == {}
    assert r.guarded_components == 1


@pytest.mark.unit
def test_t125_survivor_priority_and_provenance():
    d = _lat_for(10.0)
    recs = [_rec("jinja_n5", "神明社", 35.0), _rec("jinja_w9", "神明社", 35.0 + d, typ="way"),
            _rec("jinja_r3", "神明社", 35.0 + 2 * d, typ="relation")]
    r = merge_same_name(recs, {x["id"]: _m(x["id"]) for x in recs})
    assert [x["id"] for x in r.survivors] == ["jinja_r3"]
    s = r.survivors[0]
    assert sorted(s["merged_from"]) == ["jinja_n5", "jinja_w9"], "統合した地物を記録していない"
    assert r.aliases == {"jinja_n5": "jinja_r3", "jinja_w9": "jinja_r3"}
    # 入力の並びで答えが変わらない
    r2 = merge_same_name(list(reversed(recs)), {x["id"]: _m(x["id"]) for x in recs})
    assert [x["id"] for x in r2.survivors] == ["jinja_r3"]


@pytest.mark.unit
def test_t125_empty_names_and_different_names_are_not_merged():
    d = _lat_for(5.0)
    recs = [_rec("jinja_n1", "", 35.0), _rec("jinja_n2", "", 35.0 + d),
            _rec("jinja_n3", "八坂神社", 35.0), _rec("jinja_n4", "八幡神社", 35.0 + d)]
    r = merge_same_name(recs, {x["id"]: _m(x["id"]) for x in recs})
    assert len(r.survivors) == 4 and r.aliases == {}


@pytest.mark.unit
def test_t125_whitespace_in_names_does_not_block_a_merge():
    d = _lat_for(5.0)
    recs = [_rec("jinja_n1", "尾曳稲荷神社", 35.0), _rec("jinja_w2", "尾曳 稲荷神社", 35.0 + d, typ="way")]
    r = merge_same_name(recs, {x["id"]: _m(x["id"]) for x in recs})
    assert len(r.survivors) == 1


# ---------------------------------------------------------------- T-128 社の部分の印

@pytest.mark.unit
@pytest.mark.parametrize("name,want", [
    ("心清水八幡神社本殿", "本殿"), ("尾曳稲荷神社 拝殿", "拝殿"), ("北海道神宮神門", "神門"),
    ("札幌伏見稲荷神社手水舎", "手水舎"), ("社務所", "社務所"),
    ("八幡神社", None), ("本殿神社", None), ("", None), (None, None),
])
def test_t128_part_suffix(name, want):
    assert part_suffix(name) == want


# ---------------------------------------------------------------- T-124 一対一

@pytest.mark.unit
def test_t124_one_item_goes_to_the_best_feature_and_the_loser_takes_the_next():
    # o1 は Q1 の真上、o2 は 40 m 離れている。近くに Q2(別名)もある
    d = _lat_for(40.0)
    osm = [
        {**_rec("jinja_n2", "八幡神社", 35.0 + d), "aliases": []},
        {**_rec("jinja_n1", "八幡神社", 35.0), "aliases": []},
    ]
    wd = [_wd("Q1", 135.0, 35.0, "八幡神社"), _wd("Q2", 135.0, 35.0 + d, "八幡社")]
    many = {m.osm_id: m for m in resolve(osm, wd)}
    assert many["jinja_n1"].qid == many["jinja_n2"].qid == "Q1", "前提: 多対一では両方が Q1 を取る"

    one = {m.osm_id: m for m in resolve_one_to_one(osm, wd)}
    assert one["jinja_n1"].qid == "Q1"
    assert one["jinja_n2"].qid == "Q2", "負けたほうが空いている次の候補を取っていない"
    assert [m.osm_id for m in resolve_one_to_one(osm, wd)] == ["jinja_n2", "jinja_n1"], "入力の並びを保つ"


@pytest.mark.unit
def test_t124_loser_without_a_free_candidate_is_separate():
    d = _lat_for(40.0)
    osm = [_rec("jinja_n1", "八幡神社", 35.0), _rec("jinja_n2", "八幡神社", 35.0 + d)]
    wd = [_wd("Q1", 135.0, 35.0, "八幡神社")]
    one = {m.osm_id: m for m in resolve_one_to_one(osm, wd)}
    assert one["jinja_n1"].qid == "Q1"
    assert one["jinja_n2"].qid is None and one["jinja_n2"].decision is MatchDecision.SEPARATE


@pytest.mark.unit
def test_t124_result_is_independent_of_input_order():
    d = _lat_for(20.0)
    osm = [_rec(f"jinja_n{i}", "稲荷神社", 35.0 + i * d) for i in range(1, 6)]
    wd = [_wd(f"Q{i}", 135.0, 35.0 + i * d * 1.5, "稲荷神社") for i in range(1, 4)]
    a = sorted((m.osm_id, m.qid) for m in resolve_one_to_one(osm, wd))
    b = sorted((m.osm_id, m.qid) for m in resolve_one_to_one(list(reversed(osm)), list(reversed(wd))))
    assert a == b
    got = [q for _, q in a if q]
    assert len(got) == len(set(got)), "一つの項目が二度使われている"


# ---------------------------------------------------------------- 出荷物に対する検査

FULL = pathlib.Path("data/interim/catalog_full.json")
BUILD = pathlib.Path("public/data/meta/build.json")
INDEX = pathlib.Path("public/data/shrines/index.json")


@pytest.fixture(scope="module")
def shipped():
    if not (FULL.exists() and BUILD.exists() and INDEX.exists()):
        pytest.skip("出荷物がまだ無い")
    return {"recs": json.loads(FULL.read_text(encoding="utf-8"))["shrines"],
            "build": json.loads(BUILD.read_text(encoding="utf-8")),
            "index": json.loads(INDEX.read_text(encoding="utf-8"))}


@pytest.mark.validation
def test_t124_no_wikidata_item_is_auto_matched_twice(shipped):
    seen: dict[str, list[str]] = {}
    for r in shipped["recs"]:
        if (r.get("match") or {}).get("decision") == "auto":
            seen.setdefault(r["external_ids"]["wikidata"], []).append(r["id"])
    multi = {q: v for q, v in seen.items() if len(v) > 1}
    assert seen, "自動結合が 1 件も無い(検査が空振りする)"
    assert multi == {}, f"{len(multi)} 項目が複数の神社に結合されている。例: {list(multi.items())[:3]}"


@pytest.mark.validation
def test_t126_remaining_same_name_pairs_equal_the_guarded_count(shipped):
    from export.dedupe import same_name_pairs

    pairs = same_name_pairs(shipped["recs"], 150.0)
    d = shipped["build"]["dedupe"]
    assert d["merged_features"] > 0, "統合が 1 件も起きていない(規則が働いていない疑い)"
    assert len(pairs) == d["guarded_pairs_remaining"], (
        f"同名で 150 m 以内の組が {len(pairs)} 残っている(報告は {d['guarded_pairs_remaining']})")


@pytest.mark.validation
def test_t127_aliases_point_to_existing_ids(shipped):
    idx = shipped["index"]
    aliases = idx.get("aliases")
    assert aliases, "索引に aliases が無い"
    assert not (set(aliases) & set(idx["ids"])), "統合で消えた ID が ids にも残っている"
    bad = {k: v for k, v in aliases.items() if v not in idx["ids"]}
    assert bad == {}, f"実在しない ID を指す別名: {list(bad.items())[:3]}"
    assert len(aliases) == shipped["build"]["dedupe"]["merged_features"]


@pytest.mark.validation
def test_t128_part_flags_are_counted(shipped):
    flagged = [r for r in shipped["recs"] if r.get("suspected_part")]
    assert flagged, "社の部分の印が 1 件も無い"
    for r in flagged:
        assert part_suffix(r["name"]["ja"]) == r["suspected_part"]["suffix"]
    assert len(flagged) == shipped["build"]["dedupe"]["suspected_parts"]


@pytest.mark.unit
def test_t124_tie_goes_to_the_older_wikidata_item():
    """同じ社に項目が二つある(後から作られた重複)と得点が 0.7 で並ぶ。**古い項目を取る。**

    距離で決めると数 m 近いだけの新しい重複項目が取り、OSM と相互リンクされた本来の項目が余る。
    較正半分で測って決めた(SPEC D-08)。
    """
    d = _lat_for(5.0)
    osm = [_rec("jinja_n1", "麻賀多神社", 35.0)]
    wd = [_wd("Q135270425", 135.0, 35.0 + d / 5, "麻賀多神社"),  # 新しい重複項目。わずかに近い
          _wd("Q11677652", 135.0, 35.0 + d, "麻賀多神社")]
    one = resolve_one_to_one(osm, wd)
    assert one[0].score == pytest.approx(0.7), "前提: 両候補が同点で張り付く"
    assert one[0].qid == "Q11677652"
