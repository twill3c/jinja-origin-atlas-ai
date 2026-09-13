import type { Metadata } from "next";
import { Suspense } from "react";
import SimilarList from "@/components/shrine/SimilarList";

/* 決定 D-06: 神社ごとの HTML を作らない。`?id=` を読んで、その県のチャンクから
 * 類似の相手(名前・県・系統・上位モチーフを書き込み済み)を描く。 */

export const metadata: Metadata = {
  title: "由緒が似た神社 | Jinja Origin Atlas AI",
  description: "由緒テキストと意味的に近い神社。AI による意味関連度であり、史実の系譜ではない。",
};

export default function SimilarPage() {
  return (
    <main>
      <Suspense fallback={<p role="status">読み込み中…</p>}>
        <SimilarList />
      </Suspense>
    </main>
  );
}
