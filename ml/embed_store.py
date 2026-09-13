# -*- coding: utf-8 -*-
"""文書単位の埋め込み保存 — SPEC F-09 / N-03(T-123)。

コーパス全体の指紋を鍵にすると、1 件足すだけで全件を作り直し、途中で止まれば
最初からになる。全国(約 3,300 記事)の CPU 埋め込みは数時間かかるので:

- 鍵は **モデル名・版・本文** の SHA-256。版が変われば鍵が変わり、作り直しになる
- 一括ごとに **追記専用の断片**(`shard_NNNNN.npz`)へ保存する。止まっても保存済みから再開する
- 進捗は **区間の速度** で出す。累計の経過秒では停滞と遅さを区別できない(HC-264)
"""
from __future__ import annotations

import hashlib
import pathlib
import sys
import time
from typing import Callable, TextIO

import numpy as np

EncodeFn = Callable[[list[str]], np.ndarray]


class EmbeddingStore:
    def __init__(self, root: pathlib.Path, model_name: str, revision: str):
        self.root = pathlib.Path(root)
        self.model_name = model_name
        self.revision = revision
        self._vec: dict[str, np.ndarray] = {}
        self._load()

    def key(self, text: str) -> str:
        h = hashlib.sha256(f"{self.model_name}@{self.revision}|".encode("utf-8"))
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def _load(self) -> None:
        if not self.root.exists():
            return
        for p in sorted(self.root.glob("shard_*.npz")):
            if p.name.endswith(".tmp.npz"):
                continue  # 書きかけの断片は読まない
            with np.load(p, allow_pickle=False) as z:
                for k, v in zip(z["keys"], z["vectors"]):
                    self._vec[str(k)] = v

    def _next_shard(self) -> pathlib.Path:
        n = 0
        while (self.root / f"shard_{n:05d}.npz").exists():
            n += 1
        return self.root / f"shard_{n:05d}.npz"

    def put(self, texts: list[str], vectors: np.ndarray) -> None:
        """計算済みのベクトルを保存する。一時名で書いてから改名する(止まっても壊れた断片を残さない)。"""
        vectors = np.asarray(vectors, dtype=np.float32)
        if len(texts) != len(vectors):
            raise ValueError(f"本文 {len(texts)} 件とベクトル {len(vectors)} 件が合わない")
        if not texts:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        keys = [self.key(t) for t in texts]
        dst = self._next_shard()
        tmp = dst.with_name(dst.stem + ".tmp.npz")
        np.savez(tmp, keys=np.array(keys), vectors=vectors)
        tmp.replace(dst)
        for k, v in zip(keys, vectors):
            self._vec[k] = v

    def __contains__(self, text: str) -> bool:
        return self.key(text) in self._vec

    def encode_all(self, texts: list[str], encode: EncodeFn, batch_size: int = 64,
                   log: TextIO | None = sys.stderr) -> np.ndarray:
        """足りない文書だけを一括ごとに計算・保存し、入力の並びでベクトルを返す。"""
        todo: list[str] = []
        queued: set[str] = set()
        for t in texts:
            k = self.key(t)
            if k not in self._vec and k not in queued:
                todo.append(t)
                queued.add(k)
        if log is not None:
            print(f"  埋め込み: 保存済み {len(texts) - len(todo)} / 計算する {len(todo)}",
                  file=log, flush=True)
        t0 = time.time()
        for start in range(0, len(todo), batch_size):
            batch = todo[start:start + batch_size]
            ts = time.time()
            self.put(batch, encode(batch))
            if log is not None:
                now = time.time()
                print(f"  埋め込み {start + len(batch)}/{len(todo)}  ({now - t0:.0f}s / 区間 "
                      f"{len(batch) / max(now - ts, 1e-9):.2f} 件/s)", file=log, flush=True)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return np.vstack([self._vec[self.key(t)] for t in texts])
