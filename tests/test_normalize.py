# -*- coding: utf-8 -*-
"""T-020〜T-022: 名称の正規化と類似度。SPEC F-04。

期待値の出所: SPEC §8.2(仕様書 8.2 の正規化順)と Unicode NFKC の定義。
"""
import pytest

from etl.normalize import name_similarity, normalize_name


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("　八幡神社　", "八幡神社"),                  # 全角空白の前後トリム
        ("八幡  神社", "八幡 神社"),                    # 連続空白の畳み込み
        ("ﾊﾁﾏﾝ神社", "ハチマン神社"),                   # NFKC: 半角カナ → 全角カナ
        ("ＡＢＣ神社", "ABC神社"),                      # NFKC: 全角英字 → 半角
        ("八幡　　神社", "八幡 神社"),          # 全角空白も空白として畳む
        ("八幡神社\n", "八幡神社"),                     # 改行の除去
    ],
)
def test_t020_normalize_name(raw, expected):
    """T-020: NFKC・空白畳み・トリム。"""
    assert normalize_name(raw) == expected


@pytest.mark.unit
def test_t021_negative_control_suffix_is_not_stripped():
    """T-021 陰性対照: 接尾辞を削って同一視してはならない(仕様書 §8.2)。

    正規化だけで「八幡神社」と「八幡宮」を一致させる実装は、別の神社を融合させる。
    対照が成り立つ前提: この 2 つは実際に異なる文字列である。
    """
    assert "八幡神社" != "八幡宮"
    assert normalize_name("八幡神社") != normalize_name("八幡宮")
    assert normalize_name("諏訪神社") != normalize_name("諏訪社")
    # 「神社」という語が正規化で消えていないこと
    assert "神社" in normalize_name("八幡神社")


@pytest.mark.unit
def test_t022_similarity_invariants():
    """T-022: 類似度は [0,1]・対称・同一で 1.0。"""
    pairs = [
        ("八幡神社", "八幡神社"),
        ("八幡神社", "八幡宮"),
        ("伏見稲荷大社", "稲荷神社"),
        ("諏訪大社上社本宮", "諏訪大社"),
        ("", "八幡神社"),
    ]
    for a, b in pairs:
        s = name_similarity(a, b)
        assert 0.0 <= s <= 1.0, (a, b, s)
        assert s == pytest.approx(name_similarity(b, a)), (a, b)
    assert name_similarity("八幡神社", "八幡神社") == pytest.approx(1.0)
    # 対照が成り立つ前提: 異なる名前は 1.0 未満であること
    assert name_similarity("八幡神社", "八幡宮") < 1.0
