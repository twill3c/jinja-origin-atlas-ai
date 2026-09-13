import Link from "next/link";
import LegacyRedirect from "@/components/common/LegacyRedirect";

export default function NotFound() {
  return (
    <main>
      <LegacyRedirect />
      <h1>ページが見つかりません</h1>
      <p>
        URL が変わった可能性がある。神社の詳細は <code>/shrine/?id=…</code> の形になった。
      </p>
      <p>
        <Link href="/map/">地図</Link>から探すこと。
      </p>
    </main>
  );
}
