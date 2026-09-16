# -*- coding: utf-8 -*-
"""T-133〜T-136: 月次の自動更新(GitHub Actions で作り直して PR を開く)。SPEC D-09。

月次の実行ではランナーのキャッシュが毎回消えている(GitHub の一次資料: 7 日アクセスが無い
キャッシュは削除)。標高タイル 2.8 万枚・W05 1 GB を毎月取り直さないよう、**前回出荷した
県チャンクの地理特徴量を再利用し、新しい神社と動いた神社だけを測る。**

期待値の出所:
- 動いたとみなす距離 1 m: OSM の座標は小数 7 桁(約 1 cm)で、同じ地物なら変わらない。
  1 m 以上動いたら測り直す(標高タイルの画素は z15 で約 4 m)
- 定期実行の時刻を毎時 0 分にしない: GitHub の一次資料「schedule は毎時 0 分に遅延・取りこぼしがある」
"""
import json
import pathlib

import pytest

from etl.reuse_geography import plan

M_PER_DEG_LAT = 111_194.9


def _cat(sid, lat, lon=135.0, pref="13"):
    return {"id": sid, "location": {"lat": lat, "lon": lon, "pref_code": pref}}


def _prev(lat, lon=135.0, **geo):
    return {"lat": lat, "lon": lon, "geography": geo}


# ---------------------------------------------------------------- T-133 再利用の計画

@pytest.mark.unit
def test_t133_unchanged_shrines_reuse_and_the_rest_are_measured():
    half_m = 0.5 / M_PER_DEG_LAT
    moved = 111.0 / M_PER_DEG_LAT
    prev = {
        "a": _prev(35.0, elevation_m=10.0, elevation_source="dem5a",
                   nearest_river_distance_m=100.0, nearest_river_name="X川"),
        "b": _prev(35.1, nearest_river_note="最寄り河川が 10000 m を超える"),  # 標高が取れていなかった
        "c": _prev(35.2, elevation_m=5.0, elevation_source="dem_png",
                   nearest_river_distance_m=7.0, nearest_river_name="Y川"),
        "m": _prev(35.3, elevation_m=1.0, elevation_source="dem5a",
                   nearest_river_distance_m=1.0, nearest_river_name="Z川"),
    }
    cat = [_cat("a", 35.0), _cat("b", 35.1), _cat("c", 35.2 + half_m), _cat("m", 35.3 + moved),
           _cat("n", 35.4)]
    p = plan(cat, prev)

    assert p.elevation_reuse == {"a": {"elevation_m": 10.0, "source": "dem5a"},
                                 "c": {"elevation_m": 5.0, "source": "dem_png"}}
    assert p.elevation_todo == ["b", "m", "n"], "取れていなかった・動いた・新しい神社を測り直す"

    assert set(p.river_reuse) == {"a", "b", "c"}
    assert p.river_reuse["a"]["nearest_river_distance_m"] == 100.0
    assert p.river_reuse["b"]["nearest_river_distance_m"] is None
    assert p.river_reuse["b"]["reason"].startswith("最寄り河川が"), "理由つきの空欄を理由ごと引き継ぐ"
    assert p.river_todo == ["m", "n"]


@pytest.mark.unit
def test_t133_nothing_previous_means_everything_is_measured():
    cat = [_cat("a", 35.0), _cat("b", 35.1)]
    p = plan(cat, {})
    assert p.elevation_reuse == {} and p.river_reuse == {}
    assert p.elevation_todo == ["a", "b"] and p.river_todo == ["a", "b"]


@pytest.mark.unit
def test_t133_river_without_distance_or_note_is_measured_again():
    """河川の欄がまるごと無い神社(前回の計算から漏れた)は、再利用せず測り直す。"""
    prev = {"a": _prev(35.0, elevation_m=1.0, elevation_source="dem5a")}
    p = plan([_cat("a", 35.0)], prev)
    assert p.river_reuse == {} and p.river_todo == ["a"]
    assert "a" in p.elevation_reuse


# ---------------------------------------------------------------- T-135 PR の本文

