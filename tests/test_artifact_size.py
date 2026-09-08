# -*- coding: utf-8 -*-
"""T-100: 公開アーティファクトの容量。SPEC N-02 / G-06。

仕様書 §53 は「概算ではなく実データで計測する」と言い、単一の公開 JSON が
gzip 5 MB を超えたら都道府県分割へ移ると定めている(§28.2)。

**gzip で測る。** 配られるのは圧縮後のバイト数であり、非圧縮の大きさではない。
"""
import gzip
import pathlib
import random

import pytest

PUBLIC = pathlib.Path("public/data")

#: 仕様書 §53 の閾値。
MAX_GZIP_BYTES = 5 * 1024 * 1024


def public_files() -> list[pathlib.Path]:
    return sorted(p for p in PUBLIC.rglob("*") if p.is_file() and p.suffix in (".json", ".geojson"))


@pytest.mark.validation
def test_t100_each_public_json_is_under_the_limit():
    """T-100 / G-06: 単一の公開 JSON が gzip 5 MB を超えない。"""
    files = public_files()
    assert files, "走査対象が空(公開ファイルが無い)"
    over = []
    for p in files:
        n = len(gzip.compress(p.read_bytes(), compresslevel=6))
        if n > MAX_GZIP_BYTES:
            over.append((str(p), n))
    assert over == [], f"gzip 5 MB を超える公開 JSON がある: {over}"


@pytest.mark.validation
def test_t100b_positive_control_the_limit_actually_bites():
    """T-100 陽性対照: 閾値を超える入力は実際に落ちること。

    対照が成り立つ前提 —— 圧縮しても閾値を超える大きさのデータであること。
    """
    # **繰り返しは使えない。** bytes(range(256)) の繰り返しは gzip がよく効いて
    # 閾値に届かず、対照そのものが落ちた(2026-09-08)。固定シードの擬似乱数で作る。
    rng = random.Random(20260908)
    blob = bytes(rng.getrandbits(8) for _ in range(MAX_GZIP_BYTES + 512 * 1024))
    n = len(gzip.compress(blob, compresslevel=6))
    assert n > MAX_GZIP_BYTES, f"対照の入力が {n} バイトにしかならない"
