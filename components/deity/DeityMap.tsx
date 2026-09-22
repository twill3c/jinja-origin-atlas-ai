"use client";

import { useEffect, useRef } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DeityPoint } from "@/lib/deity-types";

/* 選んだ祭神の社を点で出す地図。
 *
 * **県を塗らない。** オオヤマツミの愛媛は 7 社である。7 社を愛媛県全体に塗ると、
 * リフト 11.8 倍という正しい数字が「面積」という嘘に化ける。点で出せば、
 * 四国に 7 つ固まっているという実態がそのまま見える。
 *
 * 総本社のピンも重ねる。**リフト最上位の県とピンが合うかどうかを目で確かめられる**
 * ようにするためで、合わないことのほうが多い(26 柱中 19 柱・SPEC §7.14)。 */

const GSI_STD = "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png";
const INITIAL = { center: [138.5, 37.0] as [number, number], zoom: 4.2 };
const ACCENT = "#b7410e";
const MUTED = "#b8b2a9";

export type HeadPin = { name: string; pref: string; lat: number; lon: number } | null;

function fc(points: DeityPoint[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
      properties: { id: p.id, name: p.name ?? "(名称タグ無し)", pref: p.pref },
    })),
  };
}

export default function DeityMap({
  all,
  selected,
  head,
  label,
}: {
  all: DeityPoint[];
  selected: DeityPoint[];
  head: HeadPin;
  label: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);

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
          // 背景を必ず置く。無いとタイルの届かない領域でページ背景が透けて見える。
          { id: "bg", type: "background", paint: { "background-color": "#dfeef7" } },
          { id: "gsi", type: "raster", source: "gsi" },
        ],
      },
      center: INITIAL.center,
      zoom: INITIAL.zoom,
      attributionControl: false,
    });
    mapRef.current = map;
    // 検品用の口(WebGL キャンバスの中身は DOM から見えない)
    (window as unknown as { __deityMap?: MapLibreMap }).__deityMap = map;

    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      map.resize();
      map.addSource("all", {
        type: "geojson",
        data: fc([]),
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a> (ODbL) · <a href="https://www.wikidata.org/wiki/Wikidata:Licensing" target="_blank" rel="noreferrer">Wikidata</a> (CC0)',
      });
      map.addSource("picked", { type: "geojson", data: fc([]) });
      map.addSource("head", { type: "geojson", data: fc([]) });

      map.addLayer({
        id: "all-point",
        type: "circle",
        source: "all",
        paint: {
          "circle-color": MUTED,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 1.6, 10, 3.2],
          "circle-opacity": 0.65,
        },
      });
      map.addLayer({
        id: "picked-point",
        type: "circle",
        source: "picked",
        paint: {
          "circle-color": ACCENT,
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 4, 10, 8],
          "circle-stroke-width": 1.4,
          "circle-stroke-color": "#ffffff",
        },
      });
      map.addLayer({
        id: "head-pin",
        type: "circle",
        source: "head",
        paint: {
          "circle-color": "#ffffff",
          "circle-radius": 8,
          "circle-stroke-width": 3.4,
          "circle-stroke-color": "#1f5673",
        },
      });
      readyRef.current = true;
      map.fire("deity-ready");
    });

    map.on("click", "picked-point", (e) => {
      const f = e.features?.[0];
      if (!f) return;
      const p = f.properties as { id: string; name: string; pref: string };
      new maplibregl.Popup({ closeButton: true })
        .setLngLat((f.geometry as GeoJSON.Point).coordinates as [number, number])
        .setHTML(
          `<strong>${p.name}</strong><br>${p.pref}<br>` +
            `<a href="/shrine/?id=${p.id}">この神社を見る</a>`,
        )
        .addTo(map);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      if (!map.getSource("all")) return;
      (map.getSource("all") as maplibregl.GeoJSONSource).setData(fc(all));
      (map.getSource("picked") as maplibregl.GeoJSONSource).setData(fc(selected));
      (map.getSource("head") as maplibregl.GeoJSONSource).setData(
        fc(head
          ? [{ id: "head", name: head.name, pref: head.pref, lat: head.lat, lon: head.lon }]
          : []),
      );
    };
    if (readyRef.current) apply();
    else map.once("deity-ready", apply);
  }, [all, selected, head]);

  return (
    <div>
      <div
        ref={ref}
        className="deity-map"
        role="application"
        aria-label={`${label}を祀る社の分布。総本社は青い輪で示す。`}
      />
    </div>
  );
}
