/** 公開アーティファクトの型。schemas/*.json と対応させる。 */

export type ShrineFeature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: {
    id: string;
    name: string | null;
    prefecture: string | null;
    /** AI 意味分析の対象になっているか。SPEC §59 に従い、位置レイヤーと分離して数える */
    ai: boolean;
  };
};

export type ShrineCollection = {
  type: "FeatureCollection";
  attribution: string;
  features: ShrineFeature[];
};

export type BuildReport = {
  osm_elements_read: number;
  shrines: number;
  with_name: number;
  without_name: number;
  with_osm_wikidata_tag: number;
  dropped: Record<string, number>;
  bytes_geojson: number;
  bytes_catalog: number;
};
