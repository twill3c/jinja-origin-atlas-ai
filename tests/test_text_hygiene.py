# -*- coding: utf-8 -*-
"""T-040: 日本語本文への異種文字・制御文字の混入。SPEC G-11。

字形の近いキリル文字・ハングルは読んでも気づけず、制御文字は構文エラーにならない
壊れ方をする。宣言で終わらせず、テストから実際に走らせる。
"""
import subprocess
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = ROOT / "harness" / "text_hygiene.py"


@pytest.mark.validation
def test_t040_no_foreign_or_control_characters():
    """T-040 / G-11: 走査して違反 0。"""
    assert CHECKER.exists(), "検査器が消えている"
    r = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert r.returncode == 0, f"字種・制御文字の違反:\n{r.stdout}\n{r.stderr}"
    # 対照が成り立つ前提: 走査対象が空でないこと。
    # 0 ファイルを走査して「違反 0」と言う検査は何も検査していない。
    assert "走査 0 ファイル" not in r.stdout, f"走査対象が空:\n{r.stdout}"
