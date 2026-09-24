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
  // D-06 以後、詳細と類似の HTML は殻である。殻が返ることと、画面が引くデータ
  // (索引とチャンク)が返ることを見る。旧 URL は 404 ページ(転送役)を返すはず。
  const id = aij.body?.shrines?.[0]?.id;
  if (id) {
    const shell = await get(`/shrine/?id=${id}`);
    check("神社詳細の殻が 200 で返る", shell.status === 200 && shell.ct.includes("text/html"),
      `status=${shell.status}`);
    const idx = await get("/data/shrines/index.json", { json: true });
    const p = idx.body?.ids?.[id];
    check("索引が引ける", idx.status === 200 && !!p, `status=${idx.status} p=${p}`);
    if (p) {
      const ch = await get(`/data/shrines/${p}.json`, { json: true });
      check("索引の指すチャンクにその神社がある",
        ch.status === 200 && (ch.body?.shrines ?? []).some((x) => x.id === id), `status=${ch.status}`);
    }
    const sim = await get(`/similar/?id=${id}`);
    check("類似ページの殻が 200 で返る", sim.status === 200, `status=${sim.status}`);
    const legacy = await get(`/shrine/${id}/`);
    check("旧 URL は 404 ページ(転送役)を返す",
      legacy.status === 404 && legacy.body.includes("URL が変わった"), `status=${legacy.status}`);
  }

  // --- 8. 祭神の三面(SPEC §7.14)----------------------------------------
  // 画面はクライアント描画なので、殻に加えて**画面が引く 6 本すべて**を名指しで取る。
  // 1 本でも欠けると三面のどれかが黙って空になる。
  const deityShell = await get("/deity/");
  check("祭神ページの殻が 200 で返る",
    deityShell.status === 200 && deityShell.ct.includes("text/html"),
    `status=${deityShell.status}`);
  const deityFiles = ["index", "points", "detail", "network", "pairs", "report"];
  const deityDocs = {};
  for (const name of deityFiles) {
    const r = await get(`/data/deity/${name}.json`, { json: true });
    deityDocs[name] = r.body;
    check(`祭神の ${name}.json が JSON で返る`, r.status === 200 && !!r.body,
      `status=${r.status}`);
  }

  // 件数が保存されているか(G-19)。**本番の数を手元の定数と比べない** ——
  // 配られている一覧の合計と、配られている総数が合うかを見る。
  const idx = deityDocs.index;
  if (idx) {
    const sum = (idx.deities ?? []).reduce((a, d) => a + d.n, 0);
    check("祭神一覧の合計が延べ言及数と一致する", sum === idx.totals?.mentions,
      `一覧=${sum} 総数=${idx.totals?.mentions}`);
    check("祭神の柱数が一覧の長さと一致する",
      (idx.deities ?? []).length === idx.totals?.deities,
      `一覧=${(idx.deities ?? []).length} 総数=${idx.totals?.deities}`);
  }

  // **画面の主張はレポートに従う**(HC-079)。測って落ちた予測を、
  // 通ったかのように書いていないこと。合否そのものは判定しない ——
  // 落ちていてよい検査なので、見るのは「文と結果が食い違っていないか」だけ。
  const rep = deityDocs.report;
  if (rep && deityShell.body) {
    const claims = ["総本社が浮かび上がる", "総本社を当てる", "総本社が浮かぶ"];
    const claimed = claims.filter((c) => deityShell.body.includes(c));
    check("G-16 が不合格なら『総本社が浮かび上がる』と書いていない",
      rep.g16?.pass === true || claimed.length === 0, claimed.join(" / "));
    check("測った的中数が画面に出ている",
      deityShell.body.includes(`${rep.g16?.hit} / ${rep.g16?.total}`),
      `${rep.g16?.hit}/${rep.g16?.total}`);
    check("主張の検査 陽性対照: 主張の語があれば撃つ",
      claims.some((c) => "ここでは総本社が浮かび上がる".includes(c)));
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
