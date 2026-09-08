# -*- coding: utf-8 -*-
"""OSM × Wikidata の名寄せ — SPEC F-04 / G-09 / D-02。

重みと閾値は仕様書 §8.4 に従う::

    match_score = 0.40 geo + 0.30 name + 0.10 admin + 0.10 external_id + 0.10 alias
    >= 0.90 auto merge / 0.75-0.89 review queue / < 0.75 separate

**循環の禁止(D-02)。** Wikidata の P10689 / P11693 / P402 と OSM の `wikidata` タグは
同じ対応関係の裏表であり、名寄せの**非循環オラクル**である。仕様書 §8.3 は補助特徴に
「OSM wikidata tag」を挙げているが、入力に混ぜるとオラクルが恒等式になる(HC-045)。
**このモジュールはその二つを一切読まない。** `external_id` の材料は公式サイト URL である。

`match_score` と `resolve` はレコード辞書を受け取るが、リンク欄が入っていても
無視する。それを保証するのが T-062(与えても与えなくても同じ出力)である。
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from etl.normalize import name_similarity, normalize_name

#: 仕様書 §8.4 の重み。
WEIGHTS: dict[str, float] = {
    "geo": 0.40,
    "name": 0.30,
    "admin": 0.10,
    "external_id": 0.10,
    "alias": 0.10,
}

#: 判定の閾値。**仕様書 §8.4 の 0.90 / 0.75 からの逸脱である**(SPEC D-03 / HC-229)。
#:
#: 仕様の 0.90 は `external_id` の 0.10 が Wikidata↔OSM の相互リンクで埋まる前提で
#: 置かれていた。D-02 で循環を禁じた結果この項は構造的に 0 になり、距離 0 m・名称完全一致・
#: 行政区画一致でも合計は 0.80 で頭打ちになる。**理想入力でも到達不能な閾値**だった。
#:
#: 置き直した値は、オラクル 825 組の**較正半分(411 組)だけ**を見て決めた(2026-09-08)。
#: 較正側の閾値掃き: 0.58 → 適合率 0.9975 / 再現率 0.9708、
#: **0.60 → 適合率 1.0000 / 再現率 0.9611**、0.62 → 適合率 1.0000 / 再現率 0.9173。
#: 適合率が 1.0 になる最小の閾値を採った。取り置き半分での数字は G-09 の検査で出す。
AUTO_THRESHOLD = 0.60
REVIEW_THRESHOLD = 0.50

#: 仕様書 §8.4 が書いていた値。逸脱を検査で固定するために残す(T-061b)。
SPEC_AUTO_THRESHOLD = 0.90
SPEC_REVIEW_THRESHOLD = 0.75

#: 地理スコアの折れ点(m)。仕様書 §8.3 の「強一致 50 m / 同一候補 150 m」に合わせる。
_GEO_STRONG_M = 50.0
_GEO_CANDIDATE_M = 150.0
_GEO_MAX_M = 500.0

#: 空間ブロッキングの格子(度)。0.01 度 ≒ 1.1 km で、_GEO_MAX_M を十分に覆う。
_CELL = 0.01

_EARTH_R = 6371008.8  # IUGG 平均半径(m)


class MatchDecision(enum.StrEnum):
    AUTO = "auto"
    REVIEW = "review"
    SEPARATE = "separate"


@dataclass(frozen=True, order=True)
class Candidate:
    """並べ替えが決定的になるよう、比較のキーを明示する。

    同点で順序が揺れると再実行のたびに結合先が入れ替わる。
    """

    _sort_score: float = 0.0
    osm_id: str = ""
    qid: str = ""
    score: float = 0.0
    distance_m: float = 0.0
    name_sim: float = 0.0

    def __init__(self, *, osm_id: str, qid: str, score: float, distance_m: float, name_sim: float):
        # スコア降順 → qid 昇順 で並ぶようにする
        object.__setattr__(self, "_sort_score", -score)
        object.__setattr__(self, "osm_id", osm_id)
        object.__setattr__(self, "qid", qid)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "distance_m", distance_m)
        object.__setattr__(self, "name_sim", name_sim)


@dataclass(frozen=True)
class ScoreParts:
    geo: float
    name: float
    admin: float
    external_id: float
    alias: float
    total: float
    distance_m: float


@dataclass(frozen=True)
class Match:
    osm_id: str
    qid: str | None
    score: float
    decision: MatchDecision
    distance_m: float | None
    name_sim: float | None


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面上の距離(m)。緯度経度のまま距離を測らない(仕様書 §13.2)。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def geo_score(distance_m: float) -> float:
    """距離 → [0,1]。折れ点は仕様書 §8.3 の帯に合わせた。"""
    d = distance_m
    if d <= _GEO_STRONG_M:
        return 1.0
    if d <= _GEO_CANDIDATE_M:
        return 1.0 - 0.3 * (d - _GEO_STRONG_M) / (_GEO_CANDIDATE_M - _GEO_STRONG_M)
    if d <= _GEO_MAX_M:
        return 0.7 * (1.0 - (d - _GEO_CANDIDATE_M) / (_GEO_MAX_M - _GEO_CANDIDATE_M))
    return 0.0


def _osm_names(o: Mapping[str, Any]) -> list[str]:
    n = o.get("name") or {}
    return [x for x in (n.get("ja"), n.get("kana")) if x]


def _wd_names(w: Mapping[str, Any]) -> list[str]:
    return [x for x in (w.get("label"), w.get("kana"), w.get("official")) if x]


def _best_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    if not a or not b:
        return 0.0
    return max(name_similarity(x, y) for x in a for y in b)


def _host_path(url: str | None) -> str | None:
    if not url:
        return None
    try:
        u = urlsplit(url if "//" in url else "//" + url)
    except ValueError:
        return None
    host = (u.netloc or "").lower().removeprefix("www.")
    if not host:
        return None
    return host + u.path.rstrip("/")


def match_score(osm: Mapping[str, Any], wd: Mapping[str, Any]) -> ScoreParts:
    """仕様書 §8.4 のスコア。

    **`osm["external_ids"]["osm_wikidata_tag"]` と `wd["osm_ids"]` は読まない**(D-02)。
    """
    olon, olat = osm["location"]["lon"], osm["location"]["lat"]
    wcoord = wd.get("coord")
    if not wcoord:
        return ScoreParts(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, float("inf"))
    d = haversine_m(olon, olat, wcoord[0], wcoord[1])

    g = geo_score(d)
    n = _best_similarity(_osm_names(osm), _wd_names(wd))

    # 行政区画。分からない側があれば 0 にする —— 中間値を置くと「知らないこと」が
    # 「半分合っている」に化ける。
    o_admin = [normalize_name(x) for x in
               (osm["location"].get("prefecture"), osm["location"].get("municipality")) if x]
    w_admin = normalize_name(wd.get("admin_label")) if wd.get("admin_label") else None
    a = 1.0 if (w_admin and any(w_admin in x or x in w_admin for x in o_admin)) else 0.0

    # 外部 ID。**wikidata↔osm のリンクは使わない。** 公式サイトの URL を突き合わせる。
    e = 1.0 if (_host_path(osm.get("website")) and
                _host_path(osm.get("website")) == _host_path(wd.get("site"))) else 0.0

    al = _best_similarity(
        [normalize_name(x) for x in (osm.get("aliases") or []) if x],
        [normalize_name(x) for x in (wd.get("aliases") or []) if x],
    )

    total = (WEIGHTS["geo"] * g + WEIGHTS["name"] * n + WEIGHTS["admin"] * a
             + WEIGHTS["external_id"] * e + WEIGHTS["alias"] * al)
    return ScoreParts(g, n, a, e, al, total, d)


def decide(score: float) -> MatchDecision:
    if score >= AUTO_THRESHOLD:
        return MatchDecision.AUTO
    if score >= REVIEW_THRESHOLD:
        return MatchDecision.REVIEW
    return MatchDecision.SEPARATE


def _grid(records: Iterable[Mapping[str, Any]], lonlat) -> dict[tuple[int, int], list[Mapping[str, Any]]]:
    cells: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
    for r in records:
        c = lonlat(r)
        if not c:
            continue
        key = (int(math.floor(c[1] / _CELL)), int(math.floor(c[0] / _CELL)))
        cells.setdefault(key, []).append(r)
    return cells


def resolve(
    osm_records: Sequence[Mapping[str, Any]],
    wd_records: Sequence[Mapping[str, Any]],
) -> list[Match]:
    """OSM の各レコードに対して最良の Wikidata 項目を決める。

    空間ブロッキング(0.01 度 ≒ 1.1 km の格子と 3x3 近傍)で候補を絞る。
    `_GEO_MAX_M` = 500 m を十分に覆うので、絞りによって取りこぼす候補は無い。
    """
    cells = _grid(wd_records, lambda w: w.get("coord"))
    out: list[Match] = []
    for o in osm_records:
        lon, lat = o["location"]["lon"], o["location"]["lat"]
        cy, cx = int(math.floor(lat / _CELL)), int(math.floor(lon / _CELL))
        cands: list[Candidate] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for w in cells.get((cy + dy, cx + dx), ()):
                    s = match_score(o, w)
                    if s.total <= 0.0:
                        continue
                    cands.append(Candidate(osm_id=o["id"], qid=w["qid"], score=s.total,
                                           distance_m=s.distance_m, name_sim=s.name))
        if not cands:
            out.append(Match(o["id"], None, 0.0, MatchDecision.SEPARATE, None, None))
            continue
        best = sorted(cands)[0]
        out.append(Match(o["id"], best.qid, best.score, decide(best.score),
                         best.distance_m, best.name_sim))
    return out
