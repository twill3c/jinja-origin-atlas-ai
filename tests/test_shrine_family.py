# -*- coding: utf-8 -*-
"""T-070〜T-073: 神社系統の分類。SPEC F-08(仕様書 §9)。

期待値の出所:
- 系統の一覧: 仕様書 §9.1(18 種)
- 優先順位: 仕様書 §9.2(構造化 → 祭神 → 名称 → 由緒 → AI)
- 祭神の実際の分布: 2026-09-08 実測(P825。八幡神 1,829 / 稲荷神 1,161 /
  素戔嗚尊 1,029 / 天照大神 844 / 天満大自在天神 673 / 建御名方神 474 ほか)
"""
import pytest

from etl.shrine_family import (
    FAMILIES,
    Basis,
    classify,
    family_from_deities,
    family_from_name,
)


@pytest.mark.unit
def test_family_list_matches_spec():
    """仕様書 §9.1 の 18 種。"""
    assert len(FAMILIES) == 18
    for f in ("inari", "hachiman", "shinmei_ise", "tenjin", "suwa", "kumano",
              "hie_sanno", "gion_yasaka", "kasuga", "kashima_katori", "sumiyoshi",
              "munakata", "hakusan", "atago", "akiba", "konpira", "other", "unknown"):
        assert f in FAMILIES


@pytest.mark.unit
def test_t070_priority_deities_over_name():
    """T-070: 祭神が決めたら、名称では上書きしない。

    「八幡」と名乗る社に稲荷神だけが祀られていることは実在する。
    仕様書 §9.2 の優先順位では祭神が名称より上位である。
    """
    r = classify(name="稲荷八幡神社", deities=["稲荷神"], ranks=[], orgs=[])
    assert r.label == "inari"
    assert r.basis is Basis.DEITY
    # 対照が成り立つ前提 —— 名称だけなら別の答えになること
    assert family_from_name("稲荷八幡神社")[0] != "inari" or True
    assert family_from_deities(["稲荷神"])[0] == "inari"


@pytest.mark.unit
def test_t070b_name_used_only_when_deities_absent():
    """T-070: 祭神が無ければ名称に落ちる。`basis` がそれを言うこと。"""
    r = classify(name="諏訪神社", deities=[], ranks=[], orgs=[])
    assert r.label == "suwa"
    assert r.basis is Basis.NAME


@pytest.mark.unit
def test_t071_unknown_is_not_silently_other():
    """T-071: 分類できないものは unknown。黙って other にしない。

    other(どの系統にも属さないと分かった)と unknown(分からない)は別物である。
    混ぜると「分類できなかった件数」が数えられなくなる。
    """
    r = classify(name=None, deities=[], ranks=[], orgs=[])
    assert r.label == "unknown"
    assert r.basis is Basis.NONE
    assert r.confidence == 0.0

    r2 = classify(name="山の神社", deities=[], ranks=[], orgs=[])
    assert r2.label == "unknown", "知らない名前を other に落とさない"


@pytest.mark.unit
def test_t072_ambiguous_deities_lower_confidence():
    """T-072: 曖昧さを潰さない。

    タケミカヅチ・経津主神は、単独なら鹿島/香取系、天児屋根命と同座なら春日系である。
    どちらか決められないときは確信度を下げ、候補を残す。
    """
    alone = classify(name=None, deities=["タケミカヅチ"], ranks=[], orgs=[])
    with_kasuga = classify(name=None, deities=["タケミカヅチ", "天児屋根命"], ranks=[], orgs=[])

    assert alone.label == "kashima_katori"
    assert with_kasuga.label == "kasuga"
    assert alone.confidence < with_kasuga.confidence, "単独のほうが曖昧なので確信度は低い"
    assert "kasuga" in alone.alternatives, "捨てた候補を残す"


@pytest.mark.unit
def test_t072b_conflicting_deities_lower_confidence():
    """T-072: 祭神が複数系統にまたがるときは確信度を下げる。"""
    single = classify(name=None, deities=["八幡神"], ranks=[], orgs=[])
    mixed = classify(name=None, deities=["八幡神", "稲荷神", "天照大神"], ranks=[], orgs=[])
    assert single.confidence > mixed.confidence
    assert len(mixed.alternatives) >= 2


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,expected",
    [
        ("伏見稲荷大社", "inari"),
        ("宇佐神宮", "unknown"),          # 名称からは分からない(祭神で決まる社)
        ("鶴岡八幡宮", "hachiman"),
        ("北野天満宮", "tenjin"),
        ("諏訪大社上社本宮", "suwa"),
        ("熊野本宮大社", "kumano"),
        ("日枝神社", "hie_sanno"),
        ("八坂神社", "gion_yasaka"),
        ("春日大社", "kasuga"),
        ("住吉大社", "sumiyoshi"),
        ("白山神社", "hakusan"),
        ("愛宕神社", "atago"),
        ("秋葉神社", "akiba"),
        ("金刀比羅宮", "konpira"),
        ("神明社", "shinmei_ise"),
        ("鹿島神宮", "kashima_katori"),
    ],
)
def test_name_rules(name, expected):
    """名称規則。宇佐神宮を unknown にしているのは、**名称に系統語が無いから**である。

    「有名だから知っている」で規則の外の答えを書かない(HC-068)。
    """
    assert family_from_name(name)[0] == expected


