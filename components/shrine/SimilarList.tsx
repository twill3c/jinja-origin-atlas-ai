"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { SimilarDoc, SimilarEntry } from "@/lib/shrine-types";
import { shrineHref, topMotifs, upperPercent } from "@/lib/shrine-types";
import { useShrine } from "./useShrine";

export default function SimilarList() {
  const st = useShrine();
  // 類似の相手は県チャンクに入れていない(詳細だけ見る人に配らないため)。
  // この画面だけが県ごとの類似ファイルを引く。
  const pref = st.status === "ready" ? st.shrine.location.pref_code : null;
  const shrineId = st.status === "ready" ? st.shrine.id : null;
  const [list, setList] = useState<SimilarEntry[] | null>(null);

  useEffect(() => {
    if (!pref || !shrineId) return;
    let cancelled = false;
    fetch(`/data/similar/${pref}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`類似の表が読めない(HTTP ${r.status})`))))
      .then((d: SimilarDoc) => !cancelled && setList(d.similar[shrineId] ?? []))
      .catch(() => !cancelled && setList([]));
    return () => {
      cancelled = true;
    };
  }, [pref, shrineId]);
  const name = st.status === "ready" ? (st.shrine.name.ja ?? st.shrine.ai_scores?.source.title ?? st.id) : null;

  useEffect(() => {
    if (name) document.title = `${name}と由緒が似た神社 | Jinja Origin Atlas AI`;
  }, [name]);

  if (st.status === "loading") return <p role="status">読み込み中…</p>;
  if (st.status === "error") {
    return (
      <>
        <h1>見つかりません</h1>
        <p role="status">{st.message}</p>
        <p>
          <Link href="/ai-space/">意味空間</Link>から探すこと。
        </p>
      </>
    );
  }

  const s = st.shrine;
  const ai = s.ai_scores;
  if (!ai) {
    return (
      <>
        <h1>{name} と由緒が似た神社</h1>
        <p role="status">
          この神社には由緒の意味分析が付いていない。<Link href="/ai-space/">意味空間</Link>
          から探すこと。
        </p>
      </>
    );
  }

  const labels = st.chunk.motif_labels;
  // **順位で取る。** 生スコアで上位を取ると 66% の神社で「勧請・分祀」が 1 位になり
  // (2026-09-08 実測)、神社ごとの違いではなくモチーフの基準値の差を見ることになる。
  const myTop = topMotifs(ai.motif_percentiles);
  if (list === null) return <p role="status">読み込み中…</p>;

  return (
    <>
      <h1>{name} と由緒が似た神社</h1>
      <p className="lede">由緒テキストの意味的な近さで並べた上位 {list.length} 件。</p>

      <div className="band band-ai">
        <h3>これは何であって、何でないか</h3>
        <p style={{ margin: 0 }}>
          文章の意味が近いという計算結果であって、
          <strong>この神社からあの神社へ勧請された、という意味ではない</strong>。
          文献で確認できる分祀の関係は、神社詳細の「文献上の母院」に別に書いてある。
        </p>
      </div>

      <div className="scroll-x">
        <table>
          <caption
            style={{
              captionSide: "bottom",
              fontSize: "0.8rem",
              color: "var(--ink-mute)",
              textAlign: "left",
              paddingTop: "0.4rem",
            }}
          >
            「共通のモチーフ」は、両方で(順位にして)上位 3 位に入っているモチーフ。
            生のスコアで順位を取ると 66 % の神社で同じモチーフが 1 位になるので、そうしていない。
          </caption>
          <thead>
            <tr>
              <th scope="col">意味関連スコア</th>
              <th scope="col">神社</th>
              <th scope="col">系統</th>
              <th scope="col">共通のモチーフ</th>
              <th scope="col">同じクラスタか</th>
            </tr>
          </thead>
          <tbody>
            {list.map((o) => {
              const shared = myTop.filter((k) => o.top3.includes(k));
              return (
                <tr key={o.id}>
                  <td>{o.score.toFixed(3)}</td>
                  <th scope="row">
                    <Link href={shrineHref(o.id, o.p)}>{o.name ?? o.id}</Link>
                    {o.prefecture ? ` — ${o.prefecture}` : ""}
                  </th>
                  <td>{o.family_ja}</td>
                  <td>{shared.length ? shared.map((k) => labels[k] ?? k).join("・") : "—"}</td>
                  <td>
                    {o.cluster !== null && o.cluster === ai.cluster.id && ai.cluster.id !== -1
                      ? `同じ(${ai.cluster.id})`
                      : "違う"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2>この神社の由緒モチーフ</h2>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th scope="col">モチーフ</th>
              <th scope="col">全体の中での位置</th>
            </tr>
          </thead>
          <tbody>
            {topMotifs(ai.motif_percentiles, 12).map((k) => (
              <tr key={k}>
                <th scope="row">{labels[k] ?? k}</th>
                <td>上位 {upperPercent(ai.motif_percentiles[k])} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
        生のコサイン類似度は 0.78〜0.88 の狭い帯に収まり、数字を並べても差が読めない。
        ここに出しているのは、そのモチーフの分布に対する順位である。
        生のスコアは <code>/data/ai/ai.min.json</code> に残してある。
      </p>

      <h2>由来</h2>
      <p style={{ fontSize: "0.9rem" }}>
        <a href={ai.source.url} rel="noreferrer" target="_blank">
          {ai.source.title}
        </a>{" "}
        — 日本語版ウィキペディア(版 {ai.source.revid}、{ai.source.license})。
        本文は再配布していない。
      </p>

      <p style={{ marginTop: "1.5rem" }}>
        <Link href={shrineHref(s.id, s.location.pref_code)}>← {name} の詳細へ</Link>
      </p>
    </>
  );
}
