import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { jp, readBuildReport } from "@/lib/data";

export const metadata: Metadata = {
  title: "統計 | Jinja Origin Atlas AI",
  description: "ビルドごとのデータ品質指標。",
};

function readFamilyLabels(): Record<string, string> {
  const p = path.join(process.cwd(), "public", "data", "catalog", "families.min.json");
  if (!fs.existsSync(p)) return {};
  return JSON.parse(fs.readFileSync(p, "utf-8")).labels ?? {};
}

const BASIS_JA: Record<string, string> = {
  structured: "構造化データ",
  deity: "祭神",
  name: "名称",
  origin_text: "由緒テキスト",
  ai: "AI 推定",
  none: "決められなかった",
};

export default function AnalyticsPage() {
  const r = readBuildReport();
  const labels = readFamilyLabels();

  if (!r) {
    return (
      <main>
        <h1>統計</h1>
        <p className="notice">公開データがまだ生成されていない。</p>
      </main>
    );
  }

  const families = Object.entries(r.family_counts).sort((a, b) => b[1] - a[1]);
  const agreement = r.signal_agreement;

  return (
    <main>
      <h1>統計</h1>
      <p className="lede">すべてビルド時の実測値。仕様書に件数を固定しない(RULE-09)。</p>

      <h2>データの量</h2>
      <div className="scroll-x">
        <table>
          <tbody>
            <tr><th scope="row">神社レコード</th><td>{jp(r.shrines)}</td><td>東京都・京都府・山梨県</td></tr>
            <tr><th scope="row">名称タグあり</th><td>{jp(r.with_name)}</td><td>無い {jp(r.without_name)} 件も地図には出す</td></tr>
            <tr><th scope="row">Wikidata(日本・座標あり)</th><td>{jp(r.wikidata_records_with_coord)}</td><td>名寄せの相手</td></tr>
          </tbody>
        </table>
      </div>

      <h2>名寄せ</h2>
      <div className="scroll-x">
        <table>
          <tbody>
            <tr><th scope="row">自動結合</th><td>{jp(r.matched_auto)}</td><td>スコア 0.60 以上</td></tr>
            <tr><th scope="row">要確認</th><td>{jp(r.matched_review)}</td><td>0.50–0.59。属性は結合していない</td></tr>
            <tr><th scope="row">結合せず</th><td>{jp(r.unmatched)}</td><td>相手が見つからない</td></tr>
            <tr>
              <th scope="row">照合用の直リンク</th>
              <td>{jp(r.with_osm_wikidata_tag)}</td>
              <td>OSM 側の <code>wikidata</code> タグ。<strong>名寄せの入力には使っていない</strong></td>
            </tr>
          </tbody>
        </table>
      </div>

      <h2>結合できた属性</h2>
      <div className="scroll-x">
        <table>
          <tbody>
            <tr><th scope="row">祭神(P825)</th><td>{jp(r.with_deities)}</td></tr>
            <tr><th scope="row">社格(P13723)</th><td>{jp(r.with_rank)}</td></tr>
            <tr><th scope="row">成立日(P571)</th><td>{jp(r.with_inception)}</td></tr>
            <tr><th scope="row">文献上の母院(P612)</th><td>{jp(r.with_parent)}</td></tr>
            <tr><th scope="row">日本語版ウィキペディア記事</th><td>{jp(r.with_ja_wikipedia)}</td></tr>
          </tbody>
        </table>
      </div>

      <h2>系統の内訳</h2>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th scope="col">系統</th>
              <th scope="col">件数</th>
              <th scope="col">割合</th>
            </tr>
          </thead>
          <tbody>
            {families.map(([key, n]) => (
              <tr key={key}>
                <th scope="row">{labels[key] ?? key}</th>
                <td>{jp(n)}</td>
                <td>{((n / r.shrines) * 100).toFixed(1)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>何を根拠に決めたか</h2>
      <div className="scroll-x">
        <table>
          <tbody>
            {Object.entries(r.family_basis)
              .sort((a, b) => b[1] - a[1])
              .map(([key, n]) => (
                <tr key={key}>
                  <th scope="row">{BASIS_JA[key] ?? key}</th>
                  <td>{jp(n)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
        優先順位は 構造化データ → 祭神 → 名称 → 由緒 → AI 推定。上位が決めたら下位で上書きしない。
      </p>

      <h2>二つの独立な手がかりの一致</h2>
      <p>
        祭神(Wikidata P825)から決めた系統と、名称の規則から決めた系統は、互いを参照していない。
        両方が決まった <strong>{jp(agreement.both_known)}</strong> 件のうち{" "}
        <strong>{jp(agreement.agree)}</strong> 件が一致した(
        {agreement.rate === null ? "—" : `${(agreement.rate * 100).toFixed(2)} %`})。
      </p>
      <p style={{ fontSize: "0.9rem" }}>
        食い違った {jp(agreement.disagree)} 件は捨てずに残してある。
        中身を読むと、いずれも実在の合祀だった —— 八坂と名乗る社に八幡神が、
        稲荷と名乗る社に白山の神が祀られている、といった例である。
        <strong>率だけを見ず、残りの数件を読むことに意味がある。</strong>
        実際、この照合を最初に走らせたときは 3 件が分類器の欠陥で、直したうえでの数字がこれである。
      </p>

      <h2>地理条件</h2>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th scope="col">項目</th>
              <th scope="col">付いた件数</th>
              <th scope="col">最小</th>
              <th scope="col">中央</th>
              <th scope="col">75%</th>
              <th scope="col">95%</th>
              <th scope="col">最大</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">標高(m)</th>
              <td>{jp(r.with_elevation)}</td>
              {r.elevation_quantiles ? (
                <>
                  <td>{r.elevation_quantiles.min}</td>
                  <td>{r.elevation_quantiles.median}</td>
                  <td>{r.elevation_quantiles.p75}</td>
                  <td>{r.elevation_quantiles.p95}</td>
                  <td>{r.elevation_quantiles.max}</td>
                </>
              ) : (
                <td colSpan={5}>—</td>
              )}
            </tr>
            <tr>
              <th scope="row">最寄り河川距離(m)</th>
              <td>{jp(r.with_river_distance)}</td>
              {r.river_distance_quantiles ? (
                <>
                  <td>{r.river_distance_quantiles.min}</td>
                  <td>{r.river_distance_quantiles.median}</td>
                  <td>{r.river_distance_quantiles.p75}</td>
                  <td>{r.river_distance_quantiles.p95}</td>
                  <td>{r.river_distance_quantiles.max}</td>
                </>
              ) : (
                <td colSpan={5}>—</td>
              )}
            </tr>
          </tbody>
        </table>
      </div>
      <p style={{ fontSize: "0.9rem" }}>
        標高は国土地理院の標高タイルから求めた。河川距離は国土数値情報 W05 を
        都道府県ごとの平面直角座標系へ投影して測っている(緯度経度のままでは測らない)。
        <strong>
          河川距離が付かなかった {jp(r.without_river_distance)} 件は島嶼部で、
          W05 に近くの河川が無い。
        </strong>
        本土の川までの距離を書くと「近くに川がある」という嘘になるので、空欄にしてある。
      </p>
      <p style={{ fontSize: "0.9rem" }}>
        海岸距離は V1.0 では測っていない。国土数値情報の海岸線(C23)の公開ページに
        非商用の旨の記載があり、再配布する派生データに条件を持ち込むためである。
      </p>

      {r.elevation_oracle && (
        <>
          <h2>標高の裏づけ</h2>
          <p>
            OpenStreetMap の投稿者が記録した標高(<code>ele</code> タグ)と突き合わせた。
            この値は標高の計算には使っていないので、一致は循環しない。
          </p>
          <div className="scroll-x">
            <table>
              <tbody>
                <tr><th scope="row">突き合わせられた件数</th><td>{jp(r.elevation_oracle.n)}</td></tr>
                <tr><th scope="row">差の中央値</th><td>{r.elevation_oracle.median_abs_diff_m} m</td></tr>
                <tr><th scope="row">1 m 以内</th><td>{jp(r.elevation_oracle.within_1m)}</td></tr>
                <tr><th scope="row">10 m 以内</th><td>{jp(r.elevation_oracle.within_10m)}</td></tr>
                <tr><th scope="row">最大の差</th><td>{r.elevation_oracle.max_abs_diff_m} m</td></tr>
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>出荷ファイルの大きさ</h2>
      <div className="scroll-x">
        <table>
          <tbody>
            <tr><th scope="row">GeoJSON(非圧縮)</th><td>{jp(Math.round(r.bytes_geojson / 1024))} KB</td></tr>
            <tr><th scope="row">カタログ(非圧縮)</th><td>{jp(Math.round(r.bytes_catalog / 1024))} KB</td></tr>
          </tbody>
        </table>
      </div>

      <h2>まだ測っていないもの</h2>
      <ul>
        <li>海岸距離(F-15。C23 の利用条件のため V1.1 送り)</li>
        <li>創建時代別の件数(成立日を持つのが {jp(r.with_inception)} 件しかない)</li>
        <li>AI クラスタの分布(コーパスの構築が済んでいない)</li>
      </ul>
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
        測っていない欄は空欄のままにする。仮の数値を置かない。
      </p>
    </main>
  );
}
