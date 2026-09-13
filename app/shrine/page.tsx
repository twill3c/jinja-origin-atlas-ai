import type { Metadata } from "next";
import { Suspense } from "react";
import ShrineDetail from "@/components/shrine/ShrineDetail";

/* 決定 D-06: 神社ごとの HTML を作らない。全国 40,776 件では静的ページ 18,508 枚・
 * 出荷ファイル 43,478 個・ビルド約 111 分となり、Vercel 無料枠の上限に二重に当たった。
 * この 1 枚が `?id=` を読み、その県のチャンクだけを引いて描く。
 * 仕様書 §33 の「神社ごとの metadata 生成」はここで失っている(SPEC に明記)。 */

export const metadata: Metadata = {
  title: "神社の詳細 | Jinja Origin Atlas AI",
  description: "神社の所在地・祭神・社格・地理情報・由緒の意味分析。公開データに基づく。",
};

export default function ShrinePage() {
  return (
    <main>
      <Suspense fallback={<p role="status">読み込み中…</p>}>
        <ShrineDetail />
      </Suspense>
    </main>
  );
}
