import type { Metadata } from "next";
import JinjaMap from "@/components/map/JinjaMap";
import { readFamilyCounts, readFamilyLabels } from "@/lib/data";

export const metadata: Metadata = {
  title: "地図 | Jinja Origin Atlas AI",
  description: "公開データから生成した神社の位置レイヤー。背景は国土地理院標準地図。",
};

export default function MapPage() {
  const families = { labels: readFamilyLabels(), counts: readFamilyCounts() };
  return (
    <main>
      <h1>神社の分布</h1>
      <p className="lede">
        OpenStreetMap の <code>amenity=place_of_worship</code> かつ <code>religion=shinto</code>{" "}
        を母集団とする位置レイヤー。低ズームでは件数の丸に集約し、拡大すると個別の神社になる。
        系統は Wikidata の祭神・社格と名称規則から決めている。
      </p>
      <JinjaMap families={families} />
      <div className="notice" style={{ marginTop: "1rem" }}>
        現在の公開範囲は東京都・京都府・山梨県の 3 都府県(仕様書 §66 の段階 1)。
        全国 40,776 件の取得は後続の実装で行う。
      </div>
    </main>
  );
}
