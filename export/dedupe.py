# -*- coding: utf-8 -*-
"""同じ社を指す OSM 地物の統合と、社の部分の印 — SPEC D-08(T-125 / T-126 / T-128)。

OSM では一つの社が node(入口の点)と way(境内の輪郭)の両方で描かれたり、
本殿・拝殿・社務所が別の地物として `amenity=place_of_worship` を持ったりする。
そのまま数えると同じ社が二度三度数えられ、名寄せでは同じ Wikidata 項目に複数が結合される
(loop_009 の実測: 222 項目 / 485 件)。

**統合の規則**(人間の判断 D-08、2026-09-14):
- 名前(NFKC・空白を除く)が同じで 150 m 以内の地物は一つの社とみなす
- ただし両方が**別の** Wikidata 項目に自動結合されていれば統合しない(佐紀神社のような実在の別社)
- 連鎖した成分の中に項目が二つ以上あれば、**成分ごと**統合しない(推移で別社を融合させない)
- 残す地物は relation > way > node、同順位は ID で決める(決定的)

この規則は二つの独立な検算で支持されている: OSM の wikidata タグが両方にある 12 組は 12 組とも同じ、
両方が自動結合された 120 組は 117 組が同じ項目(残る 3 組を上の但し書きで除く)。

**社の部分(本殿・拝殿など)は統合しない。** 本社へ寄せる規則は検算できる組が 4 組しかなく、
本社が近くに見つからない部分名も約 300 件ある(本殿だけが描かれた社がありうる)。印だけ付ける。
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from etl.entity_resolution import Match, MatchDecision, haversine_m
from etl.normalize import normalize_name

MERGE_RADIUS_M = 150.0

#: 社殿・境内の部分を指す語。名前がこれで終わる地物に印を付ける(T-128)。
PART_WORDS = (
    "随神門", "随身門", "神門", "楼門", "中門", "手水舎", "拝殿", "本殿", "幣殿", "社務所",
    "神楽殿", "神輿庫", "鳥居", "授与所", "参集殿", "絵馬殿", "宝物殿", "神饌所", "祓所",
    "回廊", "狛犬",
)
_PART = re.compile("(" + "|".join(sorted(PART_WORDS, key=len, reverse=True)) + ")$")

#: 残す地物の優先順位。輪郭を持つ地物のほうが社の範囲を表す
_TYPE_RANK = {"relation": 0, "way": 1, "node": 2}

#: 近傍探索の格子(度)。0.005 度は北緯 45 度でも東西 390 m あり、150 m を 3x3 で覆う
_CELL = 0.005


def name_key(name: str | None) -> str:
    return normalize_name(name).replace(" ", "")


def part_suffix(name: str | None) -> str | None:
    """名前が社の部分の語で終わっていれば、その語を返す。"""
    m = _PART.search(name_key(name))
    return m.group(1) if m else None


def same_name_pairs(recs: Sequence[Mapping[str, Any]], radius_m: float = MERGE_RADIUS_M) -> list[tuple[str, str]]:
    """名前が同じで radius_m 以内にある地物の組(ID の昇順の組)を返す。"""
    cells: dict[tuple[int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for r in recs:
        if name_key(r["name"].get("ja")):
            loc = r["location"]
            cells[(math.floor(loc["lat"] / _CELL), math.floor(loc["lon"] / _CELL))].append(r)
    pairs: set[tuple[str, str]] = set()
    for (cy, cx), members in cells.items():
        for r in members:
            k = name_key(r["name"]["ja"])
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    for o in cells.get((cy + dy, cx + dx), ()):
                        if o["id"] <= r["id"] or name_key(o["name"]["ja"]) != k:
                            continue
                        a, b = r["location"], o["location"]
                        if haversine_m(a["lon"], a["lat"], b["lon"], b["lat"]) <= radius_m:
                            pairs.add((r["id"], o["id"]))
    return sorted(pairs)


@dataclass
class DedupeResult:
    survivors: list[dict[str, Any]]
    aliases: dict[str, str] = field(default_factory=dict)
    guarded_pairs: int = 0
    guarded_components: int = 0
    merged_components: int = 0


def _auto_qid(m: Match | None) -> str | None:
    return m.qid if (m and m.qid and m.decision is MatchDecision.AUTO) else None


def merge_same_name(recs: Sequence[Mapping[str, Any]], matches: Mapping[str, Match],
                    radius_m: float = MERGE_RADIUS_M) -> DedupeResult:
    """同じ社を指す地物を一つにまとめる。`matches` は統合の見送りの判定にだけ使う。"""
    by_id = {r["id"]: r for r in recs}
    parent = {r["id"]: r["id"] for r in recs}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    guarded_pairs = 0
    for a, b in same_name_pairs(recs, radius_m):
        qa, qb = _auto_qid(matches.get(a)), _auto_qid(matches.get(b))
        if qa and qb and qa != qb:
            guarded_pairs += 1
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    comps: dict[str, list[str]] = defaultdict(list)
    for r in recs:
        comps[find(r["id"])].append(r["id"])

    drop: dict[str, str] = {}
    merged_from: dict[str, list[str]] = {}
    guarded_components = merged_components = 0
    for members in comps.values():
        if len(members) < 2:
            continue
        qids = {q for q in (_auto_qid(matches.get(i)) for i in members) if q}
        if len(qids) > 1:
            guarded_components += 1
            continue
        keep = min(members, key=lambda i: (_TYPE_RANK.get(by_id[i]["external_ids"].get("osm_type"), 9), i))
        others = sorted(i for i in members if i != keep)
        merged_from[keep] = others
        for i in others:
            drop[i] = keep
        merged_components += 1

    survivors = []
    for r in recs:
        if r["id"] in drop:
            continue
        rec = dict(r)
        if r["id"] in merged_from:
            rec["merged_from"] = merged_from[r["id"]]
        survivors.append(rec)
    return DedupeResult(survivors=survivors, aliases=dict(sorted(drop.items())),
                        guarded_pairs=guarded_pairs, guarded_components=guarded_components,
                        merged_components=merged_components)
