import fs from "node:fs";
import path from "node:path";
import type { BuildReport } from "./types";

/** ビルド時に公開アーティファクトのレポートを読む。数を仕様書に固定しない(RULE-09)。 */
export function readBuildReport(): BuildReport | null {
  const p = path.join(process.cwd(), "public", "data", "meta", "build.json");
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8")) as BuildReport;
}

export function jp(n: number): string {
  return n.toLocaleString("ja-JP");
}
