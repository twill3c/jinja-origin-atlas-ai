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
import { readFile, mkdir, stat } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const OUT = path.join(process.cwd(), "out");
const SHOTS = path.join(process.cwd(), "artifacts", "screenshots");
const WANT_SHOT = process.argv.includes("--shot");

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
  const browser = await chromium.launch();
  const consoleErrors = [];

  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(m.text());
    });
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

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
    await page.evaluate(() => new Promise((r) => window.__jinjaMap.once("idle", r)));
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

    // --- 陽性対照: この検品器は実際に異常を捕まえるか --------------------
    // 状態を変えたら再描画を待ってから読む。同期的に読むと変更前の値が返り、
    // 対照は「撃たない」形で静かに死ぬ(HC-222)。
    const controlDetects = await page.evaluate(async () => {
      const m = window.__jinjaMap;
      const idle = () => new Promise((r) => m.once("idle", r));
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

    // --- 複数の画面幅で横溢れを見る(HC-078) ------------------------------
    console.log("画面幅");
    for (const [w, h] of [[360, 780], [768, 900], [1280, 900], [1680, 1000]]) {
      for (const route of ["/", "/map/", "/sources/", "/analytics/", "/about-ai/"]) {
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

    // --- フッタが常時見えるか --------------------------------------------
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
    const footerVisible = await page.locator(".site-footer").isVisible();
    check("フッタが表示されている", footerVisible);

    check("コンソールエラーが無い", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

    if (WANT_SHOT) {
      await mkdir(SHOTS, { recursive: true });
      for (const [route, name] of [["/", "home"], ["/map/", "map"], ["/sources/", "sources"]]) {
        await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
        if (route === "/map/") {
          await page.waitForFunction(() => window.__jinjaMap?.isStyleLoaded?.() === true, { timeout: 30000 });
          await page.waitForTimeout(2500);
        }
        // 固定フッタが途中に焼き込まれるので fullPage は使わない(HC-194)
        await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
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
