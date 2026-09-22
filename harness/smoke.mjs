/**
 * 実ブラウザ検品 — 出荷される `out/` を静的配信して実際に開く。
 *
 * 「テストが緑」と「画面が動く」は別である(HC-041)。ここで測るのは
 * 在存ではなく**幾何と到達**(HC-138):
 *   - 地図に実際に何個描かれたか(WebGL の中身は DOM から見えないので map API で数える)
 *   - 全部を集約したクラスタの合計が、データの件数と一致するか(二重描画・欠落を捕まえる)
 *   - 複数の画面幅で横に溢れていないか(HC-078)
 *
 * **この検品器は失敗を終了コードで知らせる。** パイプの先で $? がすり替わるので
 * `node harness/smoke.mjs | tail` の形で成否を判断しないこと(HC-080)。
 *
 *   node harness/smoke.mjs           検品する
 *   node harness/smoke.mjs --shot    スクリーンショットも撮る
 */
import { createServer } from "node:http";
import { readFile, readdir, mkdir, stat } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const OUT = path.join(process.cwd(), "out");
const SHOTS = path.join(process.cwd(), "artifacts", "screenshots");
const WANT_SHOT = process.argv.includes("--shot");

// 検品器全体の上限。どこかの待ちが終わらないと、結果を返さないまま止まり続ける
// (loop_012 で地図の idle を待ったまま 15 分止まった)。止まったら落ちたと言って終わる。
const WATCHDOG_MS = 20 * 60 * 1000;
setTimeout(() => {
  console.error(`検品 NG — 検品器が ${WATCHDOG_MS / 60000} 分を超えた(どこかの待ちが終わっていない)`);
  process.exit(4);
}, WATCHDOG_MS).unref();

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".geojson": "application/geo+json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
};

const failures = [];
function check(name, ok, detail = "") {
  if (ok) {
    console.log(`  OK   ${name}`);
  } else {
    console.log(`  FAIL ${name} ${detail}`);
    failures.push(`${name} ${detail}`.trim());
  }
}

