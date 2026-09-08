# -*- coding: utf-8 -*-
"""T-001〜T-009: 権利ゲート。SPEC F-05 / G-02。

期待値の出所: tests/fixtures/jps_rights_codes.json(ジャパンサーチ公式のコード値表 +
2026-09-08 の実 API ファセット)。件数は定数で書かず、集合の一致で書く。
"""
import json
import pathlib

import pytest

from etl.rights_gate import DEFAULT_ALLOW, RightsGate, judge

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "jps_rights_codes.json"
ALL_CODES = json.loads(FIXTURE.read_text(encoding="utf-8"))["codes"]
OBSERVED = json.loads(FIXTURE.read_text(encoding="utf-8"))["observed_facet_2026_09_08"]

ALLOWED = {"cc0", "pdm", "ccby"}
DENIED = set(ALL_CODES) - ALLOWED


@pytest.mark.unit
@pytest.mark.parametrize("code", sorted(ALLOWED))
def test_t001_allow_codes(code):
    """T-001: cc0 / pdm / ccby は AI 本文に使える。"""
    assert judge(code).ai_usable is True


@pytest.mark.unit
@pytest.mark.parametrize("code", sorted(DENIED))
def test_t002_deny_codes(code):
    """T-002: 実測 18 コードのうち ALLOW 以外はすべて拒否。

    仕様書 §6.3 の DENY 集合は edu / noncom / com / ccbysa を欠いていた。
    ここではコード表の全体から ALLOW の補集合を取るので、表が増えても穴が開かない。
    """
    assert judge(code).ai_usable is False


@pytest.mark.unit
@pytest.mark.parametrize("code", ["cc-by", "CC0", "public_domain", "ccby40", "未知"])
def test_t003_unknown_code_is_denied(code):
    """T-003: コード表に無い文字列は fail-closed で拒否する。"""
    r = judge(code)
    assert r.ai_usable is False
    assert r.known is False


@pytest.mark.unit
@pytest.mark.parametrize("code", [None, "", "   ", "\t"])
def test_t004_missing_code_is_denied(code):
    """T-004: 欠落は拒否。実測で 100 件中 33 件が contentsRightsType 欄そのものを持たない。"""
    r = judge(code)
    assert r.ai_usable is False
    assert r.known is False


@pytest.mark.unit
def test_t005_code_table_is_exhaustive():
    """T-005 網羅性: 実測に現れた全コードが明示分類され、未知に落ちない。

    走査した母集団: tests/fixtures/jps_rights_codes.json の codes(18 件)と
    2026-09-08 の実ファセットに現れたコード(18 件)。両者は一致する。
    """
    assert set(OBSERVED) - {"_note"} == set(ALL_CODES), "ファセットとコード表が食い違っている"
    unclassified = [c for c in ALL_CODES if not judge(c).known]
    assert unclassified == [], f"未分類のコードがある: {unclassified}"


@pytest.mark.unit
def test_t006_positive_control_allow_set_actually_matters():
    """T-006 陽性対照: ALLOW を空にすると、通っていたコードが全部落ちる。

    これが落ちないなら、ゲートは ALLOW 集合を見ていない。
    """
    empty = RightsGate(allow=frozenset())
    assert all(empty.judge(c).ai_usable is False for c in ALLOWED)
    # 対照が成り立つ前提: 既定のゲートでは同じコードが通っていること
    assert all(judge(c).ai_usable is True for c in ALLOWED)


@pytest.mark.unit
def test_t007_negative_control_deny_set_actually_matters():
    """T-007 陰性対照: ALLOW を全コードに広げると、落ちていたコードが全部通る。

    これが落ちないなら、ゲートは拒否を ALLOW 集合以外の理由で決めている。
    """
    wide = RightsGate(allow=frozenset(ALL_CODES))
    assert all(wide.judge(c).ai_usable is True for c in DENIED)
    # 対照が成り立つ前提: DENIED が空でないこと
    assert len(DENIED) > 0


@pytest.mark.unit
def test_t008_attribution_required():
    """T-008: ccby は表示義務あり、cc0 / pdm は無し。"""
    assert judge("ccby").attribution_required is True
    assert judge("cc0").attribution_required is False
    assert judge("pdm").attribution_required is False


@pytest.mark.unit
def test_t009_filtering_records_leaves_only_allowed():
    """T-009: レコード列を通すと ALLOW 以外が 1 件も残らない(集合の一致で書く)。"""
    records = [{"common": {"contentsRightsType": c, "id": f"r-{c}"}} for c in ALL_CODES]
    records.append({"common": {"id": "r-missing"}})  # 権利欄そのものが無い
    gate = RightsGate()
    kept = gate.filter_records(records)
    kept_codes = {r["common"].get("contentsRightsType") for r in kept}
    assert kept_codes == ALLOWED
    assert DEFAULT_ALLOW == frozenset(ALLOWED)
