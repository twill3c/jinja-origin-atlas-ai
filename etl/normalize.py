# -*- coding: utf-8 -*-
"""名称の正規化と類似度 — SPEC F-04(仕様書 §8.2)。

**「神社」を削った文字列だけで同一判定してはならない。** 削ると
「八幡神社」と「八幡宮」、「諏訪神社」と「諏訪社」が一致してしまい、
別の神社が融合する。ここでは接尾辞を削らない。
"""
from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """NFKC 正規化 → 空白の畳み込み → 前後トリム。

    仕様書 §8.2 の順序に従う。旧字体の正規化は任意扱いなので V1.0 では行わない
    (異体字を潰すと別法人格の神社が融合しうるため)。
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = _WS.sub(" ", s)
    return s.strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """名称の類似度を [0, 1] で返す。対称。同一文字列で 1.0。

    rapidfuzz の token_sort_ratio ではなく ratio を使う。神社名は語順の入れ替えが
    ほぼ起きない一方、部分文字列の一致(「稲荷神社」対「伏見稲荷大社」)を
    過大評価すると名寄せが緩みすぎる。
    """
    na, nb = normalize_name(a), normalize_name(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return fuzz.ratio(na, nb) / 100.0
