import type { Metadata } from "next";
import Link from "next/link";
import { readPipelineReport } from "@/lib/data";

export const metadata: Metadata = {
  title: "AI について | Jinja Origin Atlas AI",
  description: "このサイトの AI が何を測っていて、何を測っていないか。",
};

export default function AboutAiPage() {
  const r = readPipelineReport();

  return (
    <main>
      <h1>AI について</h1>

      <div className="band band-ai">
        <h3>免責</h3>
        <p style={{ margin: 0 }}>
          AI 分析は公開可能な由緒テキストの意味的特徴を数値化したもので、
          歴史的事実、宗教的正統性、神社間の実際の系譜関係を証明するものではありません。
        </p>
      </div>

      <h2>やっていること</h2>
      <ul>
        <li>由緒の文章を Transformer でベクトルに変える</li>
        <li>ベクトルどうしの意味的な近さを測り、似た由緒の神社を並べる</li>
        <li>あらかじめ書いた 12 種類の由緒モチーフとの近さを数値にする</li>
        <li>クラスタリング(クラスタ数を先に決めない方式)と 2 次元への射影</li>
      </ul>

      <h2>やっていないこと</h2>
      <ul>
        <li>クラスタ番号に歴史学上の系統の意味を与えること</li>
        <li>スコアを「史実である確率」として扱うこと</li>
        <li>AI の類似度から「A 神社から B 神社へ勧請された」と推論すること</li>
        <li>生成 AI に由緒を書かせること</li>
        <li>ブラウザやサーバーでモデルを動かすこと(すべて事前に計算してある)</li>
      </ul>

      {r && (
        <>
          <h2>いま動いている設定</h2>
          <div className="scroll-x">
            <table>
              <tbody>
                <tr><th scope="row">モデル</th><td><code>{r.model}</code></td></tr>
                <tr>
                  <th scope="row">モデルの版</th>
                  <td><code>{r.revision}</code></td>
                </tr>
                <tr><th scope="row">ベクトルの次元</th><td>{r.embedding_dim}</td></tr>
                <tr><th scope="row">解析した由緒</th><td>{r.corpus.toLocaleString("ja-JP")} 件</td></tr>
                <tr>
                  <th scope="row">見つかったクラスタ</th>
                  <td>
                    {r.clusters} 個(どれにも入らなかったもの {r.noise.toLocaleString("ja-JP")} 件)
                  </td>
                </tr>
                <tr>
                  <th scope="row">長すぎて切り詰めた由緒</th>
                  <td>{r.truncated_docs.toLocaleString("ja-JP")} 件</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)" }}>
            モデルの版を書いてあるのは、同じ数をもう一度出せるようにするためである。
            版を書かない数値は再現できない。
          </p>

          <h2>モチーフのスコアが働いているかの確認</h2>
          <p style={{ fontSize: "0.9rem" }}>
            神社と無関係な文(料理の手順・決算の説明・アルゴリズムの解説)を同じ計算に通し、
            どのモチーフでも由緒本文より低く出ることを確かめている。
            無関係な文の最高スコアは <strong>{r.motif_control.control_max.toFixed(3)}</strong>、
            由緒本文の最高スコアの中央値は{" "}
            <strong>{r.motif_control.corpus_median_max.toFixed(3)}</strong>。
            {r.motif_control.passes ? (
              <>
                {" "}さらに、由緒本文の最高スコアの最小値は{" "}
                {r.motif_control.corpus_min_max.toFixed(3)} なので、
                <strong>解析した全件が、対照文すべてを上回っている</strong>。
              </>
            ) : (
              <>
                {" "}期待に反して、無関係な文のほうが低くならなかった。この場合、
                モチーフのスコアは「神社らしさ」ではなく別の何かを測っている可能性がある。
              </>
            )}
          </p>
        </>
      )}

      {r?.motif_score_band && (
        <>
          <h2>スコアをそのまま並べない理由</h2>
          <p>
            このモデルのコサイン類似度は、12 のモチーフすべてが{" "}
            <strong>
              {r.motif_score_band.min.toFixed(3)} 〜 {r.motif_score_band.max.toFixed(3)}
            </strong>{" "}
            という狭い帯に収まる。ひとつの神社の中で最も高いモチーフと最も低いモチーフの差は、
            中央値で <strong>{r.motif_score_band.within_doc_spread_median.toFixed(3)}</strong>
            しかない。
          </p>
          <p>
            この数字を 12 個並べると、読み手は「どれも同じくらい当てはまる」と受け取ってしまう。
            そこで画面には、<strong>そのモチーフの分布の中でこの神社がどこにいるか</strong>
            (上位何パーセントか)を出している。生のスコアは公開ファイルに残してあるので、
            自分で確かめられる。
          </p>
        </>
      )}

      <h2>史実の線と AI の線は別に描く</h2>
      <p>
        文献で確認できる分祀・分社の関係は<strong>実線</strong>で、
        AI が測った文章の意味的な近さは<strong>点線</strong>で描く。
        この二つを同じ線種で描かない。神社詳細では、前者を「文献上の母院」、
        後者を「由緒が似た神社」として別の欄に置いている。
      </p>

      <h2>系統分類の優先順位</h2>
      <p>
        八幡系・稲荷系といった系統は、次の順に決める。AI 推定は最後の手段であり、
        AI 推定だけで決まった場合は画面にそう書く。
      </p>
      <ol>
        <li>明示された構造化データ(Wikidata の包括団体)</li>
        <li>祭神(Wikidata P825「献呈先」)</li>
        <li>名称の規則</li>
        <li>由緒テキスト</li>
        <li>AI 推定</li>
      </ol>
      <p style={{ fontSize: "0.9rem" }}>
        いまのところ、系統は 2 番目と 3 番目までで決まっており、
        <strong>AI 推定にまで落ちたものは無い</strong>。
        <Link href="/analytics/">統計</Link>で内訳を見られる。
      </p>

      <h2>使っているテキストと、配っていないもの</h2>
      <p>
        由緒の解析には日本語版ウィキペディアの記事本文を使っている。ライセンスは
        CC BY-SA 4.0 で、次の三つを守ることを条件に利用している。
      </p>
      <ol>
        <li>本文を公開ファイルに含めない</li>
        <li>埋め込みベクトルも含めない</li>
        <li>神社ごとに、由来した記事の題名・版・ライセンスを表示する</li>
      </ol>
      <p style={{ fontSize: "0.9rem" }}>
        配っているのは数値のスコア(モチーフ・類似度・クラスタ番号・2 次元の座標)だけである。
        この約束が守られていることは、公開ファイルに長い文字列や長い数値列が入っていないかを
        機械で検査して確かめている。
      </p>

      <h2>権利条件の明確な由緒本文が少ないこと</h2>
      <p>
        ジャパンサーチで「神社」かつ「由緒」を検索すると 1,892 件が当たるが、
        先頭 100 件を調べたところ、再利用可能な権利コード(CC0 / PDM / CC BY)を持ち、
        かつ 100 字以上の説明文がある記録は 5 件だった(2026-09-08 実測)。
        これが、ウィキペディアを使うことにした理由である。
      </p>

      <div className="notice">
        全国の神社すべてに AI 由緒分析があるわけではない。地図では「神社の位置」と
        「AI 由緒分析つき」を別に数え、件数はビルド時の実測値を表示する。
      </div>
    </main>
  );
}
