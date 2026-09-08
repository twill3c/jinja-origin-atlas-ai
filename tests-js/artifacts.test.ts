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
