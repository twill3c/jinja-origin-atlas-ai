import type { Metadata } from "next";
import { Suspense } from "react";
import DeityExplorer from "@/components/deity/DeityExplorer";

/* 祭神の三面。SPEC §7.14。
 *
 * 一柱を選ぶと「誰と並ぶか」「どこに濃いか」「何という名で呼ばれるか」が同時に変わる。
 * 数も合否もビルド時に測った値をクライアントが読む —— **画面の中で数え直さない**。
 * 文書とコードで数が二重になると、片方だけが静かに嘘になる(HC-152)。 */

export const metadata: Metadata = {
  title: "祭神 | Jinja Origin Atlas AI",
  description:
    "Wikidata が神社に書き込んだ祭神を、共祀ネットワーク・県別リフトの地図・習合の対応表の三面で見る。",
};

export default function DeityPage() {
  return (
    <main>
      <h1>祭神</h1>
      <p className="lede">
        一柱を選ぶと、三つの面が同じ祭神について同時に答える ——
        <strong>誰と並ぶか</strong>(共祀ネットワーク)・<strong>どこに濃いか</strong>
        (点の地図と県別リフト)・<strong>何という名で呼ばれるか</strong>(習合の対応表)。
      </p>
      <Suspense fallback={<p role="status">読み込み中…</p>}>
        <DeityExplorer />
      </Suspense>
    </main>
  );
}
