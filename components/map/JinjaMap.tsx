"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const GSI_STD = "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png";
const SHRINES = "/data/osm/shrines.min.geojson";

/** 日本全体が入る初期表示(仕様書 §15.3 の Japan overview)。 */
const INITIAL = { center: [138.5, 37.0] as [number, number], zoom: 4.6 };

/* 地図は「どの二色も隣り合いうる」形なので、カテゴリを色で塗り分けられるのは
 * せいぜい 3 色までである(それ以上は色覚多様性の分離が保てない)。系統は 17 種あるので
 * **色で塗り分けない** —— 選んだ系統だけを強調色にし、残りを無彩色に落とす。
 *
 * 無彩色は「系列」ではなく「選ばれていない状態」なので彩度の下限は当たらない。
 * 効く検査(分離・コントラスト)は通っている:
 * 強調 #b7410e と無彩 #8a8580 で CVD ΔE 12.6 / 通常視 ΔE 17.6 / 背景比 3:1 以上。 */
const ACCENT = "#b7410e";
const MUTED = "#8a8580";

type Selected = { id: string; name: string | null; prefecture: string | null; family: string };
type Feature = {
  type: "Feature";
  geometry: { type: "Point"; coordinates: [number, number] };
  properties: { id: string; name: string | null; prefecture: string | null; family: string };
};
type FamilyMeta = { labels: Record<string, string>; counts: Record<string, number> };

