import fs from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import Link from "next/link";

type Shrine = {
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
  ja_wikipedia?: string;
  match?: { score: number; distance_m: number; name_similarity: number; decision: string };
  sources: string[];
};

const BASIS_JA: Record<string, string> = {
  structured: "構造化データ(包括団体)",
  deity: "祭神",
  name: "名称",
  origin_text: "由緒テキスト",
  ai: "AI 推定",
  none: "根拠なし",
};

function readCatalog(): Shrine[] {
  const p = path.join(process.cwd(), "public", "data", "catalog", "shrines.min.json");
  if (!fs.existsSync(p)) return [];
  return (JSON.parse(fs.readFileSync(p, "utf-8")).shrines ?? []) as Shrine[];
}

/** 静的書き出しなので、詳細ページを作るのは属性を持つ神社だけにする。
 *  全件ぶん HTML を作ると出荷物が無用に膨らむ。 */
function detailed(): Shrine[] {
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
  const s = detailed().find((x) => x.id === id);
  if (!s) return { title: "神社 | Jinja Origin Atlas AI" };
  return {
    title: `${s.name.ja} | Jinja Origin Atlas AI`,
    description: `${s.name.ja}の所在地・祭神・社格・地理情報。公開データに基づく。`,
  };
}

export default async function ShrinePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = detailed().find((x) => x.id === id);
  if (!s) {
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
                  <td>Wikidata(P571)。**社伝の年代ではない**</td>
                </tr>
              )}
              {s.documented_parents && (
                <tr>
                  <th scope="row">文献上の母院</th>
                  <td>{s.documented_parents.qids.join("、")}</td>
                  <td>Wikidata(P612)。実線で描く関係</td>
                </tr>
              )}
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
        <p style={{ margin: 0, color: "var(--ink-mute)" }}>
          この神社にはまだ AI 意味分析が付いていない。
          <Link href="/about-ai/">AI について</Link>
        </p>
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
