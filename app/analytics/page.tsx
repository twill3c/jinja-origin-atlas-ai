import type { Metadata } from "next";
import { jp, readBuildReport } from "@/lib/data";

export const metadata: Metadata = {
  title: "統計 | Jinja Origin Atlas AI",
  description: "ビルドごとのデータ品質指標。",
};

export default function AnalyticsPage() {
  const r = readBuildReport();

  return (
    <main>
      <h1>統計</h1>
      <p className="lede">
        すべてビルド時の実測値。仕様書に件数を固定しない(RULE-09)。
      </p>

      <h2>データ品質指標</h2>
      {r ? (
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th scope="col">項目</th>
                <th scope="col">値</th>
              </tr>
            </thead>
            <tbody>
              <tr><th scope="row">読み込んだ OSM 要素</th><td>{jp(r.osm_elements_read)}</td></tr>
              <tr><th scope="row">神社レコード</th><td>{jp(r.shrines)}</td></tr>
              <tr><th scope="row">名称タグあり</th><td>{jp(r.with_name)}</td></tr>
              <tr><th scope="row">名称タグなし</th><td>{jp(r.without_name)}</td></tr>
              <tr>
                <th scope="row">OSM 側に wikidata タグあり</th>
                <td>
                  {jp(r.with_osm_wikidata_tag)}
                  <br />
                  <span style={{ fontSize: "0.8rem", color: "var(--ink-mute)" }}>
                    名寄せの照合用。マッチャーの入力には使わない
                  </span>
                </td>
              </tr>
              {Object.entries(r.dropped).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">落とした要素 — {k}</th>
                  <td>{jp(v)}</td>
                </tr>
              ))}
              <tr><th scope="row">GeoJSON(非圧縮)</th><td>{jp(Math.round(r.bytes_geojson / 1024))} KB</td></tr>
              <tr><th scope="row">カタログ(非圧縮)</th><td>{jp(Math.round(r.bytes_catalog / 1024))} KB</td></tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="notice">公開データがまだ生成されていない。</p>
      )}

      <h2>まだ測っていないもの</h2>
      <ul>
        <li>系統別・創建時代別の件数(Wikidata の結合が済んでいない)</li>
        <li>標高・河川距離の分布(地理特徴量の計算が済んでいない)</li>
        <li>AI クラスタの分布(コーパスの構築が済んでいない)</li>
      </ul>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
        測っていない欄は空欄のままにする。仮の数値を置かない。
      </p>
    </main>
  );
}
