import Link from "next/link";
import { jp, readBuildReport } from "@/lib/data";

export default function Home() {
  const report = readBuildReport();

  return (
    <main>
      <h1>Jinja Origin Atlas AI</h1>
      <p className="lede">
        日本の神社を、公開情報だけから地図に置く。
        史実として確認できること、社伝として伝わること、AI が文章から測ったことを、
        画面の上で混ぜない。
      </p>

      <h2>いま出せているもの</h2>
      {report ? (
        <div className="scroll-x">
          <table>
            <caption style={{ captionSide: "bottom", fontSize: "0.8rem", color: "var(--ink-mute)", textAlign: "left", paddingTop: "0.4rem" }}>
              ビルド時の実測値。仕様書に件数を固定しない(RULE-09)。
            </caption>
            <tbody>
              <tr>
                <th scope="row">神社位置(公開中)</th>
                <td>{jp(report.shrines)} 件</td>
                <td>東京都・京都府・山梨県</td>
              </tr>
              <tr>
                <th scope="row">うち名称タグあり</th>
                <td>{jp(report.with_name)} 件</td>
                <td>名称の無い {jp(report.without_name)} 件も地図には出す</td>
              </tr>
              <tr>
                <th scope="row">AI 由緒分析つき</th>
                <td>0 件</td>
                <td>後続の実装で結合する</td>
              </tr>
              <tr>
                <th scope="row">全国の母集団(実測)</th>
                <td>40,776 件</td>
                <td>2026-09-08 に Overpass で計数</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : (
        <p className="notice">公開データがまだ生成されていない。<code>python -m export.build_geojson</code> を実行する。</p>
      )}

      <p style={{ marginTop: "1rem" }}>
        <Link href="/map/">地図を開く →</Link>
      </p>

      <h2>三つの層を混ぜない</h2>
      <div className="band band-evidence">
        <h3>A — 公開史料・構造化データで確認できること</h3>
        <p style={{ margin: 0 }}>
          所在地、祭神、社格、文献上の分祀関係。出典を属性ごとに表示する。
        </p>
      </div>
      <div className="band band-tradition">
        <h3>B — 社伝・伝承として伝わること</h3>
        <p style={{ margin: 0 }}>
          伝承年代は史料確認年代と別の欄に置く。「創建 660 年」とは書かない。
        </p>
      </div>
      <div className="band band-ai">
        <h3>C — AI が文章から測ったこと</h3>
        <p style={{ margin: 0 }}>
          意味的な関連度であって、史実の確からしさでも、神社どうしの実際の系譜関係でもない。
          <Link href="/about-ai/">AI について</Link>
        </p>
      </div>

      <h2>実測して分かったこと</h2>
      <ul>
        <li>
          全国の神社(OSM の <code>religion=shinto</code>)は <strong>40,776 件</strong>。
          §29 の PMTiles 移行閾値 50,000 を下回るので GeoJSON で始められる
        </li>
        <li>
          祭神の構造化項目は <strong>P825「献呈先」11,888 件</strong>。
          仕様の想定候補 P1049 では 1 件しか無かった
        </li>
        <li>
          社格 <strong>P13723 は 7,936 件</strong>あり、仕様書に無い資産だった
          (式内小社 4,598 / 村社 1,907 / 郷社 948 ほか)
        </li>
        <li>
          <strong>権利条件の明確な由緒本文はほとんど無い。</strong>
          ジャパンサーチで「神社 AND 由緒」は 1,892 件だが、
          先頭 100 件で「再利用可 かつ 100 字以上」は 5 件だった
        </li>
      </ul>

      <h2>課金経路をひとつも持たない</h2>
      <p>
        有料 API・データベースサーバ・GPU サーバを使わない。AI の結果はすべて事前計算し、
        静的ファイルとして配る。地図の描画とデータの読み込みはブラウザの中で完結する。
      </p>
    </main>
  );
}
