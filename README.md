# Jinja Origin Atlas AI

日本の神社を、公開情報だけから地図に置く。史実として確認できること、社伝として伝わること、
AI が文章から測ったことを、画面の上で混ぜない。

- 課金経路をひとつも持たない(有料 API・DB サーバ・GPU サーバ・実行時推論なし)
- AI の結果はすべて事前計算し、静的ファイルとして配る
- 権利条件を機械的に検査したテキストにだけ AI を掛ける

## Demo

(未デプロイ)

## Features

| 状態 | 機能 |
|---|---|
| ✅ | 神社位置レイヤー(MapLibre + 国土地理院標準地図、クラスタ表示) |
| ✅ | 権利ゲート(fail-closed、ジャパンサーチ全 18 コードを網羅) |
| ✅ | 国土地理院 DEM からの標高取得(層ごとの配信ズームを実測済み) |
| ✅ | 出典・ライセンス画面、AI 免責画面 |
| ✅ | Wikidata の構造化属性(祭神 P825・社格 P13723・母院 P612)の結合 |
| ✅ | 名寄せ(OSM × Wikidata)。非循環オラクル 825 組で較正 |
| ✅ | 標高(国土地理院 DEM)・最寄り河川距離(国土数値情報 W05)・統計画面 |
| ✅ | Embedding・類似神社 Top20・12 モチーフ・HDBSCAN・UMAP |
| 🚧 | 全国 40,776 件への展開(いまは東京都・京都府・山梨県の 3,152 件) |
| 🚧 | Vercel へのデプロイ |

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
python -m etl.fetch_osm              # 段階 1: 東京都・京都府・山梨県
python -m etl.fetch_osm --all-japan  # 段階 3: 全国(40,776 件)
python -m export.build_geojson       # 公開 GeoJSON / カタログ / ビルドレポート

python -m etl.fetch_wikidata         # 祭神・社格・成立日・母院ほか(9 クエリ)
python -m etl.fetch_elevation        # 国土地理院 DEM(タイルはディスクにキャッシュ)
python -m etl.fetch_rivers           # 国土数値情報 W05
python -m etl.river_distance         # 最寄り河川距離(二経路で照合)
python -m etl.fetch_wikipedia        # 由緒本文(版 ID つき。本文は配らない)
python -m ml.pipeline                # 埋め込み・モチーフ・クラスタ・UMAP・類似
python -m export.build_public        # 結合して公開アーティファクトを作る

python -m quality.calibrate_matching  # 名寄せ閾値の較正(較正半分だけを見る)
python -m quality.motif_vs_geography  # モチーフと地理条件の照合(循環しない)
```

Overpass の公共インスタンスは連続投入で 429 を返す(2026-09-08 実測)。
`etl/fetch_osm.py` は指数バックオフで待ち直す。`OVERPASS_ENDPOINT` で差し替えられる。

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
