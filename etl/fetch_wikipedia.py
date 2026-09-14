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

CATALOG = pathlib.Path("data/interim/catalog_full.json")  # ja_wikipedia は結合後にしか無い
RAW_DIR = pathlib.Path("data/raw/wikipedia")
OUT = pathlib.Path("data/raw/wikipedia/_index.json")

API = "https://ja.wikipedia.org/w/api.php"
USER_AGENT = "JinjaOriginAtlasAI/0.2 (https://github.com/twill3c/jinja-origin-atlas-ai)"
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
    fetched = cached = missing = reused = stale = 0
    # 一つの記事が複数の神社に結合されている(全国で 157 記事 / 346 件、2026-09-14 実測)。
    # 同じ記事を同じ実行の中で二度取りに行かない。
    seen: dict[str, dict | None] = {}
    t0 = time.time()
    # 累計の経過秒だけでは停滞と遅さを区別できない(HC-264)。区間の速度を出す。
    t_seg, i_seg = t0, 0
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}) as client:
        for i, r in enumerate(recs, 1):
            path = RAW_DIR / f"{r['id']}.json"
            title = title_of(r["ja_wikipedia"])
            d = json.loads(path.read_text(encoding="utf-8")) if path.exists() and not args.refresh else None
            if d is not None and d.get("requested_title", d.get("title")) != title:
                # 名寄せが変わって別の記事を指すようになった(D-08)。キャッシュは神社 ID で
                # 引いているので、確かめないと古い記事をそのまま使ってしまう
                d = None
                stale += 1
            if d is not None:
                cached += 1
            else:
                if title in seen:
                    d = seen[title]
                    reused += 1
                else:
                    d = fetch_one(client, title)
                    seen[title] = d
                    fetched += 1
                    time.sleep(args.sleep)
                if d is None:
                    missing += 1
                    continue
                path.write_text(json.dumps(dict(d, requested_title=title), ensure_ascii=False),
                                encoding="utf-8")
            index[r["id"]] = {k: v for k, v in d.items() if k != "text"} | {
                "chars": len(d.get("text", ""))
            }
            if i % 100 == 0:
                now = time.time()
                rate = (i - i_seg) / max(now - t_seg, 1e-9)
                print(f"  {i}/{len(recs)} 取得 {fetched} / キャッシュ {cached} / 同記事 {reused} "
                      f"({now - t0:.0f}s / 区間 {rate:.1f} 件/s)", file=sys.stderr, flush=True)
                t_seg, i_seg = now, i

    OUT.write_text(json.dumps({"articles": index, "fetched": fetched,
                               "from_cache": cached, "missing": missing,
                               "same_article_reused": reused, "stale_cache_refetched": stale},
                              ensure_ascii=False), encoding="utf-8")
    chars = sorted(v["chars"] for v in index.values())
    print(json.dumps({
        "対象": len(recs), "取れた": len(index), "取れなかった": missing,
        "取得": fetched, "キャッシュ": cached, "同記事の再利用": reused, "古いキャッシュを取り直し": stale,
        "本文長": {"最小": chars[0], "中央": chars[len(chars) // 2], "最大": chars[-1]} if chars else None,
        "秒": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
