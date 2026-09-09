/**
 * 本番検品 — 実際に配られているものを見る。
 *
 * **最初に刻印を照合し、合わなければ他を一切見ずに止める**(HC-148)。
 * 「健やかか」と「新しいか」は別の問いで、健やかさの項目をいくら増やしても
 * 反映の有無は分からない。デプロイが上限で拒否されても本番は健やかなままなので、
 * 全項目合格が**前日の本番に対して**返ってくる。
 *
 * **CLI の終了コードで反映を判定しない。** `vercel ls` も当てにならない。
 * 配信物そのものを引いて判定する。
 *
 *   node harness/live.mjs https://<host>
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

const base = (process.argv[2] || process.env.LIVE_URL || "").replace(/\/$/, "");
if (!base) {
  console.error("本番 URL を渡すこと: node harness/live.mjs https://<host>");
  process.exit(2);
}

const failures = [];
function check(name, ok, detail = "") {
  console.log(`  ${ok ? "OK  " : "FAIL"} ${name}${detail ? ` ${detail}` : ""}`);
  if (!ok) failures.push(`${name} ${detail}`.trim());
}

async function get(p, { json = false } = {}) {
  const r = await fetch(`${base}${p}`, { redirect: "follow" });
  const body = json ? await r.json().catch(() => null) : await r.text();
  return { status: r.status, ct: r.headers.get("content-type") || "", body };
}

async function main() {
  console.log(`本番: ${base}`);

  // --- 1. 刻印。ここが合わなければ以降は見ない ---------------------------
  const local = JSON.parse(await readFile(path.join(process.cwd(), "public/data/meta/stamp.json"), "utf-8"));
  const live = await get("/data/meta/stamp.json", { json: true });
  if (live.status !== 200 || !live.body?.stamp) {
    console.error(`刻印が取れない(HTTP ${live.status})。まだ配られていないか、経路が違う。`);
    process.exit(1);
  }
  if (live.body.stamp !== local.stamp) {
    console.error("配られている版が手元と違う。");
    console.error(`  手元: ${local.stamp} (${local.generated_at})`);
    console.error(`  本番: ${live.body.stamp} (${live.body.generated_at})`);
    console.error("**以降の検品は行わない** —— 古い版が健やかでも意味が無い(HC-148)。");
    process.exit(1);
  }
  console.log(`  OK   刻印が一致 ${local.stamp}`);

  // --- 2. 主要な経路が引けるか ------------------------------------------
  for (const p of ["/", "/map/", "/ai-space/", "/analytics/", "/sources/", "/about-ai/"]) {
    const r = await get(p);
    check(`${p} が 200 で返る`, r.status === 200, `status=${r.status}`);
    check(`${p} が HTML を返す`, r.ct.includes("text/html"), r.ct);
  }

  // --- 3. 出典が本文にある(JS 抜きで) ---------------------------------
  const map = await get("/map/");
  check("地図に OSM の出典がある", map.body.includes("© OpenStreetMap contributors"));
  check("地図に国土地理院の出典がある", map.body.includes("国土地理院"));
  const src = await get("/sources/");
  check("出典ページに ODbL がある", src.body.includes("ODbL"));
  check("出典ページに CC BY-SA がある", src.body.includes("CC BY-SA"));

  // --- 4. AI の免責 ------------------------------------------------------
  const ai = await get("/about-ai/");
  check("AI 画面に免責がある", ai.body.includes("証明するものではありません"));

  // --- 5. 配っているデータの形(D-01 の履行) ---------------------------
  const aij = await get("/data/ai/ai.min.json", { json: true });
  check("AI データが JSON で返る", aij.status === 200 && Array.isArray(aij.body?.shrines),
    `status=${aij.status}`);
  if (Array.isArray(aij.body?.shrines)) {
    const one = aij.body.shrines[0];
    check("本文も埋め込みも配っていない",
      !("text" in one) && !("embedding" in one) && !Array.isArray(one.motifs));
    check("モデルの版が記録されている", (aij.body.model?.revision ?? "").length >= 7,
      aij.body.model?.revision);
    check("由来記事の帰属が付いている",
      !!one.source?.title && typeof one.source?.revid === "number" &&
      one.source?.license === "CC BY-SA 4.0");
  }

  // --- 6. フッタ規約(コードの変更が本番へ届いたかの実測) ---------------
  // **刻印だけに頼らない。** 刻印はデータとソースの指紋であって、
  // 「その通りに配信されたか」までは言わない。宛先そのものを本文で確かめる。
  const home = await get("/");
  check(
    "App Menu が本番(app-menu-amber)を指している",
    home.body.includes("app-menu-amber.vercel.app"),
  );
  check(
    "App Menu が他者のドメインを指していない",
    !/https:\/\/app-menu\.vercel\.app/.test(home.body),
  );
  check(
    "GitHub がこのリポジトリを指している",
    home.body.includes("github.com/twill3c/jinja-origin-atlas-ai"),
  );

  // --- 7. 個別ページ -----------------------------------------------------
  const id = aij.body?.shrines?.[0]?.id;
  if (id) {
    const d = await get(`/shrine/${id}/`);
    check("神社詳細が 200 で返る", d.status === 200, `${id} status=${d.status}`);
    const s = await get(`/similar/${id}/`);
    check("類似ページが 200 で返る", s.status === 200, `status=${s.status}`);
  }

  console.log("");
  if (failures.length) {
    console.error(`本番検品 NG — ${failures.length} 件`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log("本番検品 OK");
}

main().catch((e) => {
  console.error("検品器そのものが落ちた:", e);
  process.exit(3);
});
