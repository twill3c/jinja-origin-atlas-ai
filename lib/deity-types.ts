/* 祭神アーティファクトの型 — `public/data/deity/*.json`。SPEC §7.14。
 *
 * これらは `export/build_deity.py` が書く。**画面は数を自分で計算しない** ——
 * 件数も合否もビルド時に測った値を読むだけにする(文書とコードで数が二重になると、
 * 片方だけが嘘になる)。 */

export type DeityIndex = {
  totals: {
    mentions: number;
    shrines_with_deities: number;
    shrines_total: number;
    deities: number;
  };
  deities: { qid: string; name: string; n: number }[];
};

export type DeityPoint = {
  id: string;
  name: string | null;
  pref: string;
  lat: number;
  lon: number;
};

export type PointsDoc = { shrines: DeityPoint[] };

export type LiftRow = {
  pref: string;
  n: number;
  expected: number;
  lift: number | null;
};

export type DetailDoc = {
  floor: number;
  deities: Record<string, { prefs: LiftRow[]; ids: string[] }>;
};

/** 辺の型。`identity` だけが畳める(SPEC §7.14)。 */
export type PairType = "identity" | "kin" | "partof" | "other" | "unlabeled" | "mixed";

export type NetNode = {
  qid: string;
  name: string;
  n: number;
  x: number;
  y: number;
  center: boolean;
};
export type NetEdge = { a: string; b: string; w: number; type: PairType };

/** 一柱を中心に置いた図。環なので、相手が何柱でも必ず読める。 */
export type EgoGraph = {
  center: string;
  nodes: NetNode[];
  edges: NetEdge[];
  /** 同じ社に並ぶ相手の総数と、図に描いた数(上限で切っている)。 */
  neighbours_total: number;
  neighbours_shown: number;
};

export type NetworkDoc = {
  params: {
    cap: number;
    radius: number;
    digits: number;
    labeled_threshold: number;
  };
  ego: Record<string, EgoGraph>;
  /** 畳んだ図。**変わる祭神のぶんだけ**持つ(同じ図を二度配らない)。 */
  collapsed_ego: Record<string, EgoGraph>;
  collapsed_of: Record<string, string>;
  merged_groups: Record<string, string[]>;
  names: Record<string, string>;
};

export type PairsDoc = {
  threshold: number;
  types: Record<string, string>;
  pairs: {
    a: string;
    a_qid: string;
    b: string;
    b_qid: string;
    type: PairType;
    note: string | null;
    w: number;
  }[];
  unlabeled_at_threshold: { a: string; b: string; w: number }[];
};

export type ReportDoc = {
  g16: {
    threshold: number;
    floor: number;
    hit: number;
    total: number;
    pass: boolean;
    misses_below_floor: number;
    rows: {
      deity: string;
      deity_qid: string;
      head_shrine: string;
      head_pref: string;
      top_pref: string | null;
      top_lift: number | null;
      top_n: number | null;
      hit: boolean;
      head_pref_n: number;
      head_pref_base: number;
      below_floor: boolean;
      /** 総本社の座標(凍結表が持つ検証済みの値。地図のピンに使う)。 */
      lat: number;
      lon: number;
    }[];
  };
  g20: {
    trials: number;
    observed: number;
    mean: number;
    p95: number;
    max: number;
    p_value: number;
    pass: boolean;
  };
  g17: {
    rule: string;
    k: number;
    correct: number;
    precision: number;
    threshold: number;
    pass: boolean;
    predicted: { a: string; b: string; jaccard: number; w: number; truth: string }[];
    missed: { a: string; b: string; jaccard: number; w: number }[];
  };
  pairs: {
    labeled: number;
    threshold: number;
    unlabeled_at_threshold: number;
    by_type: Record<string, number>;
  };
  network: {
    cap: number;
    deities_with_ego: number;
    deities_total: number;
    merged_groups: number;
    merged_deities: number;
    pairs_total: number;
    by_type: Record<string, number>;
  };
};

/** 辺の型の日本語。**画面の記号は仕様の述語に対応していなければならない**(HC-079)。 */
export const PAIR_TYPE_JA: Record<PairType, string> = {
  identity: "同一視",
  kin: "親族",
  partof: "総称と構成神",
  other: "その他の相殿",
  unlabeled: "未分類",
  mixed: "混在",
};
