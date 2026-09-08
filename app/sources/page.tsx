import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "出典・ライセンス | Jinja Origin Atlas AI",
  description: "使用している公開データ源と、それぞれの権利条件。",
};

type Row = {
  name: string;
  url: string;
  use: string;
  license: string;
  note?: string;
};

const SOURCES: Row[] = [
  {
    name: "OpenStreetMap",
    url: "https://www.openstreetmap.org/copyright",
    use: "全国の神社位置・名称",
    license: "ODbL",
    note: "地図と本ページに © OpenStreetMap contributors を常時表示する。派生データベースを配る場合は ODbL の条件を継承する",
  },
  {
    name: "Wikidata",
    url: "https://www.wikidata.org/wiki/Wikidata:Licensing",
    use: "祭神(P825)・社格(P13723)・成立日(P571)・母院(P612)・読み仮名・別名",
    license: "CC0",
  },
  {
    name: "ジャパンサーチ",
    url: "https://jpsearch.go.jp/policy",
    use: "由緒資料・文化財メタデータへの導線",
    license: "レコードごとの利用条件に従う",
    note: "AI 本文として使うのは cc0 / pdm / ccby のみ。権利コードが無いレコードは使わない",
  },
  {
    name: "日本語版ウィキペディア",
    url: "https://ja.wikipedia.org/wiki/Wikipedia:ウィキペディアを二次利用する",
    use: "由緒テキストの意味解析(埋め込み)",
    license: "CC BY-SA 4.0",
    note: "本文と埋め込みベクトルは配布しない。配るのは数値スコアだけで、由来した記事の帰属を神社ごとに表示する",
  },
  {
    name: "国土地理院",
    url: "https://maps.gsi.go.jp/development/ichiran.html",
    use: "背景地図・標高(DEM)",
    license: "コンテンツ利用規約 / PDL1.0 基本",
    note: "加工した場合は加工の旨を明示する",
  },
  {
    name: "国土交通省 国土数値情報",
    url: "https://nlftp.mlit.go.jp/ksj/other/agreement.html",
    use: "河川(W05)・行政区域(N03)",
    license: "PDL1.0 基本・データごとに個別確認",
    note: "海岸線 C23 は公開ページ上に非商用の旨の記載があるため V1.0 では採用しない",
  },
];

export default function SourcesPage() {
  return (
    <main>
      <h1>出典・ライセンス</h1>
      <p className="lede">
        このサイトが使っている公開データと、それぞれの権利条件。
        「検索できる」「閲覧できる」ことと「学習用本文として再利用できる」ことは別に扱う。
      </p>

      <h2>データ源</h2>
      <div className="scroll-x">
        <table>
          <thead>
            <tr>
              <th scope="col">源</th>
              <th scope="col">用途</th>
              <th scope="col">権利条件</th>
              <th scope="col">扱い</th>
            </tr>
          </thead>
          <tbody>
            {SOURCES.map((s) => (
              <tr key={s.name}>
                <th scope="row">
                  <a href={s.url} rel="noreferrer" target="_blank">
                    {s.name}
                  </a>
                </th>
                <td>{s.use}</td>
                <td>{s.license}</td>
                <td>{s.note ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>コード</h2>
      <p>MIT License。</p>

      <h2>OpenStreetMap</h2>
      <p>
        © OpenStreetMap contributors — ODbL。
        <br />
        <a href="https://www.openstreetmap.org/copyright" rel="noreferrer" target="_blank">
          https://www.openstreetmap.org/copyright
        </a>
      </p>

      <h2>権利ゲートの方針</h2>
      <ul>
        <li>公開されていることは、AI の学習・埋め込みに使ってよいことを意味しない</li>
        <li>権利コードがコード表に無い、または欠落しているレコードは<strong>使わない</strong>(fail-closed)</li>
        <li>CC BY-SA の本文は、意味解析の入力にはするが、本文も埋め込みベクトルも配布しない</li>
      </ul>
    </main>
  );
}
