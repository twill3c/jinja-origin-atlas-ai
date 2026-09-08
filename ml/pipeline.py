# -*- coding: utf-8 -*-
"""AI パイプライン — SPEC F-09 / G-08 / G-10 / D-01。

    埋め込み → モチーフ → クラスタ → UMAP → 類似 → 公開スコア

**Vercel では動かさない**(RULE-07)。ここで事前計算し、静的 JSON だけを配る。

**本文も埋め込みも配らない**(D-01)。埋め込みは `data/processed/embeddings/`
(`.gitignore` 済み)に置き、公開するのは数値スコアだけである。

仕様書からの逸脱:
- `hdbscan` パッケージではなく scikit-learn の `HDBSCAN` を使う(同じ手法。依存が減る)
- FAISS を使わない。対象が 1,000 件未満では numpy の総当たりのほうが速く、
  仕様書 §23 も FAISS を「ビルド時の道具」としか要求していない

    python -m ml.pipeline
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time

import numpy as np

from ml.corpus import load_corpus

MODEL_NAME = "intfloat/multilingual-e5-base"
MOTIF_FILE = pathlib.Path("ml/labels/motifs.json")
EMB_DIR = pathlib.Path("data/processed/embeddings")
REPORT = pathlib.Path("data/reports/ai_pipeline.json")

OUT_DIR = pathlib.Path("public/data/ai")
OUT_AI = OUT_DIR / "ai.min.json"
OUT_SIM = OUT_DIR / "similarity.min.json"

TOP_K = 20

#: 仕様書 §12.3 の初期値。
PCA_DIM = 50
UMAP_CLUSTER_DIM = 10
MIN_CLUSTER_SIZE = 15
MIN_SAMPLES = 5

#: 陽性対照用の、神社と無関係な文(T-096)。
#: **どのモチーフでも由緒本文より低く出るはず**。出なければ、モチーフ得点は
#: 「神社らしさ」ではなく別の何かを測っている。
CONTROL_TEXTS = (
    "玉ねぎをみじん切りにし、油をひいた鍋で飴色になるまで炒める。",
    "四半期の売上高は前年同期比で 12 パーセント増加し、営業利益率も改善した。",
    "この関数は入力の配列を昇順に整列し、計算量は最悪でも O(n log n) である。",
)


def resolve_revision(model_name: str) -> str:
    """Hugging Face の commit hash を取る。**版を固定できないなら止める**(G-08)。"""
    from huggingface_hub import model_info

    info = model_info(model_name)
    sha = getattr(info, "sha", None)
    if not sha:
        raise RuntimeError(f"{model_name}: commit hash が取れない。版を固定できないので中止する")
    return sha


def encode(texts: list[str], model) -> np.ndarray:
    return model.encode(texts, normalize_embeddings=True, batch_size=16,
                        show_progress_bar=False, convert_to_numpy=True)


def corpus_fingerprint(texts: list[str], model_name: str, revision: str) -> str:
    """本文とモデルの版から鍵を作る。**どれかが変われば作り直す**(仕様書 §22)。"""
    h = hashlib.sha256()
    h.update(f"{model_name}@{revision}|".encode())
    for t in texts:
        h.update(hashlib.sha256(t.encode("utf-8")).digest())
    return h.hexdigest()


def load_or_encode(name: str, texts: list[str], model_name: str, revision: str,
                   model_factory) -> tuple[np.ndarray, bool]:
    """埋め込みを再利用するか、無ければ計算する。

    CPU での埋め込みは 701 件で約 44 分かかる(2026-09-08 実測)。
    本文もモデルの版も変わっていないのに毎回作り直すのは、ただの浪費である。
    """
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    npy = EMB_DIR / f"{name}.npy"
    meta = EMB_DIR / f"{name}.meta.json"
    key = corpus_fingerprint(texts, model_name, revision)
    if npy.exists() and meta.exists():
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m.get("fingerprint") == key and m.get("n") == len(texts):
            v = np.load(npy)
            if v.shape[0] == len(texts):
                print(f"  {name}: 既存の埋め込みを再利用({v.shape})", file=sys.stderr)
                return v, True
    v = encode(texts, model_factory())
    np.save(npy, v)
    meta.write_text(json.dumps({"fingerprint": key, "n": len(texts),
                                "model": model_name, "revision": revision,
                                "dim": int(v.shape[1])}, ensure_ascii=False),
                    encoding="utf-8")
    return v, False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI パイプライン")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    t0 = time.time()
    docs, dropped = load_corpus()
    if args.limit:
        docs = docs[: args.limit]
    print(f"コーパス {len(docs)} 件(落とした内訳 {dropped})", file=sys.stderr)
    if len(docs) < MIN_CLUSTER_SIZE * 2:
        raise RuntimeError(f"コーパスが {len(docs)} 件しかない。クラスタリングが成立しない")

    revision = resolve_revision(MODEL_NAME)
    print(f"モデル {MODEL_NAME} @ {revision[:12]}", file=sys.stderr)

    _model: list = []

    def model_factory():
        if not _model:
            from sentence_transformers import SentenceTransformer

            _model.append(SentenceTransformer(MODEL_NAME, revision=revision))
        return _model[0]

    # --- 埋め込み(E5 の入力形式に従う) ---
    passages = [f"passage: {d.text}" for d in docs]
    emb, reused = load_or_encode("origin_e5", passages, MODEL_NAME, revision, model_factory)
    print(f"埋め込み {emb.shape} {'(再利用)' if reused else ''} ({time.time() - t0:.0f}s)",
          file=sys.stderr)

    # --- モチーフ(定義文の重心とのコサイン類似度) ---
    spec = json.loads(MOTIF_FILE.read_text(encoding="utf-8"))["motifs"]
    motif_keys = list(spec)
    motif_texts: list[str] = []
    motif_spans: list[tuple[int, int]] = []
    for k in motif_keys:
        start = len(motif_texts)
        motif_texts += [f"query: {x}" for x in spec[k]["descriptions"]]
        motif_spans.append((start, len(motif_texts)))
    mv, _ = load_or_encode("motifs_e5", motif_texts, MODEL_NAME, revision, model_factory)
    centroids = []
    for a, b in motif_spans:
        c = mv[a:b].mean(axis=0)
        centroids.append(c / np.linalg.norm(c))
    C = np.vstack(centroids)
    motif_scores = emb @ C.T  # (n, 12) コサイン類似度

    # 陽性対照: 無関係な文はどのモチーフでも低いか(T-096)
    ctl, _ = load_or_encode("control_e5", [f"passage: {t}" for t in CONTROL_TEXTS],
                           MODEL_NAME, revision, model_factory)
    ctl_scores = ctl @ C.T
    control = {
        "control_max": float(ctl_scores.max()),
        "corpus_median_max": float(np.median(motif_scores.max(axis=1))),
        "corpus_min_max": float(motif_scores.max(axis=1).min()),
    }
    control["passes"] = control["control_max"] < control["corpus_median_max"]

    # --- 次元圧縮とクラスタリング ---
    from sklearn.cluster import HDBSCAN
    from sklearn.decomposition import PCA
    import umap

    pca = PCA(n_components=min(PCA_DIM, len(docs) - 1, emb.shape[1]), random_state=20260908)
    reduced = pca.fit_transform(emb)
    u10 = umap.UMAP(n_components=UMAP_CLUSTER_DIM, random_state=20260908,
                    n_neighbors=15, min_dist=0.0).fit_transform(reduced)
    hdb = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES, metric="euclidean")
    labels = hdb.fit_predict(u10)
    probs = getattr(hdb, "probabilities_", np.zeros(len(docs)))

    u2 = umap.UMAP(n_components=2, random_state=20260908,
                   n_neighbors=15, min_dist=0.1).fit_transform(emb)

    # --- 類似神社 Top-K(numpy の総当たり。729 件では FAISS は要らない) ---
    sim = emb @ emb.T
    np.fill_diagonal(sim, -np.inf)  # 自己を除く
    order = np.argsort(-sim, axis=1)[:, :TOP_K]

    # --- 決定 D-05: 生のコサインは画面に出せない ---
    # 実測(2026-09-08): 12 モチーフの値が全部 0.780〜0.882 に収まり、
    # 1 神社の中の最大-最小は中央値 0.042。仕様書 §12.4 の表示例のような開きは無い。
    # 生の数値を 12 個並べると「どれも同じくらい当てはまる」と読まれてしまう。
    # そこで**モチーフごとの分布に対する順位(パーセンタイル)**を併せて出す。
    # 生スコアは再現性のために残す。
    ranks = motif_scores.argsort(axis=0).argsort(axis=0)  # 各列で昇順の順位
    pct = ranks / max(1, len(docs) - 1)  # 0..1

    # --- 公開アーティファクト(**スコアだけ**) ---
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    shrines = []
    for i, d in enumerate(docs):
        shrines.append({
            "id": d.shrine_id,
            "motifs": {k: round(float(motif_scores[i, j]), 4) for j, k in enumerate(motif_keys)},
            "motif_percentiles": {k: round(float(pct[i, j]), 4) for j, k in enumerate(motif_keys)},
            "cluster": {"id": int(labels[i]),
                        "probability": round(float(probs[i]), 4) if labels[i] != -1 else 0.0},
            "umap": {"x": round(float(u2[i, 0]), 4), "y": round(float(u2[i, 1]), 4)},
            "source": {"title": d.title, "revid": d.revid, "url": d.url,
                       "license": d.license, "sections": list(d.used_sections)[:6],
                       "truncated": d.truncated},
        })
    neighbors = {
        docs[i].shrine_id: [[docs[j].shrine_id, round(float(sim[i, j]), 4)] for j in order[i]]
        for i in range(len(docs))
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_AI.write_text(json.dumps({
        "model": {"embedding": MODEL_NAME, "revision": revision, "generated_at": now},
        "note": "スコアは意味的な関連度であり、史実の確からしさではない。"
                "クラスタ番号に歴史学上の意味は無い。",
        "score_note": "生のコサイン類似度は 0.78〜0.88 の狭い帯に収まる(2026-09-08 実測)。"
                      "そのまま並べると 12 個が同じに見えるので、画面には"
                      "モチーフごとの分布に対する順位(motif_percentiles)を出す。",
        "motif_labels": {k: spec[k]["ja"] for k in motif_keys},
        "shrines": shrines,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT_SIM.write_text(json.dumps({
        "model": {"embedding": MODEL_NAME, "revision": revision},
        "top_k": TOP_K, "neighbors": neighbors,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    n_clusters = len({int(x) for x in labels if x != -1})
    report = {
        "corpus": len(docs),
        "corpus_dropped": dropped,
        "model": MODEL_NAME,
        "revision": revision,
        "embedding_dim": int(emb.shape[1]),
        "clusters": n_clusters,
        "noise": int((labels == -1).sum()),
        "cluster_sizes": {str(c): int((labels == c).sum())
                          for c in sorted({int(x) for x in labels})},
        "motif_control": control,
        "motif_score_band": {
            "min": float(motif_scores.min()), "max": float(motif_scores.max()),
            "within_doc_spread_median": float(np.median(
                motif_scores.max(axis=1) - motif_scores.min(axis=1))),
        },
        "truncated_docs": sum(1 for d in docs if d.truncated),
        "bytes_ai": OUT_AI.stat().st_size,
        "bytes_similarity": OUT_SIM.stat().st_size,
        "seconds": round(time.time() - t0, 1),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
