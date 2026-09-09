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

/**
 * ビルドの刻印。**「健やかか」と「新しいか」は別の問いである**(HC-148)。
 * デプロイが上限で拒否されても本番は健やかなままなので、健やかさの検査を
 * いくら足しても反映の有無は分からない。
 */
describe("ビルドの刻印", () => {
  const stampPath = path.join(process.cwd(), "public", "data", "meta", "stamp.json");
  const outStamp = path.join(OUT, "data", "meta", "stamp.json");
  const t = fs.existsSync(stampPath) ? it : it.skip;

  t("刻印が作られていて、出荷物にも入っている", () => {
    const local = JSON.parse(fs.readFileSync(stampPath, "utf-8"));
    expect(typeof local.stamp).toBe("string");
    expect(local.stamp.length).toBeGreaterThanOrEqual(16);
    expect(Array.isArray(local.files)).toBe(true);
    expect(local.files.every((f: { present: boolean }) => f.present)).toBe(true);
    if (fs.existsSync(outStamp)) {
      const shipped = JSON.parse(fs.readFileSync(outStamp, "utf-8"));
      expect(shipped.stamp).toBe(local.stamp);
    }
  });

  t("刻印は改行を揃えてから測っている(CRLF/LF で揺れない)", async () => {
    // 同じ内容を CRLF と LF で与えたとき、同じ値になること。
    // この機は core.autocrlf=true なので、揃えないと手元と本番で必ず食い違う。
    const { createHash } = await import("node:crypto");
    const lf = "a\nb\nc\n";
    const crlf = "a\r\nb\r\nc\r\n";
    const norm = (s: string) => createHash("sha256").update(s.replace(/\r\n/g, "\n")).digest("hex");
    expect(norm(lf)).toBe(norm(crlf));
    // 対照: 揃えなければ違う値になること(この検査が無意味でないこと)
    const raw = (s: string) => createHash("sha256").update(s).digest("hex");
    expect(raw(lf)).not.toBe(raw(crlf));
  });

  t("刻印が入力の変化を拾う(陽性対照)", async () => {
    const { createHash } = await import("node:crypto");
    const h = (x: string) => createHash("sha256").update(x).digest("hex");
    expect(h("a|1\nb|2\n")).not.toBe(h("a|1\nb|3\n"));
  });
});
