# Jinja Origin Atlas AI

日本の神社を、公開情報だけから地図に置く。史実として確認できること、社伝として伝わること、
AI が文章から測ったことを、画面の上で混ぜない。

- 課金経路をひとつも持たない(有料 API・DB サーバ・GPU サーバ・実行時推論なし)
- AI の結果はすべて事前計算し、静的ファイルとして配る
- 権利条件を機械的に検査したテキストにだけ AI を掛ける

## Demo

**https://jinja-origin-atlas-ai.vercel.app**

app-menu(フリートの玄関口)にも掲載: https://app-menu-amber.vercel.app/

## Features

| 状態 | 機能 |
|---|---|
| ✅ | 神社位置レイヤー(MapLibre + 国土地理院標準地図、クラスタ表示) |
| ✅ | 権利ゲート(fail-closed、ジャパンサーチ全 18 コードを網羅) |
| ✅ | 国土地理院 DEM からの標高取得(層ごとの配信ズームを実測済み) |
| ✅ | 出典・ライセンス画面、AI 免責画面 |
| ✅ | **史実と AI を画面の上で混ぜない**検査(G-13): 神社詳細で公開データと AI の意味分析が別の見出しの下にあることを実ブラウザで数え、わざと混ぜた陽性対照 3 通りで働くことを確かめる |
| ✅ | Wikidata の構造化属性(祭神 P825・社格 P13723・母院 P612)の結合 |
| ✅ | 名寄せ(OSM × Wikidata)。**一対一**。非循環オラクル 4,975 組を較正と取り置きに割って検証(取り置き 適合率 0.9928 / 再現率 0.9512) |
| ✅ | 標高(国土地理院 DEM)・最寄り河川距離(国土数値情報 W05)・統計画面 |
| ✅ | Embedding・類似神社 Top20・12 モチーフ・HDBSCAN・UMAP(**記事単位**で計算。同じ記事を持つ神社を類似に出さない) |
| ✅ | **全国 47 都道府県 40,325 社**の位置・属性・系統(県ごとのチャンク配信 + クライアント描画。OSM 地物 40,792 から同じ社の重複 467 を統合) |
| ✅ | 全国の標高 40,787 件・最寄り河川距離 40,652 件(島嶼部など 10 km 超の 140 件は理由つきで空欄) |
| ✅ | 全国の AI 由緒分析 **3,184 記事 / 3,186 社**(ja.wikipedia。120 字未満の 147 記事は理由つきで除外) |

## Architecture

```text
公開データ源 → Python ETL → 権利ゲート → 名寄せ → 地理特徴量 / AI
                                                        ↓
                              静的 JSON / GeoJSON → Next.js(静的書き出し)
```

Vercel 上で PyTorch を動かさない。ビルドで作るのは静的ファイルだけで、
serverless function をひとつも生成しない(`output: 'export'`)。

## Data Sources

`/sources` に全部書いてある。要点だけ:

| 源 | 用途 | ライセンス |
|---|---|---|
| OpenStreetMap | 神社位置・名称 | ODbL |
| Wikidata | 祭神 P825 / 社格 P13723 / 成立日 P571 / 母院 P612 | CC0 |
| ジャパンサーチ | 由緒資料への導線 | レコードごと |
| 日本語版ウィキペディア | 由緒テキストの意味解析 | CC BY-SA(本文は再配布しない) |
| 国土地理院 | 背景地図・標高 | コンテンツ利用規約 |
| 国土数値情報 | 河川 W05 / 行政区域 N03 | PDL1.0 基本 |

## AI

`/about-ai` を読むこと。要点:

- クラスタ番号に歴史学上の系統の意味は無い
- スコアは史実の確率ではない
- AI の類似度から勧請関係を推論しない
- 文献で確認できる分祀関係は**実線**、AI の意味類似は**点線**で描く

## Setup

```bash
# Node
npm install

# Python(この機の system python は 3.14 だが、本プロジェクトは >=3.11,<3.14)
uv venv --python 3.12
uv sync --group dev
```

## ETL

```bash
python -m etl.fetch_osm                                   # 段階 1: 東京都・京都府・山梨県
python -m etl.fetch_osm --all-prefectures --skip-existing  # 段階 3: 47 都道府県を 1 県ずつ
python -m export.build_geojson       # 県の帰属つき OSM カタログ(data/interim/)と GeoJSON

python -m etl.fetch_wikidata         # 祭神・社格・成立日・母院ほか(9 クエリ)
python -m etl.fetch_elevation        # 国土地理院 DEM(タイルはディスクにキャッシュ)
python -m etl.fetch_rivers --all     # 国土数値情報 W05(47 都道府県)
python -m etl.river_distance         # 最寄り河川距離(二経路で照合)
python -m etl.fetch_wikipedia        # 由緒本文(版 ID つき。本文は配らない)
python -m ml.pipeline                # 埋め込み・モチーフ・クラスタ・UMAP・類似(記事単位・D-07)
python -m export.build_public        # 結合 → 都道府県チャンク + 索引(D-06)

python -m quality.calibrate_matching  # 名寄せ閾値の較正(較正半分だけを見る)
python -m quality.motif_vs_geography  # モチーフと地理条件の照合(循環しない)
```

Overpass の公共インスタンスは連続投入で 429 を返す(2026-09-08 実測)。
`etl/fetch_osm.py` は指数バックオフで待ち直す。`OVERPASS_ENDPOINT` で差し替えられる。

**県ごとに取る理由**(D-06): OSM の `addr:province` は 3 都府県で 162/3,152 件にしか
付いていなかった。県別に問い合わせれば、県の帰属は取得の経路からそのまま決まる。
県境の神社は二つの県に返るので、最初の県に帰属させて重複として数える。

