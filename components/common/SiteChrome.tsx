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
export function SiteFooter() {
  return (
    <footer className="site-footer">
      <span>MIT License © 2026 坂田哲朗</span>
      <span aria-hidden="true">・</span>
      <a href="https://github.com/" rel="noreferrer">
        GitHub
      </a>
      <span aria-hidden="true">・</span>
      <Link href="/sources/">出典</Link>
      <span aria-hidden="true">・</span>
      <a href="https://app-menu.vercel.app/" rel="noreferrer">
        App Menu
      </a>
    </footer>
  );
}
/* /fleet: fixed footer */
