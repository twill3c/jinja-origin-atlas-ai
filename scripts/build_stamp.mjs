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
import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";

/**
 * 刻印の対象。**データだけでは足りない。**
 *
 * 最初はデータだけを測っていたが、フッタのリンクを直したときに刻印が変わらず、
 * 本番検品が古い版に対して「刻印が一致」を返した(2026-09-09)。
 * 「新しいか」を判定するつもりの検査が、コードの変更については何も言わなかった。
 * 画面を作るソースも対象に入れる。
 *
 * **ソースは手書きの一覧にしない**(2026-09-21)。一覧で持っていたとき、
 * `/deity` を一式(画面・部品・型・データ)足しても刻印は一文字も変わらなかった ——
 * **書き忘れた対象について、刻印は沈黙する。** 走査して集める形に変えた。
 * 走査が空振りしていないことは T-153 が数で確かめる。
 */
const SOURCE_DIRS = [
  { dir: "app", exts: [".tsx", ".ts", ".css"] },
  { dir: "components", exts: [".tsx", ".ts"] },
  { dir: "lib", exts: [".ts"] },
];

/** 画面が読むデータ。こちらは数が決まっているので名指しで持つ。 */
const DATA = [
  "public/data/meta/build.json",
  // D-06: 全カタログは配らない。索引を入れ、チャンクは下で実在するものを全部足す
  "public/data/shrines/index.json",
  "public/data/catalog/families.min.json",
  "public/data/osm/shrines.min.geojson",
  "public/data/ai/ai.min.json",
  "public/data/ai/similarity.min.json",
  "data/reports/ai_pipeline.json",
  "data/reports/motif_vs_geography.json",
];

/** ディレクトリを再帰的に走査して、対象の拡張子のファイルを相対パスで返す。 */
async function walk(dir, exts) {
  const out = [];
  let entries;
  try {
    entries = await readdir(path.join(process.cwd(), dir), { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries.sort((a, b) => (a.name < b.name ? -1 : 1))) {
    const rel = `${dir}/${e.name}`;
    if (e.isDirectory()) out.push(...(await walk(rel, exts)));
    else if (exts.some((x) => e.name.endsWith(x))) out.push(rel);
  }
  return out;
}

const OUT = "public/data/meta/stamp.json";

async function main() {
  const h = createHash("sha256");
  const parts = [];
  // 都道府県チャンク(D-06)は数が決まっていないので、実在するものを全部足す
  const chunks = [];
  for (const dir of ["shrines", "similar"]) {
    try {
      const names = (await readdir(path.join(process.cwd(), "public", "data", dir)))
        .filter((f) => /^\d{2}\.json$/.test(f))
        .sort();
      chunks.push(...names.map((f) => `public/data/${dir}/${f}`));
    } catch {
      /* まだ作られていない */
    }
  }
  // 祭神のアーティファクト(§7.14)も数が決まっていないので走査して足す
  try {
    const names = (await readdir(path.join(process.cwd(), "public", "data", "deity")))
      .filter((f) => f.endsWith(".json"))
      .sort();
    chunks.push(...names.map((f) => `public/data/deity/${f}`));
  } catch {
    /* まだ作られていない */
  }

  const sources = [];
  for (const { dir, exts } of SOURCE_DIRS) sources.push(...(await walk(dir, exts)));
  if (sources.length === 0) {
    console.error("刻印の走査対象が空。app / components / lib が見つからない");
    process.exit(2);
  }

  for (const rel of [...sources, ...DATA, ...chunks]) {
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
