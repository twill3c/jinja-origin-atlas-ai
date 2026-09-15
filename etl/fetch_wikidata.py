# -*- coding: utf-8 -*-
"""Wikidata から神社の構造化属性を取得する — SPEC F-03。

ライセンス: CC0。

**OPTIONAL を重ねた 1 本のクエリで取らない。** 2026-09-08 の実測では、OPTIONAL 7 本の
クエリが Blazegraph の `java.util.concurrent.TimeoutException` で打ち切られたが、
**HTTP は 200・content-type も `application/sparql-results+json` のまま**、途中で切れた
JSON の末尾に Java のスタックトレースが付いて返ってきた(30,069,925 バイト)。
`raise_for_status()` も content-type 検査も素通りし、`json()` の失敗としてしか現れない。

そこでプロパティごとに分けて取り、**本文が JSON として解けることを検算に置く**(HC-075)。
分割後の実測は 1 本あたり 4〜21 秒。

**`P31/P279*` は経路が複数あると同じ item を複数回返す。** 実測で座標つき日本の神社は
`COUNT(DISTINCT)` 16,917 に対し行数 29,233。必ず item で畳む。

使い方::

    python -m etl.fetch_wikidata
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Iterable

import httpx

ENDPOINT = os.environ.get("WIKIDATA_SPARQL_ENDPOINT", "https://query.wikidata.org/sparql")
USER_AGENT = os.environ.get(
    "USER_AGENT", "JinjaOriginAtlasAI/0.2 (https://github.com/twill3c/jinja-origin-atlas-ai)"
)
RAW_DIR = pathlib.Path("data/raw/wikidata")

#: 神社(Q845945)で、日本(Q17)にあり、座標を持つもの。
_BASE = "?item wdt:P31/wdt:P279* wd:Q845945 . ?item wdt:P17 wd:Q17 . ?item wdt:P625 ?coord ."

_POINT = re.compile(r"Point\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)")
_TIME = re.compile(r"^([+-])(\d{4,})-(\d{2})-(\d{2})T")

#: 取得するクエリ群。1 本ずつ投げる。
QUERIES: dict[str, str] = {
    # 基本(座標・行政区画)。**ラベルサービスを使わない。** 神社 4.3 万件と行政区画に名前を付けると
    # Wikidata の約 60 秒の上限を越え、HTTP 200 のまま決定的に切れるようになった
    # (2026-09-15、手元で 12,907,568 バイト・ランナーで 999,417 バイト)。名前は ITEM_LABELS と
    # 行政区画の VALUES 分割で別に取り、compose_core で組み立てる(T-138。fetch_core を見よ)
    "core": f"""
SELECT ?item ?coord ?admin WHERE {{ {_BASE}
  OPTIONAL {{ ?item wdt:P131 ?admin }} }}""",
    # 読み仮名・正式名称・別名
    "names": f"""
SELECT ?item ?kana ?official ?alias WHERE {{ {_BASE}
  OPTIONAL {{ ?item wdt:P1814 ?kana }}
  OPTIONAL {{ ?item wdt:P1448 ?official }}
  OPTIONAL {{ ?item skos:altLabel ?alias FILTER(LANG(?alias)="ja") }} }}""",
    # 祭神(P825 献呈先)
    "deities": f"""
