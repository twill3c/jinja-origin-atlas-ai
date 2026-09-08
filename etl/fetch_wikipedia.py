# -*- coding: utf-8 -*-
"""ja.wikipedia から由緒本文を取る — SPEC F-09 / D-01。

**ライセンスは CC BY-SA 4.0。** 決定 D-01 の三条件を守る:

1. 本文を公開アーティファクトに含めない
2. 埋め込みベクトルも含めない
3. 各神社に**由来した記事の帰属・ライセンス・版**を表示する

そのため**版 ID(revid)と取得日時を必ず記録する**。帰属できない本文は使わない。
本文は `data/raw/wikipedia/`(`.gitignore` 済み)にしか置かない。

`prop=extracts` は複数題名を渡すと 1 件しか本文を返さない(2026-09-08 実測。
20 件まとめて投げたら中央値 0 字だった)。**1 件ずつ取る。**

    python -m etl.fetch_wikipedia
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.parse

import httpx

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
RAW_DIR = pathlib.Path("data/raw/wikipedia")
OUT = pathlib.Path("data/raw/wikipedia/_index.json")

API = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "JinjaOriginAtlasAI/0.1 (https://github.com/; contact via repository)"
LICENSE = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"


def title_of(url: str) -> str:
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]).replace("_", " ")


def fetch_one(client: httpx.Client, title: str) -> dict | None:
    r = client.get(API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "prop": "extracts|revisions", "rvprop": "ids|timestamp",
        "explaintext": "1", "redirects": "1", "titles": title,
    })
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return None
    p = pages[0]
    rev = (p.get("revisions") or [{}])[0]
    if not rev.get("revid"):
        # **版が分からない本文は使わない。** 帰属が書けないため(D-01 の条件 3)
        return None
    return {
        "title": p["title"],
        "pageid": p.get("pageid"),
        "revid": rev["revid"],
        "rev_timestamp": rev.get("timestamp"),
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "url": f"https://ja.wikipedia.org/wiki/{urllib.parse.quote(p['title'].replace(' ', '_'))}",
        "text": p.get("extract") or "",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ja.wikipedia の記事本文を取る")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して取り直す")
    args = ap.parse_args(argv)

    recs = [r for r in json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]
            if r.get("ja_wikipedia")]
    if args.limit:
        recs = recs[: args.limit]
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    index: dict[str, dict] = {}
    fetched = cached = missing = 0
    t0 = time.time()
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        for i, r in enumerate(recs, 1):
            path = RAW_DIR / f"{r['id']}.json"
            if path.exists() and not args.refresh:
                d = json.loads(path.read_text(encoding="utf-8"))
                cached += 1
            else:
                d = fetch_one(client, title_of(r["ja_wikipedia"]))
                fetched += 1
                time.sleep(args.sleep)
                if d is None:
                    missing += 1
                    continue
                path.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            index[r["id"]] = {k: v for k, v in d.items() if k != "text"} | {
                "chars": len(d.get("text", ""))
            }
            if i % 100 == 0:
                print(f"  {i}/{len(recs)} 取得 {fetched} / キャッシュ {cached} "
                      f"({time.time() - t0:.0f}s)", file=sys.stderr)

    OUT.write_text(json.dumps({"articles": index, "fetched": fetched,
                               "from_cache": cached, "missing": missing},
                              ensure_ascii=False), encoding="utf-8")
    chars = sorted(v["chars"] for v in index.values())
    print(json.dumps({
        "対象": len(recs), "取れた": len(index), "取れなかった": missing,
        "取得": fetched, "キャッシュ": cached,
        "本文長": {"最小": chars[0], "中央": chars[len(chars) // 2], "最大": chars[-1]} if chars else None,
        "秒": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