function serve() {
  const server = createServer(async (req, res) => {
    try {
      let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
      let file = path.join(OUT, p);
      const s = await stat(file).catch(() => null);
      if (!s || s.isDirectory()) file = path.join(file, "index.html");
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[path.extname(file)] ?? "application/octet-stream" });
      res.end(body);
    } catch {
      // Vercel は存在しない経路に 404.html を 404 で返す。同じ振る舞いにする ——
      // 旧 URL の転送は 404 ページの中で行うので、これが無いと検品できない(D-06)。
      for (const cand of ["404.html", path.join("404", "index.html")]) {
        const body404 = await readFile(path.join(OUT, cand)).catch(() => null);
        if (body404) {
          res.writeHead(404, { "content-type": "text/html; charset=utf-8" });
          res.end(body404);
          return;
        }
      }
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
    }
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

async function main() {
  const s = await stat(OUT).catch(() => null);
  if (!s) {
    console.error("out/ が無い。先に `npm run build` を実行すること。");
    process.exit(2);
  }

  const server = await serve();
  const base = `http://127.0.0.1:${server.address().port}`;
  // GPU の無い環境(GitHub Actions の Linux ランナー)では WebGL をソフトウェアで描くしかない。
  // Chromium は SwiftShader への自動の後退を廃止しつつあり、明示しないと地図の WebGL 文脈が作れない
  // (Chromium の docs/gpu/swiftshader.md)。GPU のある手元ではこの指定は後退を許すだけで描画は変わらない
  const browser = await chromium.launch({ args: ["--enable-unsafe-swiftshader"] });
  const consoleErrors = [];

  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(m.text());
    });
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    // **どの資源が落ちたかを URL で言えるようにする。** コンソールの本文は
    // 「Failed to load resource: 404」としか言わず、意図的に踏んだ旧 URL の副作用なのか
    // 本物の欠落なのか区別できない。
    const badResponses = [];
    page.on("response", (r) => {
      if (r.status() >= 400) badResponses.push({ status: r.status(), url: r.url() });
    });

    // --- 地図ページ -------------------------------------------------------
    console.log("地図ページ");
    const resp = await page.goto(`${base}/map/`, { waitUntil: "networkidle" });
    check("HTTP 200 で開く", resp?.status() === 200, `status=${resp?.status()}`);

    // 出典は JS 抜きでも DOM にあること(SPEC F-02)
    const attrText = await page.locator("body").innerText();
    check("出典 © OpenStreetMap contributors が本文にある", attrText.includes("© OpenStreetMap contributors"));
    check("背景地図の出典 国土地理院が本文にある", attrText.includes("国土地理院"));

    // 地図が実際に読み込まれるまで待つ
    await page.waitForFunction(() => window.__jinjaMap?.isStyleLoaded?.() === true, { timeout: 30000 });
    await page.waitForFunction(
      () => (window.__jinjaMap?.querySourceFeatures?.("shrines") ?? []).length > 0,
      { timeout: 30000 },
    );
    await page.waitForTimeout(1200); // 描画の収束を待つ

    // 「データの全体」と「描かれたもの」を比べる前に、全体が視野に入る状態を作る(HC-222)。
    // queryRenderedFeatures が返すのは視野の中身であって母集団ではない。
    // 東京都は小笠原村・硫黄島を含むので、初期表示のままでは 4 件が範囲外になる。
    const fc = JSON.parse(await readFile(path.join(OUT, "data/osm/shrines.min.geojson"), "utf-8"));
    const total = fc.features.length;
    const xs = fc.features.map((f) => f.geometry.coordinates[0]);
    const ys = fc.features.map((f) => f.geometry.coordinates[1]);
    const dataBounds = [
      [Math.min(...xs), Math.min(...ys)],
      [Math.max(...xs), Math.max(...ys)],
    ];
    await page.evaluate((b) => {
      window.__jinjaMap.fitBounds(b, { padding: 40, animate: false });
    }, dataBounds);
    // once("idle") を登録する前に地図が落ち着いていると、idle は二度と来ずに永久に待つ(loop_012 で 15 分止まった)。
    // 登録してから再描画を促し、それでも来なければ 15 秒で先へ進む(後の検査が状態を見て落ちる)
    await page.evaluate(() => new Promise((r) => {
      const m = window.__jinjaMap;
      m.once("idle", r);
      m.triggerRepaint();
      setTimeout(r, 15000);
    }));
    await page.waitForTimeout(800);

    // --- 幾何: 何が描かれたか(HC-138) -----------------------------------
    const geo = await page.evaluate(() => {
      const m = window.__jinjaMap;
      const clusters = m.queryRenderedFeatures({ layers: ["clusters"] });
      const points = m.queryRenderedFeatures({ layers: ["shrine-point"] });
      const b = m.getBounds();
      return {
        clusters: clusters.length,
        points: points.length,
        clusterSum: clusters.reduce((a, f) => a + (f.properties.point_count ?? 0), 0),
        outOfView: [...clusters, ...points].filter((f) => {
          const [x, y] = f.geometry.coordinates;
          return x < b.getWest() || x > b.getEast() || y < b.getSouth() || y > b.getNorth();
        }).length,
      };
    });
    check("地図に何かが描かれている", geo.clusters + geo.points > 0, JSON.stringify(geo));
    check(
      "データ全体を視野に入れるとクラスタの合計が総件数と一致する(二重描画・欠落の検出)",
      geo.clusterSum + geo.points === total,
      `描画=${geo.clusterSum}+${geo.points} データ=${total}`,
    );
    check("描かれた要素がすべて表示範囲の中にある", geo.outOfView === 0, `範囲外=${geo.outOfView}`);

    // --- 幾何: キャンバスが器を埋めているか -------------------------------
    // 器の上に要素を足すと、MapLibre のキャンバスが初期化時の寸法のまま取り残され、
    // 地図の中に空白の帯ができる。**要素の在存も横溢れも正常なので捕まらない**ので、
    // 矩形どうしを突き合わせる(2026-09-08 に目視でのみ見つかった欠陥の再発防止)。
    const fit = await page.evaluate(() => {
      const c = document.querySelector(".maplibregl-canvas");
      // 比べる相手は**地図の器そのもの**である。親要素を取るとコンポーネント全体
      // (しぼりの fieldset や説明文を含む)と比べてしまい、常に落ちる。
      const box = c.closest(".maplibregl-map");
      const a = c.getBoundingClientRect();
      const b = box.getBoundingClientRect();
      return { cw: Math.round(a.width), ch: Math.round(a.height),
               bw: Math.round(b.width), bh: Math.round(b.height),
               dx: Math.round(a.left - b.left), dy: Math.round(a.top - b.top) };
    });
    check("キャンバスが器を埋めている(空白の帯がない)",
      Math.abs(fit.cw - fit.bw) <= 2 && Math.abs(fit.ch - fit.bh) <= 2 &&
      Math.abs(fit.dx) <= 2 && Math.abs(fit.dy) <= 2, JSON.stringify(fit));

    // --- 陽性対照: この検品器は実際に異常を捕まえるか --------------------
    // 状態を変えたら再描画を待ってから読む。同期的に読むと変更前の値が返り、
    // 対照は「撃たない」形で静かに死ぬ(HC-222)。
    const controlDetects = await page.evaluate(async () => {
      const m = window.__jinjaMap;
      // 登録してから再描画を促し、来なくても 15 秒で先へ進む(永久に待たない)
      const idle = () => new Promise((r) => { m.once("idle", r); m.triggerRepaint(); setTimeout(r, 15000); });
      const before = m.queryRenderedFeatures({ layers: ["clusters"] }).length;
      m.setLayoutProperty("clusters", "visibility", "none");
      await idle();
      const after = m.queryRenderedFeatures({ layers: ["clusters"] }).length;
      m.setLayoutProperty("clusters", "visibility", "visible");
      await idle();
      const restored = m.queryRenderedFeatures({ layers: ["clusters"] }).length;
      return { before, after, restored };
    });
    check(
      "陽性対照: 層を隠すと検品器がそれを検出する",
      controlDetects.before > 0 && controlDetects.after === 0 && controlDetects.restored > 0,
      JSON.stringify(controlDetects),
    );

    // --- 到達: クラスタを押すと拡大する(HC-138 の「操作が届いた証拠」) ---
    const zoomBefore = await page.evaluate(() => window.__jinjaMap.getZoom());
    const clicked = await page.evaluate(async () => {
      const m = window.__jinjaMap;
      const f = m.queryRenderedFeatures({ layers: ["clusters"] })[0];
      if (!f) return false;
      const p = m.project(f.geometry.coordinates);
      m.fire("click", { lngLat: m.unproject(p), point: p, originalEvent: new MouseEvent("click") });
      return true;
    });
    await page.waitForTimeout(1500);
    const zoomAfter = await page.evaluate(() => window.__jinjaMap.getZoom());
    check("クラスタを押すと拡大する", clicked && zoomAfter > zoomBefore, `${zoomBefore} → ${zoomAfter}`);

    // --- 系統のしぼり: 操作が届いた証拠を見る(HC-138) ----------------------
    console.log("系統のしぼり");
    const box = page.locator('fieldset input[type="checkbox"]').first();
    const label = await page.locator("fieldset label").first().innerText();
    await box.scrollIntoViewIfNeeded();
    await box.check();
    // once("idle") を登録する前に地図が落ち着いていると、idle は二度と来ずに永久に待つ(loop_012 で 15 分止まった)。
    // 登録してから再描画を促し、それでも来なければ 15 秒で先へ進む(後の検査が状態を見て落ちる)
    await page.evaluate(() => new Promise((r) => {
      const m = window.__jinjaMap;
      m.once("idle", r);
      m.triggerRepaint();
      setTimeout(r, 15000);
    }));
    await page.waitForTimeout(600);
    // 内部の _data を覗かない。公開 API の querySourceFeatures / queryRenderedFeatures で見る(HC-080)。
    const hl = await page.evaluate(() => {
      const m = window.__jinjaMap;
      return {
        highlighted: m.querySourceFeatures("highlight").length,
        clusterColor: m.getPaintProperty("clusters", "circle-color"),
        rendered: m.queryRenderedFeatures({ layers: ["highlight-point"] }).length,
      };
    });
    check("しぼると強調レイヤーに要素が入る", hl.highlighted > 0, JSON.stringify(hl));
    check("しぼると残りが無彩色に落ちる", hl.clusterColor === "#8a8580", String(hl.clusterColor));
    check("強調が実際に描画されている", hl.rendered > 0, `凡例=${label.trim()} 描画=${hl.rendered}`);

    await box.uncheck();
    // once("idle") を登録する前に地図が落ち着いていると、idle は二度と来ずに永久に待つ(loop_012 で 15 分止まった)。
    // 登録してから再描画を促し、それでも来なければ 15 秒で先へ進む(後の検査が状態を見て落ちる)
    await page.evaluate(() => new Promise((r) => {
      const m = window.__jinjaMap;
      m.once("idle", r);
      m.triggerRepaint();
      setTimeout(r, 15000);
    }));
    const cleared = await page.evaluate(() => ({
      rendered: window.__jinjaMap.queryRenderedFeatures({ layers: ["highlight-point"] }).length,
      clusterColor: window.__jinjaMap.getPaintProperty("clusters", "circle-color"),
    }));
    check("しぼりを外すと元に戻る",
      cleared.rendered === 0 && cleared.clusterColor === "#b7410e", JSON.stringify(cleared));

    // --- 神社詳細(クライアント描画・D-06)-----------------------------------
    // HTML は殻で、中身は画面が県のチャンクを引いて描く。**描き終わるのを待ってから**見る。
    console.log("神社詳細");
    const settled = () =>
      page.waitForFunction(() => !document.body.innerText.includes("読み込み中"), { timeout: 30000 });
    const chunkFiles = (await readdir(path.join(OUT, "data/shrines")))
      .filter((f) => /^\d{2}\.json$/.test(f))
      .sort();
    check("都道府県チャンクが出荷物にある", chunkFiles.length > 0, `チャンク ${chunkFiles.length}`);
    // 県の違う神社を選ぶ(先頭・中ほど・末尾のチャンクから、Wikidata に結合したものを 1 件ずつ)
    const pickFrom = [...new Set([chunkFiles[0], chunkFiles[Math.floor(chunkFiles.length / 2)],
                                  chunkFiles[chunkFiles.length - 1]])];
    const picks = [];
    for (const f of pickFrom) {
      const ch = JSON.parse(await readFile(path.join(OUT, "data/shrines", f), "utf-8"));
      const s = ch.shrines.find((x) => x.external_ids.wikidata && x.name.ja) ?? ch.shrines[0];
      picks.push({ id: s.id, p: ch.pref_code, name: s.name.ja ?? "名称のタグが無い神社", matched: !!s.match });
    }
    for (const pk of picks) {
      const r2 = await page.goto(`${base}/shrine/?id=${pk.id}&p=${pk.p}`, { waitUntil: "networkidle" });
      check(`詳細ページが開く(県 ${pk.p})`, r2?.status() === 200, `${pk.id} status=${r2?.status()}`);
      await settled();
      const body = await page.locator("body").innerText();
      const h1 = (await page.locator("h1").first().innerText()).trim();
      check(`詳細の見出しがその神社の名前(県 ${pk.p})`, h1 === pk.name, `h1=${h1} 期待=${pk.name}`);
      check(`詳細に三区分の見出しが出ている(県 ${pk.p})`,
        body.includes("公開データで確認できること") && body.includes("社伝") && body.includes("AI が文章から測ったこと"));
      check(`詳細に出典が出ている(県 ${pk.p})`, body.includes("OpenStreetMap"));
      if (pk.matched) {
        check(`名寄せに直リンクを使っていないことが書かれている(県 ${pk.p})`, body.includes("使っていない"));
      }
      const title = await page.title();
      check(`タブの題名が神社名になる(県 ${pk.p})`, title.startsWith(pk.name), title);
    }
    // --- G-13 史実と AI の非混在(T-129)---------------------------------------
    // 「公開データの情報」と「AI の意味分析」が同じ見出しの下に出ていないことを DOM で数える。
    // 文字列の有無ではなく、**どの帯(見出し)の下にあるか**を見る。
    const g13 = () => page.evaluate(() => {
      const v = [];
      const bands = [...document.querySelectorAll(".band")];
      const ev = bands.filter((b) => b.classList.contains("band-evidence"));
      const ai = bands.filter((b) => b.classList.contains("band-ai"));
      if (ev.length !== 1 || ai.length !== 1) v.push(`帯の数 公開データ=${ev.length} AI=${ai.length}`);
      const AI_MARK = /上位 \d+ %|クラスタ|モチーフ|意味空間|AI 推定|由緒テキスト/;
      const EV_MARK = /祭神|社格|成立日|文献上の母院|標高|最寄り河川|座標/;
      for (const b of bands) {
        const hs = b.querySelectorAll("h2, h3, h4");
        const head = hs[0]?.textContent ?? "(見出しなし)";
        if (hs.length !== 1) v.push(`見出しが ${hs.length} 個の帯: ${head}`);
        const text = [...b.children].filter((n) => !n.matches("h2, h3, h4")).map((n) => n.textContent).join(" ");
        if (!b.classList.contains("band-ai") && AI_MARK.test(text)) v.push(`AI の内容が「${head}」の下にある`);
        if (!b.classList.contains("band-evidence") && EV_MARK.test([...b.querySelectorAll("th")].map((t) => t.textContent).join(" "))) {
          v.push(`公開データの行が「${head}」の下にある`);
        }
      }
      return v;
    });
    // AI と祭神・社格が両方ある神社で確かめる(片方しか無い神社では混ざりようがなく、検査が空振りする)
    let g13Pick = null;
    let partPick = null;
    let plainPick = null;
    for (const f of chunkFiles) {
      const ch = JSON.parse(await readFile(path.join(OUT, "data/shrines", f), "utf-8"));
      g13Pick ??= ch.shrines.find((x) => x.ai_scores && x.deities && x.shrine_rank && x.name.ja);
      partPick ??= ch.shrines.find((x) => x.suspected_part && x.name.ja);
      plainPick ??= ch.shrines.find((x) => !x.suspected_part && x.name.ja);
      if (g13Pick && partPick && plainPick) break;
    }
    check("G-13: AI と祭神・社格を両方持つ神社が出荷物にある", !!g13Pick);
    if (g13Pick) {
      const openG13 = async () => {
        await page.goto(`${base}/shrine/?id=${g13Pick.id}&p=${g13Pick.location.pref_code}`, { waitUntil: "networkidle" });
        await settled();
      };
      await openG13();
      const v0 = await g13();
      check("G-13: 公開データと AI の意味分析が別の見出しの下にある", v0.length === 0, v0.join(" / "));
      // 陽性対照 1: AI の項目を公開データの帯へ移す
      await page.evaluate(() => {
        const li = document.querySelector(".band-ai li");
        document.querySelector(".band-evidence").appendChild(li);
      });
      const v1 = await g13();
      check("G-13 陽性対照: AI の項目を公開データの帯へ移すと検出する", v1.some((x) => x.startsWith("AI の内容")), v1.join(" / "));
      // 陽性対照 2: AI の帯の見出しを消す(AI の内容が社伝の見出しの下に続いて見える)
      await openG13();
      await page.evaluate(() => document.querySelector(".band-ai h3").remove());
      const v2 = await g13();
      check("G-13 陽性対照: AI の帯の見出しを消すと検出する", v2.some((x) => x.startsWith("見出しが 0 個")), v2.join(" / "));
      // 陽性対照 3: 祭神の行を AI の帯へ移す
      await openG13();
      await page.evaluate(() => {
        const tr = [...document.querySelectorAll(".band-evidence tr")].find((t) => t.textContent.includes("祭神"));
        const tb = document.createElement("table");
        tb.appendChild(tr);
        document.querySelector(".band-ai").appendChild(tb);
      });
      const v3 = await g13();
      check("G-13 陽性対照: 祭神の行を AI の帯へ移すと検出する", v3.some((x) => x.startsWith("公開データの行")), v3.join(" / "));
    }
    // D-08 / T-130: 社の部分の印は、印のある神社にだけ出る
    check("社の部分の印を持つ神社が出荷物にある", !!partPick && !!plainPick);
    if (partPick && plainPick) {
      await page.goto(`${base}/shrine/?id=${partPick.id}&p=${partPick.location.pref_code}`, { waitUntil: "networkidle" });
      await settled();
      const partBody = await page.locator("body").innerText();
      check("社の部分の印が詳細に出る", partBody.includes("社殿・境内の部分") && partBody.includes(partPick.suspected_part.suffix),
        `${partPick.id} ${partPick.name.ja}`);
      await page.goto(`${base}/shrine/?id=${plainPick.id}&p=${plainPick.location.pref_code}`, { waitUntil: "networkidle" });
      await settled();
      check("印の無い神社には社の部分の注記が出ない", !(await page.locator("body").innerText()).includes("社殿・境内の部分"),
        plainPick.id);
    }

    // 県コード無し(索引を引く経路)と、外れた県コード(索引へ引き直す経路)でも同じ神社が開くこと
    const pk0 = picks[0];
    const wrongP = picks.find((x) => x.p !== pk0.p)?.p ?? "99";
    for (const [label, url] of [["県コード無し", `/shrine/?id=${pk0.id}`],
                                ["外れた県コード", `/shrine/?id=${pk0.id}&p=${wrongP}`]]) {
      await page.goto(`${base}${url}`, { waitUntil: "networkidle" });
      await settled();
      const h1 = (await page.locator("h1").first().innerText()).trim();
      check(`${label}でも同じ神社が開く`, h1 === pk0.name, `h1=${h1}`);
    }
    // 陽性対照: 実在しない ID は「見つかりません」になる(何でも開いてしまう検査ではないこと)
    await page.goto(`${base}/shrine/?id=jinja_n1`, { waitUntil: "networkidle" });
    await settled();
    check("陽性対照: 実在しない ID は見つからないと言う",
      (await page.locator("h1").first().innerText()).includes("見つかりません"));
    // 旧 URL(/shrine/<id>/)は 404 ページの中で新しい形へ送られる
    await page.goto(`${base}/shrine/${pk0.id}/`, { waitUntil: "networkidle" });
    await page.waitForURL(/\/shrine\/\?id=/, { timeout: 15000 }).catch(() => {});
    check("旧 URL が新しい形へ送られる", page.url().includes(`/shrine/?id=${pk0.id}`), page.url());

    // D-08: 同じ社を指す地物の統合で消えた ID は、残った神社を開き、アドレス欄も置き換わる(T-127)
    const idxD08 = JSON.parse(await readFile(path.join(OUT, "data/shrines/index.json"), "utf-8"));
    const aliasEntries = Object.entries(idxD08.aliases ?? {});
    check("索引に統合の別名がある", aliasEntries.length > 0, `別名=${aliasEntries.length}`);
    let aliasChecked = false;
    for (const [oldId, newId] of aliasEntries.slice(0, 20)) {
      const newP = idxD08.ids[newId];
      const chunkD08 = JSON.parse(await readFile(path.join(OUT, `data/shrines/${newP}.json`), "utf-8"));
      const newName = chunkD08.shrines.find((x) => x.id === newId)?.name?.ja;
      if (!newName) continue; // 名前の無い神社は h1 で照合できない
      await page.goto(`${base}/shrine/?id=${oldId}`, { waitUntil: "networkidle" });
      await settled();
      const h1a = (await page.locator("h1").first().innerText()).trim();
      check("統合で消えた ID は残った神社を開く", h1a === newName, `${oldId} → h1=${h1a} 期待=${newName}`);
      check("アドレス欄が残った神社の ID に置き換わる", page.url().includes(`id=${newId}`), page.url());
      aliasChecked = true;
      break;
    }
    check("別名の転送を少なくとも 1 件確かめた", aliasChecked);

    // --- 意味空間(UMAP)-------------------------------------------------
    console.log("意味空間");
    await page.goto(`${base}/ai-space/`, { waitUntil: "networkidle" });
    await page.waitForSelector("svg circle", { timeout: 30000 });
    const ai = JSON.parse(await readFile(path.join(OUT, "data/ai/ai.min.json"), "utf-8"));
    const scatter = await page.evaluate(() => {
      const svg = document.querySelector("svg[role='img']");
      const cs = [...svg.querySelectorAll("circle")];
      const vb = svg.getAttribute("viewBox").split(/\s+/).map(Number);
      const outside = cs.filter((c) => {
        const x = +c.getAttribute("cx"), y = +c.getAttribute("cy");
        return x < vb[0] || x > vb[0] + vb[2] || y < vb[1] || y > vb[1] + vb[3];
      }).length;
      const fills = new Set(cs.map((c) => c.getAttribute("fill")));
      return { n: cs.length, outside, fills: [...fills] };
    });
    check("散布図の点の数がデータと一致する", scatter.n === ai.shrines.length,
      `描画=${scatter.n} データ=${ai.shrines.length}`);
    check("点がすべて viewBox の中にある(切れていない)", scatter.outside === 0,
      `外=${scatter.outside}`);
    check("しぼる前は単色である(カテゴリを色で塗り分けていない)", scatter.fills.length === 1,
      JSON.stringify(scatter.fills));

    // モチーフを選ぶと濃淡がつく(到達の証拠)
    await page.selectOption("fieldset select >> nth=0", { index: 1 });
    await page.waitForTimeout(400);
    const ramped = await page.evaluate(() => {
      const cs = [...document.querySelectorAll("svg[role='img'] circle")];
      return new Set(cs.map((c) => c.getAttribute("fill"))).size;
    });
    check("モチーフを選ぶと濃淡が複数段になる", ramped >= 3, `色数=${ramped}`);

    const aiText = await page.locator("body").innerText();
    check("意味空間に免責が出ている", aiText.includes("史実の関係ではない") ||
      aiText.includes("歴史的事実"));
    check("本文を配っていないことが書かれている", aiText.includes("本文も埋め込みベクトルも") ||
      aiText.includes("本文は配っていない"));

    // --- 類似神社 ---------------------------------------------------------
    console.log("類似神社");
    const someId = ai.shrines[0].id;
    const r3 = await page.goto(`${base}/similar/?id=${someId}`, { waitUntil: "networkidle" });
    check("類似ページが開く", r3?.status() === 200, `${someId} status=${r3?.status()}`);
    await settled();
    const simText = await page.locator("body").innerText();
    check("勧請の推論をしないと書いてある", simText.includes("勧請された、という意味ではない"));
    check("順位で表示している", simText.includes("上位") && simText.includes("全体の中での位置"));
    const rows = await page.locator("table >> nth=0 >> tbody tr").count();
    check("類似の一覧に行がある", rows > 0, `行=${rows}`);
    // 相手が詳細へのリンクになっていること(県コード付き。到達の証拠)
    const href = await page.locator("table >> nth=0 >> tbody tr >> nth=0 >> a").first().getAttribute("href");
    check("類似の相手が詳細へのリンクになっている", !!href && /^\/shrine\/\?id=jinja_[nwr]\d+&p=\d{2}$/.test(href),
      String(href));

    // --- 祭神の三面(T-151 / SPEC §7.14)----------------------------------
    console.log("祭神ページ");
    await page.setViewportSize({ width: 1280, height: 900 });
    const rDeity = await page.goto(`${base}/deity/`, { waitUntil: "networkidle" });
    check("祭神ページが開く", rDeity?.status() === 200, `status=${rDeity?.status()}`);

    const deityReport = JSON.parse(await readFile(path.join(OUT, "data/deity/report.json"), "utf-8"));
    const deityDetail = JSON.parse(await readFile(path.join(OUT, "data/deity/detail.json"), "utf-8"));

    await page.waitForSelector(".deity-panels h2");
    await page.waitForFunction(() => window.__deityMap?.isStyleLoaded?.() === true, { timeout: 30000 });

    // 三面が同じ一柱に従うこと。**到達の証拠を取ってから結果を見る**(HC-138) ——
    // 選び直して見出しが実際に変わったことを確かめてから、地図と表を数える。
    const before = await page.locator(".deity-panels h2").innerText();
    const pick = page.locator(".deity-list button", { hasText: "オオヤマツミ" }).first();
    await pick.scrollIntoViewIfNeeded();
    await pick.click();
    await page.waitForFunction(
      (prev) => document.querySelector(".deity-panels h2")?.innerText !== prev,
      before,
      { timeout: 10000 },
    );
    const after = await page.locator(".deity-panels h2").innerText();
    check("一柱を選ぶと見出しが変わる(操作が届いた証拠)", after !== before && after.includes("オオヤマツミ"), after);

    // 面 2: 地図に描かれた数が、出荷したデータの件数と一致する
    await page.evaluate(() => new Promise((r) => {
      const m = window.__deityMap;
      m.once("idle", r);
      m.triggerRepaint();
      setTimeout(r, 15000);
    }));
    const wantIds = deityDetail.deities.Q386563.ids.length;
    // **querySourceFeatures はタイルごとに返す。** タイル境界にかかる点は何度も出てくるので、
    // そのまま数えると実際より多くなる(2026-09-21 に 86 社が 180 と数えられた)。
    // 数えるのは要素の数ではなく、**別々の社の数**である(HC-080)。
    const drawn = await page.evaluate(() => {
      const m = window.__deityMap;
      const distinct = (src) =>
        new Set(m.querySourceFeatures(src).map((f) => f.properties.id)).size;
      return { picked: distinct("picked"), head: distinct("head") };
    });
    check("地図に選んだ祭神の社がデータの件数どおり載る", drawn.picked === wantIds,
      `地図=${drawn.picked} データ=${wantIds}`);
    check("総本社のピンが 1 つ載る", drawn.head === 1, `head=${drawn.head}`);

    // 面 1: 図の中身が viewBox に収まっているか(HC-159)。**ラベルは描画領域の外に出やすい**
    const clipped = await page.evaluate(() => {
      const svg = document.querySelector('.deity-panels svg[role="img"]');
      if (!svg) return { error: "図が無い" };
      const vb = svg.viewBox.baseVal;
      const out = [];
      for (const el of svg.querySelectorAll("text, circle, line")) {
        const b = el.getBBox();
        if (b.x < vb.x - 0.5 || b.y < vb.y - 0.5 ||
            b.x + b.width > vb.x + vb.width + 0.5 ||
            b.y + b.height > vb.y + vb.height + 0.5) {
          out.push(`${el.tagName}:${el.textContent?.slice(0, 8) ?? ""}`);
        }
      }
      return { total: svg.querySelectorAll("text, circle, line").length, outside: out };
    });
    check("図の要素が viewBox に収まっている", clipped.outside?.length === 0,
      JSON.stringify(clipped).slice(0, 300));
    check("図に要素がある(走査対象が空でない)", (clipped.total ?? 0) > 0, JSON.stringify(clipped.total));

    // **ラベルどうしの重なりを測る**(HC-317)。丸の重なりだけを見ていたせいで、
    // 「viewBox に収まる」「要素がある」が緑のまま読めない図を二度作った。
    const labelOverlap = await page.evaluate(() => {
      const svg = document.querySelector('.deity-panels svg[role="img"]');
      if (!svg) return { error: "図が無い" };
      const boxes = [...svg.querySelectorAll("text")].map((el) => ({
        t: el.textContent ?? "", b: el.getBBox(),
      }));
      const hits = [];
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i].b, c = boxes[j].b;
          if (a.x < c.x + c.width && c.x < a.x + a.width &&
              a.y < c.y + c.height && c.y < a.y + a.height) {
            hits.push(`${boxes[i].t}×${boxes[j].t}`);
          }
        }
      }
      return { labels: boxes.length, hits };
    });
    check("ラベルどうしが重なっていない", labelOverlap.hits?.length === 0,
      JSON.stringify(labelOverlap).slice(0, 300));
    check("ラベルの重なりの検査 陽性対照: 同じ矩形を二つ置けば撃つ",
      await page.evaluate(() => {
        const a = { x: 0, y: 0, width: 10, height: 10 };
        const c = { x: 5, y: 5, width: 10, height: 10 };
        return a.x < c.x + c.width && c.x < a.x + a.width &&
          a.y < c.y + c.height && c.y < a.y + a.height;
      }));

    // 畳みは同一視の対にだけ効く。八幡神は応神天皇と同一視の対なので、
    // 畳むと中心の名が「八幡神・応神天皇」になる。**到達の証拠は図の中心の名**。
    const pickHachiman = page.locator(".deity-list button", { hasText: "八幡神" }).first();
    await pickHachiman.scrollIntoViewIfNeeded();
    await pickHachiman.click();
    await page.waitForFunction(
      () => document.querySelector(".deity-panels h2")?.innerText.includes("八幡神"),
      null, { timeout: 10000 },
    );
    const centreOf = () => page.evaluate(() => {
      const svg = document.querySelector('.deity-panels svg[role="img"]');
      return svg?.querySelector("text[font-weight='700']")?.textContent ?? "";
    });
    const centreBefore = await centreOf();
    await page.locator(".deity-toggle input").check();
    await page.waitForTimeout(400);
    const centreAfter = await centreOf();
    check("同一視の対を畳むと中心が一つの柱になる",
      !centreBefore.includes("応神天皇") && centreAfter.includes("八幡神") &&
        centreAfter.includes("応神天皇"),
      `${centreBefore} → ${centreAfter}`);
    await page.locator(".deity-toggle input").uncheck();
    await page.waitForTimeout(300);
    check("畳みを戻すと中心も戻る", (await centreOf()) === centreBefore);

    // **画面の主張はレポートに従う**(HC-079)。測って落ちた予測を、通ったかのように書かない。
    const deityText = await page.locator("main").innerText();
    const claims = ["総本社が浮かび上がる", "総本社を当てる", "総本社が浮かぶ"];
    const claimed = claims.filter((c) => deityText.includes(c));
    check("G-16 が不合格なのに『総本社が浮かび上がる』と書いていない",
      deityReport.g16.pass || claimed.length === 0, claimed.join(" / "));
    check("測った的中数が画面に出ている",
      deityText.includes(`${deityReport.g16.hit} / ${deityReport.g16.total}`),
      `${deityReport.g16.hit}/${deityReport.g16.total}`);
    check("主張の検査 陽性対照: 主張の語があれば撃つ",
      claims.filter((c) => "ここでは総本社が浮かび上がる".includes(c)).length > 0);

    // --- 複数の画面幅で横溢れを見る(HC-078) ------------------------------
    console.log("画面幅");
    for (const [w, h] of [[360, 780], [768, 900], [1280, 900], [1680, 1000]]) {
      for (const route of ["/", "/map/", "/deity/", "/ai-space/", "/sources/", "/analytics/", "/about-ai/"]) {
        await page.setViewportSize({ width: w, height: h });
        await page.goto(`${base}${route}`, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(250);
        const m = await page.evaluate(() => ({
          sw: document.documentElement.scrollWidth,
          cw: document.documentElement.clientWidth,
          sh: document.documentElement.scrollHeight,
        }));
        check(`${route} @${w}px 横に溢れない`, m.sw <= m.cw + 1, `scrollWidth=${m.sw} clientWidth=${m.cw}`);
        check(`${route} @${w}px 縦に伸びすぎない`, m.sh < 16000, `scrollHeight=${m.sh}`);
      }
    }

    // --- 画面の範囲の文が出荷物と合っているか(T-132 / HC-280)----------------
    // 数値の欄はビルド報告を読むので自動で変わるが、**隣の散文は書き込んだまま残る**。
    // 全国版を出してから 5 ループ、3 都府県版の範囲と結論の文が本番に出ていた。
    console.log("範囲の文");
    const buildRep = JSON.parse(await readFile(path.join(OUT, "data/meta/build.json"), "utf-8"));
    const STALE = ["東京都・京都府・山梨県", "3 都府県", "段階 1", "成り立ったのは一つだけ"];
    const scopeProblems = (text) => {
      const out = [];
      if (!text.includes(`全国 ${buildRep.chunks} 都道府県`)) out.push(`「全国 ${buildRep.chunks} 都道府県」が無い`);
      for (const s of STALE) if (text.includes(s)) out.push(`旧範囲の語「${s}」がある`);
      return out;
    };
    check("範囲の検査 陽性対照: 旧範囲の文を検出する",
      scopeProblems("現在の公開範囲は東京都・京都府・山梨県の 3 都府県").length >= 2);
    check("範囲の検査 陰性対照: 正しい文は通す", scopeProblems(`全国 ${buildRep.chunks} 都道府県の神社`).length === 0);
    for (const route of ["/", "/map/", "/analytics/"]) {
      await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
      const problems = scopeProblems(await page.locator("main").innerText());
      check(`${route} の範囲の文が出荷物(${buildRep.chunks} 都道府県)と合う`, problems.length === 0, problems.join(" / "));
    }

    // --- フッタが常時見えるか --------------------------------------------
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
    const footerVisible = await page.locator(".site-footer").isVisible();
    check("フッタが表示されている", footerVisible);

    // フリート共通のフッタ規約。**HTML を文字列で grep しない** ——
    // MIT License のリンク先(github.com/.../LICENSE)が GitHub 項目より先に当たり、
    // 「並びが規約と違う」を大量にでっち上げる。描画して DOM の innerText で見る。
    const footer = await page.evaluate(() => {
      const f = document.querySelector(".site-footer");
      return {
        text: f ? f.innerText.replace(/\s+/g, " ").trim() : "",
        links: f ? [...f.querySelectorAll("a")].map((a) => [a.innerText.trim(), a.href]) : [],
        fixed: f ? getComputedStyle(f).position : "",
      };
    });
    check("フッタが下部固定である", footer.fixed === "fixed", footer.fixed);
    check("フッタに MIT License がある", footer.text.includes("MIT License"));
    check("フッタに App Menu がある", footer.text.includes("App Menu"));
    const appMenu = footer.links.find(([t]) => t === "App Menu");
    check(
      "App Menu が本番(app-menu-amber)を指している",
      !!appMenu && appMenu[1].includes("app-menu-amber.vercel.app"),
      appMenu ? appMenu[1] : "(リンクが無い)",
    );
    const gh = footer.links.find(([t]) => t === "GitHub");
    check(
      "GitHub がこのリポジトリを指している",
      !!gh && gh[1].includes("github.com/twill3c/jinja-origin-atlas-ai"),
      gh ? gh[1] : "(リンクが無い)",
    );
    // 宛先の無いリンクを残さない。最初の実装は `https://github.com/`(ドメインだけ)で、
    // 押しても GitHub のトップに飛ぶだけだった。
    // **「ドメイン直下は全部だめ」とは書けない** —— App Menu はドメイン直下が正しい宛先である。
    // 捕まえるのは「そのサービスの中で個別のものを指していないリンク」に限る。
    const NEEDS_PATH = ["github.com", "wikipedia.org", "wikidata.org"];
    const bare = footer.links.filter(([, href]) => {
      try {
        const u = new URL(href);
        return NEEDS_PATH.some((h) => u.hostname.endsWith(h)) && u.pathname.replace(/\/+$/, "") === "";
      } catch {
        return true;
      }
    });
    check("フッタに宛先のないリンクが無い", bare.length === 0, JSON.stringify(bare));

    // 旧 URL は**意図的に**踏んでいる(D-06 の転送はその 404 の上で成り立つ)。
    // その 1 件だけを織り込み、**ほかの 404 は落とす**。
    const isLegacy = (r) => /\/(shrine|similar)\/jinja_[nwr]\d+\/?$/.test(new URL(r.url).pathname);
    const legacy404 = badResponses.filter(isLegacy);
    const unexpected = badResponses.filter((r) => !isLegacy(r));
    check("旧 URL が実際に 404 を返している(転送はその上で働く)", legacy404.length > 0,
      JSON.stringify(badResponses.slice(0, 3)));
    check("ほかに 404 になった資源が無い", unexpected.length === 0,
      JSON.stringify(unexpected.slice(0, 3)));
    const realErrors = consoleErrors.filter((t) => !/Failed to load resource/.test(t));
    check("コンソールエラーが無い(資源の 404 を除く)", realErrors.length === 0,
      realErrors.slice(0, 3).join(" | "));

    if (WANT_SHOT) {
      await mkdir(SHOTS, { recursive: true });
      // AI の画面も撮る。撮影の一覧に無い画面は、中身が大きく変わっても(701 → 3,356 点)
      // 目で見られないまま出荷される(loop_008 で ai_space.png が 5 日前のままだった)。
      for (const [route, name] of [
        ["/", "home"], ["/map/", "map"], ["/sources/", "sources"],
        ["/ai-space/", "ai_space"], [`/similar/?id=${someId}`, "similar"], ["/about-ai/", "about_ai"],
        ["/deity/?q=Q386563", "deity"],
      ]) {
        await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
        if (route === "/ai-space/") await page.waitForSelector("svg circle", { timeout: 30000 });
        if (route.startsWith("/deity/")) {
          await page.waitForSelector('.deity-panels svg[role="img"] circle', { timeout: 30000 });
          await page.waitForFunction(() => window.__deityMap?.isStyleLoaded?.() === true, { timeout: 30000 });
          await page.evaluate(async () => {
            const m = window.__deityMap;
            m.resize();
            await new Promise((r) => { m.once("idle", r); m.triggerRepaint(); setTimeout(r, 15000); });
            await new Promise((r) => { m.triggerRepaint(); m.once("render", r); });
          });
          await page.waitForTimeout(1500);
        }
        if (route.startsWith("/similar/")) await page.waitForSelector("table tbody tr", { timeout: 30000 });
        if (route === "/map/") {
          await page.waitForFunction(() => window.__jinjaMap?.isStyleLoaded?.() === true, { timeout: 30000 });
          // 撮影の前に再描画を強制する。WebGL の描画バッファは保持されないので、
          // 直前に描き直さないと**古い(あるいは空の)バッファ**が写る(HC-194)。
          await page.evaluate(async () => {
            const m = window.__jinjaMap;
            m.resize();
            await new Promise((r) => { m.once("idle", r); m.triggerRepaint(); setTimeout(r, 15000); });
            await new Promise((r) => { m.triggerRepaint(); m.once("render", r); });
          });
          await page.waitForTimeout(1500);
        }
        // **撮影は嘘をつく**(HC-194)。固定フッタはキャンバスの上に焼き込まれ、
        // ビューポート撮影では地図の上下に「空白の帯」が写る —— fullPage でなくても起きる。
        // 2026-09-08 にこれを実装の欠陥と誤診して 3 度直そうとした。
        // 地図は**要素単位で**撮り、フッタは撮影中だけ退ける。
        await page.evaluate(() => {
          const f = document.querySelector(".site-footer");
          if (f) f.style.visibility = "hidden";
        });
        if (route === "/map/") {
          await page.locator(".maplibregl-map").screenshot({ path: path.join(SHOTS, `${name}.png`) });
        } else {
          await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
        }
        await page.evaluate(() => {
          const f = document.querySelector(".site-footer");
          if (f) f.style.visibility = "";
        });
        console.log(`  撮影 → artifacts/screenshots/${name}.png`);
      }
    }
  } finally {
    await browser.close();
    server.close();
  }

  console.log("");
  if (failures.length) {
    console.error(`検品 NG — ${failures.length} 件`);
    for (const f of failures) console.error(`  - ${f}`);
    process.exit(1);
  }
  console.log("検品 OK");
}

main().catch((e) => {
  console.error("検品器そのものが落ちた:", e);
  process.exit(3);
});
