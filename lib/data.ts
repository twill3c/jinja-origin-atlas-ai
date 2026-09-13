import fs from "node:fs";
import path from "node:path";
import type { BuildReport } from "./types";

/**
 * ビルド時に読む公開アーティファクト(サーバ側だけで使う)。
 *
 * **モジュール水準で一度だけ読む。** ページごとに読み直すと、静的書き出しで
 * 同じ JSON を何度も JSON.parse することになる(2026-09-09 に 143 ページで数分かかった)。
 *
 * **神社のカタログはここで読まない**(D-06)。神社詳細と類似はクライアント描画になり、
 * 都道府県チャンクを画面が直接引く。型は lib/shrine-types.ts にある。
 */

function readJson<T>(...parts: string[]): T | null {
  const p = path.join(process.cwd(), ...parts);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8")) as T;
}

function once<T>(load: () => T): () => T {
  let cached: { v: T } | null = null;
  return () => {
    if (!cached) cached = { v: load() };
    return cached.v;
  };
}

export const readBuildReport = once((): BuildReport | null =>
  readJson<BuildReport>("public", "data", "meta", "build.json"),
);

export const readFamilyLabels = once((): Record<string, string> =>
  readJson<{ labels: Record<string, string> }>(
    "public", "data", "catalog", "families.min.json",
  )?.labels ?? {},
);

export const readFamilyCounts = once((): Record<string, number> =>
  readJson<{ counts: Record<string, number> }>(
    "public", "data", "catalog", "families.min.json",
  )?.counts ?? {},
);

export type GeoCheck = {
  label: string;
  n: number;
  spearman?: number;
  permutation_p?: number;
  sign_matches?: boolean;
  "significant_at_0.01"?: boolean;
  note?: string;
};

export const readGeoChecks = once((): GeoCheck[] =>
  readJson<{ results: GeoCheck[] }>("data", "reports", "motif_vs_geography.json")?.results ?? [],
);

export type PipelineReport = {
  corpus: number;
  corpus_dropped: Record<string, number>;
  model: string;
  revision: string;
  embedding_dim: number;
  clusters: number;
  noise: number;
  motif_control: {
    control_max: number;
    corpus_median_max: number;
    corpus_min_max: number;
    passes: boolean;
  };
  motif_score_band?: { min: number; max: number; within_doc_spread_median: number };
  truncated_docs: number;
};

export const readPipelineReport = once((): PipelineReport | null =>
  readJson<PipelineReport>("data", "reports", "ai_pipeline.json"),
);

export function jp(n: number): string {
  return n.toLocaleString("ja-JP");
}
