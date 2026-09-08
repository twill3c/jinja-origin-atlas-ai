# -*- coding: utf-8 -*-
"""T-035: SPEC の品質ゲート表と TEST_SPEC のケース表の対応を機械で数える。SPEC G-12。

**品質ゲート表は宣言であって検査ではない**(HC-157)。`G-xx` を書いた時点で
「守られている」と錯覚しやすく、しかも書き忘れたゲートについてテストは沈黙する。
だから対応そのものを検査する。

各 `G-xx` は次のどちらかでなければならない。
  (a) TEST_SPEC のケース表の「対応要求」欄から ID で参照されている
  (b) SPEC に「未実装」と明記されている
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = (ROOT / "SPEC.md").read_text(encoding="utf-8")
TEST_SPEC = (ROOT / "TEST_SPEC.md").read_text(encoding="utf-8")

_GATE_ROW = re.compile(r"^\|\s*(G-\d+)\s*\|", re.MULTILINE)
_CASE_ROW = re.compile(r"^\|\s*(T-\d+[a-z]?)\s*\|([^|]*)\|", re.MULTILINE)
_UNIMPL = re.compile(r"未実装のゲート[^:：]*[:：]\s*([^\n]*)")


def declared_gates() -> set[str]:
    return set(_GATE_ROW.findall(SPEC))


def unimplemented_gates() -> set[str]:
    m = _UNIMPL.search(SPEC)
    return set(re.findall(r"G-\d+", m.group(1))) if m else set()


def gates_referenced_by_cases() -> set[str]:
    out: set[str] = set()
    for _tid, requirement in _CASE_ROW.findall(TEST_SPEC):
        out.update(re.findall(r"G-\d+", requirement))
    return out


@pytest.mark.validation
def test_t035_every_gate_is_covered_or_declared_unimplemented():
    """T-035 / G-12: どのケースからも参照されず、未実装とも書かれていないゲートは無い。"""
    gates = declared_gates()
    assert gates, "SPEC のゲート表を読めていない(走査対象が空)"

    covered = gates_referenced_by_cases()
    unimpl = unimplemented_gates()
    orphan = sorted(gates - covered - unimpl)
    assert orphan == [], (
        f"宣言されただけで誰も守っていないゲート: {orphan}。"
        "テストを書くか、SPEC に未実装と明記すること"
    )


@pytest.mark.validation
def test_t035b_unimplemented_list_names_only_real_gates():
    """T-035: 未実装と書いたゲートが実在すること(緩める側だけを増やさない)。"""
    gates = declared_gates()
    ghosts = sorted(unimplemented_gates() - gates)
    assert ghosts == [], f"ゲート表に無い ID を未実装として挙げている: {ghosts}"


@pytest.mark.validation
def test_t035c_unimplemented_gates_are_not_also_claimed_tested():
    """T-035: 未実装と書いたゲートを、同時にケース表から参照していないこと。

    両方に書くと「どちらの主張が本当か」が言えなくなる。
    """
    both = sorted(unimplemented_gates() & gates_referenced_by_cases())
    assert both == [], f"未実装と書きながらケース表からも参照している: {both}"


@pytest.mark.validation
def test_t035d_positive_control_parser_actually_reads_the_tables():
    """T-035 陽性対照: この検査は本当に表を読んでいるか。

    対照が成り立つ前提 —— 表が実在し、既知のゲート・ケースが読めていること。
    パーサが空を返していれば、上の 3 件は何も主張せずに緑になる。
    """
    gates = declared_gates()
    assert "G-01" in gates and "G-12" in gates
    assert len(gates) >= 10, f"ゲートを {len(gates)} 件しか読めていない"

    covered = gates_referenced_by_cases()
    assert "G-02" in covered, "T-001 の対応要求から G-02 が読めていない"
    assert "G-14" in covered, "T-010 の対応要求から G-14 が読めていない"

    # 未実装の宣言も読めていること
    assert unimplemented_gates(), "未実装宣言の行を読めていない"

    # 壊した入力は落ちること(パーサが何でも通す実装になっていないか)
    assert not _GATE_ROW.findall("| Ｇ-01 | 全角の G は読まない |")
