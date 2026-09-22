"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import DeityMap, { type HeadPin } from "./DeityMap";
import DeityNetwork from "./DeityNetwork";
import {
  PAIR_TYPE_JA,
  type DeityIndex,
  type DetailDoc,
  type NetworkDoc,
  type PairsDoc,
  type PointsDoc,
  type ReportDoc,
} from "@/lib/deity-types";

/* 祭神を一柱選ぶと、三つの面が同じ祭神について同時に答える。
 *
 *   誰と並ぶか  → 共祀ネットワーク(同一視の辺だけ畳める)
 *   どこに濃いか → 点の地図と県別リフト(**県は塗らない**)
 *   何という名で → 習合の対応表(手で分類した 51 組だけ)
 *
 * **画面の主張はレポートに従う**(HC-079)。「総本社が浮かび上がる」と書いてよいのは
 * `report.g16.pass` が真のときだけで、実測は偽である(7/26・SPEC §7.14)。
 * 測って見せるだけの数に良し悪しの色を付けない。 */

const QID_RE = /^Q\d+$/;

type Loaded = {
  index: DeityIndex;
  points: PointsDoc;
  detail: DetailDoc;
  network: NetworkDoc;
  pairs: PairsDoc;
  report: ReportDoc;
};

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} が読めない(HTTP ${r.status})`);
  return (await r.json()) as T;
}

function jp(n: number): string {
  return n.toLocaleString("ja-JP");
}

export default function DeityExplorer() {
  const params = useSearchParams();
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getJson<DeityIndex>("/data/deity/index.json"),
      getJson<PointsDoc>("/data/deity/points.json"),
      getJson<DetailDoc>("/data/deity/detail.json"),
      getJson<NetworkDoc>("/data/deity/network.json"),
      getJson<PairsDoc>("/data/deity/pairs.json"),
      getJson<ReportDoc>("/data/deity/report.json"),
    ])
      .then(([index, points, detail, network, pairs, report]) => {
        if (cancelled) return;
        setData({ index, points, detail, network, pairs, report });
        const q = params.get("q");
        setSelected(q && QID_RE.test(q) && detail.deities[q]
          ? q
          : index.deities[0]?.qid ?? null);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
    // 初回だけ読む。選択は URL に書き戻すが、読み直しはしない
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = useCallback((qid: string) => {
    setSelected(qid);
    const u = new URL(window.location.href);
    u.searchParams.set("q", qid);
    window.history.replaceState(null, "", u.toString());
  }, []);

  const pointsById = useMemo(() => {
    const m = new Map<string, PointsDoc["shrines"][number]>();
    for (const p of data?.points.shrines ?? []) m.set(p.id, p);
    return m;
  }, [data]);

  const current = useMemo(() => {
    if (!data || !selected) return null;
    const meta = data.index.deities.find((d) => d.qid === selected) ?? null;
    const det = data.detail.deities[selected] ?? null;
    if (!meta || !det) return null;
    const head = data.report.g16.rows.find((r) => r.deity_qid === selected) ?? null;
    const pairs = data.pairs.pairs.filter(
      (p) => p.a_qid === selected || p.b_qid === selected,
    );
    return {
      meta,
      det,
      head,
      pairs,
      shrines: det.ids.map((id) => pointsById.get(id)).filter(Boolean) as
        PointsDoc["shrines"],
    };
  }, [data, selected, pointsById]);

  const filtered = useMemo(() => {
    const list = data?.index.deities ?? [];
    const q = query.trim();
    return q ? list.filter((d) => d.name.includes(q)) : list;
  }, [data, query]);

  if (error) return <p className="notice" role="alert">{error}</p>;
  if (!data || !current) return <p role="status">読み込み中…</p>;

  const t = data.index.totals;
  const g16 = data.report.g16;
  const g17 = data.report.g17;
  const g20 = data.report.g20;
  const headPin: HeadPin = current.head
    ? {
        name: current.head.head_shrine,
        pref: current.head.head_pref,
        lat: current.head.lat,
        lon: current.head.lon,
      }
    : null;

  return (
    <>
      <div className="notice">
        Wikidata が日本の神社に書き込んだ祭神は延べ {jp(t.mentions)} 件・{jp(t.deities)} 柱。
        これは全国 {jp(t.shrines_total)} 社のうち <strong>{jp(t.shrines_with_deities)} 社
        ({((t.shrines_with_deities / t.shrines_total) * 100).toFixed(1)}%)</strong> にしか
        付いていない。しかも無作為な一割ではなく、Wikidata に項目がある著名な社に偏っている。
        以下は<strong>日本の信仰の分布ではなく、Wikidata の収録の分布</strong>である。
      </div>

      <div className="deity-layout">
        <div className="deity-list">
          <label className="deity-search">
            <span>祭神を探す</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="八幡神・稲荷神…"
            />
          </label>
          <p className="deity-count">
            {jp(filtered.length)} / {jp(t.deities)} 柱
          </p>
          <ul>
            {filtered.map((d) => (
              <li key={d.qid}>
                <button
                  type="button"
                  onClick={() => select(d.qid)}
                  aria-current={d.qid === selected ? "true" : undefined}
                  className={d.qid === selected ? "is-selected" : undefined}
                >
                  <span>{d.name}</span>
                  <span className="deity-n">{jp(d.n)}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="deity-panels">
          <h2 className="deity-head">
            {current.meta.name}
            <small>
              {jp(current.meta.n)} 社
              <a
                href={`https://www.wikidata.org/wiki/${current.meta.qid}`}
                rel="noreferrer"
                target="_blank"
              >
                {current.meta.qid}
              </a>
            </small>
          </h2>

          <section className="band band-evidence">
            <h3>誰と並ぶか —— 同じ社に並ぶ祭神</h3>
            <p>
              選んだ一柱を中心に置き、同じ社に並ぶ相手を環に並べた図
              (最大 {data.network.params.cap} 柱)。相手は型でまとめて並べてある。
              <strong>最も太い辺は「二柱が並んでいる」ではなく「同じ一柱が二つの名で書かれている」</strong>
              —— 八幡神と応神天皇、牛頭天王と素戔嗚尊。押して畳むと、その対が一つの柱になる。
            </p>
            <label className="deity-toggle">
              <input
                type="checkbox"
                checked={collapsed}
                onChange={(e) => setCollapsed(e.target.checked)}
              />
              <span>
                同一視の対を畳む(
                {jp(data.report.network.merged_groups)} 組・
                {jp(data.report.network.merged_deities)} 柱が {jp(data.report.network.merged_groups)} 柱になる
                {!data.network.collapsed_of[current.meta.qid] && " —— この祭神の図は変わらない"})
              </span>
            </label>
            <DeityNetwork
              doc={data.network}
              collapsed={collapsed}
              selected={current.meta.qid}
              onSelect={select}
            />
            <p className="deity-fine">
              同じ社に並ぶ対は全部で {jp(data.report.network.pairs_total)} 通りある。
              そのうち手で型を付けたのは共起 {data.pairs.threshold} 回以上の
              {jp(data.report.pairs.labeled)} 通りだけで、残り
              {jp(data.report.network.by_type.unlabeled ?? 0)} 通りは<strong>未分類</strong>
              のまま薄く描いている。推測で型は付けない。
            </p>
          </section>

          <section className="band band-evidence">
            <h3>どこに濃いか —— 点の地図と県別リフト</h3>
            <p>
              {current.meta.name}を祀る {jp(current.shrines.length)} 社を朱で示す
              (灰色は祭神が付いている社すべて)。
              <strong>県は塗らない</strong> —— 数社を県全体に塗ると、正しい数字が面積という
              嘘に化けるため。青い輪は総本社。
            </p>
            <DeityMap
              all={data.points.shrines}
              selected={current.shrines}
              head={headPin}
              label={current.meta.name}
            />
            <div className="scroll-x">
              <table>
                <caption>
                  県別のリフト(実際の社数 ÷ 期待値)。期待値は祭神つき社そのものの県分布から出す。
                  該当 {data.detail.floor} 社未満の県は順位付けに使わない。
                </caption>
                <thead>
                  <tr>
                    <th scope="col">県</th>
                    <th scope="col">社</th>
                    <th scope="col">期待</th>
                    <th scope="col">リフト</th>
                  </tr>
                </thead>
                <tbody>
                  {current.det.prefs.slice(0, 8).map((r) => (
                    <tr key={r.pref}>
                      <th scope="row">
                        {r.pref}
                        {current.head && r.pref === current.head.head_pref && (
                          <span className="deity-headmark"> 総本社</span>
                        )}
                      </th>
                      <td>{jp(r.n)}</td>
                      <td>{r.expected.toFixed(1)}</td>
                      <td>{r.n >= data.detail.floor ? r.lift?.toFixed(2) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {current.head && (
              <p className="deity-fine">
                総本社は{current.head.head_shrine}({current.head.head_pref})。
                リフト最上位は{current.head.top_pref ?? "—"}で、
                {current.head.hit ? "一致している" : "一致しない"}。
                {current.head.below_floor && (
                  <>
                    {" "}
                    {current.head.head_pref}に収録されている{current.meta.name}の社は
                    {jp(current.head.head_pref_n)} 社しかない
                    (この県の祭神つき社は {jp(current.head.head_pref_base)} 社)。
                  </>
                )}
              </p>
            )}
          </section>

          <section className="band band-tradition">
            <h3>何という名で呼ばれるか —— 習合の対応表</h3>
            {current.pairs.length === 0 ? (
              <p>
                {current.meta.name}を含む対は、手で分類した {jp(data.report.pairs.labeled)} 組
                (共起 {data.pairs.threshold} 回以上)の中に無い。<strong>未分類</strong>であって、
                「関係が無い」という意味ではない。
              </p>
            ) : (
              <div className="scroll-x">
                <table>
                  <caption>
                    {current.meta.name}を含む対。型は手で付けた
                    ({Object.entries(data.report.pairs.by_type)
                      .map(([k, v]) => `${PAIR_TYPE_JA[k as never] ?? k} ${v}`)
                      .join("・")})。
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">相手</th>
                      <th scope="col">型</th>
                      <th scope="col">同じ社</th>
                      <th scope="col">なぜ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {current.pairs.map((p) => {
                      const other = p.a_qid === selected ? p.b : p.a;
                      const otherQid = p.a_qid === selected ? p.b_qid : p.a_qid;
                      return (
                        <tr key={`${p.a_qid}-${p.b_qid}`}>
                          <th scope="row">
                            <button type="button" className="linkish"
                              onClick={() => select(otherQid)}>
                              {other}
                            </button>
                          </th>
                          <td>{PAIR_TYPE_JA[p.type]}</td>
                          <td>{jp(p.w)}</td>
                          <td>{p.note ?? "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>

      <section className="band band-evidence" id="measured">
        <h3>測ったこと —— 登録した予測は二つとも落ちた</h3>
        <p>
          作る前に合否線を決め、機械に判定させた。<strong>どちらも落ちた。</strong>
          落ちたことを消さずに書いておく。
        </p>
        <div className="scroll-x">
          <table>
            <tbody>
              <tr>
                <th scope="row">リフトは総本社を指すか(G-16)</th>
                <td>
                  {g16.hit} / {g16.total} 柱(合格線 {g16.threshold})。
                  <strong>不合格。</strong>外れた {g16.total - g16.hit} 柱のうち
                  {g16.misses_below_floor} 柱は、総本社のある県にその祭神の社が
                  {g16.floor} 社も収録されていない。
                </td>
              </tr>
              <tr>
                <th scope="row">それでも偶然ではないか(G-20)</th>
                <td>
                  祭神の割り当てを社のあいだで {jp(g20.trials)} 回振り直すと、的中は
                  平均 {g20.mean}・最大 {g20.max}。実測 {g20.observed} に対し
                  p = {g20.p_value.toFixed(4)}。<strong>県ごとの偏りは偶然では説明できない</strong>
                  が、その偏りが指しているのは総本社ではない。
                </td>
              </tr>
              <tr>
                <th scope="row">同一視は共起の強さで見分けられるか(G-17)</th>
                <td>
                  Jaccard 上位 {g17.k} 件を同一視と予測したときの適合率{" "}
                  {g17.precision.toFixed(3)}(合格線 {g17.threshold})。<strong>不合格。</strong>
                  最も強く共起する対は八坂刀売神と建御名方神(Jaccard{" "}
                  {g17.predicted[0]?.jaccard.toFixed(3)})で、これは同一神ではなく夫婦である。
                  だから型は手で分類した。
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
