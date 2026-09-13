"use client";

import { useEffect } from "react";

/* D-06 以前の URL(`/shrine/jinja_w123/`・`/similar/jinja_w123/`)を新しい形へ送る。
 * 2026-09-09〜10 の本番ではこの形で神社ごとの HTML を配っていたので、外に出たリンクが
 * 404 で行き止まりにならないようにする。静的書き出しでは rewrite を置けないため、
 * 404 ページの中で送り直す。 */
const LEGACY = /^\/(shrine|similar)\/(jinja_[nwr]\d+)\/?$/;

export default function LegacyRedirect() {
  useEffect(() => {
    const m = window.location.pathname.match(LEGACY);
    if (m) window.location.replace(`/${m[1]}/?id=${m[2]}`);
  }, []);
  return null;
}
