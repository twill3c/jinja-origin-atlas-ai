/**
 * ビルドの刻印 — 配られている版が、手元で作った版かを判定するための目印。
 *
 * **本番検品は「健やかか」しか答えない。「新しいか」は別の仕掛けが要る**(HC-148)。
 * デプロイが上限で拒否されても本番は健やかなままなので、健やかさの項目をいくら増やしても
 * 反映の有無は分からない —— むしろ「全部緑」という強い誤った安心が出る。
 *
 * **改行を揃えてから測る。** この機は `core.autocrlf=true` なので、作業ツリーは CRLF・
 * 配信側は LF になり、生のバイト列で測ると**同じ内容でも手元と本番で必ず食い違う**。
 * 狼少年になった検査は、無視する癖がつくぶん何もしない検査より悪い。
 */
import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

/**
 * 刻印の対象。**データだけでは足りない。**
 *
 * 最初はデータだけを測っていたが、フッタのリンクを直したときに刻印が変わらず、
 * 本番検品が古い版に対して「刻印が一致」を返した(2026-09-09)。
 * 「新しいか」を判定するつもりの検査が、コードの変更については何も言わなかった。
 * 画面を作るソースも対象に入れる。
 */
const SOURCES = [
  "components/common/SiteChrome.tsx",
  "components/map/JinjaMap.tsx",
  "components/ai/UmapExplorer.tsx",
  "app/page.tsx",
  "app/map/page.tsx",
  "app/ai-space/page.tsx",
  "app/analytics/page.tsx",
  "app/sources/page.tsx",
  "app/about-ai/page.tsx",
  "app/shrine/[id]/page.tsx",
  "app/similar/[id]/page.tsx",
  "app/globals.css",
  "lib/data.ts",
  "lib/types.ts",
  "public/data/meta/build.json",
  "public/data/catalog/shrines.min.json",
  "public/data/catalog/families.min.json",
  "public/data/osm/shrines.min.geojson",
  "public/data/ai/ai.min.json",
  "public/data/ai/similarity.min.json",
  "data/reports/ai_pipeline.json",
  "data/reports/motif_vs_geography.json",
];

const OUT = "public/data/meta/stamp.json";

async function main() {
  const h = createHash("sha256");
  const parts = [];
  for (const rel of SOURCES) {
    let text;
    try {
      text = await readFile(path.join(process.cwd(), rel), "utf-8");
    } catch {
      parts.push({ file: rel, present: false });
      h.update(`${rel}|missing\n`);
      continue;
    }
    // **改行を揃えてから測る。** CRLF / LF の違いで刻印がずれないように。
    const normalized = text.replace(/\r\n/g, "\n");
    const one = createHash("sha256").update(normalized).digest("hex");
    parts.push({ file: rel, present: true, bytes: normalized.length, sha256: one.slice(0, 16) });
    h.update(`${rel}|${one}\n`);
  }
  const stamp = {
    stamp: h.digest("hex").slice(0, 32),
    generated_at: new Date().toISOString(),
    files: parts,
    note: "画面が読むデータの内容から作った刻印。改行を LF に揃えてから測っている。",
  };
  await mkdir(path.dirname(OUT), { recursive: true });
  await writeFile(OUT, JSON.stringify(stamp, null, 1), "utf-8");
  console.log(`刻印 ${stamp.stamp} → ${OUT}`);
}

await main();