export default function JinjaMap({ families }: { families: FamilyMeta }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const dataRef = useRef<Feature[] | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const applyFilter = useCallback((keys: string[]) => {
    const map = mapRef.current;
    const feats = dataRef.current;
    if (!map || !feats || !map.getSource("highlight")) return;
    const hit = keys.length ? feats.filter((f) => keys.includes(f.properties.family)) : [];
    (map.getSource("highlight") as maplibregl.GeoJSONSource).setData({
      type: "FeatureCollection",
      features: hit,
    });
    map.setPaintProperty("clusters", "circle-color", keys.length ? MUTED : ACCENT);
    map.setPaintProperty("shrine-point", "circle-color", keys.length ? MUTED : ACCENT);
  }, []);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {
          gsi: {
            type: "raster",
            tiles: [GSI_STD],
            tileSize: 256,
            maxzoom: 18,
            attribution:
              '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">国土地理院</a>',
          },
        },
        layers: [
          // 背景レイヤーを必ず置く。これが無いと、タイルの無い/まだ届いていない領域で
          // キャンバスが透明のままになり、**ページの背景色が地図の中に透けて見える**。
          // 「地図の上部が白く抜ける」という形で現れ、要素の在存検査では捕まらない。
          { id: "bg", type: "background", paint: { "background-color": "#dfeef7" } },
          { id: "gsi", type: "raster", source: "gsi" },
        ],
      },
      center: INITIAL.center,
      zoom: INITIAL.zoom,
      attributionControl: false,
    });
    mapRef.current = map;
    // 検品用の口。WebGL キャンバスに何が描かれたかは DOM から見えないので、
    // 実ブラウザ検品(harness/smoke.mjs)が queryRenderedFeatures を呼べるようにする。
    (window as unknown as { __jinjaMap?: MapLibreMap }).__jinjaMap = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");

    map.on("load", () => {
      // 初期化時の器の寸法で固まることがあるので、読み込み完了時に一度取り直す。
      // これを怠ると、キャンバスの上部が塗られずページ背景が透けて見える。
      map.resize();
      map.addSource("shrines", {
        type: "geojson",
        data: SHRINES,
        cluster: true,
        clusterRadius: 44,
        clusterMaxZoom: 12,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> (ODbL) · <a href="https://www.wikidata.org/wiki/Wikidata:Licensing" target="_blank" rel="noreferrer">Wikidata</a> (CC0)',
      });
      map.addSource("highlight", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "shrines",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": ACCENT,
          "circle-opacity": 0.82,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#ffffff",
          "circle-radius": ["step", ["get", "point_count"], 13, 25, 18, 100, 24, 500, 30],
        },
      });
      map.addLayer({
        id: "cluster-count",
        type: "symbol",
        source: "shrines",
        filter: ["has", "point_count"],
        layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 12 },
        paint: { "text-color": "#ffffff" },
      });
      map.addLayer({
        id: "shrine-point",
        type: "circle",
        source: "shrines",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": ACCENT,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3, 15, 7],
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
        },
      });
      // 強調は集約しない。集約すると、選んだ系統がどこにあるか見えなくなる。
      map.addLayer({
        id: "highlight-point",
        type: "circle",
        source: "highlight",
        paint: {
          "circle-color": ACCENT,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 3.5, 8, 5, 15, 8],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#ffffff",
        },
      });

      map.on("click", "clusters", (e) => {
        const f = map.queryRenderedFeatures(e.point, { layers: ["clusters"] })[0];
        if (!f) return;
        const src = map.getSource("shrines") as maplibregl.GeoJSONSource;
        void src.getClusterExpansionZoom(f.properties!.cluster_id as number).then((z) => {
          map.easeTo({ center: (f.geometry as GeoJSON.Point).coordinates as [number, number], zoom: z });
        });
      });

      for (const layer of ["shrine-point", "highlight-point"]) {
        map.on("click", layer, (e) => {
          const p = e.features?.[0]?.properties as Selected | undefined;
          if (p) {
            setSelected({
              id: p.id,
              name: p.name ?? null,
              prefecture: p.prefecture ?? null,
              family: p.family ?? "unknown",
            });
          }
        });
      }
      for (const layer of ["clusters", "shrine-point", "highlight-point"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
    });

    map.on("error", (e) => setError(String(e.error?.message ?? e.error ?? "地図の読み込みに失敗しました")));

    // 器の寸法が変わってもキャンバスは追随しない。上に要素を足した・折り返しが変わった、
    // どちらでも地図の中に空白の帯ができる。検査は全部緑のまま通るので、追随を明示的に書く。
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(ref.current);

    fetch(SHRINES)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        dataRef.current = d.features as Feature[];
        setCount(d.features.length);
      })
      .catch((e) => setError(String(e)));

    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    applyFilter(picked);
  }, [picked, count, applyFilter]);

  const toggle = (key: string) =>
    setPicked((cur) => (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]));

  const shown = picked.length
    ? picked.reduce((a, k) => a + (families.counts[k] ?? 0), 0)
    : (count ?? 0);

  const order = Object.entries(families.counts)
    .filter(([k]) => k !== "unknown")
    .sort((a, b) => b[1] - a[1]);

  return (
    <div>
      <fieldset
        style={{
          border: "1px solid var(--line)",
          borderRadius: 4,
          padding: "0.6rem 0.9rem",
          margin: "0 0 0.75rem",
          background: "var(--panel)",
        }}
      >
        <legend style={{ fontSize: "0.85rem", padding: "0 0.4rem" }}>系統でしぼる</legend>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.15rem 1rem" }}>
          {order.map(([key, n]) => (
            <label key={key} style={{ fontSize: "0.85rem", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={picked.includes(key)}
                onChange={() => toggle(key)}
              />{" "}
              {families.labels[key] ?? key}
              <span style={{ color: "var(--ink-mute)" }}> {n}</span>
            </label>
          ))}
        </div>
        <p style={{ margin: "0.5rem 0 0", fontSize: "0.78rem", color: "var(--ink-mute)" }}>
          選ぶと、その系統だけが朱色になり、残りは灰色に落ちる。
          系統は 17 種あるので色では塗り分けない —— 地図上では任意の二色が隣り合うため、
          見分けのつく色数は限られる。
          {picked.length > 0 && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => setPicked([])}
                style={{ font: "inherit", cursor: "pointer" }}
              >
                しぼりを外す
              </button>
            </>
          )}
        </p>
      </fieldset>

      <div
        ref={ref}
        role="application"
        aria-label="神社の分布地図。キーボードでは矢印キーで移動、+ / - で拡大縮小できます。"
        tabIndex={0}
        style={{ width: "100%", height: "min(70vh, 620px)", border: "1px solid var(--line)" }}
      />
      {/* 出典は JavaScript に依存させない。地図が読めなくても表示される(SPEC F-02) */}
      <p style={{ fontSize: "0.78rem", color: "var(--ink-mute)", margin: "0.5rem 0 0" }}>
        地図データ: © OpenStreetMap contributors(ODbL) ／ 属性: Wikidata(CC0) ／ 背景地図:
        国土地理院
      </p>
      {error && (
        <p role="status" style={{ color: ACCENT, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)", margin: "0.4rem 0 0" }}>
        {picked.length ? "強調中" : "表示中"}の神社:{" "}
        {count === null ? "読み込み中…" : `${shown.toLocaleString("ja-JP")} 件`}
        {picked.length > 0 && ` / 全 ${(count ?? 0).toLocaleString("ja-JP")} 件`}
        {" ／ "}AI 由緒分析つき: 0 件(後続の実装で結合する)
      </p>
      {selected && (
        <div className="band band-evidence" role="status">
          <h3>選択中(公開データに基づく情報)</h3>
          <p style={{ margin: 0 }}>
            <strong>{selected.name ?? "(名称のタグが無い神社)"}</strong>
            {selected.prefecture ? ` — ${selected.prefecture}` : ""}
            {selected.family && selected.family !== "unknown" && (
              <> ／ {families.labels[selected.family] ?? selected.family}</>
            )}
          </p>
          <p style={{ margin: "0.2rem 0 0", fontSize: "0.8rem", color: "var(--ink-mute)" }}>
            ID: {selected.id} ／ 出典: OpenStreetMap
            {selected.name && (
              <>
                {" ／ "}
                <Link href={`/shrine/${selected.id}/`}>詳細を見る</Link>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
