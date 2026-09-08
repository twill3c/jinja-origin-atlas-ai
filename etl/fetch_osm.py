# -*- coding: utf-8 -*-
"""OpenStreetMap から神社位置レイヤーを取得する — SPEC F-01 / F-02。

ライセンス: ODbL。公開画面に `© OpenStreetMap contributors` を常時表示する(F-02)。

**公共インスタンスに高負荷を掛けない。**
- 段階取得(仕様書 §66)。既定は東京・京都・山梨の 3 都府県
- 429 / 504 は指数バックオフで待つ。2026-09-08 の実測では、間隔 3 秒で 4 本連続に
  投げた 3 本目から 429 が返った
- `OVERPASS_ENDPOINT` で差し替え可能

使い方::

    python -m etl.fetch_osm                  # 既定(段階 1: 東京・京都・山梨)
    python -m etl.fetch_osm --area JP-13
    python -m etl.fetch_osm --all-japan      # 全国(段階 3)
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

import httpx

ENDPOINT = os.environ.get("OVERPASS_ENDPOINT", "https://overpass-api.de/api/interpreter")
USER_AGENT = os.environ.get(
    "USER_AGENT", "JinjaOriginAtlasAI/0.1 (+https://github.com/; contact via repository)"
)

RAW_DIR = pathlib.Path("data/raw/osm")

#: 仕様書 §66 の段階 1。ISO3166-2 で指定する(名称一致より安定する)。
STAGE1_AREAS = ["JP-13", "JP-26", "JP-19"]  # 東京都 / 京都府 / 山梨県

_QUERY_AREA = """[out:json][timeout:600];
area["ISO3166-2"="{area}"]->.a;
(
  nwr["amenity"="place_of_worship"]["religion"="shinto"](area.a);
);
out center tags;
"""

_QUERY_JAPAN = """[out:json][timeout:900];
area["ISO3166-1"="JP"][admin_level=2]->.a;
(
  nwr["amenity"="place_of_worship"]["religion"="shinto"](area.a);
);
out center tags;
"""


def run_query(query: str, *, max_attempts: int = 6, client: httpx.Client | None = None) -> dict:
    """Overpass に問い合わせる。429 / 5xx は指数バックオフで待ち直す。"""
    owns = client is None
    client = client or httpx.Client(timeout=960.0, headers={"User-Agent": USER_AGENT})
    try:
        delay = 20.0
        last: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                r = client.post(ENDPOINT, data={"data": query})
                if r.status_code in (429, 502, 503, 504):
                    print(f"  HTTP {r.status_code} — {delay:.0f} 秒待つ(試行 {attempt}/{max_attempts})",
                          file=sys.stderr)
                    time.sleep(delay)
                    delay = min(delay * 2, 300.0)
                    continue
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last = exc
                print(f"  {type(exc).__name__} — {delay:.0f} 秒待つ(試行 {attempt}/{max_attempts})",
                      file=sys.stderr)
                time.sleep(delay)
                delay = min(delay * 2, 300.0)
        raise RuntimeError(f"Overpass が {max_attempts} 回とも応答しなかった: {last}")
    finally:
        if owns:
            client.close()


def fetch_area(area: str, client: httpx.Client | None = None) -> dict:
    print(f"Overpass: {area} …", file=sys.stderr)
    t0 = time.time()
    d = run_query(_QUERY_AREA.format(area=area), client=client)
    n = len(d.get("elements", []))
    print(f"  {area}: {n} 要素 ({time.time() - t0:.1f}s)", file=sys.stderr)
    return d


def fetch_japan(client: httpx.Client | None = None) -> dict:
    print("Overpass: 日本全国 …", file=sys.stderr)
    t0 = time.time()
    d = run_query(_QUERY_JAPAN, client=client)
    print(f"  全国: {len(d.get('elements', []))} 要素 ({time.time() - t0:.1f}s)", file=sys.stderr)
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="OSM から神社を取得する")
    ap.add_argument("--area", action="append", help="ISO3166-2 コード(例 JP-13)。複数指定可")
    ap.add_argument("--all-japan", action="store_true", help="全国を一度に取得する(段階 3)")
    ap.add_argument("--sleep", type=float, default=30.0, help="連続問い合わせの間隔(秒)")
    args = ap.parse_args(argv)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=960.0, headers={"User-Agent": USER_AGENT}) as client:
        if args.all_japan:
            d = fetch_japan(client=client)
            out = RAW_DIR / "shrines_overpass_JP.json"
            out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            print(f"→ {out}")
            return 0

        areas = args.area or STAGE1_AREAS
        for i, area in enumerate(areas):
            if i:
                time.sleep(args.sleep)
            d = fetch_area(area, client=client)
            out = RAW_DIR / f"shrines_overpass_{area}.json"
            out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
