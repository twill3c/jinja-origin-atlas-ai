# -*- coding: utf-8 -*-
"""T-131: G-13 のデータ側 —— A 帯(公開データで確認できること)に出す系統の根拠が AI 由来でない。

詳細画面は系統の行を A 帯に置き、根拠(`shrine_family.basis`)を併記する。分類器には
`ai` と `origin_text`(由緒テキスト)の根拠も定義されているが、全国の実測(2026-09-14)では
none 27,411 / name 10,293 / deity 2,621 だけだった。**いまは違反していないが、分類器が
AI の結果を根拠に使うようになった瞬間に、A 帯に AI の結果が出る。** 画面の検査(T-129)は
表示の文字列を見るので、根拠の値そのものをここで押さえる。
"""
import json
import pathlib

import pytest

CHUNK_DIR = pathlib.Path("public/data/shrines")

#: A 帯に出してよい根拠。AI 由来のもの(ai / origin_text)は含めない
EVIDENCE_BASES = frozenset({"structured", "deity", "name", "none"})


def ai_based_family(recs: list[dict]) -> list[tuple[str, str]]:
    """系統の根拠が A 帯に出してはならないもの(AI 由来)を返す。"""
    return [(r["id"], r["shrine_family"]["basis"]) for r in recs
            if r["shrine_family"]["basis"] not in EVIDENCE_BASES]


@pytest.mark.validation
def test_t131_family_basis_in_evidence_band_is_not_ai():
    files = sorted(CHUNK_DIR.glob("[0-9][0-9].json"))
    if not files:
        pytest.skip("チャンクがまだ無い")
    recs = [r for p in files for r in json.loads(p.read_text(encoding="utf-8"))["shrines"]]
    assert len(recs) > 1000, f"走査対象が {len(recs)} 件しかない"
    bad = ai_based_family(recs)
    assert bad == [], f"{len(bad)} 件の系統が AI 由来の根拠で A 帯に出る。例: {bad[:5]}"


@pytest.mark.validation
@pytest.mark.parametrize("basis", ["ai", "origin_text"])
def test_t131_positive_control(basis):
    """陽性対照: AI 由来の根拠を混ぜると落ちる。"""
    recs = [{"id": "a", "shrine_family": {"basis": "deity"}},
            {"id": "b", "shrine_family": {"basis": basis}}]
    assert ai_based_family(recs) == [("b", basis)]