**同じ社を指す OSM 地物は一つにまとめる**(D-08)。一つの社が node と way の両方で描かれていることが多く、
そのまま数えると二度数える。名前が同じで 150 m 以内なら 1 社にする(両方が別の Wikidata 項目に結合されて
いれば別社として残す)。統合で消えた ID の URL は、索引の `aliases` で残った神社を開く。
本殿・拝殿などの**社の部分の名前は統合しない**(検算できないため)。印だけ付ける。
名寄せは**一対一**で、同点は古い Wikidata 項目を先にする(後から作られた重複の項目に取られないため)。

**AI は神社ではなく記事を単位に計算する**(D-07)。名寄せで神門や手水舎、同じ社の node と way が
一つの Wikidata 項目に結合されるので、同じ記事を持つ神社がある(全国で 151 記事 / 332 社)。
神社単位で埋め込むと類似の 1 位がただの自己一致になる —— 3 都府県版では 701 件中 71 件がそうだった。
埋め込みは**文書単位で保存**する(`data/processed/embeddings/origin_e5_store/`)。記事を足しても
既存の分は作り直さず、止まっても保存済みから再開する。

**全カタログは配らない**(D-06)。全国では 33.7 MB になる。配るのは都道府県チャンク
`public/data/shrines/NN.json` と索引 `public/data/shrines/index.json`、
それに類似の相手だけを集めた `public/data/similar/NN.json`。
**類似を県チャンクに同居させない** —— 東京都で測ると欄の 52.6% を占め、詳細を見るだけの人に
要らないものを配ることになる(分離で 3.99 MB → 1.97 MB)。
全カタログは検査と下流の ETL のために `data/interim/catalog_full.json` に置く。

## 月次のデータ更新(D-09)

`.github/workflows/monthly-data.yml` が**毎月 1 日 02:23 UTC**(日本時間 11:23。公共の Overpass が混む欧州の昼を避ける)に走り、公開データを作り直して
**PR を開く**。main へは直接入れない —— **マージしたときだけ本番に出る**。PR の本文に神社・自動結合・AI・標高・
河川距離の前後と、件数の変わった県が並ぶので、急な増減が無いか見てからマージすること。

- 手動で起動するときは GitHub の Actions 画面で `monthly-data` → **Run workflow**
- 標高と河川距離は `data/state/geo_state.jsonl` の前回値を再利用し、新しい・動いた地物だけ測る
  (地理院タイル約 2.8 万枚・W05 約 1 GB を毎月取り直さないため)
- **公開リポジトリの定期実行は、60 日活動が無いと GitHub が自動で止める。** 数か月マージが無いときは
  Actions 画面で止まっていないか確かめること
- 手元で同じことをするときは、ワークフローの `run:` を上から順に実行する
- **手動で起動するのも欧州の深夜(日本時間の昼ごろ)にする。** 日本時間 20 時の起動では公共の Overpass が 504 を 23 分返し続けて落ちた

## Development

```bash
npm run dev                 # 開発サーバ
npm run verify              # 型検査 → vitest → 出荷ビルド
node harness/smoke.mjs      # 実ブラウザ検品(out/ を配信して実際に開く)
node harness/smoke.mjs --shot

pytest -q                   # 単体・結合(外部ネットワークは除外)
pytest -q -m network        # 外部に触れる検算(GSI DEM の既知点など)
```

## Deployment

```bash
npm run build          # prebuild で public/data/meta/stamp.json を作る
node harness/smoke.mjs # out/ を配信して実ブラウザで確かめる
vercel deploy --prod --yes --scope twill3c-8670s-projects
node harness/live.mjs https://<本番ホスト>
```

**`main` への push はそのまま本番に出る**(Vercel の Git 連携。2026-09-14 に確認)。
CLI のデプロイは連携が使えないときの手段で、送る前に本番の刻印を引いて、既に一致していれば送らない。

**`.vercelignore` を先に書いてある。** 送る中身を測ると `data/raw` 199MB /
`node_modules` 461MB / `out` 72MB あり、そのまま送ると無料枠のファイル数上限
(5,000 件/24h)に当たる。除外後は約 9MB。
**`--archive=tgz` は `.vercelignore` をローカルで適用しない**ので使わない。

**`harness/live.mjs` は最初に刻印を照合し、合わなければ他を一切見ずに止める。**
本番検品は「健やかか」しか答えず、「新しいか」は別の仕掛けが要る。デプロイが
上限で拒否されても本番は健やかなままなので、健やかさの項目をいくら増やしても
反映の有無は分からない —— むしろ「全部緑」という誤った安心が出る。

刻印は**改行を LF に揃えてから**測っている。この機は `core.autocrlf=true` なので、
生のバイト列で測ると同じ内容でも手元と本番で必ず食い違う。

## Data Caveats

- **伝承年代と史料確認年代は別物である。** 「創建 660 年」と一行で書かない
- **神社名だけでは系統を決められない。** 同名の別系統、改称、合祀、復祀がある
- **由緒の再利用可能なテキストはごく少ない。** ジャパンサーチで「神社 AND 由緒」は
  1,892 件だが、先頭 100 件で「再利用可な権利コード かつ 100 字以上」は 5 件だった(2026-09-08 実測)
- **現代語の由緒説明を埋め込むと、現代の記述スタイルがクラスタに影響しうる**
- **AI の類似度は系譜関係ではない**

## Licenses

- コード: MIT(`LICENSE`)
- データ: `LICENSE-DATA.md` を読むこと。OSM 由来のデータは ODbL の条件を継承する

## Contributing

誤りの報告は GitHub Issues へ。神社 ID・項目・現在値・提案値・根拠 URL を書くこと。
