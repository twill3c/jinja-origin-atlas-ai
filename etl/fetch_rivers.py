# -*- coding: utf-8 -*-
"""国土数値情報 W05(河川)を取得する — SPEC F-07。

出典: 国土交通省 国土数値情報ダウンロードサイト。利用約款は PDL1.0 が基本だが、
**データごとに個別確認する**(`LICENSE-DATA.md`)。

**版を固定しない**(仕様書 §5.6)。製品ページから都道府県ごとの最新リンクを拾う。
実測(2026-09-08)では都道府県で版が違った —— 東京都・山梨県は W05-08、京都府は W05-09。

    python -m etl.fetch_rivers
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import sys
import time
import zipfile

import httpx

PRODUCT_PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html"
BASE = "https://nlftp.mlit.go.jp/ksj/gml/"
RAW_DIR = pathlib.Path("data/raw/ksj/W05")
USER_AGENT = "JinjaOriginAtlasAI/0.1 (+https://github.com/; contact via repository)"

#: 段階 1 の対象(仕様書 §66)。都道府県コード。
STAGE1_PREF_CODES = ("13", "26", "19")  # 東京都 / 京都府 / 山梨県

_LINK = re.compile(r'data/W05/(W05-\d+)/(W05-\d+_(\d{2})_GML\.zip)')


def discover(client: httpx.Client) -> dict[str, tuple[str, str]]:
    """製品ページから {都道府県コード: (版, 相対パス)} を作る。

    同じ県に複数の版が載っていたら**新しいほうを採る**。
    """
    r = client.get(PRODUCT_PAGE)
    r.raise_for_status()
    found: dict[str, tuple[str, str]] = {}
    for ver, fname, code in _LINK.findall(r.text):
        rel = f"data/W05/{ver}/{fname}"
        prev = found.get(code)
        if prev is None or ver > prev[0]:
            found[code] = (ver, rel)
    if not found:
        raise RuntimeError("製品ページから W05 のリンクを 1 件も拾えなかった。ページ構造が変わった疑い")
    return found


def download(client: httpx.Client, code: str, ver: str, rel: str) -> pathlib.Path:
    dest = RAW_DIR / code
    if dest.exists() and any(dest.rglob("*.shp")) or (dest.exists() and any(dest.rglob("*.xml"))):
        print(f"  {code}: 展開済み({dest})", file=sys.stderr)
        return dest
    url = BASE + rel
    print(f"  {code}: {ver} を取得 {url}", file=sys.stderr)
    t0 = time.time()
    r = client.get(url)
    r.raise_for_status()
    body = r.content
    if body[:2] != b"PK":
        raise RuntimeError(f"{code}: zip ではない応答({len(body)} バイト)。先頭 {body[:16]!r}")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        z.extractall(dest)
    print(f"  {code}: {len(body) / 1e6:.1f} MB 展開 ({time.time() - t0:.1f}s)", file=sys.stderr)
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="国土数値情報 W05(河川)を取得する")
    ap.add_argument("--pref", action="append", help="都道府県コード(既定: 13 26 19)")
    args = ap.parse_args(argv)
    codes = tuple(args.pref) if args.pref else STAGE1_PREF_CODES

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=300.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        found = discover(client)
        print(f"製品ページから {len(found)} 都道府県ぶんのリンクを検出", file=sys.stderr)
        for code in codes:
            if code not in found:
                raise RuntimeError(f"{code}: 製品ページにリンクが無い")
            ver, rel = found[code]
            d = download(client, code, ver, rel)
            files = sorted(p.name for p in d.rglob("*") if p.is_file())
            print(f"→ {d}  ({len(files)} ファイル) 例: {files[:4]}")
            time.sleep(2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
