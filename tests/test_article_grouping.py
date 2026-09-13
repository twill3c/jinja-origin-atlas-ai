# -*- coding: utf-8 -*-
"""T-121 / T-122 の部品: 記事単位へのまとめ方と、代表の神社の選び方。SPEC D-07。

出力の検査(T-121 / T-122)は「同じ記事を出さない」「同じ値を配る」を見るが、
**どの本文を使い、どの神社の名前で指すか**は見ない。ここで決め方そのものを固定する。
"""
import pytest

from ml.corpus import Doc
from ml.pipeline import group_by_article, representative


def doc(sid: str, url: str, revid: int = 1, text: str = "本文") -> Doc:
    return Doc(shrine_id=sid, title="T", revid=revid, url=url, license="CC BY-SA 4.0",
               text=text, used_sections=(), truncated=False)


@pytest.mark.unit
def test_shared_article_becomes_one_document_with_all_members():
    arts, members, mismatch = group_by_article([
        doc("jinja_n2", "u1"), doc("jinja_w1", "u1"), doc("jinja_n3", "u2"),
    ])
    assert len(arts) == 2
    assert members == {"u1": ["jinja_n2", "jinja_w1"], "u2": ["jinja_n3"]}
    assert mismatch == 0


@pytest.mark.unit
def test_revision_mismatch_uses_the_newer_text_and_is_counted():
    """取得時期が違えば同じ記事でも版が違う。黙って片方を選ばず、新しい版を使って数える。"""
    arts, _, mismatch = group_by_article([
        doc("a", "u1", revid=10, text="古い"), doc("b", "u1", revid=20, text="新しい"),
    ])
    assert [a.text for a in arts] == ["新しい"]
    assert mismatch == 1


@pytest.mark.unit
def test_grouping_is_independent_of_input_order():
    ds = [doc("b", "u2"), doc("a", "u1"), doc("c", "u1", revid=3)]
    one = group_by_article(ds)
    two = group_by_article(list(reversed(ds)))
    assert [a.shrine_id for a in one[0]] == [a.shrine_id for a in two[0]]
    assert one[1] == two[1]


@pytest.mark.unit
@pytest.mark.parametrize("members,title,names,want", [
    # 本社と神門なら本社
    (["jinja_n1", "jinja_w2"], "北海道神宮", {"jinja_n1": "北海道神宮神門", "jinja_w2": "北海道神宮"}, "jinja_w2"),
    # 曖昧さ回避の括弧を外して一致を見る
    (["a", "b"], "氷川神社 (目黒区八雲)", {"a": "八雲氷川神社", "b": "氷川神社"}, "b"),
    # 一致が無ければ題名に含まれる名前
    (["a", "b"], "札幌伏見稲荷神社", {"a": "手水舎", "b": "伏見稲荷"}, "b"),
    # 名前が無い神社は選ばれにくい。最後は ID で決まる
    (["z", "y"], "某神社", {}, "y"),
])
def test_representative(members, title, names, want):
    assert representative(members, title, names) == want
