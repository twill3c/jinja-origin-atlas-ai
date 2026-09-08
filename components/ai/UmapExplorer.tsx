"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

type AiShrine = {
  id: string;
  motifs: Record<string, number>;
  motif_percentiles: Record<string, number>;
  cluster: { id: number; probability: number };
  umap: { x: number; y: number };
  source: { title: string; revid: number; url: string; license: string };
};
type AiDoc = { motif_labels: Record<string, string>; shrines: AiShrine[] };

const W = 720;
const H = 520;
const PAD = 28;

/* 散布図は「どの二色も隣り合いうる」形なので、カテゴリを色で塗り分けられるのは 3 色まで。
 * クラスタは十数個あるので**色相で塗り分けない**。
 * 連続量(モチーフのスコア)は**単一色相の濃淡**で表す —— これが量に対する正しい表し方である。
 * クラスタは「ひとつ選んで強調する」に留める。 */
const RAMP = ["#f2ede5", "#e6c9b4", "#d8996f", "#c96b3a", "#b7410e"];
const MUTED = "#c9c4bc";

function rampColor(t: number): string {
  const i = Math.max(0, Math.min(RAMP.length - 1, Math.floor(t * RAMP.length)));
  return RAMP[i];
}

export default function UmapExplorer() {
  const [doc, setDoc] = useState<AiDoc | null>(null);
  const [motif, setMotif] = useState<string>("");
  const [cluster, setCluster] = useState<number | null>(null);
  const [hover, setHover] = useState<AiShrine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    fetch("/data/ai/ai.min.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: AiDoc) => setDoc(d))
      .catch((e) => setError(String(e)));
  }, []);

  const layout = useMemo(() => {
    if (!doc) return null;
    const xs = doc.shrines.map((s) => s.umap.x);
    const ys = doc.shrines.map((s) => s.umap.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (v: number) => PAD + ((v - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
    const sy = (v: number) => H - PAD - ((v - y0) / (y1 - y0 || 1)) * (H - 2 * PAD);
    const clusters = [...new Set(doc.shrines.map((s) => s.cluster.id))].sort((a, b) => a - b);
    return { sx, sy, clusters };
  }, [doc]);

  // 濃淡は**順位**で決める。生のコサインは 0.78〜0.88 の狭い帯に収まるので、
  // 値そのものを min-max で伸ばしても、どこが濃いかは順位とほぼ同じにしかならない。
  // 順位なら「全体の中でどのあたりか」と読み手に説明できる。
  const range = useMemo(() => {
    if (!doc || !motif) return null;
    const vs = doc.shrines.map((s) => s.motifs[motif]);
    return { lo: Math.min(...vs), hi: Math.max(...vs) };
  }, [doc, motif]);

  if (error) return <p role="status" style={{ color: "#b7410e" }}>{error}</p>;
  if (!doc || !layout) return <p>読み込み中…</p>;

  const motifKeys = Object.keys(doc.motif_labels);

  return (
    <div>
      <fieldset
        style={{
          border: "1px solid var(--line)", borderRadius: 4, padding: "0.6rem 0.9rem",
          margin: "0 0 0.75rem", background: "var(--panel)",
        }}
      >
        <legend style={{ fontSize: "0.85rem", padding: "0 0.4rem" }}>見かたを変える</legend>
        <label style={{ fontSize: "0.9rem", display: "block", marginBottom: "0.4rem" }}>
          モチーフの強さで濃淡をつける:{" "}
          <select value={motif} onChange={(e) => setMotif(e.target.value)}>
            <option value="">(つけない)</option>
            {motifKeys.map((k) => (
              <option key={k} value={k}>{doc.motif_labels[k]}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: "0.9rem" }}>
          クラスタを強調:{" "}
          <select
            value={cluster === null ? "" : String(cluster)}
            onChange={(e) => setCluster(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">(しない)</option>
            {layout.clusters.map((c) => (
              <option key={c} value={c}>
                {c === -1 ? "どのクラスタにも入らない" : `クラスタ ${c}`}
              </option>
            ))}
          </select>
        </label>
        <p style={{ margin: "0.5rem 0 0", fontSize: "0.78rem", color: "var(--ink-mute)" }}>
          クラスタ番号は識別子であって、歴史学上の系統ではない。番号そのものに意味は無く、
          データや設定が変われば付け替わる。
          {range && (
            <>
              {" "}濃いほど、そのモチーフが全体の中で上位にある。
              生のスコアは {range.lo.toFixed(3)} 〜 {range.hi.toFixed(3)} の狭い帯に収まるので、
              値ではなく<strong>順位</strong>で濃淡をつけている。
            </>
          )}
        </p>
      </fieldset>

      <div className="scroll-x">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          style={{ maxWidth: W, border: "1px solid var(--line)", background: "var(--panel)" }}
          role="img"
          aria-label={`由緒テキストの意味空間。${doc.shrines.length} 件の神社を 2 次元に射影した散布図。`}
        >
          {doc.shrines.map((s) => {
            const dimmed = cluster !== null && s.cluster.id !== cluster;
            let fill = "#b7410e";
            if (motif) {
              fill = rampColor(s.motif_percentiles[motif]);
            }
            if (dimmed) fill = MUTED;
            return (
              <circle
                key={s.id}
                cx={layout.sx(s.umap.x)}
                cy={layout.sy(s.umap.y)}
                r={dimmed ? 2.5 : 4}
                fill={fill}
                stroke="#ffffff"
                strokeWidth={0.8}
                opacity={dimmed ? 0.55 : 0.95}
                onMouseEnter={() => setHover(s)}
                onFocus={() => setHover(s)}
                tabIndex={0}
                style={{ cursor: "pointer" }}
              >
                <title>{s.source.title}</title>
              </circle>
            );
          })}
        </svg>
      </div>

      {motif && (
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", marginTop: "0.5rem",
                      fontSize: "0.8rem", color: "var(--ink-mute)" }}>
          <span>下位</span>
          {RAMP.map((c) => (
            <span key={c} style={{ width: 28, height: 12, background: c,
                                   border: "1px solid var(--line)" }} />
          ))}
          <span>上位</span>
          <span>／ {doc.motif_labels[motif]}</span>
        </div>
      )}

      <div className="band band-ai" style={{ marginTop: "0.75rem" }} role="status">
        <h3>{hover ? "指している神社" : "点にふれると内訳が出る"}</h3>
        {hover ? (
          <>
            <p style={{ margin: 0 }}>
              <strong>{hover.source.title}</strong>
              {" ／ "}
              {hover.cluster.id === -1 ? "どのクラスタにも入らない" : `クラスタ ${hover.cluster.id}`}
            </p>
            <p style={{ margin: "0.3rem 0 0", fontSize: "0.85rem" }}>
              {Object.entries(hover.motif_percentiles)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(([k]) => doc.motif_labels[k])
                .join(" ／ ")}
              {" が上位のモチーフ"}
            </p>
            <p style={{ margin: "0.3rem 0 0", fontSize: "0.8rem", color: "var(--ink-mute)" }}>
              <Link href={`/shrine/${hover.id}/`}>詳細</Link>
              {" ／ "}
              <Link href={`/similar/${hover.id}/`}>似た由緒</Link>
              {" ／ 由来: "}
              <a href={hover.source.url} rel="noreferrer" target="_blank">
                {hover.source.title}
              </a>{" "}
              (rev {hover.source.revid}, {hover.source.license})
            </p>
          </>
        ) : (
          <p style={{ margin: 0, color: "var(--ink-mute)" }}>
            近い位置にある点は、由緒の文章が意味的に近いことを表す。
            <strong>史実の関係ではない。</strong>
          </p>
        )}
      </div>
    </div>
  );
}
