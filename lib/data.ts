import fs from "node:fs";
import path from "node:path";
import type { BuildReport } from "./types";

/**
 * ビルド時に読む公開アーティファクト。
 *
 * **モジュール水準で一度だけ読む。** ページごとに読み直すと、静的書き出しで
 * 1,665 ページ × 3.3 MB を JSON.parse することになり、ビルドが数分から
 * 十数分に伸びる(2026-09-09 実測。143 ページ生成するのに数分かかった)。
 * Vercel のビルド時間には上限があるので、公開時に効いてくる。
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

export type ShrineRecord = {
  id: string;
  name: { ja: string | null; kana: string | null; en: string | null };
  aliases: string[];
  location: { lat: number; lon: number; prefecture: string | null; municipality: string | null };
  external_ids: { osm_type: string; osm_id: number; wikidata?: string; wikipedia?: string | null };
  shrine_family: {
    label: string;
    label_ja: string;
    basis: string;
    confidence: number;
    alternatives: string[];
  };
  deities?: { name: string; wikidata_id: string | null; source_ids: string[] }[];
  shrine_rank?: { labels: string[]; source_ids: string[] };
  foundation?: { structured?: { year_min: number; year_max: number; source_ids: string[] } };
  documented_parents?: { qids: string[]; source_ids: string[] };
  geography?: {
    elevation_m?: number;
    elevation_source?: string;
    nearest_river_distance_m?: number;
    nearest_river_name?: string;
    nearest_river_note?: string;
    coast_distance_m: number | null;
  };
  ja_wikipedia?: string;
  match?: { score: number; distance_m: number; name_similarity: number; decision: string };
  ai?: boolean;
  sources: string[];
};

export type AiRecord = {
  id: string;
  motifs: Record<string, number>;
  motif_percentiles: Record<string, number>;
  cluster: { id: number; probability: number };
  umap: { x: number; y: number };
  source: { title: string; revid: number; url: string; license: string; sections?: string[] };
};

export const readBuildReport = once((): BuildReport | null =>
  readJson<BuildReport>("public", "data", "meta", "build.json"),
);

export const readCatalog = once((): ShrineRecord[] =>
  readJson<{ shrines: ShrineRecord[] }>("public", "data", "catalog", "shrines.min.json")?.shrines ??
  [],
);

export const readCatalogIndex = once((): Map<string, ShrineRecord> =>
  new Map(readCatalog().map((s) => [s.id, s])),
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

export const readAi = once((): {
  labels: Record<string, string>;
  shrines: AiRecord[];
  byId: Map<string, AiRecord>;
} => {
  const d = readJson<{ motif_labels: Record<string, string>; shrines: AiRecord[] }>(
    "public", "data", "ai", "ai.min.json",
  );
  const shrines = d?.shrines ?? [];
  return {
    labels: d?.motif_labels ?? {},
    shrines,
    byId: new Map(shrines.map((x) => [x.id, x])),
  };
});

export const readSimilarity = once((): Record<string, [string, number][]> =>
  readJson<{ neighbors: Record<string, [string, number][]> }>(
    "public", "data", "ai", "similarity.min.json",
  )?.neighbors ?? {},
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
