# -*- coding: utf-8 -*-
"""AI コーパスの組み立て — SPEC F-09 / D-01。

ja.wikipedia の記事から**由緒に相当する部分**を取り出す。記事全体を入れると
「所在地」「交通アクセス」「参考文献」まで埋め込みに混じり、クラスタが
「記事の書き方」を測ってしまう。

**本文はここから外へ出さない。** 呼び手は埋め込みとスコアだけを受け取る。
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass

RAW_DIR = pathlib.Path("data/raw/wikipedia")

#: 由緒に相当する節の見出し。**含める**もの。
KEEP_SECTIONS = ("歴史", "由緒", "沿革", "創建", "概要", "祭神", "信仰", "縁起", "社伝")

#: 明らかに由緒でない節。**除く**もの。
DROP_SECTIONS = (
    "交通", "アクセス", "所在地", "参考文献", "脚注", "注釈", "出典", "関連項目",
    "外部リンク", "ギャラリー", "画像", "現地情報", "周辺", "利用案内",
)

_SECTION = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.MULTILINE)

#: 短すぎる本文は埋め込んでも意味が出ない。**この境目は実測で置く**(§7.6)。
MIN_CHARS = 120

#: E5 の入力長。多言語 e5-base は 512 トークン。日本語は 1 トークン ≒ 1〜2 字なので
#: 800 字で切る。切った旨はレコードに残す。
MAX_CHARS = 800


@dataclass(frozen=True)
class Doc:
    shrine_id: str
    title: str
    revid: int
    url: str
    license: str
    text: str
    used_sections: tuple[str, ...]
    truncated: bool


def split_sections(text: str) -> list[tuple[str, str]]:
    """(見出し, 本文)の列。冒頭の導入部は見出し `(導入)` にする。"""
    marks = list(_SECTION.finditer(text))
    out: list[tuple[str, str]] = []
    lead = text[: marks[0].start()] if marks else text
    if lead.strip():
        out.append(("(導入)", lead.strip()))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            out.append((m.group(2), body))
    return out


def select_origin_text(text: str) -> tuple[str, tuple[str, ...]]:
    """由緒に相当する部分だけを繋ぐ。:returns: (本文, 使った見出し)"""
    secs = split_sections(text)
    kept: list[str] = []
    used: list[str] = []
    for head, body in secs:
        if any(k in head for k in DROP_SECTIONS):
            continue
        if head == "(導入)" or any(k in head for k in KEEP_SECTIONS):
            kept.append(body)
            used.append(head)
    if not kept:
        # 見出しが無い短い記事。全文を使う(除外節だけは落とす)
        kept = [b for h, b in secs if not any(k in h for k in DROP_SECTIONS)]
        used = ["(全文)"]
    return "\n".join(kept).strip(), tuple(used)


def load_corpus(min_chars: int = MIN_CHARS, max_chars: int = MAX_CHARS) -> tuple[list[Doc], dict]:
    """`data/raw/wikipedia/` から由緒コーパスを作る。落としたものは理由ごとに数える。"""
    docs: list[Doc] = []
    dropped = {"本文なし": 0, f"{min_chars} 字未満": 0, "版 ID なし": 0}
    for p in sorted(RAW_DIR.glob("jinja_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        raw = d.get("text") or ""
        if not raw.strip():
            dropped["本文なし"] += 1
            continue
        if not d.get("revid"):
            dropped["版 ID なし"] += 1
            continue
        text, used = select_origin_text(raw)
        if len(text) < min_chars:
            dropped[f"{min_chars} 字未満"] += 1
            continue
        truncated = len(text) > max_chars
        docs.append(Doc(
            shrine_id=p.stem, title=d["title"], revid=int(d["revid"]), url=d["url"],
            license=d["license"], text=text[:max_chars],
            used_sections=used, truncated=truncated,
        ))
    return docs, dropped
