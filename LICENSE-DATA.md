# データのライセンス

コードのライセンス(MIT)は `LICENSE` にある。**このファイルはデータの話である。**

## レイヤーを分けて置く理由

OSM 由来のデータと、それ以外の出所のデータを、同じファイルに混ぜていない。

```text
public/data/osm/       ← OpenStreetMap 由来。ODbL
public/data/catalog/   ← Wikidata / ジャパンサーチ由来。CC0 ほか
public/data/ai/        ← 埋め込みから計算した数値スコア
```

混ぜて 1 つのデータベースを作ると、その派生データベース全体に ODbL の条件が及びうる。
分けたまま配り、結合はブラウザ側で行う。

## OpenStreetMap — ODbL

```text
© OpenStreetMap contributors
https://www.openstreetmap.org/copyright
```

- `public/data/osm/shrines.min.geojson` は OSM のデータから作った派生物である
- 地図画面と `/sources` に出典を常時表示する
- この派生データを再配布する場合、ODbL の条件(表示・継承)を引き継ぐ

## Wikidata — CC0

```text
https://www.wikidata.org/wiki/Wikidata:Licensing
```

祭神(P825)・社格(P13723)・成立日(P571)・母院(P612)・読み仮名・別名を使う。
CC0 なので、そのまま再配布できる。

## ジャパンサーチ — レコードごとの利用条件

```text
https://jpsearch.go.jp/policy
```

**「検索できる」「閲覧できる」ことと「学習用本文として再利用できる」ことは別である。**

AI の本文として使うのは、`common.contentsRightsType` が次のいずれかのレコードだけ:

```text
cc0
pdm
ccby
```

**コード表に無い値・欠落は使わない**(fail-closed)。判定は `etl/rights_gate.py`。
実測では 100 件中 33 件が権利コードの欄そのものを持っていなかった(2026-09-08)。

## 日本語版ウィキペディア — CC BY-SA 4.0

由緒テキストの意味解析(埋め込みの計算)に使う。**次の三つを守る。**

1. **本文を公開アーティファクトに含めない**
2. **埋め込みベクトルも含めない。** 配るのは数値スコアだけ
   (モチーフスコア / 類似度 / クラスタ番号 / UMAP 座標)
3. 各神社の詳細画面に、由来した記事の**帰属・ライセンス・版**を表示する

仕様書 V1.0 §5.4 は `ccbysa` を AI 本文コーパスから既定除外していた。上の三条件のもとで
これを解除する判断を 2026-09-08 に行った(SPEC の D-01)。

## 国土地理院

```text
出典:国土地理院ウェブサイト
https://maps.gsi.go.jp/development/ichiran.html
```

背景地図タイルと標高タイル(DEM)を使う。標高値を加工して属性にしているので、
加工した旨を表示する。

## 国土交通省 国土数値情報

```text
出典:国土交通省 国土数値情報ダウンロードサイト
https://nlftp.mlit.go.jp/ksj/other/agreement.html
```

河川(W05)・行政区域(N03)を使う。

**海岸線(C23)は使わない。** 公開ページ上に非商用の旨の記載があり、再配布する派生データに
条件を持ち込むため。`coast_distance_m` は V1.0 では `null` のままにする。

## AI モデル

| モデル | ライセンス |
|---|---|
| `intfloat/multilingual-e5-base` | MIT |

モデルの重みはこのリポジトリに含めない。
