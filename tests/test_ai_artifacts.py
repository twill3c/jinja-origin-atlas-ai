# -*- coding: utf-8 -*-
"""T-090〜T-099: AI アーティファクト。SPEC F-09 / D-01 / G-08 / G-10。

**この検査の要は T-090** —— 決定 D-01 は「CC BY-SA の本文も埋め込みベクトルも
配布しない」を条件に ja.wikipedia の利用を認めている。条件を破っていないことを
機械で確かめる。

期待値の出所:
- 12 モチーフ: 仕様書 §12.4
- Top-K = 20: 仕様書 §12.2
- E5 の入力形式: モデルカード(intfloat/multilingual-e5-base)
"""
import json
import math
import pathlib

import pytest

AI_DIR = pathlib.Path("public/data/ai")
AI_JSON = AI_DIR / "ai.min.json"
SIM_JSON = AI_DIR / "similarity.min.json"
UMAP_JSON = AI_DIR / "umap.min.json"

# **モジュール全体を skip しない。** そうすると陽性対照・陰性対照まで黙って
# skip され、「検査器が働くこと」の確認まで消える。
# データを要る検査だけがフィクスチャの中で skip する。

MOTIFS = (
    "kanjo_bunshi", "ujigami_chinju", "mountain_nature", "water_river",
    "sea_navigation", "agriculture_rice", "goryo_pacification", "warrior_samurai",
    "person_memorial", "epidemic_disaster", "settlement_frontier", "modern_merger",
)
TOP_K = 20


