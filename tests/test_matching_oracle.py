# -*- coding: utf-8 -*-
"""T-063 / T-065 / T-066: 名寄せの非循環オラクル。SPEC G-09 / §7 / D-02。

**オラクルの性格**: Wikidata の P10689(way)/ P11693(node)/ P402(relation)と、
OSM 要素の `wikidata=Q…` タグ。どちらも**人間が「この項目はこの要素だ」と明示した対応**
であり、マッチャーはこれを一切入力に使わない(D-02)。したがって「何組を再現できたか」は
循環しない。

**閾値の床は取り置き半分を見て決めたのではない。** 較正半分(411 組)の掃きで
0.60 の再現率が 0.9611 だったので、余裕を見て床を 0.90 に置いた。取り置き半分の数字は
その床に対する**標本外の答え**である。
"""
import json
import pathlib

import pytest

from etl.entity_resolution import AUTO_THRESHOLD, match_score, resolve
from quality.calibrate_matching import build_oracle, load_osm, split

CATALOG = pathlib.Path("public/data/catalog/shrines.min.json")
RAW_WD = pathlib.Path("data/raw/wikidata/core.json")

pytestmark = pytest.mark.skipif(
    not (CATALOG.exists() and RAW_WD.exists()),
    reason="OSM カタログか Wikidata 生データがまだ無い",
)

#: 較正半分で決めた床。**取り置き半分を見て決めていない。**
#: 較正側の実測は 0.60 で再現率 0.9611・適合率 1.0000(2026-09-08、411 組)。
HOLDOUT_RECALL_FLOOR = 0.90
HOLDOUT_PRECISION_FLOOR = 0.95
TOP1_FLOOR = 0.95


@pytest.fixture(scope="module")
def resolved():
    from etl.wikidata_records import load_records

    osm = load_osm()
    wd = [r for r in load_records().values() if r.get("coord")]
    oracle = build_oracle(osm, wd_map := {r["qid"]: r for r in wd})["pairs"]
    matches = {m.osm_id: m for m in resolve(osm, wd)}
    return {"osm": {r["id"]: r for r in osm}, "wd": wd_map,
            "oracle": oracle, "matches": matches}


@pytest.mark.validation
def test_t066_oracle_is_non_empty_and_two_directional(resolved):
    """T-066: オラクルが空でなく、両方向から作られていること。

    **走査対象が空の検査は、何も検査していないのに緑になる。**
    """
    oracle = resolved["oracle"]
    assert len(oracle) >= 100, f"オラクルのペアが {len(oracle)} 組しかない"
    dirs = {v["direction"] for v in oracle.values()}
    assert "osm_tag" in dirs, "OSM 側の wikidata タグから作られたペアが無い"
    assert dirs & {"wd_id", "both"}, "Wikidata 側の OSM ID から作られたペアが無い"


@pytest.mark.validation
def test_t063_holdout_recall_and_precision(resolved):
    """T-063 / G-09: 取り置き半分に対する再現率・適合率。"""
    oracle, matches = resolved["oracle"], resolved["matches"]
    hold = [(k, v) for k, v in oracle.items() if split(k) == "holdout"]
    assert len(hold) >= 50, f"取り置きが {len(hold)} 組しかない"

    top1 = sum(1 for k, v in hold if matches[k].qid == v["qid"])
    kept = [(k, v) for k, v in hold if matches[k].score >= AUTO_THRESHOLD]
    correct = sum(1 for k, v in kept if matches[k].qid == v["qid"])

    top1_rate = top1 / len(hold)
    recall = correct / len(hold)
    precision = correct / len(kept) if kept else 0.0

    assert top1_rate >= TOP1_FLOOR, f"top-1 一致 {top1_rate:.4f} < {TOP1_FLOOR}"
    assert recall >= HOLDOUT_RECALL_FLOOR, f"再現率 {recall:.4f} < {HOLDOUT_RECALL_FLOOR}"
    assert precision >= HOLDOUT_PRECISION_FLOOR, f"適合率 {precision:.4f} < {HOLDOUT_PRECISION_FLOOR}"


@pytest.mark.validation
def test_t065_positive_control_ignoring_names_hurts_recall(resolved):
    """T-065 陽性対照: 名称類似度を無視すると再現率が落ちること。

    落ちないなら、この照合は名称を見ていない —— つまりオラクルは距離だけを
    測っており、名寄せの性能を測っていない。
    """
    osm, wd, oracle = resolved["osm"], resolved["wd"], resolved["oracle"]
    hold = [(k, v) for k, v in oracle.items() if split(k) == "holdout"]

    # 名称を消した OSM レコードで測り直す(距離だけが残る)
    stripped = [dict(r, name={"ja": None, "kana": None, "en": None}, aliases=[])
                for r in osm.values()]
    m2 = {m.osm_id: m for m in resolve(stripped, list(wd.values()))}

    base = sum(1 for k, v in hold if resolved["matches"][k].qid == v["qid"]) / len(hold)
    blind = sum(1 for k, v in hold if m2[k].qid == v["qid"]) / len(hold)
    assert blind < base, f"名称を消しても top-1 が下がらない(base={base:.4f} blind={blind:.4f})"

    # 対照が成り立つ前提 —— 元のレコードに実際に名前が入っていること
    named = sum(1 for r in osm.values() if r["name"]["ja"])
    assert named > len(osm) * 0.5, f"名前を持つ OSM レコードが {named}/{len(osm)} しかない"


@pytest.mark.validation
def test_t062c_no_oracle_field_reaches_the_matcher(resolved):
    """T-062 / D-02: オラクルの欄を消しても結果が 1 件も変わらないこと。

    「使っていないつもり」を実物で確かめる。
    """
    osm, wd = resolved["osm"], resolved["wd"]
    blinded_osm = [
        dict(r, external_ids=dict(r["external_ids"], osm_wikidata_tag=None))
        for r in osm.values()
    ]
    # 対照が成り立つ前提 —— 消す前に実際にリンクが入っていること
    assert sum(1 for r in osm.values() if r["external_ids"].get("osm_wikidata_tag")) > 0

    before = [(m.osm_id, m.qid, round(m.score, 9)) for m in resolved["matches"].values()]
    after = [(m.osm_id, m.qid, round(m.score, 9)) for m in resolve(blinded_osm, list(wd.values()))]
    assert sorted(before) == sorted(after)
