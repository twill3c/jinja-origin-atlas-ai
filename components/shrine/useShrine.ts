"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import type { ChunkDoc, IndexDoc, ShrineRecord } from "@/lib/shrine-types";

/* 神社 1 件を URL の `?id=` から引く(D-06)。
 *
 * `?p=`(県コード)があればその県のチャンクを直接読む。無い、または外れていたら
 * 索引(ID → 県コード)を引き直す。**外れた県コードを信じて「見つからない」と言わない。** */

const ID_RE = /^jinja_[nwr]\d+$/;
const P_RE = /^\d{2}$/;

export type ShrineState =
  | { status: "loading"; id: string | null }
  | { status: "error"; id: string | null; message: string }
  | { status: "ready"; id: string; shrine: ShrineRecord; chunk: ChunkDoc };

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} が読めない(HTTP ${r.status})`);
  return (await r.json()) as T;
}

async function lookupPref(id: string): Promise<string | null> {
  const idx = await getJson<IndexDoc>("/data/shrines/index.json");
  return idx.ids[id] ?? null;
}

async function findIn(p: string, id: string): Promise<{ shrine: ShrineRecord; chunk: ChunkDoc } | null> {
  const chunk = await getJson<ChunkDoc>(`/data/shrines/${p}.json`);
  const shrine = chunk.shrines.find((x) => x.id === id);
  return shrine ? { shrine, chunk } : null;
}

export function useShrine(): ShrineState {
  const params = useSearchParams();
  const id = params.get("id");
  const pParam = params.get("p");
  const [state, setState] = useState<ShrineState>({ status: "loading", id });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading", id });

    async function run(): Promise<ShrineState> {
      if (!id || !ID_RE.test(id)) {
        return { status: "error", id, message: "神社の ID が指定されていない(または形が違う)。" };
      }
      const hinted = pParam && P_RE.test(pParam) ? pParam : null;
      if (hinted) {
        const hit = await findIn(hinted, id);
        if (hit) return { status: "ready", id, ...hit };
      }
      const p = await lookupPref(id);
      if (!p) return { status: "error", id, message: `ID ${id} の神社は見つからない。` };
      const hit = await findIn(p, id);
      if (!hit) return { status: "error", id, message: `索引は ${p} を指しているが、そこに ${id} が無い。` };
      return { status: "ready", id, ...hit };
    }

    run()
      .then((s) => !cancelled && setState(s))
      .catch((e) => !cancelled && setState({ status: "error", id, message: String(e) }));
    return () => {
      cancelled = true;
    };
  }, [id, pParam]);

  return state;
}