@pytest.fixture(scope="module")
def ai():
    if not AI_JSON.exists():
        pytest.skip("AI アーティファクトが未生成")
    return json.loads(AI_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sim():
    if not SIM_JSON.exists():
        pytest.skip("類似度アーティファクトが未生成")
    return json.loads(SIM_JSON.read_text(encoding="utf-8"))


#: 埋め込みと疑う数値列の長さ。E5-base は 768 次元、UMAP に落としても 10 次元。
#: モチーフは 12 種なので、この閾値なら正しい出力には当たらない。
VECTOR_SUSPECT_LEN = 32

#: 由緒本文と疑う文字列長。神社名・記事題名・注記・URL はこれより短い。
TEXT_SUSPECT_LEN = 300

#: 名前が紛らわしい欄。**名前だけで落とさない** —— 仕様書 §7.2 の
#: `model.embedding` は「使ったモデルの名前」であって埋め込みではない。
#: 陰性対照 test_t090c がこの誤検出を捕まえた(2026-09-08)。
#: 名前は手がかりにとどめ、**判定は形(数値列か・長い文字列か)で行う**。
SUSPICIOUS_KEYS = frozenset({"text", "extract", "body", "embedding", "vector", "vec", "embeddings"})


def assert_no_text_or_vectors(node, path: str = "ai") -> None:
    """本文と埋め込みが混じっていないことを確かめる(D-01 の条件 1・2)。

    判定は**形**で行う。長さ 32 以上の数値列は埋め込み、300 字以上の文字列は本文とみなす。
    紛らわしい名前の欄は、値が列か長文のときにだけ落とす。
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SUSPICIOUS_KEYS:
                assert not isinstance(v, list), f"{path}.{k}: 配ってはならない列がある"
                if isinstance(v, str):
                    assert len(v) < 120, f"{path}.{k}: {len(v)} 字の文字列がある(本文の疑い)"
            assert_no_text_or_vectors(v, f"{path}.{k}")
    elif isinstance(node, list):
        if len(node) >= VECTOR_SUSPECT_LEN and all(isinstance(x, (int, float)) for x in node):
            raise AssertionError(f"{path}: 長さ {len(node)} の数値列がある(埋め込みの疑い)")
        for i, v in enumerate(node):
            assert_no_text_or_vectors(v, f"{path}[{i}]")
    elif isinstance(node, str):
        assert len(node) < TEXT_SUSPECT_LEN, f"{path}: {len(node)} 字の文字列がある(本文の疑い)"


@pytest.mark.validation
def test_t090_no_text_and_no_vectors_in_public(ai):
    """T-090 / G-10 / D-01: 公開物に本文も埋め込みも入っていない。

    決定 D-01 はこの二つを配らないことを条件に CC BY-SA の利用を認めている。
    **条件を破ったら、この検査が落ちる。**
    """
    assert_no_text_or_vectors(ai)


@pytest.mark.validation
@pytest.mark.parametrize(
    "bad",
    [
        {"shrines": [{"id": "x", "embedding": [0.1] * 768}]},
        {"shrines": [{"id": "x", "text": "あ" * 400}]},
        {"shrines": [{"id": "x", "body": "い" * 500}]},
        {"shrines": [{"id": "x", "scores": [0.1] * 128}]},
    ],
)
def test_t090b_positive_control_the_check_actually_fires(bad):
    """T-090 陽性対照: 禁じたものを入れた偽の文書は落ちること。

    落ちないなら、T-090 は何も検査していない。名前を変えて隠しても
    (`scores` に 128 次元)長さで捕まえる。
    """
    with pytest.raises(AssertionError):
        assert_no_text_or_vectors(bad)


@pytest.mark.validation
def test_t090c_negative_control_valid_document_passes():
    """T-090 陰性対照: 正しい形の文書は通ること(誤検出 0)。

    通らないなら検査が厳しすぎて、正しい実装のほうを落とす。
    """
    good = {
        "model": {"embedding": "intfloat/multilingual-e5-base", "revision": "a" * 40},
        "shrines": [{
            "id": "jinja_n1",
            "motifs": {m: 0.5 for m in MOTIFS},
            "cluster": {"id": 3, "probability": 0.8},
            "umap": {"x": 1.0, "y": -2.0},
            "source": {"title": "八幡神社", "revid": 123, "license": "CC BY-SA 4.0",
                       "url": "https://ja.wikipedia.org/wiki/..."},
        }],
    }
    assert_no_text_or_vectors(good)


@pytest.mark.validation
def test_t091_model_revision_is_recorded(ai):
    """T-091 / G-08: モデル名と revision が記録されている。

    どのモデルのどの版で出したスコアか言えないなら、その数は再現できない。
    """
    m = ai.get("model")
    assert m, "model の記録が無い"
    assert m.get("embedding"), "モデル名が無い"
    rev = m.get("revision")
    assert rev and rev not in ("", "main", "master", "PINNED_COMMIT_HASH"), (
        f"revision が固定されていない: {rev!r}"
    )
    assert len(rev) >= 7, f"revision が短すぎる: {rev!r}"
    assert m.get("generated_at")


@pytest.mark.validation
def test_t095_motifs_are_complete_and_in_range(ai):
    """T-095: 12 モチーフすべてに値が出て、コサインの値域に収まる。"""
    recs = ai["shrines"]
    assert recs, "走査対象が空"
    for r in recs[:200]:
        ms = r["motifs"]
        assert set(ms) == set(MOTIFS), f"{r['id']}: モチーフが揃っていない"
        for k, v in ms.items():
            assert -1.0001 <= v <= 1.0001, f"{r['id']}.{k} = {v}"


@pytest.mark.validation
def test_t094_similarity_invariants(sim, ai):
    """T-094: 自己を含まない・Top-K 以内・降順・相手が実在する。"""
    ids = {r["id"] for r in ai["shrines"]}
    assert sim["neighbors"], "走査対象が空"
    for sid, lst in list(sim["neighbors"].items())[:200]:
        assert len(lst) <= TOP_K, f"{sid}: {len(lst)} 件ある"
        assert all(other != sid for other, _ in lst), f"{sid}: 自分自身が入っている"
        assert all(other in ids for other, _ in lst), f"{sid}: 存在しない相手がいる"
        scores = [s for _, s in lst]
        assert scores == sorted(scores, reverse=True), f"{sid}: 降順でない"
        assert all(-1.0001 <= s <= 1.0001 for s in scores)


@pytest.mark.validation
def test_t098_cluster_labels_are_not_given_meaning(ai):
    """T-098: クラスタ番号は識別子であって意味ではない。

    番号に意味があるかのように見せていないことを、`cluster` の作りで確かめる。
    ノイズ(-1)が「クラスタ 0」に潰されていないこと。
    """
    labels = [r["cluster"]["id"] for r in ai["shrines"]]
    assert any(x == -1 for x in labels) or len(set(labels)) > 1, (
        "全部が同じクラスタに入っている(クラスタリングが働いていない疑い)"
    )
    for r in ai["shrines"][:200]:
        c = r["cluster"]
        assert isinstance(c["id"], int)
        assert 0.0 <= c["probability"] <= 1.0
        if c["id"] == -1:
            assert c["probability"] == 0.0, "ノイズに確からしさを与えない"


@pytest.mark.validation
def test_t099_attribution_is_present(ai):
    """T-099 / D-01: 由来記事の題名・版 ID・ライセンスが付いている。

    帰属できない本文は使わない、というのが D-01 の条件 3 である。
    """
    for r in ai["shrines"][:200]:
        s = r["source"]
        assert s["title"], r["id"]
        assert isinstance(s["revid"], int) and s["revid"] > 0, r["id"]
        assert s["license"] == "CC BY-SA 4.0", r["id"]
        assert s["url"].startswith("https://ja.wikipedia.org/"), r["id"]


@pytest.mark.validation
def test_umap_coordinates_are_finite(ai):
    """UMAP 座標が有限であること(NaN を配らない)。"""
    for r in ai["shrines"][:500]:
        u = r["umap"]
        assert math.isfinite(u["x"]) and math.isfinite(u["y"]), r["id"]


@pytest.mark.validation
def test_t096_motif_control_passes():
    """T-096 陽性対照: 神社と無関係な文は、どのモチーフでも由緒本文より低く出る。

    通らないなら、モチーフのスコアは「神社らしさ」ではなく別の何か
    (文の長さ・書き言葉らしさ)を測っている。

    対照の文はパイプラインに埋め込んである(料理の手順・決算の説明・
    アルゴリズムの解説)。結果は data/reports/ai_pipeline.json に残る。
    """
    p = pathlib.Path("data/reports/ai_pipeline.json")
    if not p.exists():
        pytest.skip("パイプラインのレポートが未生成")
    c = json.loads(p.read_text(encoding="utf-8"))["motif_control"]
    assert c["control_max"] < c["corpus_median_max"], (
        f"無関係な文の最高スコア {c['control_max']:.3f} が "
        f"由緒本文の中央値 {c['corpus_median_max']:.3f} を下回っていない"
    )
    assert c["passes"] is True


@pytest.mark.validation
def test_t097_motif_vs_geography_is_measured():
    """T-097: モチーフと地理条件の照合が実際に行われ、記録されていること。

    **結果の向きをここで固定しない。** 「山岳のモチーフが高い神社は標高が高い」は
    仮説であって、外れたら外れたと書く。この検査が守るのは
    「測って記録したこと」であって「期待どおりだったこと」ではない。
    """
    p = pathlib.Path("data/reports/motif_vs_geography.json")
    if not p.exists():
        pytest.skip("照合レポートが未生成")
    rs = json.loads(p.read_text(encoding="utf-8"))["results"]
    assert rs, "照合が 1 件も行われていない"
    for r in rs:
        assert "n" in r
        if r["n"] >= 50:
            assert "spearman" in r and "permutation_p" in r, r
            assert -1.0 <= r["spearman"] <= 1.0
            assert 0.0 < r["permutation_p"] <= 1.0


@pytest.mark.validation
def test_corpus_selection_drops_are_counted():
    """コーパスから落としたものが理由ごとに数えられていること(黙って捨てない)。"""
    p = pathlib.Path("data/reports/ai_pipeline.json")
    if not p.exists():
        pytest.skip("パイプラインのレポートが未生成")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(d["corpus_dropped"], dict) and d["corpus_dropped"]
    assert d["corpus"] > 0
