import type { Metadata } from "next";
import Link from "next/link";
import UmapExplorer from "@/components/ai/UmapExplorer";

export const metadata: Metadata = {
  title: "意味空間 | Jinja Origin Atlas AI",
  description: "由緒テキストの意味的な近さを 2 次元に射影した散布図。",
};

export default function AiSpacePage() {
  return (
    <main>
      <h1>由緒の意味空間</h1>
      <p className="lede">
        日本語版ウィキペディアの記事から取り出した由緒の文章を、Transformer でベクトルに変え、
        2 次元に射影した図。近い点どうしは<strong>文章が意味的に近い</strong>。
      </p>

      <div className="band band-ai">
        <h3>この図が言っていないこと</h3>
        <p style={{ margin: 0 }}>
          近いことは、勧請・分祀の関係を意味しない。歴史的事実の証明でもない。
          クラスタ番号は識別子であって、歴史学上の系統ではない。
          <Link href="/about-ai/">AI について</Link>
        </p>
      </div>

      <UmapExplorer />

      <h2>色の使い方について</h2>
      <p style={{ fontSize: "0.9rem" }}>
        クラスタを色で塗り分けていない。散布図では任意の二色が隣り合いうるので、
        色覚の多様性まで含めて確実に見分けられる系列は 3 色程度に限られる。
        クラスタは十数個あるため、色相ではなく<strong>ひとつ選んで強調する</strong>形にした。
        モチーフの強さのような連続量には、単一色相の濃淡を当てている。
      </p>

      <h2>本文は配っていない</h2>
      <p style={{ fontSize: "0.9rem" }}>
        由緒の解析には日本語版ウィキペディアの記事本文を使っているが、
        本文も埋め込みベクトルも公開ファイルに含めていない。配っているのは数値のスコアだけで、
        由来した記事の題名・版・ライセンス(CC BY-SA 4.0)は神社ごとに表示している。
        詳しくは<Link href="/sources/">出典・ライセンス</Link>。
      </p>
    </main>
  );
}
