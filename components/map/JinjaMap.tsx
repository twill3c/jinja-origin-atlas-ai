"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const GSI_STD = "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png";
const SHRINES = "/data/osm/shrines.min.geojson";

/** 日本全体が入る初期表示(仕様書 §15.3 の Japan overview)。 */
const INITIAL = { center: [138.5, 37.0] as [number, number], zoom: 4.6 };

type Selected = { id: string; name: string | null; prefecture: string | null };

export default function JinjaMap() {
  const ref = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        layers: [{ id: "gsi", type: "raster", source: "gsi" }],
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
      map.addSource("shrines", {
        type: "geojson",
        data: SHRINES,
        cluster: true,
        clusterRadius: 44,
        clusterMaxZoom: 12,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> (ODbL)',
      });

      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "shrines",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#b7410e",
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
        layout: {
          "text-field": ["get", "point_count_abbreviated"],
          "text-size": 12,
        },
        paint: { "text-color": "#ffffff" },
      });
      map.addLayer({
        id: "shrine-point",
        type: "circle",
        source: "shrines",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": "#b7410e",
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3, 15, 7],
          "circle-stroke-width": 1,
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

      map.on("click", "shrine-point", (e) => {
        const p = e.features?.[0]?.properties as Selected | undefined;
        if (p) setSelected({ id: p.id, name: p.name ?? null, prefecture: p.prefecture ?? null });
      });

      for (const layer of ["clusters", "shrine-point"]) {
        map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
        map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
      }
    });

    map.on("error", (e) => setError(String(e.error?.message ?? e.error ?? "地図の読み込みに失敗しました")));

    fetch(SHRINES)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => setCount(d.features.length))
      .catch((e) => setError(String(e)));

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  return (
    <div>
      <div
        ref={ref}
        role="application"
        aria-label="神社の分布地図。キーボードでは矢印キーで移動、+ / - で拡大縮小できます。"
        tabIndex={0}
        style={{ width: "100%", height: "min(70vh, 620px)", border: "1px solid var(--line)" }}
      />
      {/* 出典は JavaScript に依存させない。地図が読めなくても表示される(SPEC F-02) */}
      <p style={{ fontSize: "0.78rem", color: "var(--ink-mute)", margin: "0.5rem 0 0" }}>
        地図データ: © OpenStreetMap contributors(ODbL) ／ 背景地図: 国土地理院
      </p>
      {error && (
        <p role="status" style={{ color: "var(--vermilion)", fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      <p style={{ fontSize: "0.85rem", color: "var(--ink-mute)", margin: "0.4rem 0 0" }}>
        表示中の神社: {count === null ? "読み込み中…" : `${count.toLocaleString("ja-JP")} 件`}
        {" ／ "}AI 由緒分析つき: 0 件(後続の実装で結合する)
      </p>
      {selected && (
        <div className="band band-evidence" role="status">
          <h3>選択中(公開データに基づく情報)</h3>
          <p style={{ margin: 0 }}>
            <strong>{selected.name ?? "(名称のタグが無い神社)"}</strong>
            {selected.prefecture ? ` — ${selected.prefecture}` : ""}
          </p>
          <p style={{ margin: "0.2rem 0 0", fontSize: "0.8rem", color: "var(--ink-mute)" }}>
            ID: {selected.id} ／ 出典: OpenStreetMap
          </p>
        </div>
      )}
    </div>
  );
}