@pytest.mark.unit
def test_t135_pr_summary_shows_before_after_and_prefecture_changes():
    from scripts.pr_summary import summarize

    old_b = {"shrines": 10, "matched_auto": 5, "with_ai": 2, "with_elevation": 10,
             "with_river_distance": 9, "dedupe": {"merged_features": 1}}
    new_b = {"shrines": 12, "matched_auto": 5, "with_ai": 3, "with_elevation": 12,
             "with_river_distance": 11, "dedupe": {"merged_features": 1}}
    old_i = {"prefectures": {"13": {"name": "東京都", "count": 5}, "26": {"name": "京都府", "count": 5}}}
    new_i = {"prefectures": {"13": {"name": "東京都", "count": 7}, "26": {"name": "京都府", "count": 5}}}
    md = summarize(old_b, new_b, old_i, new_i)
    assert "| 神社 | 10 | 12 | +2 |" in md
    assert "| AI の欄が付いた神社 | 2 | 3 | +1 |" in md
    assert "| 自動結合 | 5 | 5 | ±0 |" in md
    assert "東京都" in md and "京都府" not in md, "件数の変わった県だけを並べる"


@pytest.mark.unit
def test_t135_pr_summary_says_when_no_prefecture_changed():
    from scripts.pr_summary import summarize

    b = {"shrines": 1, "matched_auto": 0, "with_ai": 0, "with_elevation": 1,
         "with_river_distance": 1, "dedupe": {"merged_features": 0}}
    i = {"prefectures": {"13": {"name": "東京都", "count": 1}}}
    assert "件数の変わった県は無い" in summarize(b, b, i, i)


# ---------------------------------------------------------------- T-136 ワークフロー

WORKFLOW = pathlib.Path(".github/workflows/monthly-data.yml")


@pytest.mark.unit
def test_t136_workflow_opens_a_pull_request_and_never_pushes_main():
    assert WORKFLOW.exists(), "月次のワークフローが無い"
    t = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" in t, "手動で起動できない(初回を見届けられない)"
    assert "schedule:" in t
    crons = [ln.split("cron:")[1].strip().strip("'\"") for ln in t.splitlines() if "cron:" in ln]
    assert crons, "cron が無い"
    for c in crons:
        assert c.split()[0] not in ("0", "00"), f"毎時 0 分は遅延・取りこぼしがある: {c}"
    assert "timeout-minutes:" in t, "時間の上限を書いていない"
    minutes = [int(ln.split(":")[1]) for ln in t.splitlines() if "timeout-minutes:" in ln]
    assert all(m <= 360 for m in minutes), f"ジョブの上限 6 時間を超えている: {minutes}"
    assert "pull-requests: write" in t and "contents: write" in t
    assert "gh pr create" in t, "PR を開いていない"
    assert "git push origin HEAD:main" not in t and "push origin main" not in t, "main へ直接 push している"
    assert "--reuse-from" in t, "地理特徴量を再利用していない(毎月 2.8 万枚を取り直す)"


# ---------------------------------------------------------------- T-134 増分の被覆

@pytest.mark.validation
def test_t134_incremental_river_run_loaded_every_needed_prefecture():
    """増分で河川距離を計算したときも、計算した神社の候補の県はすべて読んでいること。

    全件のとき(T-119)は 47 県すべて。増分のときは、**再利用した件数と計算した件数を報告に残し**、
    計算に要る県が一つも欠けていないことを見る(HC-263: 単位がまるごと欠けても下流は区別できない)。
    """
    p = pathlib.Path("data/interim/river_distance.json")
    if not p.exists():
        pytest.skip("河川距離がまだ計算されていない")
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("mode") != "incremental":
        pytest.skip("全件で計算した報告(T-119 が見る)")
    assert d["reused"] + d["computed"] == d["shrines"] - d["shrines_without_pref"]
    missing = sorted(set(d["prefs_needed"]) - set(d["streams_per_pref"]))
    assert missing == [], f"計算に要る県の河川を読んでいない: {missing}"


