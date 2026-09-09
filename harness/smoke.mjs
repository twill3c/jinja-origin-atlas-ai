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

    // --- 系統のしぼり: 操作が届いた証拠を見る(HC-138) ----------------------
    console.log("系統のしぼり");
    const box = page.locator('fieldset input[type="checkbox"]').first();
    const label = await page.locator("fieldset label").first().innerText();
    await box.scrollIntoViewIfNeeded();
    await box.check();
    await page.evaluate(() => new Promise((r) => window.__jinjaMap.once("idle", r)));
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
    await page.evaluate(() => new Promise((r) => window.__jinjaMap.once("idle", r)));
    const cleared = await page.evaluate(() => ({
      rendered: window.__jinjaMap.queryRenderedFeatures({ layers: ["highlight-point"] }).length,
      clusterColor: window.__jinjaMap.getPaintProperty("clusters", "circle-color"),
    }));
    check("しぼりを外すと元に戻る",
      cleared.rendered === 0 && cleared.clusterColor === "#b7410e", JSON.stringify(cleared));

    // --- 神社詳細ページ ---------------------------------------------------
    console.log("神社詳細");
    const shrineIds = Object.keys(
      JSON.parse(await readFile(path.join(OUT, "data/catalog/shrines.min.json"), "utf-8"))
        .shrines.filter((s) => s.external_ids.wikidata && s.name.ja)
        .slice(0, 1)
        .reduce((a, s) => ({ ...a, [s.id]: 1 }), {}),
    );
    if (shrineIds.length) {
      const r2 = await page.goto(`${base}/shrine/${shrineIds[0]}/`, { waitUntil: "domcontentloaded" });
      check("詳細ページが開く", r2?.status() === 200, `${shrineIds[0]} status=${r2?.status()}`);
      const body = await page.locator("body").innerText();
      check("詳細に三区分の見出しが出ている",
        body.includes("公開データで確認できること") && body.includes("社伝") && body.includes("AI が文章から測ったこと"));
      check("詳細に出典が出ている", body.includes("OpenStreetMap") && body.includes("Wikidata"));
      check("名寄せに直リンクを使っていないことが書かれている", body.includes("使っていない"));
    }

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
    const r3 = await page.goto(`${base}/similar/${someId}/`, { waitUntil: "domcontentloaded" });
    check("類似ページが開く", r3?.status() === 200, `${someId} status=${r3?.status()}`);
    const simText = await page.locator("body").innerText();
    check("勧請の推論をしないと書いてある", simText.includes("勧請された、という意味ではない"));
    check("順位で表示している", simText.includes("上位") && simText.includes("全体の中での位置"));
    const rows = await page.locator("table >> nth=0 >> tbody tr").count();
    check("類似の一覧に行がある", rows > 0, `行=${rows}`);

    // --- 複数の画面幅で横溢れを見る(HC-078) ------------------------------
    console.log("画面幅");
    for (const [w, h] of [[360, 780], [768, 900], [1280, 900], [1680, 1000]]) {
      for (const route of ["/", "/map/", "/ai-space/", "/sources/", "/analytics/", "/about-ai/"]) {
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

    check("コンソールエラーが無い", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));

    if (WANT_SHOT) {
      await mkdir(SHOTS, { recursive: true });
      for (const [route, name] of [["/", "home"], ["/map/", "map"], ["/sources/", "sources"]]) {
        await page.goto(`${base}${route}`, { waitUntil: "networkidle" });
        if (route === "/map/") {
          await page.waitForFunction(() => window.__jinjaMap?.isStyleLoaded?.() === true, { timeout: 30000 });
          // 撮影の前に再描画を強制する。WebGL の描画バッファは保持されないので、
          // 直前に描き直さないと**古い(あるいは空の)バッファ**が写る(HC-194)。
          await page.evaluate(async () => {
            const m = window.__jinjaMap;
            m.resize();
            await new Promise((r) => m.once("idle", r));
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
