/**
 * T-032 ほか: 出荷される静的ファイルそのものに対する検査。
 * ソースではなく `out/` を見る — 配られる木で成り立っていることを確かめるため(HC-062)。
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const OUT = path.join(process.cwd(), "out");
const hasOut = fs.existsSync(OUT);
const d = hasOut ? describe : describe.skip;

function html(route: string): string {
  return fs.readFileSync(path.join(OUT, route, "index.html"), "utf-8");
}

d("出荷アーティファクト", () => {
  it("T-032: 地図ページに OSM の出典が JavaScript 抜きで含まれる", () => {
    const h = html("map");
    expect(h).toContain("© OpenStreetMap contributors");
    expect(h).toContain("国土地理院");
  });

  it("T-032b: 出典ページに ODbL とライセンス URL がある", () => {
    const h = html("sources");
    expect(h).toContain("ODbL");
    expect(h).toContain("https://www.openstreetmap.org/copyright");
  });

  it("AI 画面に免責が出ている(SPEC F-13 / 仕様書 §46)", () => {
    const h = html("about-ai");
    expect(h).toContain("歴史的事実");
    expect(h).toContain("証明するものではありません");
  });

  it("陽性対照: この検査は実際に文字列を見ている", () => {
    // 対照が成り立つ前提 — 出荷 HTML に絶対に無い文字列は落ちること。
    const h = html("map");
    expect(h).not.toContain("__この文字列は出荷物に存在しない__");
  });

  it("課金経路ゼロ(SPEC N-01 / G-05): 有料 API のホスト名が出荷物に無い", () => {
    const forbidden = [
      "api.openai.com",
      "api.anthropic.com",
      "generativelanguage.googleapis.com",
      "api.mapbox.com",
      "api.maptiler.com",
    ];
    const files = fs
      .readdirSync(OUT, { recursive: true, encoding: "utf-8" })
      .filter((f) => /\.(html|js|json)$/.test(f))
      .map((f) => path.join(OUT, f))
      .filter((f) => fs.statSync(f).isFile());
    expect(files.length).toBeGreaterThan(0);
    for (const f of files) {
      const body = fs.readFileSync(f, "utf-8");
      for (const host of forbidden) {
        expect(body, `${f} に ${host} が現れた`).not.toContain(host);
      }
    }
  });

  it("静的書き出しに serverless function が含まれない(RULE-07)", () => {
    // out/ 配下は静的ファイルだけであること。
    expect(fs.existsSync(path.join(OUT, "map", "index.html"))).toBe(true);
    expect(fs.existsSync(path.join(process.cwd(), ".next", "server", "app", "api"))).toBe(false);
  });
});

/**
 * Python が書く JSON と TypeScript が読む型の契約。
 * この検査が無かったため、`export/build_public.py` が build.json の欄を差し替えたとき
 * pytest 116 件が全部緑のまま静的書き出しが TypeError で落ちた(HC-190)。
 * **境界をまたぐ契約は、両側から触れる場所に置く。**
 */
describe("Python↔TypeScript の JSON 契約", () => {
  const dataDir = path.join(process.cwd(), "public", "data");
  const hasData = fs.existsSync(path.join(dataDir, "meta", "build.json"));
  const t = hasData ? it : it.skip;

  t("build.json が UI の読む数値欄をすべて持つ", async () => {
    const { BUILD_REPORT_NUMERIC_KEYS } = await import("../lib/types");
    const r = JSON.parse(fs.readFileSync(path.join(dataDir, "meta", "build.json"), "utf-8"));
    for (const k of BUILD_REPORT_NUMERIC_KEYS) {
      expect(typeof r[k], `build.json に ${k} が無い(または数値でない)`).toBe("number");
    }
    expect(typeof r.family_counts).toBe("object");
    expect(typeof r.family_basis).toBe("object");
    expect(typeof r.signal_agreement.both_known).toBe("number");
    expect(typeof r.signal_agreement.agree).toBe("number");
  });

  t("陽性対照: 欄がひとつ欠けたら落ちる", async () => {
    const { BUILD_REPORT_NUMERIC_KEYS } = await import("../lib/types");
    const r = JSON.parse(fs.readFileSync(path.join(dataDir, "meta", "build.json"), "utf-8"));
    // 対照が成り立つ前提 —— 検査対象の欄一覧が空でないこと
    expect(BUILD_REPORT_NUMERIC_KEYS.length).toBeGreaterThan(5);
    const broken = { ...r };
    delete broken[BUILD_REPORT_NUMERIC_KEYS[0]];
    const missing = BUILD_REPORT_NUMERIC_KEYS.filter((k) => typeof broken[k] !== "number");
    expect(missing).toEqual([BUILD_REPORT_NUMERIC_KEYS[0]]);
  });

  t("families.min.json のラベルが GeoJSON の family 値をすべて覆う", () => {
    const fam = JSON.parse(fs.readFileSync(path.join(dataDir, "catalog", "families.min.json"), "utf-8"));
    const fc = JSON.parse(fs.readFileSync(path.join(dataDir, "osm", "shrines.min.geojson"), "utf-8"));
    const used = new Set<string>(fc.features.map((f: { properties: { family: string } }) => f.properties.family));
    expect(used.size).toBeGreaterThan(1);
    for (const k of used) {
      expect(Object.keys(fam.labels), `families.min.json に ${k} のラベルが無い`).toContain(k);
    }
  });
});
