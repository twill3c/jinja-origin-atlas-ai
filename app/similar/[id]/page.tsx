import type { Metadata } from "next";
import Link from "next/link";
import { readAi, readCatalogIndex, readSimilarity } from "@/lib/data";

export function generateStaticParams() {
  return readAi().shrines.map((s) => ({ id: s.id }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const name = readCatalogIndex().get(id)?.name.ja ?? "神社";
  return {
    title: `${name}と由緒が似た神社 | Jinja Origin Atlas AI`,
    description: `${name}の由緒テキストと意味的に近い神社。AI による意味関連度であり、史実の系譜ではない。`,
  };
}

export default async function SimilarPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const ai = readAi();
  const index = readCatalogIndex();
  const me = ai.byId.get(id) ?? null;
  const list = readSimilarity()[id] ?? [];
  const byId = ai.byId;

  if (!me) {
    return (
      <main>
        <h1>見つかりません</h1>
        <p>
          この神社には由緒の意味分析が付いていない。
          <Link href="/ai-space/">意味空間</Link>から探すこと。
        </p>
      </main>
    );
  }

  // **順位で取る。** 生スコアで上位を取ると 66% の神社で「勧請・分祀」が 1 位になり
  // (2026-09-08 実測)、神社ごとの違いではなくモチーフの基準値の差を見ることになる。
  const myTop = Object.entries(me.motif_percentiles)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k]) => k);
  const name = index.get(id)?.name.ja ?? me.source.title;

  return (
    <main>
      <h1>{name} と由緒が似た神社</h1>
      <p className="lede">
        由緒テキストの意味的な近さで並べた上位 {list.length} 件。
      </p>

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
            style={{ captionSide: "bottom", fontSize: "0.8rem", color: "var(--ink-mute)",
                     textAlign: "left", paddingTop: "0.4rem" }}
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
            {list.map(([other, score]) => {
              const o = byId.get(other);
              const info = index.get(other);
              const theirTop = o
                ? Object.entries(o.motif_percentiles)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 3)
                    .map(([k]) => k)
                : [];
              const shared = myTop.filter((k) => theirTop.includes(k));
              return (
                <tr key={other}>
                  <td>{score.toFixed(3)}</td>
                  <th scope="row">
                    <Link href={`/shrine/${other}/`}>
                      {info?.name.ja ?? o?.source.title ?? other}
                    </Link>
                    {info?.location.prefecture ? ` — ${info.location.prefecture}` : ""}
                  </th>
                  <td>{info?.shrine_family.label_ja ?? "—"}</td>
                  <td>
                    {shared.length
                      ? shared.map((k) => ai.labels[k]).join("・")
                      : "—"}
                  </td>
                  <td>
                    {o && o.cluster.id === me.cluster.id && me.cluster.id !== -1
                      ? `同じ(${me.cluster.id})`
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
              <th scope="col">生のスコア</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(me.motif_percentiles)
              .sort((a, b) => b[1] - a[1])
              .map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{ai.labels[k]}</th>
                  <td>上位 {Math.max(1, Math.round((1 - v) * 100))} %</td>
                  <td style={{ color: "var(--ink-mute)" }}>{me.motifs[k].toFixed(3)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
        生のスコアは<strong>意味関連スコア</strong>であって、確率ではない。
        しかもこのモデルでは 0.78〜0.88 の狭い帯に収まるので、数字を並べても差が読めない。
        左の「全体の中での位置」は、そのモチーフの分布に対する順位である。
      </p>

      <h2>由来</h2>
      <p style={{ fontSize: "0.9rem" }}>
        <a href={me.source.url} rel="noreferrer" target="_blank">
          {me.source.title}
        </a>{" "}
        — 日本語版ウィキペディア(版 {me.source.revid}、{me.source.license})。
        本文は再配布していない。
      </p>

      <p style={{ marginTop: "1.5rem" }}>
        <Link href={`/shrine/${id}/`}>← {name} の詳細へ</Link>
      </p>
    </main>
  );
}
