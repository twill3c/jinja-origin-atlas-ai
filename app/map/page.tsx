import type { Metadata } from "next";
import JinjaMap from "@/components/map/JinjaMap";
import { jp, readBuildReport, readFamilyCounts, readFamilyLabels } from "@/lib/data";

export const metadata: Metadata = {
  title: "地図 | Jinja Origin Atlas AI",
  description: "公開データから生成した神社の位置レイヤー。背景は国土地理院標準地図。",
};

export default function MapPage() {
  const families = { labels: readFamilyLabels(), counts: readFamilyCounts() };
  // 範囲の文はビルド報告から組み立てる。3 都府県版の文を書き込んだまま全国版を出していた(HC-280)
  const report = readBuildReport();
  return (
    <main>
      <h1>神社の分布</h1>
      <p className="lede">
        OpenStreetMap の <code>amenity=place_of_worship</code> かつ <code>religion=shinto</code>{" "}
        を母集団とする位置レイヤー。低ズームでは件数の丸に集約し、拡大すると個別の神社になる。
        系統は Wikidata の祭神・社格と名称規則から決めている。
      </p>
      <JinjaMap families={families} />
      {report && (
        <div className="notice" style={{ marginTop: "1rem" }}>
          公開範囲は全国 {jp(report.chunks)} 都道府県の {jp(report.shrines)} 社。OpenStreetMap の地物{" "}
          {jp(report.dedupe.osm_features)} 件のうち、同じ社を node と way の両方で描いたものなどを一つにまとめている。
        </div>
      )}
    </main>
  );
}
