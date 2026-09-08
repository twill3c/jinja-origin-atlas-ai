import type { Metadata } from "next";
import { SiteFooter, SiteNav } from "@/components/common/SiteChrome";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jinja Origin Atlas AI",
  description:
    "日本の神社の所在地・祭神・社格・創建情報と地形情報を、公開データだけから地図と AI 意味分析で探索する。",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <SiteNav />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
