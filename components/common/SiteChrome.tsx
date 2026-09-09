import Link from "next/link";

const NAV: [string, string][] = [
  ["/", "ホーム"],
  ["/map/", "地図"],
  ["/ai-space/", "意味空間"],
  ["/analytics/", "統計"],
  ["/sources/", "出典・ライセンス"],
  ["/about-ai/", "AI について"],
];

export function SiteNav() {
  return (
    <nav className="nav" aria-label="主要ナビゲーション">
      <strong>Jinja Origin Atlas AI</strong>
      {NAV.map(([href, label]) => (
        <Link key={href} href={href}>
          {label}
        </Link>
      ))}
    </nav>
  );
}

/* fleet: fixed footer */
/* フリート共通のフッタ規約(5 項目・この並び・下部固定)。
 * **App Menu の本番は app-menu-amber.vercel.app である。**
 * app-menu.vercel.app は他者の別サービスなので、そこへ送ってはならない。 */
export function SiteFooter() {
  return (
    <footer className="site-footer">
      <a
        href="https://github.com/twill3c/jinja-origin-atlas-ai/blob/main/LICENSE"
        rel="noreferrer"
        target="_blank"
      >
        MIT License
      </a>
      <span> © 2026 坂田哲朗</span>
      <span aria-hidden="true">・</span>
      <a href="https://github.com/twill3c/jinja-origin-atlas-ai" rel="noreferrer" target="_blank">
        GitHub
      </a>
      <span aria-hidden="true">・</span>
      <Link href="/sources/">出典とライセンス</Link>
      <span aria-hidden="true">・</span>
      <Link href="/about-ai/">AI の読み方</Link>
      <span aria-hidden="true">・</span>
      <a href="https://app-menu-amber.vercel.app/" rel="noreferrer" target="_blank">
        App Menu
      </a>
    </footer>
  );
}
/* /fleet: fixed footer */
