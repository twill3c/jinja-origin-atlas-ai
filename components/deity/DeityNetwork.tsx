"use client";

import { useMemo } from "react";
import type { EgoGraph, NetworkDoc, PairType } from "@/lib/deity-types";
import { PAIR_TYPE_JA } from "@/lib/deity-types";

/* 選んだ一柱を中心に置いた共祀の図。**座標はビルド時に決めてある**(G-18)。
 *
 * 全体を一枚に描くのは二度試してやめた。73 柱を力学配置で並べると、中心部で
 * 丸とラベルが重なって読めない —— しかも `viewBox` の検査も要素数の検査も
 * **緑のまま**である(図が読めるかは目視でしか分からない・HC-041)。
 * 問いが「この祭神は誰と並ぶか」である以上、中心を決めた図のほうが答えになる。
 *
 * **畳めるのは同一視の辺だけ。** 八幡神と応神天皇のような「同じ一柱が二つの名で
 * 書かれている」対だけを畳む。親族・総称と構成神・その他は別の神格なので畳まない。 */

const STYLE: Record<PairType, { stroke: string; dash?: string; width: number }> = {
  identity: { stroke: "#b7410e", dash: "7 5", width: 3.2 },
  kin: { stroke: "#1f5673", width: 2.4 },
  partof: { stroke: "#7a5c2e", dash: "3 4", width: 2.4 },
  other: { stroke: "#57534e", width: 1.6 },
  mixed: { stroke: "#57534e", dash: "1 4", width: 1.6 },
  unlabeled: { stroke: "#c6bfb5", width: 1.1 },
};

/** ラベルの字送り(全角 1 文字 = 1em)。環の半径 320 に対して 26 で約 12px。 */
const LABEL_EM = 26;

function radius(n: number, center: boolean): number {
  return (center ? 12 : 7) + Math.sqrt(n) * (center ? 1.8 : 1.3);
}

export default function DeityNetwork({
  doc,
  collapsed,
  selected,
  onSelect,
}: {
  doc: NetworkDoc;
  collapsed: boolean;
  selected: string;
  onSelect: (qid: string) => void;
}) {
  const graph: EgoGraph | null = useMemo(() => {
    if (collapsed) {
      const root = doc.collapsed_of[selected];
      if (root && doc.collapsed_ego[root]) return doc.collapsed_ego[root];
    }
    return doc.ego[selected] ?? null;
  }, [doc, selected, collapsed]);

  /* viewBox は**ノードの座標だけでは決めない**(HC-159)。ラベルは環の外へ伸びるので、
   * データの範囲で切ると静かに切り取られる。半径とラベルの幅を足してから外接矩形を取る。 */
  const box = useMemo(() => {
    if (!graph) return { x: -10, y: -10, w: 20, h: 20 };
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of graph.nodes) {
      const r = radius(n.n, n.center);
      const w = n.name.length * LABEL_EM + r + 10;
      x0 = Math.min(x0, n.x - w);
      x1 = Math.max(x1, n.x + w);
      y0 = Math.min(y0, n.y - r - LABEL_EM);
      y1 = Math.max(y1, n.y + r + LABEL_EM);
    }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }, [graph]);

  if (!graph) {
    return (
      <p className="notice">
        この祭神と同じ社に並ぶ相手は、公開データの中に一柱もいない。
        <strong>関係が無いという意味ではなく、Wikidata に書かれていない</strong>ということ。
      </p>
    );
  }

  const byQid = new Map(graph.nodes.map((n) => [n.qid, n]));
  const shown = new Set<PairType>(graph.edges.map((e) => e.type));
  const centre = graph.nodes.find((n) => n.center)!;
  const hiddenNeighbours = graph.neighbours_total - graph.neighbours_shown;

  return (
    <div>
      <svg
        viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
        role="img"
        aria-label={`${centre.name}と同じ社に並ぶ祭神の図。相手 ${graph.neighbours_shown} 柱、辺 ${graph.edges.length} 本。`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        <g>
          {graph.edges.map((e) => {
            const a = byQid.get(e.a);
            const b = byQid.get(e.b);
            if (!a || !b) return null;
            const s = STYLE[e.type] ?? STYLE.unlabeled;
            const central = e.a === centre.qid || e.b === centre.qid;
            return (
              <line
                key={`${e.a}-${e.b}`}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={s.stroke}
                strokeWidth={s.width}
                strokeDasharray={s.dash}
                strokeOpacity={central ? 0.9 : 0.28}
              >
                <title>
                  {a.name}と{b.name}: 同じ社 {e.w} 件・{PAIR_TYPE_JA[e.type]}
                </title>
              </line>
            );
          })}
        </g>
        <g>
          {graph.nodes.map((n) => {
            const r = radius(n.n, n.center);
            const right = n.x >= 0;
            return (
              <g key={n.qid}>
                <circle
                  cx={n.x} cy={n.y} r={r}
                  fill={n.center ? "#b7410e" : "#ffffff"}
                  stroke={n.center ? "#7a2a09" : "#57534e"}
                  strokeWidth={n.center ? 3 : 1.6}
                  style={{ cursor: n.center ? "default" : "pointer" }}
                  onClick={() => !n.center && onSelect(n.qid)}
                  role={n.center ? undefined : "button"}
                  tabIndex={n.center ? undefined : 0}
                  aria-label={`${n.name} ${n.n} 社`}
                  onKeyDown={(ev) => {
                    if (!n.center && (ev.key === "Enter" || ev.key === " ")) {
                      ev.preventDefault();
                      onSelect(n.qid);
                    }
                  }}
                />
                <text
                  x={n.center ? n.x : right ? n.x + r + 7 : n.x - r - 7}
                  y={n.center ? n.y + r + LABEL_EM : n.y + LABEL_EM * 0.35}
                  textAnchor={n.center ? "middle" : right ? "start" : "end"}
                  fontSize={LABEL_EM}
                  fontWeight={n.center ? 700 : 400}
                  fill="#1c1917"
                  style={{ pointerEvents: "none" }}
                >
                  {n.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <ul className="net-legend" aria-label="辺の凡例">
        {(["identity", "kin", "partof", "other", "mixed", "unlabeled"] as PairType[])
          .filter((t) => shown.has(t))
          .map((t) => (
            <li key={t}>
              <svg width="30" height="10" aria-hidden="true">
                <line
                  x1="1" y1="5" x2="29" y2="5"
                  stroke={STYLE[t].stroke}
                  strokeWidth={STYLE[t].width}
                  strokeDasharray={STYLE[t].dash}
                />
              </svg>
              <span>{PAIR_TYPE_JA[t]}</span>
            </li>
          ))}
      </ul>
      <p className="deity-fine">
        中心は{centre.name}。同じ社に並ぶ相手は {graph.neighbours_total} 柱で、
        そのうち {graph.neighbours_shown} 柱を描いている
        {hiddenNeighbours > 0 && (
          <>(残り {hiddenNeighbours} 柱は環に名前が並びきらないので省いた。
            <strong>無いのではない</strong>)</>
        )}
        。外周どうしの細い辺は、相手どうしが同じ社に並ぶこと。
      </p>
    </div>
  );
}
