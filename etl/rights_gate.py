# -*- coding: utf-8 -*-
"""権利ゲート — SPEC F-05 / G-02 / RULE-01 / RULE-03。

「検索できる」「閲覧できる」と「学習用本文として再利用できる」は別である。
このゲートを通らない本文は embedding にも分類にも公開用全文保存にも回さない。

コード表の出所は tests/fixtures/jps_rights_codes.json に記録した
ジャパンサーチ公式のコード値表(2026-09-08 取得)。

**fail-closed である。** 表に無いコード・欠落は必ず拒否する。
仕様書 V1.0 §6.3 は ALLOW と DENY を列挙していたが、両者の和は実際のコード表を
網羅しておらず、edu / noncom / com / ccbysa の 4 コードがどちらにも属さなかった。
列挙した DENY に当たらなければ通す実装だと、この 4 つが黙って通る。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Mapping

#: ジャパンサーチ common.contentsRightsType のコード値表(公式・18 件)。
#: この集合に無い文字列は「未知」であり、既定で拒否される。
KNOWN_CODES: frozenset[str] = frozenset(
    {
        "edu",
        "noncom",
        "com",
        "cc0",
        "pdm",
        "ccby",
        "ccbysa",
        "ccbynd",
        "ccbync",
        "ccbyncsa",
        "ccbyncnd",
        "incr",
        "incr_edu",
        "nocr_cont",
        "nocr_other",
        "uneval",
        "undet",
        "others",
    }
)

#: V1.0 で AI 本文として許可する権利コード。
DEFAULT_ALLOW: frozenset[str] = frozenset({"cc0", "pdm", "ccby"})

#: 表示義務(帰属)が要るコード。
_ATTRIBUTION_REQUIRED: frozenset[str] = frozenset(
    {"ccby", "ccbysa", "ccbynd", "ccbync", "ccbyncsa", "ccbyncnd"}
)

#: 人間向けの説明。judge().reason に載る。
_LABEL: dict[str, str] = {
    "edu": "教育利用",
    "noncom": "非商用利用",
    "com": "商用利用",
    "cc0": "CC0",
    "pdm": "PDM",
    "ccby": "CC BY",
    "ccbysa": "CC BY-SA",
    "ccbynd": "CC BY-ND",
    "ccbync": "CC BY-NC",
    "ccbyncsa": "CC BY-NC-SA",
    "ccbyncnd": "CC BY-NC-ND",
    "incr": "著作権あり",
    "incr_edu": "著作権あり-教育目的の利用可",
    "nocr_cont": "著作権なし-契約による制限あり",
    "nocr_other": "著作権なし-他の法的制限あり",
    "uneval": "著作権未評価",
    "undet": "著作権未決定-裁定制度利用著作物",
    "others": "該当なし",
}


@dataclass(frozen=True)
class RightsVerdict:
    """権利判定の結果。"""

    code: str | None
    known: bool
    ai_usable: bool
    redistributable: bool
    attribution_required: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "known": self.known,
            "ai_usable": self.ai_usable,
            "redistributable": self.redistributable,
            "attribution_required": self.attribution_required,
            "reason": self.reason,
        }


class RightsGate:
    """権利コードの判定器。

    `allow` を差し替えられるようにしてあるのは、テストが陽性対照・陰性対照を
    置けるようにするためである(TEST_SPEC T-006 / T-007)。
    出荷時は常に既定の :data:`DEFAULT_ALLOW` を使う。
    """

    def __init__(self, allow: Iterable[str] | None = None) -> None:
        self.allow: frozenset[str] = frozenset(DEFAULT_ALLOW if allow is None else allow)

    def judge(self, code: Any) -> RightsVerdict:
        norm = code.strip() if isinstance(code, str) else None
        if not norm:
            return RightsVerdict(
                code=None,
                known=False,
                ai_usable=False,
                redistributable=False,
                attribution_required=False,
                reason="権利コードが無い(fail-closed で拒否)",
            )
        if norm not in KNOWN_CODES:
            return RightsVerdict(
                code=norm,
                known=False,
                ai_usable=False,
                redistributable=False,
                attribution_required=False,
                reason=f"コード表に無い値 {norm!r}(fail-closed で拒否)",
            )
        allowed = norm in self.allow
        return RightsVerdict(
            code=norm,
            known=True,
            ai_usable=allowed,
            redistributable=allowed,
            attribution_required=norm in _ATTRIBUTION_REQUIRED,
            reason=_LABEL[norm],
        )

    def filter_records(self, records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        """ジャパンサーチのレコード列から AI 本文に使えるものだけを残す。"""
        return list(self.iter_allowed(records))

    def iter_allowed(self, records: Iterable[Mapping[str, Any]]) -> Iterator[Mapping[str, Any]]:
        for rec in records:
            common = rec.get("common") or {}
            if self.judge(common.get("contentsRightsType")).ai_usable:
                yield rec


_DEFAULT_GATE = RightsGate()


def judge(code: Any) -> RightsVerdict:
    """既定のゲートで 1 件判定する。"""
    return _DEFAULT_GATE.judge(code)