@pytest.mark.unit
def test_t133_state_file_survives_unicode_line_separators(tmp_path):
    """状態ファイルは LF だけで行を割る。値に NEL(U+0085)や U+2028 が入っていても壊れない。

    str.splitlines() はこれらでも行を割る。loop_012 の試走で、化けた河川名に入っていた U+0085 で
    状態ファイルの行が途中で切れた。
    """
    from etl.reuse_geography import load_previous, write_state

    odd = "川" + chr(0x2028) + "名" + chr(0x85)
    cat = tmp_path / "cat.json"
    ele = tmp_path / "ele.json"
    riv = tmp_path / "riv.json"
    cat.write_text(json.dumps({"shrines": [{"id": "a", "location": {"lat": 35.0, "lon": 135.0}}]}),
                   encoding="utf-8")
    ele.write_text(json.dumps({"elevation": {"a": {"elevation_m": 1.5, "source": "dem5a"}}}), encoding="utf-8")
    riv.write_text(json.dumps({"river": {"a": {"nearest_river_distance_m": 2.0, "nearest_river_name": odd}}},
                              ensure_ascii=False), encoding="utf-8")
    state = tmp_path / "state.jsonl"
    write_state(cat, ele, riv, state)
    prev = load_previous(state)
    assert prev["a"]["geography"]["nearest_river_name"] == odd
    assert prev["a"]["geography"]["elevation_m"] == 1.5


@pytest.mark.unit
def test_t134_needed_prefectures_are_chosen_per_shrine(tmp_path, monkeypatch):
    """計算に要る県は、**神社ごとの小さな箱**で選ぶ。県の神社をまとめた大きな箱で選ぶと、
    離れた二社のあいだにあるだけの県まで読むことになる。

    loop_012 の試走では、無作為に選んだ 30 社のために 35 県の W05 を読んでいた。
    最寄り河川は上限 10 km なので、神社の周り 0.15 度(南北 16.7 km)の箱の外にある県は答えを変えない。
    """
    import etl.river_distance as rd

    ref = {"prefectures": {
        "A": {"bbox": [130.0, 33.0, 130.2, 33.2]},   # 神社 1 の近く
        "B": {"bbox": [140.0, 38.0, 140.2, 38.2]},   # 神社 2 の近く
        "Z": {"bbox": [135.0, 35.5, 135.2, 35.7]},   # 二社のあいだにあるだけ
    }}
    p = tmp_path / "bbox.json"
    p.write_text(json.dumps(ref), encoding="utf-8")
    monkeypatch.setattr(rd, "BBOX_REF", p)
    recs = [_cat("s1", 33.1, 130.1, pref="99"), _cat("s2", 38.1, 140.1, pref="99"), _cat("s3", 36.0, 136.0)]
    assert rd.needed_prefs(recs, {"s1", "s2"}) == ["A", "B"]
    assert rd.needed_prefs(recs, set()) == []


@pytest.mark.unit
def test_t141_model_cache_is_outside_the_working_tree():
    """T-141: モデルのキャッシュを作業ツリーの中に置かない。

    五回目の実行で、HF_HOME を `${{ github.workspace }}/.hf` に置いたため、字種検査(G-11)が
    モデルの tokenizer.json を走査して違反 37,084 件を出し、pytest だけが落ちた(データは健全)。
    検査器は「人が書いた文」を見るもので、依存のキャッシュは対象外にする —— 置き場所で外す。
    """
    t = WORKFLOW.read_text(encoding="utf-8")
    hf = [ln.strip() for ln in t.splitlines() if "HF_HOME" in ln]
    assert hf, "HF_HOME を指定していない(既定の置き場所は環境で変わる)"
    for ln in hf:
        assert "github.workspace" not in ln and "$GITHUB_WORKSPACE" not in ln, \
            f"モデルのキャッシュが作業ツリーの中にある: {ln}"
        assert "runner.temp" in ln or "RUNNER_TEMP" in ln, f"ランナーの一時領域を使っていない: {ln}"


@pytest.mark.unit
def test_t141b_runner_context_is_not_used_outside_steps():
    """T-141: `${{ runner.* }}` を書かない(環境変数 $RUNNER_TEMP を使う)。

    runner コンテキストは env: の位置では使えず、GitHub はワークフローの解析に失敗して
    起動そのものを HTTP 422 で拒否する。**手元の検査は文字列として runner.temp を見ていたので緑だった** ——
    構文として妥当かは見ていなかった。書き方を一つに絞って、誤用の入り口を塞ぐ。
    """
    t = WORKFLOW.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in t.splitlines() if "${{ runner." in ln or "${{runner." in ln]
    assert bad == [], f"runner コンテキストを使っている(env: では解析に失敗する): {bad}"
    assert "$RUNNER_TEMP" in t, "ランナーの一時領域を環境変数で参照していない"
