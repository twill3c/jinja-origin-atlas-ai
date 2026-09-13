# -*- coding: utf-8 -*-
"""T-110〜T-115: 都道府県チャンクとクライアント描画。SPEC D-06。

決定 D-06(2026-09-10・人間の判断): 全国 40,776 件では神社ごとの HTML を作らない。
実測からの外挿で、静的ページ 18,508 枚・出荷ファイル 43,478 個・ビルド約 111 分となり、
Vercel 無料枠の上限(ビルド 45 分・アップロード 5,000 ファイル/24h)に二重に当たった。
神社詳細と類似は 1 枚ずつのクライアント描画ページにし、都道府県ごとの JSON を引く。

件数は定数で書かない。**集合の一致と違反 0** で書く。
"""
import json
import pathlib

import pytest

CHUNK_DIR = pathlib.Path("public/data/shrines")
SIMILAR_DIR = pathlib.Path("public/data/similar")
INDEX = CHUNK_DIR / "index.json"
FULL = pathlib.Path("data/interim/catalog_full.json")
OUT = pathlib.Path("out")

#: Vercel 無料枠のアップロード上限。**こちらで決めた数ではない。**
#: 出所: 記憶 vercel-deploy-quirks(onomato-atlas の初回デプロイで実際に返ったエラー
#: `Too many requests (more than 5000, code: api-upload-free)`)。
UPLOAD_FILE_LIMIT = 5000


@pytest.fixture(scope="module")
def chunks():
    if not INDEX.exists() or not FULL.exists():
        pytest.skip("チャンクか全カタログがまだ無い")
    out = {}
    for p in sorted(CHUNK_DIR.glob("[0-9][0-9].json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))["shrines"]
    return {
        "chunks": out,
        "index": json.loads(INDEX.read_text(encoding="utf-8"))["ids"],
        "full": json.loads(FULL.read_text(encoding="utf-8"))["shrines"],
    }


@pytest.mark.validation
def test_t110_chunks_partition_the_catalog(chunks):
    """T-110: チャンクの和集合 = 全カタログ、どの ID も 2 つのチャンクに入らない。"""
    seen: dict[str, str] = {}
    for code, recs in chunks["chunks"].items():
        for r in recs:
            assert r["id"] not in seen, f"{r['id']} が {seen.get(r['id'])} と {code} の両方にある"
            seen[r["id"]] = code
    full_ids = {r["id"] for r in chunks["full"]}
    assert full_ids, "走査対象が空"
    assert set(seen) == full_ids


@pytest.mark.validation
def test_t111_index_points_to_the_right_chunk(chunks):
    """T-111: 索引が全 ID を覆い、指す先のチャンクに実際にその ID がある。"""
    index = chunks["index"]
    assert set(index) == {r["id"] for r in chunks["full"]}
    by_chunk = {code: {r["id"] for r in recs} for code, recs in chunks["chunks"].items()}
    wrong = [i for i, code in index.items() if i not in by_chunk.get(code, set())]
    assert wrong == [], f"索引が違うチャンクを指している: {wrong[:5]}"


@pytest.mark.validation
def test_t112_records_belong_to_their_chunk(chunks):
    """T-112: チャンク内のレコードの県コードがチャンクの県コードと一致する。"""
    for code, recs in chunks["chunks"].items():
        for r in recs:
            assert r["location"]["pref_code"] == code, (r["id"], r["location"]["pref_code"], code)


@pytest.mark.validation
def test_t115_ai_fields_and_similar_targets(chunks):
    """T-115: AI 欄は ai=true の神社にだけあり、類似の相手はすべて実在する。

    **類似は県チャンクに入れない。** 東京都で測ると欄の 52.6% を占めており、
    詳細を開くだけの人には要らない(2026-09-11 実測)。別ファイルに置く。
    """
    ids = {r["id"] for r in chunks["full"]}
    n_ai = 0
    for recs in chunks["chunks"].values():
        for r in recs:
            assert "similar" not in r, f"{r['id']}: 類似が県チャンクに入っている"
            if r.get("ai"):
                n_ai += 1
                assert "motif_percentiles" in r["ai_scores"], r["id"]
            else:
                assert "ai_scores" not in r, f"{r['id']}: ai=false なのに AI 欄がある"
    assert n_ai > 0, "AI 欄を持つ神社が 1 件も無い(結合が働いていない疑い)"

    n_sim = 0
    for p in sorted(SIMILAR_DIR.glob("[0-9][0-9].json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert doc["pref_code"] == p.stem
        for sid, lst in doc["similar"].items():
            assert sid in ids, f"類似の表に実在しない神社 {sid} がある"
            n_sim += 1
            for other in lst:
                assert other["id"] in ids, f"{sid} の類似相手 {other['id']} が実在しない"
                assert other["id"] != sid, f"{sid}: 自分自身が類似に入っている"
    assert n_sim > 0, "類似の表が空(結合が働いていない疑い)"
    assert n_sim <= n_ai, f"類似を持つ神社 {n_sim} 件が AI つき {n_ai} 件より多い"


@pytest.mark.validation
def test_t113_shipped_file_count_is_under_the_upload_limit():
    """T-113 / D-06: 出荷ファイル数が Vercel 無料枠のアップロード上限を下回る。"""
    if not OUT.exists():
        pytest.skip("out/ がまだ無い")
    n = sum(1 for p in OUT.rglob("*") if p.is_file())
    assert n < UPLOAD_FILE_LIMIT, f"出荷ファイルが {n} 個ある(上限 {UPLOAD_FILE_LIMIT})"


@pytest.mark.validation
def test_t114_no_per_shrine_html():
    """T-114 / D-06: 神社ごとの HTML を作らない(回帰の防止)。

    `/shrine/[id]` に戻すと、全国では 18,508 枚になり上限に当たる。
    """
    if not OUT.exists():
        pytest.skip("out/ がまだ無い")
    for route in ("shrine", "similar"):
        htmls = [p for p in (OUT / route).rglob("*.html")] if (OUT / route).exists() else []
        assert [p.name for p in htmls] == ["index.html"], (
            f"out/{route}/ に HTML が {len(htmls)} 枚ある: {[str(p) for p in htmls[:3]]}"
        )
