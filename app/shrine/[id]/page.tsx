import type { Metadata } from "next";
import Link from "next/link";
import { jp, readAi, readCatalog, readCatalogIndex } from "@/lib/data";

const BASIS_JA: Record<string, string> = {
  structured: "構造化データ(包括団体)",
  deity: "祭神",
  name: "名称",
  origin_text: "由緒テキスト",
  ai: "AI 推定",
  none: "根拠なし",
};

/** 静的書き出しなので、詳細ページを作るのは属性を持つ神社だけにする。
 *  全件ぶん HTML を作ると出荷物が無用に膨らむ。
 *
 *  **データはモジュール水準で一度だけ読む**(lib/data.ts)。ページごとに読み直すと
 *  1,665 ページ × 3.3 MB を JSON.parse することになり、静的書き出しが十数分に伸びる。 */
function detailed() {
  return readCatalog().filter((s) => s.external_ids.wikidata && s.name.ja);
}

export function generateStaticParams() {
  return detailed().map((s) => ({ id: s.id }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const s = readCatalogIndex().get(id);
  if (!s?.name.ja) return { title: "神社 | Jinja Origin Atlas AI" };
  return {
    title: `${s.name.ja} | Jinja Origin Atlas AI`,
    description: `${s.name.ja}の所在地・祭神・社格・地理情報。公開データに基づく。`,
  };
}

export default async function ShrinePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = readCatalogIndex().get(id);
  if (!s || !s.name.ja || !s.external_ids.wikidata) {
    return (
      <main>
        <h1>見つかりません</h1>
        <p>
          この神社の詳細ページは作られていない。<Link href="/map/">地図</Link>から探すこと。
        </p>
      </main>
    );
  }

  const fam = s.shrine_family;
  const { labels: motifLabels, byId: aiById, shrines: aiAll } = readAi();
  const ai = aiById.get(s.id) ?? null;
  const aiCount = aiAll.length;
  const osmUrl = `https://www.openstreetmap.org/${s.external_ids.osm_type}/${s.external_ids.osm_id}`;

  return (
    <main>
      <h1>{s.name.ja}</h1>
      <p className="lede">
        {s.name.kana ? `${s.name.kana} ／ ` : ""}
        {[s.location.prefecture, s.location.municipality].filter(Boolean).join(" ") || "所在地の詳細タグなし"}
      </p>

      <div className="band band-evidence">
        <h3>A — 公開データで確認できること</h3>
        <div className="scroll-x">
          <table>
            <tbody>
              <tr>
                <th scope="row">座標</th>
                <td>
                  {s.location.lat.toFixed(6)}, {s.location.lon.toFixed(6)}
                </td>
                <td>OpenStreetMap</td>
              </tr>
              <tr>
                <th scope="row">系統</th>
                <td>
                  {fam.label_ja}
                  {fam.alternatives.length > 0 && (
                    <span style={{ color: "var(--ink-mute)", fontSize: "0.85em" }}>
                      {" "}／ 他の候補: {fam.alternatives.join("・")}
                    </span>
                  )}
                </td>
                <td>
                  根拠: {BASIS_JA[fam.basis] ?? fam.basis} ／ 確信度 {fam.confidence.toFixed(2)}
                </td>
              </tr>
              {s.deities && (
                <tr>
                  <th scope="row">祭神</th>
                  <td>{s.deities.map((d) => d.name).join("、")}</td>
                  <td>Wikidata(P825 献呈先)</td>
                </tr>
              )}
              {s.shrine_rank && (
                <tr>
                  <th scope="row">社格</th>
                  <td>{s.shrine_rank.labels.join("、")}</td>
                  <td>Wikidata(P13723)</td>
                </tr>
              )}
              {s.foundation?.structured && (
                <tr>
                  <th scope="row">成立日</th>
                  <td>
                    {s.foundation.structured.year_min === s.foundation.structured.year_max
                      ? `${s.foundation.structured.year_min} 年`
                      : `${s.foundation.structured.year_min}–${s.foundation.structured.year_max} 年`}
                  </td>
                  <td>
                    Wikidata(P571)。<strong>社伝の年代ではない</strong>
                  </td>
                </tr>
              )}
              {s.documented_parents && (
                <tr>
                  <th scope="row">文献上の母院</th>
                  <td>{s.documented_parents.qids.join("、")}</td>
                  <td>Wikidata(P612)。実線で描く関係</td>
                </tr>
              )}
              {s.geography?.elevation_m !== undefined && (
                <tr>
                  <th scope="row">標高</th>
                  <td>{s.geography.elevation_m.toFixed(1)} m</td>
                  <td>国土地理院 標高タイル({s.geography.elevation_source})</td>
                </tr>
              )}
              {s.geography?.nearest_river_distance_m !== undefined && (
                <tr>
                  <th scope="row">最寄り河川</th>
                  <td>
                    {s.geography.nearest_river_name} まで{" "}
                    {Math.round(s.geography.nearest_river_distance_m).toLocaleString("ja-JP")} m
                  </td>
                  <td>国土数値情報 W05。平面直角座標系で計測</td>
                </tr>
              )}
              {s.geography?.nearest_river_note && (
                <tr>
                  <th scope="row">最寄り河川</th>
                  <td>—</td>
                  <td>{s.geography.nearest_river_note}</td>
                </tr>
              )}
              <tr>
                <th scope="row">海岸距離</th>
                <td>—</td>
                <td>V1.0 では測っていない(海岸線データの利用条件のため)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="band band-tradition">
        <h3>B — 社伝・伝承として伝わること</h3>
        <p style={{ margin: 0, color: "var(--ink-mute)" }}>
          伝承年代・由緒の本文は、権利条件を確認したものだけを載せる。この神社については
          まだ取得していない。
        </p>
      </div>

      <div className="band band-ai">
        <h3>C — AI が文章から測ったこと</h3>
        {ai ? (
          <>
            <p style={{ margin: 0, fontSize: "0.9rem" }}>
              由緒モチーフの<strong>相対的な強さ</strong>(全体の中での位置。確率ではない):
            </p>
            <ul style={{ margin: "0.3rem 0 0", fontSize: "0.9rem" }}>
              {Object.entries(ai.motif_percentiles)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 4)
                .map(([k, v]) => (
                  <li key={k}>
                    {motifLabels[k] ?? k} — 全 {aiCount} 件中の上位{" "}
                    {Math.max(1, Math.round((1 - v) * 100))} %
                  </li>
                ))}
            </ul>
            <p style={{ margin: "0.3rem 0 0", fontSize: "0.8rem", color: "var(--ink-mute)" }}>
              生のコサイン類似度は 0.78〜0.88 の狭い帯に収まるので、そのまま並べると
              12 個が同じに見える。ここでは<strong>そのモチーフの分布の中でどこにいるか</strong>を出している。
            </p>
            <p style={{ margin: "0.4rem 0 0", fontSize: "0.85rem", color: "var(--ink-mute)" }}>
              {ai.cluster.id === -1
                ? "どのクラスタにも入らない"
                : `クラスタ ${ai.cluster.id}(番号に歴史学上の意味は無い)`}
              {" ／ "}
              <Link href={`/similar/${s.id}/`}>由緒が似た神社</Link>
              {" ／ "}
              <Link href="/ai-space/">意味空間で見る</Link>
            </p>
            <p style={{ margin: "0.4rem 0 0", fontSize: "0.8rem", color: "var(--ink-mute)" }}>
              解析に使った文章の由来:{" "}
              <a href={ai.source.url} rel="noreferrer" target="_blank">
                {ai.source.title}
              </a>{" "}
              — 日本語版ウィキペディア(版 {ai.source.revid}、{ai.source.license})。
              本文は再配布していない。
            </p>
          </>
        ) : (
          <p style={{ margin: 0, color: "var(--ink-mute)" }}>
            この神社には AI 意味分析が付いていない(由緒の記事が無いか、短すぎる)。
            <Link href="/about-ai/">AI について</Link>
          </p>
        )}
      </div>

      <h2>出典</h2>
      <ul>
        <li>
          <a href={osmUrl} rel="noreferrer" target="_blank">
            OpenStreetMap {s.external_ids.osm_type}/{s.external_ids.osm_id}
          </a>{" "}
          — © OpenStreetMap contributors(ODbL)
        </li>
        {s.external_ids.wikidata && (
          <li>
            <a
              href={`https://www.wikidata.org/wiki/${s.external_ids.wikidata}`}
              rel="noreferrer"
              target="_blank"
            >
              Wikidata {s.external_ids.wikidata}
            </a>{" "}
            — CC0
          </li>
        )}
        {s.geography?.elevation_m !== undefined && (
          <li>
            <a href="https://maps.gsi.go.jp/development/ichiran.html" rel="noreferrer" target="_blank">
              国土地理院 標高タイル
            </a>{" "}
            — 出典:国土地理院ウェブサイト(標高値を復号して利用)
          </li>
        )}
        {s.geography?.nearest_river_distance_m !== undefined && (
          <li>
            <a href="https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html" rel="noreferrer" target="_blank">
              国土数値情報 河川(W05)
            </a>{" "}
            — 出典:国土交通省 国土数値情報ダウンロードサイト(距離を計算して利用)
          </li>
        )}
        {s.ja_wikipedia && (
          <li>
            <a href={s.ja_wikipedia} rel="noreferrer" target="_blank">
              日本語版ウィキペディアの記事
            </a>{" "}
            — CC BY-SA 4.0(本文は再配布していない)
          </li>
        )}
      </ul>

      {s.match && (
        <>
          <h2>名寄せの根拠</h2>
          <p style={{ fontSize: "0.88rem", color: "var(--ink-mute)" }}>
            OpenStreetMap の地物と Wikidata の項目を、距離 {s.match.distance_m.toFixed(0)} m ・
            名称類似度 {s.match.name_similarity.toFixed(2)} で結合した(合計スコア{" "}
            {s.match.score.toFixed(3)}、判定 {s.match.decision})。
            <br />
            この結合には、両者を直接つなぐ ID(OSM の <code>wikidata</code> タグ・Wikidata の
            OSM ID)を<strong>使っていない</strong>。それらは名寄せの精度を測るための照合用に
            取ってある。
          </p>
        </>
      )}

      <p style={{ marginTop: "1.5rem" }}>
        <Link href="/map/">← 地図へ戻る</Link>
      </p>
    </main>
  );
}
