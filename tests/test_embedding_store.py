# -*- coding: utf-8 -*-
"""T-123: 埋め込みの保存は文書単位。SPEC F-09 / N-03。

コーパス全体の指紋を鍵にすると、1 件足しただけで全件を作り直す(701 件で約 44 分)。
途中で止まれば最初からになる。全国(約 3,300 記事)では数時間の処理なので、
**足した分だけ計算し、止まっても保存済みから再開する**ことを、偽のモデルで
符号化の回数を数えて確かめる。
"""
import numpy as np
import pytest

from ml.embed_store import EmbeddingStore


class FakeModel:
    """呼ばれた文を記録し、文の長さから決まるベクトルを返す。"""

    def __init__(self, fail_after_calls: int | None = None):
        self.calls: list[list[str]] = []
        self.fail_after_calls = fail_after_calls

    def __call__(self, texts: list[str]) -> np.ndarray:
        if self.fail_after_calls is not None and len(self.calls) >= self.fail_after_calls:
            raise RuntimeError("途中で止まった")
        self.calls.append(list(texts))
        return np.array([[len(t), 1.0, 0.0] for t in texts], dtype=np.float32)

    @property
    def encoded(self) -> list[str]:
        return [t for c in self.calls for t in c]


@pytest.mark.unit
def test_t123_adding_documents_encodes_only_the_new_ones(tmp_path):
    m1 = FakeModel()
    v1 = EmbeddingStore(tmp_path, "m", "rev1").encode_all(["a", "bb", "ccc"], m1, batch_size=2, log=None)
    assert m1.encoded == ["a", "bb", "ccc"]
    assert v1.shape == (3, 3)

    m2 = FakeModel()
    # 別プロセスを想定して開き直す
    v2 = EmbeddingStore(tmp_path, "m", "rev1").encode_all(["a", "bb", "ccc", "dddd"], m2,
                                                           batch_size=2, log=None)
    assert m2.encoded == ["dddd"], "既存の文書を作り直している"
    np.testing.assert_array_equal(v2[:3], v1)
    assert v2[3, 0] == 4


@pytest.mark.unit
def test_t123_resume_after_interruption(tmp_path):
    texts = [f"t{i}" * (i + 1) for i in range(5)]
    broken = FakeModel(fail_after_calls=1)
    with pytest.raises(RuntimeError):
        EmbeddingStore(tmp_path, "m", "rev1").encode_all(texts, broken, batch_size=2, log=None)
    assert broken.encoded == texts[:2]

    m = FakeModel()
    v = EmbeddingStore(tmp_path, "m", "rev1").encode_all(texts, m, batch_size=2, log=None)
    assert m.encoded == texts[2:], "保存済みの分から再開していない"
    assert [int(x) for x in v[:, 0]] == [len(t) for t in texts], "並び順が入力と合わない"


@pytest.mark.unit
def test_t123_revision_change_reencodes_everything(tmp_path):
    EmbeddingStore(tmp_path, "m", "rev1").encode_all(["a", "b"], FakeModel(), log=None)
    m = FakeModel()
    EmbeddingStore(tmp_path, "m", "rev2").encode_all(["a", "b"], m, log=None)
    assert m.encoded == ["a", "b"], "モデルの版が変わったのに古い埋め込みを使っている"


@pytest.mark.unit
def test_t123_duplicate_texts_are_encoded_once(tmp_path):
    m = FakeModel()
    v = EmbeddingStore(tmp_path, "m", "rev1").encode_all(["x", "yy", "x"], m, log=None)
    assert m.encoded == ["x", "yy"]
    np.testing.assert_array_equal(v[0], v[2])


@pytest.mark.unit
def test_t123_put_seeds_existing_vectors(tmp_path):
    """既存の一括保存(origin_e5.npy)から種を入れられる。"""
    s = EmbeddingStore(tmp_path, "m", "rev1")
    s.put(["a", "b"], np.array([[9, 9, 9], [8, 8, 8]], dtype=np.float32))
    m = FakeModel()
    v = EmbeddingStore(tmp_path, "m", "rev1").encode_all(["b", "a", "c"], m, log=None)
    assert m.encoded == ["c"]
    assert v[0, 0] == 8 and v[1, 0] == 9


@pytest.mark.unit
def test_t123_leftover_temp_shard_is_ignored(tmp_path):
    """書きかけの一時断片が残っていても読まない(止まった瞬間の残骸)。"""
    EmbeddingStore(tmp_path, "m", "rev1").encode_all(["a"], FakeModel(), log=None)
    (tmp_path / "shard_00001.tmp.npz").write_bytes(b"broken")
    m = FakeModel()
    EmbeddingStore(tmp_path, "m", "rev1").encode_all(["a", "b"], m, log=None)
    assert m.encoded == ["b"]
