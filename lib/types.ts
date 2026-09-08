/** 公開アーティファクトの型。schemas/*.json と対応させる。
 *
 * **この型は Python 側の `export/build_public.py` が書く JSON との契約である。**
 * 片方を変えたらもう片方が壊れる。壊れても pytest は緑のままなので、
 * 契約は `tests-js/artifacts.test.ts` で出荷物に対して確かめる(HC-190)。
 */

export type ShrineFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: string;
    name: string | null;
    prefecture: string | null;
    family: string;
    /** AI 意味分析の対象になっているか。SPEC §59 に従い、位置レイヤーと分離して数える */
    ai: boolean;
  };
};

export type ShrineCollection = {
  type: "FeatureCollection";
  attribution: string;
  features: ShrineFeature[];
};

export type SignalAgreement = {
  both_known: number;
  agree: number;
  disagree: number;
  rate: number | null;
};

export type Quantiles = {
  min: number;
  p25: number;
  median: number;
  p75: number;
  p95: number;
  max: number;
};

export type ElevationOracle = {
  n: number;
  median_abs_diff_m: number;
  within_1m: number;
  within_5m: number;
  within_10m: number;
  max_abs_diff_m: number;
};

export type BuildReport = {
  shrines: number;
  with_name: number;
  without_name: number;
  with_osm_wikidata_tag: number;
  wikidata_records_with_coord: number;
  matched_auto: number;
  matched_review: number;
  unmatched: number;
  with_deities: number;
  with_rank: number;
  with_inception: number;
  with_parent: number;
  with_ja_wikipedia: number;
  family_counts: Record<string, number>;
  family_basis: Record<string, number>;
  with_elevation: number;
  without_elevation: number;
  with_river_distance: number;
  without_river_distance: number;
  elevation_quantiles: Quantiles | null;
  river_distance_quantiles: Quantiles | null;
  elevation_oracle: ElevationOracle | null;
  signal_agreement: SignalAgreement;
  bytes_geojson: number;
  bytes_catalog: number;
};

/** `BuildReport` に必ず入っているべき数値欄。契約検査が参照する。 */
export const BUILD_REPORT_NUMERIC_KEYS = [
  "shrines",
  "with_name",
  "without_name",
  "with_osm_wikidata_tag",
  "wikidata_records_with_coord",
  "matched_auto",
  "matched_review",
  "unmatched",
  "with_deities",
  "with_rank",
  "with_inception",
  "with_parent",
  "with_ja_wikipedia",
  "with_elevation",
  "without_elevation",
  "with_river_distance",
  "without_river_distance",
  "bytes_geojson",
  "bytes_catalog",
] as const;