SELECT ?item ?d ?dLabel WHERE {{ {_BASE} ?item wdt:P825 ?d .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en". }} }}""",
    # 社格(P13723)
    "ranks": f"""
SELECT ?item ?rank ?rankLabel WHERE {{ {_BASE} ?item wdt:P13723 ?rank .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en". }} }}""",
    # 成立日(P571)。precision つきで取る。
    # **文ノード経路(p:/psv:)は重い。** 座標と国の絞りを重ねた形は HTTP 200 のまま
    # 458,752 バイトで決定的に打ち切られた(2026-09-08 実測)。神社という型の絞りだけに
    # して結合を減らし、日本・座標の絞りは core の集合との突き合わせで Python 側で行う。
    "inception": """
SELECT ?item ?value ?precision WHERE {
  ?item wdt:P31/wdt:P279* wd:Q845945 .
  ?item p:P571/psv:P571 ?node .
  ?node wikibase:timeValue ?value ; wikibase:timePrecision ?precision . }""",
    # 文献上の分祀関係(P612 母院)。SPEC §43 の「実線」
    "parents": f"""
SELECT ?item ?parent WHERE {{ {_BASE} ?item wdt:P612 ?parent . }}""",
    # 包括団体(P611)・公式サイト(P856)
    "misc": f"""
SELECT ?item ?org ?orgLabel ?site WHERE {{ {_BASE}
  OPTIONAL {{ ?item wdt:P611 ?org }} OPTIONAL {{ ?item wdt:P856 ?site }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "ja,en". }} }}""",
    # ja.wikipedia 記事(D-01 の AI コーパス)
    "articles": f"""
SELECT ?item ?article WHERE {{ {_BASE}
  ?article schema:about ?item ; schema:isPartOf <https://ja.wikipedia.org/> . }}""",
    # --- 以下はオラクル専用。名寄せの入力に使ってはならない(D-02 / SPEC §7) ---
    "oracle_osm_ids": f"""
SELECT ?item ?way ?node ?rel WHERE {{ {_BASE}
  {{ ?item wdt:P10689 ?way }} UNION {{ ?item wdt:P11693 ?node }} UNION {{ ?item wdt:P402 ?rel }} }}""",
}

#: 名寄せの入力に渡してはならないクエリ名。
ORACLE_ONLY = frozenset({"oracle_osm_ids"})


def verify_sparql_body(raw: bytes) -> dict[str, Any]:
    """SPARQL の応答本文を検算してから返す。

    HTTP 200 でも本文が JSON として解けないことがある(サーバ側の打ち切り)。
    黙って通る道を残さない —— 打ち切りは「壊れたデータ」ではなく「取れなかった」である。
    """
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        tail = raw[-400:].decode("utf-8", "replace")
        hint = ""
        for marker in ("TimeoutException", "java.", "SPARQL-QUERY:"):
            if marker in tail or marker.encode() in raw[-4000:]:
                hint = f" サーバ側の打ち切りらしい(末尾に {marker!r})。"
                break
        raise RuntimeError(
            f"SPARQL 応答が JSON として解けない({len(raw)} バイト)。{hint}"
            f"打ち切られた可能性が高い。末尾: {tail[-200:]!r}"
        ) from exc
    if not isinstance(d, dict) or "results" not in d:
        raise RuntimeError(f"SPARQL 応答の形が想定と違う: キー {list(d)[:5] if isinstance(d, dict) else type(d)}")
    return d


def parse_wkt_point(wkt: str | None) -> tuple[float, float] | None:
    """WKT の Point を (lon, lat) で返す。WKT は経度が先である。"""
    if not wkt:
        return None
    m = _POINT.match(wkt.strip())
    return (float(m.group(1)), float(m.group(2))) if m else None


def parse_time_value(value: str | None, precision: int | None) -> tuple[int, int] | None:
    """Wikidata の時間値を年の範囲 (最小, 最大) に変換する。

    precision の意味は https://www.wikidata.org/wiki/Help:Dates による。
    7 = 世紀 / 8 = 10 年紀 / 9 = 年 / 10 = 月 / 11 = 日。
    **解釈できない精度は None を返す** —— もっともらしい年を作らない。
    """
    if not value or precision is None:
        return None
    m = _TIME.match(value)
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    year = sign * int(m.group(2))
    p = int(precision)
    if p >= 9:
        return (year, year)
    if p == 8:  # 10 年紀
        base = (year // 10) * 10
        return (base, base + 9)
    if p == 7:  # 世紀
        base = (year // 100) * 100
        return (base, base + 99)
    return None


def qid_of(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _val(row: dict[str, Any], key: str) -> Any:
    v = row.get(key)
    return v.get("value") if isinstance(v, dict) else None


def fold_rows(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """`core` クエリの行を item ごとに畳む。

    `P31/P279*` は経路が複数あると同じ item を複数回返すので、必ず畳む。
    多値(座標が複数ある item がある)は**捨てずに全部持ち、代表値は決定的に選ぶ**。
    行の並びで結果が変わってはならない。
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = _val(row, "item")
        if not item:
            continue
        qid = qid_of(item)
        rec = out.setdefault(
            qid, {"qid": qid, "label": None, "coords": [], "admin_label": None, "admins": []}
        )
        if rec["label"] is None:
            rec["label"] = _val(row, "itemLabel")
        pt = parse_wkt_point(_val(row, "coord"))
        if pt and pt not in rec["coords"]:
            rec["coords"].append(pt)
        adm = _val(row, "adminLabel")
        if adm and adm not in rec["admins"]:
            rec["admins"].append(adm)
    for rec in out.values():
        # 代表値は並びに依存させない。座標は辞書順で最小のものを採る。
        rec["coords"].sort()
        rec["admins"].sort()
        rec["coord"] = rec["coords"][0] if rec["coords"] else None
        rec["admin_label"] = rec["admins"][0] if rec["admins"] else None
    return out


class DeterministicTruncation(RuntimeError):
    """キャッシュを通らない応答が、同じ長さで二度切れた。待っても直らないので再試行しない(HC-228)。"""


def run_query(name: str, query: str, client: httpx.Client, max_attempts: int = 4) -> list[dict[str, Any]]:
    """1 本のクエリを投げる。

    **再試行する前に「これは再試行で直る種類か」を判定する**(HC-228)。

    **切れた本文はエッジのキャッシュに 5 分残る。** 2026-09-16 の実測で、切れた応答が
    `x-cache-status: hit-local`・`age 62` で返り、同じ文面で取り直すと同じ切れた本文が返った。
    文面にコメントを足すとキャッシュを通らず、全件(10 MB)が返った。つまり「二度とも同じ長さ」は
    重すぎる証拠ではなく、**同じキャッシュを二度読んだ証拠**のことがある。そこで取り直しのたびに
    文面を変え(T-140)、**キャッシュを通らない応答が同じ長さで二度切れたとき**だけ重すぎると判定する。
    """
    delay = 15.0
    truncated_lengths: list[int] = []
    text = query
    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        r = client.get(ENDPOINT, params={"query": text})
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"  {name}: HTTP {r.status_code} — {delay:.0f} 秒待つ({attempt}/{max_attempts})",
                  file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
            continue
        r.raise_for_status()
        try:
            d = verify_sparql_body(r.content)
        except RuntimeError as exc:
            n = len(r.content)
            cached = "hit" in (r.headers.get("x-cache-status") or "").lower()
            if not cached:
                if n in truncated_lengths:
                    raise DeterministicTruncation(
                        f"{name}: キャッシュを通らない本文が二度とも {n} バイトで切れた。一時障害ではなく"
                        "「このクエリは重すぎる」という決定的な応答である。"
                        "待っても直らないので、クエリの結合を減らすこと。"
                    ) from exc
                truncated_lengths.append(n)
            # 文面を変えてキャッシュを避ける(切れた本文はエッジに 5 分残る)
            text = query + chr(10) + f"# retry {attempt} {time.time_ns()}"
            wait = 5.0 if cached else delay
            print(f"  {name}: {exc} — {'キャッシュの切れた本文。' if cached else ''}{wait:.0f} 秒待って文面を変えて取り直す"
                  f"({attempt}/{max_attempts})", file=sys.stderr)
            time.sleep(wait)
            if not cached:
                delay = min(delay * 2, 120.0)
            continue
        rows = d["results"]["bindings"]
        print(f"  {name}: {len(rows)} 行 {len(r.content) / 1e6:.2f} MB ({time.time() - t0:.1f}s)",
              file=sys.stderr)
        return rows
    raise RuntimeError(f"{name}: {max_attempts} 回とも取得できなかった")


#: 神社のラベル(ja と en)。ラベルサービスを使わずに取る(実測 5.7 秒、2026-09-15)
ITEM_LABELS = f"""SELECT ?item ?ja ?en WHERE {{ {_BASE}
  OPTIONAL {{ ?item rdfs:label ?ja FILTER(LANG(?ja)="ja") }}
  OPTIONAL {{ ?item rdfs:label ?en FILTER(LANG(?en)="en") }} }}"""

#: 行政区画のラベルは QID を VALUES で渡して分割で取る。副問い合わせの DISTINCT で一括に取ると
#: 41.2 秒かかり上限に近い。500 件ずつなら 1 本 4 秒以内(実測 2,623 件で計 16.4 秒)
ADMIN_LABEL_BATCH = 500


def compose_core(core_rows: list[dict[str, Any]], item_labels: dict[str, dict[str, str]],
                 admin_labels: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """ラベルなしの core にラベルを付け、ラベルサービスと同じ形の行にする(T-138)。

    ラベルサービスの規則は **ja → en → QID そのもの**。行政区画の無い行には adminLabel を付けない。
    """
    def label(uri: str, labels: dict[str, dict[str, str]]) -> str:
        qid = qid_of(uri)
        d = labels.get(qid) or {}
        # ラベルが無いとき、項目なら QID、項目でない値(「不明な値」の空白ノード genid など)は
        # URI そのものを返す。ラベルサービスがそうしていた(2026-09-15 の突き合わせで 1 件だけ食い違った)
        fallback = qid if uri.startswith("http://www.wikidata.org/entity/") else uri
        return d.get("ja") or d.get("en") or fallback

    out = []
    for r in core_rows:
        row = dict(r)
        row["itemLabel"] = {"type": "literal", "value": label(r["item"]["value"], item_labels)}
        if "admin" in r:
            row["adminLabel"] = {"type": "literal", "value": label(r["admin"]["value"], admin_labels)}
        out.append(row)
    return out


def _label_map(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, str]]:
    m: dict[str, dict[str, str]] = {}
    for r in rows:
        d = m.setdefault(qid_of(r[key]["value"]), {})
        for lang in ("ja", "en"):
            if lang in r and lang not in d:
                d[lang] = r[lang]["value"]
    return m


def _post_query(name: str, query: str, client: httpx.Client, max_attempts: int = 4) -> list[dict[str, Any]]:
    """VALUES を並べた長いクエリは POST で送る(URL の長さの上限を避ける)。"""
    delay = 15.0
    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        r = client.post(ENDPOINT, data={"query": query})
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"  {name}: HTTP {r.status_code} — {delay:.0f} 秒待つ({attempt}/{max_attempts})", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
            continue
        r.raise_for_status()
        rows = verify_sparql_body(r.content)["results"]["bindings"]
        print(f"  {name}: {len(rows)} 行 ({time.time() - t0:.1f}s)", file=sys.stderr)
        return rows
    raise RuntimeError(f"{name}: {max_attempts} 回とも取得できなかった")


def fetch_core(client: httpx.Client, sleep: float = 3.0) -> list[dict[str, Any]]:
    """core を三本の軽いクエリから組み立てる(ラベルなしの core / 神社のラベル / 行政区画のラベル)。"""
    core = run_query("core", QUERIES["core"], client)
    time.sleep(sleep)
    items = _label_map(run_query("core_item_labels", ITEM_LABELS, client), "item")
    admins = sorted({qid_of(r["admin"]["value"]) for r in core if "admin" in r})
    admin_rows: list[dict[str, Any]] = []
    for i in range(0, len(admins), ADMIN_LABEL_BATCH):
        time.sleep(sleep)
        vals = " ".join(f"wd:{q}" for q in admins[i:i + ADMIN_LABEL_BATCH])
        q = f"""SELECT ?admin ?ja ?en WHERE {{ VALUES ?admin {{ {vals} }}
  OPTIONAL {{ ?admin rdfs:label ?ja FILTER(LANG(?ja)="ja") }}
  OPTIONAL {{ ?admin rdfs:label ?en FILTER(LANG(?en)="en") }} }}"""
        admin_rows += _post_query(f"core_admin_labels[{i // ADMIN_LABEL_BATCH}]", q, client)
    rows = compose_core(core, items, _label_map(admin_rows, "admin"))
    print(f"  core(組み立て): {len(rows)} 行 / 神社のラベル {len(items)} / 行政区画 {len(admins)}", file=sys.stderr)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Wikidata から神社の構造化属性を取得する")
    ap.add_argument("--only", action="append", help="このクエリ名だけ実行する")
    ap.add_argument("--sleep", type=float, default=3.0)
    args = ap.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    names = args.only or list(QUERIES)
    with httpx.Client(
        timeout=300.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
    ) as client:
        for i, name in enumerate(names):
            if i:
                time.sleep(args.sleep)
            rows = fetch_core(client, args.sleep) if name == "core" else run_query(name, QUERIES[name], client)
            out = RAW_DIR / f"{name}.json"
            out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
