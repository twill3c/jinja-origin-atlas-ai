# -*- coding: utf-8 -*-
"""生の SPARQL 応答 → 神社 1 件 1 レコード — SPEC F-03。

**オラクル専用のファイル(`oracle_osm_ids.json`)はここで読まない。** 読むのは
`load_oracle_pairs()` だけで、名寄せに渡すレコードには一切入らない(D-02 / SPEC §7)。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from etl.fetch_wikidata import ORACLE_ONLY, fold_rows, parse_time_value, qid_of

RAW_DIR = pathlib.Path("data/raw/wikidata")


def _rows(name: str) -> list[dict[str, Any]]:
    p = RAW_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _v(row: dict[str, Any], key: str) -> Any:
    x = row.get(key)
    return x.get("value") if isinstance(x, dict) else None


def load_records() -> dict[str, dict[str, Any]]:
    """名寄せと属性結合に使うレコード。**オラクル由来の欄は含まない。**"""
    recs = fold_rows(_rows("core"))

    for row in _rows("names"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        for src, dst in (("kana", "kana"), ("official", "official")):
            val = _v(row, src)
            if val and not r.get(dst):
                r[dst] = val
        alias = _v(row, "alias")
        if alias:
            r.setdefault("aliases", [])
            if alias not in r["aliases"]:
                r["aliases"].append(alias)

    for row in _rows("misc"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        site = _v(row, "site")
        if site and not r.get("site"):
            r["site"] = site
        org = _v(row, "orgLabel")
        if org:
            r.setdefault("orgs", [])
            if org not in r["orgs"]:
                r["orgs"].append(org)

    for row in _rows("deities"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        label = _v(row, "dLabel")
        item = _v(row, "d")
        if label:
            r.setdefault("deities", [])
            entry = {"name": label, "wikidata_id": qid_of(item) if item else None}
            if entry not in r["deities"]:
                r["deities"].append(entry)

    for row in _rows("ranks"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        label = _v(row, "rankLabel")
        if label:
            r.setdefault("ranks", [])
            if label not in r["ranks"]:
                r["ranks"].append(label)

    for row in _rows("inception"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        prec = _v(row, "precision")
        rng = parse_time_value(_v(row, "value"), int(prec) if prec is not None else None)
        if rng and not r.get("inception"):
            r["inception"] = {"year_min": rng[0], "year_max": rng[1]}

    for row in _rows("parents"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        parent = _v(row, "parent")
        if parent:
            r.setdefault("parents", [])
            pq = qid_of(parent)
            if pq not in r["parents"]:
                r["parents"].append(pq)

    for row in _rows("articles"):
        qid = qid_of(_v(row, "item") or "")
        r = recs.get(qid)
        if not r:
            continue
        art = _v(row, "article")
        if art and not r.get("ja_wikipedia"):
            r["ja_wikipedia"] = art

    # 多値は決定的に並べる(再実行で入れ替わらないように)
    for r in recs.values():
        for key in ("aliases", "orgs", "ranks", "parents"):
            if key in r:
                r[key] = sorted(r[key])
        if "deities" in r:
            r["deities"] = sorted(r["deities"], key=lambda d: (d["name"], d["wikidata_id"] or ""))
    return recs


def load_oracle_pairs() -> dict[tuple[str, int], str]:
    """Wikidata が直接指している OSM 要素 → QID。**名寄せに渡してはならない。**

    :returns: {(osm_type, osm_id): qid}
    """
    assert "oracle_osm_ids" in ORACLE_ONLY, "オラクル専用の印が外れている"
    out: dict[tuple[str, int], str] = {}
    for row in _rows("oracle_osm_ids"):
        qid = qid_of(_v(row, "item") or "")
        for key, typ in (("way", "way"), ("node", "node"), ("rel", "relation")):
            val = _v(row, key)
            if val and str(val).isdigit():
                out[(typ, int(val))] = qid
    return out
