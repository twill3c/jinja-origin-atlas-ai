# -*- coding: utf-8 -*-
"""月次の自動更新で開く PR の本文を作る — SPEC D-09(T-135)。

**マージするか決める人が、差分のファイルを開かずに判断できる形にする。** 神社の件数・自動結合・
AI・標高・河川距離の前後と差、件数の変わった県だけを並べる。

    python -m scripts.pr_summary --old-build prev/build.json --old-index prev/index.json > pr.md
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any, Mapping

NEW_BUILD = pathlib.Path("public/data/meta/build.json")
NEW_INDEX = pathlib.Path("public/data/shrines/index.json")

ROWS = (
    ("神社", lambda b: b["shrines"]),
    ("自動結合", lambda b: b["matched_auto"]),
    ("AI の欄が付いた神社", lambda b: b["with_ai"]),
    ("標高あり", lambda b: b["with_elevation"]),
    ("河川距離あり", lambda b: b["with_river_distance"]),
    ("同じ社として統合した地物", lambda b: b["dedupe"]["merged_features"]),
)


def _diff(a: int, b: int) -> str:
    d = b - a
    return "±0" if d == 0 else f"{d:+,}"


def summarize(old_build: Mapping[str, Any], new_build: Mapping[str, Any],
              old_index: Mapping[str, Any], new_index: Mapping[str, Any]) -> str:
    lines = ["## 月次のデータ更新", "",
             "公開データを作り直し、pytest・出荷ビルド・実ブラウザ検品を通したうえで開いた PR。",
             "**マージすると本番に出る。** 件数の急な増減が無いか、下の表で確かめてからマージすること。", "",
             "| 項目 | 前回 | 今回 | 差 |", "|---|---|---|---|"]
    for label, get in ROWS:
        a, b = get(old_build), get(new_build)
        lines.append(f"| {label} | {a:,} | {b:,} | {_diff(a, b)} |")

    lines += ["", "### 件数の変わった県", ""]
    old_p, new_p = old_index.get("prefectures", {}), new_index.get("prefectures", {})
    changed = []
    for code in sorted(set(old_p) | set(new_p)):
        a = (old_p.get(code) or {}).get("count", 0)
        b = (new_p.get(code) or {}).get("count", 0)
        if a != b:
            name = (new_p.get(code) or old_p.get(code) or {}).get("name", code)
            changed.append(f"| {name} | {a:,} | {b:,} | {_diff(a, b)} |")
    if changed:
        lines += ["| 県 | 前回 | 今回 | 差 |", "|---|---|---|---|", *changed]
    else:
        lines.append("件数の変わった県は無い。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="月次 PR の本文")
    ap.add_argument("--old-build", type=pathlib.Path, required=True)
    ap.add_argument("--old-index", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)
    read = lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    print(summarize(read(args.old_build), read(NEW_BUILD), read(args.old_index), read(NEW_INDEX)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