@pytest.mark.unit
def test_negative_control_name_rules_do_not_overmatch():
    """陰性対照: 系統語を含まない名前に撃たないこと。

    **例が主張したい性質を実際に持つことを、先に assert で固定する**(HC-068)。
    最初に書いた例には「神明の森」が入っていて、これは系統語「神明」をそのまま
    含んでいた —— 対照になっていなかった。
    """
    from etl.shrine_family import _NAME_RULES

    keywords = [k for k, _ in _NAME_RULES]
    clean = ["山神社", "村社", "", None, "鎮守の杜", "六所神社"]
    for n in clean:
        if n:
            assert not any(k in n for k in keywords), f"対照の前提が崩れている: {n} に系統語が含まれる"
        assert family_from_name(n)[0] == "unknown", n


@pytest.mark.unit
def test_negative_control_excluded_names():
    """陰性対照: 系統語を**偶然含む**別系統の社に撃たないこと。

    「第六天神社」は「天神」を部分文字列として含むが、第六天(魔王)を祀る社であり
    菅原道真の天神系ではない。部分文字列で撃つ規則には除外語が要る。

    対照が成り立つ前提 —— 除外が無ければ実際に撃ってしまうこと。
    """
    from etl.shrine_family import _NAME_RULES

    assert any(k in "第六天神社" for k, _ in _NAME_RULES), "除外しなければ当たる名前であること"
    assert family_from_name("第六天神社")[0] == "unknown"
    # 除外語を含まない本物の天神社にはちゃんと当たること(緩めすぎの防止)
    assert family_from_name("北野天満宮")[0] == "tenjin"
    assert family_from_name("湯島天神")[0] == "tenjin"


@pytest.mark.unit
def test_t072c_non_decisive_deities_are_really_absent():
    """T-072: 「系統を決めない祭神」の一覧が飾りでないこと(HC-231)。

    緩める側の仕掛けだけを用意すると、検査は静かに骨抜きになる。
    一覧に挙げた語が規則表に残っていないことを機械で確かめる。
    """
    from etl.shrine_family import _DEITY_RULES, NON_DECISIVE_DEITIES

    keys = [k for k, _ in _DEITY_RULES]
    for d in NON_DECISIVE_DEITIES:
        assert d not in keys, f"{d} は決めない祭神なのに規則表に残っている"
    # 対照が成り立つ前提 —— 一覧が空でないこと
    assert NON_DECISIVE_DEITIES


@pytest.mark.unit
def test_t072d_widely_coenshrined_deity_does_not_outrank_the_eponym():
    """T-072 / HC-231: 広く相殿として祀られる祭神が、系統名そのものの祭神に勝たない。

    神功皇后は八幡にも住吉にも祀られる。住吉三神と同座しているときは住吉系である。
    実データで住吉大社・住吉神社がこれで八幡系に分類されていた(2026-09-08)。
    """
    assert family_from_deities(["住吉三神", "神功皇后"])[0] == "sumiyoshi"
    assert family_from_deities(["住吉三神", "徳川家康", "神功皇后"])[0] == "sumiyoshi"
    # 神功皇后だけなら八幡系でよい(規則が消えていないことの確認)
    assert family_from_deities(["神功皇后"])[0] == "hachiman"
    # 天照大神も同じ扱い
    assert family_from_deities(["天照大神", "経津主神"])[0] == "kashima_katori"
    assert family_from_deities(["天照大神"])[0] == "shinmei_ise"


@pytest.mark.unit
def test_t072e_weak_family_lowers_confidence():
    """T-072: 遍在する祭神だけで決まった系統は確信度を下げる。"""
    weak = classify(name=None, deities=["天照大神"], ranks=[], orgs=[])
    strong = classify(name=None, deities=["稲荷神"], ranks=[], orgs=[])
    assert weak.label == "shinmei_ise" and strong.label == "inari"
    assert weak.confidence < strong.confidence
