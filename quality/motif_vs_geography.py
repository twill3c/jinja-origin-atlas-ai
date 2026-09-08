# -*- coding: utf-8 -*-
"""モチーフのスコアを、独立に測った地理条件と突き合わせる — SPEC T-097。

**循環しない照合である。** モチーフのスコアは由緒テキストの埋め込みから出ており、
標高は国土地理院の DEM から、河川距離は国土数値情報 W05 から出ている。
互いを参照していないので、一致したなら「文章が土地のことを言っている」ことになる。

問いは二つ:

- 「山岳・自然」の高い神社は、実際に標高が高いか
- 「水・河川」の高い神社は、実際に川に近いか

**当たらなくても、当たらなかったと書く。** 期待どおりにならない結果を消さない。

    python -m quality.motif_vs_geography
"""
from __future__ import annotations

import json
import math
import pathlib
import random

AI = pathlib.Path("public/data/ai/ai.min.json")
CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
REPORT = pathlib.Path("data/reports/motif_vs_geography.json")


def spearman(xs: list[float], ys: list[float]) -> float:
    """順位相関。外れ値と単調でない関係に強い。"""
    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def permutation_p(xs: list[float], ys: list[float], observed: float, n: int = 2000,
                  seed: int = 20260908) -> float:
    """並べ替え検定。**対照を置く** —— 偶然でこの相関が出る確率を測る。"""
    rng = random.Random(seed)
    shuffled = list(ys)
    hits = 0
    for _ in range(n):
        rng.shuffle(shuffled)
        if abs(spearman(xs, shuffled)) >= abs(observed):
            hits += 1
    return (hits + 1) / (n + 1)


def main() -> int:
    if not AI.exists():
        raise SystemExit("AI アーティファクトが無い。先に python -m ml.pipeline を実行する")
    ai = json.loads(AI.read_text(encoding="utf-8"))
    cat = {r["id"]: r for r in json.loads(CATALOG.read_text(encoding="utf-8"))["shrines"]}

    pairs = [
        ("mountain_nature", "elevation_m", "山岳・自然のスコアと標高", +1),
        ("water_river", "nearest_river_distance_m", "水・河川のスコアと河川距離", -1),
        ("sea_navigation", "elevation_m", "海・航海のスコアと標高(低いほうへ出るはず)", -1),
    ]

    results = []
    for motif, geo_key, label, expect_sign in pairs:
        xs, ys = [], []
        for s in ai["shrines"]:
            g = (cat.get(s["id"]) or {}).get("geography") or {}
            v = g.get(geo_key)
            if v is None:
                continue
            xs.append(s["motifs"][motif])
            ys.append(float(v))
        if len(xs) < 50:
            results.append({"label": label, "n": len(xs), "note": "標本が少なすぎる"})
            continue
        rho = spearman(xs, ys)
        p = permutation_p(xs, ys, rho)
        results.append({
            "label": label, "motif": motif, "geography": geo_key,
            "n": len(xs),
            "spearman": round(rho, 4),
            "expected_sign": expect_sign,
            "sign_matches": (rho > 0) == (expect_sign > 0),
            "permutation_p": round(p, 4),
            "significant_at_0.01": p < 0.01,
        })

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(json.dumps({"results": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
