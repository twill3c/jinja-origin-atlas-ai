/**
 * 都道府県チャンク(public/data/shrines/NN.json)の型と、クライアント側の小道具。
 *
 * **node:fs を読む lib/data.ts とは分けてある。** クライアント描画の画面から
 * 読み込めるように、この型ファイルはサーバ専用の依存を持たない。
 */

export type MotifPercentiles = Record<string, number>;

export type SimilarEntry = {
  id: string;
  score: number;
  name: string | null;
  p: string;
  prefecture: string | null;
  family_ja: string;
  top3: string[];
  cluster: number | null;
};

export type ShrineRecord = {
  id: string;
  name: { ja: string | null; kana: string | null; en: string | null };
  aliases: string[];
  location: {
    lat: number;
    lon: number;
    prefecture: string | null;
    municipality: string | null;
    pref_code: string | null;
  };
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
  /** D-08: 名前が社殿・境内の部分を指す語で終わる(本社とは別に数えている) */
  suspected_part?: { suffix: string; note: string };
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
  ai_scores?: {
    motif_percentiles: MotifPercentiles;
    cluster: { id: number; probability: number };
    source: { title: string; revid: number; url: string; license: string };
  };
  similar?: SimilarEntry[];
  sources: string[];
};

export type ChunkDoc = {
  pref_code: string;
  prefecture: string;
  ai_count: number;
  motif_labels: Record<string, string>;
  shrines: ShrineRecord[];
};

/** 類似の相手は県チャンクに入れず、この形で別ファイルに置く(詳細だけ見る人に配らない)。 */
export type SimilarDoc = {
  pref_code: string;
  similar: Record<string, SimilarEntry[]>;
};

export type IndexDoc = {
  ids: Record<string, string>;
  /** D-08: 同じ社を指す地物を統合して消えた ID → 残った ID */
  aliases?: Record<string, string>;
  prefectures: Record<string, { name: string; count: number }>;
  ai_count: number;
  motif_labels: Record<string, string>;
};

/** **順位で**上位を取る(D-05)。同点は鍵の辞書順 —— export/build_public.py の top_motifs と同じ規則。 */
export function topMotifs(p: MotifPercentiles, n = 3): string[] {
  return Object.entries(p)
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .slice(0, n)
    .map(([k]) => k);
}

export function shrineHref(id: string, p?: string | null): string {
  return `/shrine/?id=${encodeURIComponent(id)}${p ? `&p=${p}` : ""}`;
}

export function similarHref(id: string, p?: string | null): string {
  return `/similar/?id=${encodeURIComponent(id)}${p ? `&p=${p}` : ""}`;
}

export function upperPercent(v: number): number {
  return Math.max(1, Math.round((1 - v) * 100));
}
