# -*- coding: utf-8 -*-
"""神社系統の分類 — SPEC F-08(仕様書 §9)。

優先順位は仕様書 §9.2 に従う::

    1. 明示された structured data(包括団体・社格)
    2. 祭神
    3. 名称ルール
    4. 由緒テキスト     ← V1.0 後半
    5. AI 推定          ← V1.0 後半

**`unknown` と `other` を混ぜない。** `other`「どの系統にも属さないと分かった」と
`unknown`「分からない」は別物で、混ぜると「分類できなかった件数」が数えられなくなる。

**曖昧さを潰さない。** タケミカヅチ・経津主神は、単独なら鹿島/香取系、天児屋根命と
同座なら春日系である。決められないときは確信度を下げ、捨てた候補を `alternatives` に残す。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Sequence

from etl.normalize import normalize_name

#: 仕様書 §9.1 の系統一覧。
FAMILIES: tuple[str, ...] = (
    "inari", "hachiman", "shinmei_ise", "tenjin", "suwa", "kumano",
    "hie_sanno", "gion_yasaka", "kasuga", "kashima_katori", "sumiyoshi",
    "munakata", "hakusan", "atago", "akiba", "konpira", "other", "unknown",
)

FAMILY_JA: dict[str, str] = {
    "inari": "稲荷系", "hachiman": "八幡系", "shinmei_ise": "神明・伊勢系",
    "tenjin": "天神系", "suwa": "諏訪系", "kumano": "熊野系",
    "hie_sanno": "日吉・山王系", "gion_yasaka": "祇園・八坂系", "kasuga": "春日系",
    "kashima_katori": "鹿島・香取系", "sumiyoshi": "住吉系", "munakata": "宗像系",
    "hakusan": "白山系", "atago": "愛宕系", "akiba": "秋葉系", "konpira": "金刀比羅系",
    "other": "その他", "unknown": "不明",
}


class Basis(enum.StrEnum):
    STRUCTURED = "structured"
    DEITY = "deity"
    NAME = "name"
    ORIGIN_TEXT = "origin_text"
    AI = "ai"
    NONE = "none"


@dataclass(frozen=True)
class FamilyVerdict:
    label: str
    basis: Basis
    confidence: float
    alternatives: tuple[str, ...] = field(default_factory=tuple)


#: 祭神ラベル → 系統。値は 2026-09-08 に P825 の実分布(上位 20)を見て決めた。
#:
#: **この表の並びが優先順位である**(HC-231)。入力の並びで答えが変わらないよう、
#: 走査はこの表を外側で回す。系統を強く決める祭神を先に、**遍在する祭神を末尾に**置く。
#: 神功皇后は八幡にも住吉にも祀られ、天照大神は多くの社の相殿にいる。
#: 系統名そのものの祭神(住吉三神・稲荷神など)より上位に置いてはならない。
_DEITY_RULES: tuple[tuple[str, str], ...] = (
    ("八幡神", "hachiman"), ("応神天皇", "hachiman"), ("誉田別命", "hachiman"),
    ("稲荷神", "inari"), ("ウカノミタマ", "inari"), ("宇迦之御魂", "inari"), ("倉稲魂", "inari"),
    ("天満大自在天神", "tenjin"), ("菅原道真", "tenjin"),
    ("建御名方", "suwa"), ("八坂刀売", "suwa"),
    ("熊野権現", "kumano"), ("家都御子", "kumano"), ("熊野牟須美", "kumano"),
    ("大山咋", "hie_sanno"),
    ("素戔嗚", "gion_yasaka"), ("スサノオ", "gion_yasaka"), ("牛頭天王", "gion_yasaka"),
    ("春日神", "kasuga"), ("天児屋根", "kasuga"),
    ("タケミカヅチ", "kashima_katori"), ("建御雷", "kashima_katori"),
    ("経津主", "kashima_katori"), ("フツヌシ", "kashima_katori"),
    ("住吉", "sumiyoshi"), ("底筒", "sumiyoshi"), ("中筒", "sumiyoshi"), ("上筒", "sumiyoshi"),
    ("宗像", "munakata"), ("市杵島", "munakata"), ("田心", "munakata"), ("湍津", "munakata"),
    ("菊理媛", "hakusan"), ("白山比咩", "hakusan"),
    ("愛宕", "atago"), ("火産霊", "atago"), ("迦具土", "atago"),
    ("秋葉", "akiba"),
    ("金山彦", "konpira"), ("大物主", "konpira"),
    # --- ここから下は広く相殿として祀られる祭神。他が当たっていれば勝たせない(HC-231) ---
    ("神功皇后", "hachiman"),
    ("天照大神", "shinmei_ise"), ("天照大御神", "shinmei_ise"),
)

#: **系統を決めない祭神。** 規則表から外してある理由をここに残す。
#: - 豊受・トヨウケ: 稲荷信仰では豊受姫が宇迦之御魂と習合する。神明系とも稲荷系とも取れる
#: - 比売神・比売大神: 八幡・春日・宗像いずれにも現れる一般名
#: 決められないものを決めない —— 名称や構造化データに判断を譲る(HC-231)。
NON_DECISIVE_DEITIES: tuple[str, ...] = ("豊受", "トヨウケ", "比売神", "比売大神")

#: 遍在するため単独では系統を強く決めない祭神が属する系統。確信度を下げる。
_WEAK_FAMILIES = frozenset({"shinmei_ise"})

#: 名称 → 系統。**部分文字列で撃つので、撃ちすぎないことを陰性対照で押さえる。**
_NAME_RULES: tuple[tuple[str, str], ...] = (
    ("稲荷", "inari"),
    ("八幡", "hachiman"),
    ("天満", "tenjin"), ("天神", "tenjin"),
    ("諏訪", "suwa"),
    ("熊野", "kumano"),
    ("日吉", "hie_sanno"), ("日枝", "hie_sanno"), ("山王", "hie_sanno"),
    ("八坂", "gion_yasaka"), ("祇園", "gion_yasaka"), ("素盞嗚", "gion_yasaka"),
    ("津島", "gion_yasaka"),
    ("春日", "kasuga"),
    ("鹿島", "kashima_katori"), ("香取", "kashima_katori"),
    ("住吉", "sumiyoshi"),
    ("宗像", "munakata"), ("厳島", "munakata"),
    ("白山", "hakusan"),
    ("愛宕", "atago"),
    ("秋葉", "akiba"),
    ("金刀比羅", "konpira"), ("琴平", "konpira"), ("金比羅", "konpira"),
    ("神明", "shinmei_ise"), ("皇大神", "shinmei_ise"), ("大神宮", "shinmei_ise"),
)

#: 「春日と同座なら春日系」のように、同座で解釈が変わる組。
_KASUGA_COMPANIONS = ("天児屋根", "春日神", "比売大神")

#: **撃ってはならない語。** 部分文字列で撃つ規則は、系統語を偶然含む別系統の社に当たる。
#: 「第六天神社」は第六天(魔王)を祀る社で、菅原道真の天神系ではない
#: (陰性対照 test_negative_control_name_rules_do_not_overmatch が捕まえた)。
_NAME_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("第六天", "tenjin"),
    ("天神地祇", "tenjin"),
)


def family_from_deities(deities: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """祭神から系統を決める。:returns: (系統, 捨てた候補)

    **規則を外側で回す。** 祭神リストを外側で回すと、答えが Wikidata の値の並び順で
    決まってしまう(HC-231)。天照大神・豊受は多くの社に相殿として祀られる**弱い手がかり**
    なので、規則表の末尾に置き、他の系統が当たっているときは勝たせない。
    """
    normalized = [normalize_name(d) for d in deities]
    hits: list[str] = []
    for key, fam in _DEITY_RULES:
        if fam in hits:
            continue
        if any(key in n for n in normalized):
            hits.append(fam)
    if not hits:
        return "unknown", ()

    # 鹿島/香取の神は、春日の神と同座していれば春日系である
    if "kashima_katori" in hits:
        companion = any(k in normalize_name(d) for d in deities for k in _KASUGA_COMPANIONS)
        if companion:
            hits = ["kasuga"] + [h for h in hits if h not in ("kashima_katori", "kasuga")]
    return hits[0], tuple(hits[1:])


def family_from_name(name: str | None) -> tuple[str, tuple[str, ...]]:
    """名称から系統を決める。当たらなければ unknown(other にしない)。"""
    if not name:
        return "unknown", ()
    n = normalize_name(name)
    blocked = {fam for key, fam in _NAME_EXCLUSIONS if key in n}
    hits: list[str] = []
    for key, fam in _NAME_RULES:
        if key in n and fam not in hits and fam not in blocked:
            hits.append(fam)
    if not hits:
        return "unknown", ()
    return hits[0], tuple(hits[1:])


def _structured(ranks: Sequence[str], orgs: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """包括団体から系統が読めることがある(例: 稲荷神社の包括団体)。

    社格(式内小社・村社など)は**格であって系統ではない**ので、ここでは使わない。
    """
    for o in orgs:
        n = normalize_name(o)
        for key, fam in _NAME_RULES:
            if key in n:
                return fam, ()
    return "unknown", ()


def classify(
    *,
    name: str | None,
    deities: Sequence[str],
    ranks: Sequence[str],
    orgs: Sequence[str],
) -> FamilyVerdict:
    """仕様書 §9.2 の優先順位で系統を決める。上位が決めたら下位で上書きしない。"""
    fam, alts = _structured(ranks, orgs)
    if fam != "unknown":
        return FamilyVerdict(fam, Basis.STRUCTURED, 0.95, alts)

    fam, alts = family_from_deities(deities)
    if fam != "unknown":
        # 祭神が複数系統にまたがるほど確信度を下げる
        conf = max(0.55, 0.92 - 0.12 * len(alts))
        # 鹿島/香取は単独だと春日系かどうか決められない
        if fam == "kashima_katori":
            conf = min(conf, 0.70)
            alts = tuple(dict.fromkeys(alts + ("kasuga",)))
        # 遍在する祭神だけで決まった系統は弱い
        if fam in _WEAK_FAMILIES:
            conf = min(conf, 0.65)
        return FamilyVerdict(fam, Basis.DEITY, round(conf, 2), alts)

    fam, alts = family_from_name(name)
    if fam != "unknown":
        conf = max(0.45, 0.75 - 0.10 * len(alts))
        return FamilyVerdict(fam, Basis.NAME, round(conf, 2), alts)

    return FamilyVerdict("unknown", Basis.NONE, 0.0, ())
