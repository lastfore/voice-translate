"""Lightweight G2P preroll rules for LRC boundary search windows."""

from __future__ import annotations

# Rule table: Mandarin lyric leading characters by typical initial type.
# 清塞音/擦音起头 — full preroll
SIBILANT_CHARS = frozenset(
    "他思可七清才从出三死四说去小下先想谢徐许"
    "特土天同童图推体提跳铁太通汤唐"
    "司声松散色深书数水所"
    "词次草参仓"
    "子自总走最"
    "期其气前钱强请青"
    "西息细新心信"
    "科口开看康空"
    "七"
)

# 鼻音/边音 — 0.6 × preroll
NASAL_LATERAL_CHARS = frozenset(
    "么呢来你鸟那南女内年念难"
    "吗嘛美明名面民"
    "呢嫩"
    "了里力立李利连林"
)

# 元音起头 — 0.3 × preroll
VOWEL_START_CHARS = frozenset("爱我啊哦额阿埃")


def first_char(text: str) -> str:
    for ch in text.strip():
        if not ch.isspace():
            return ch
    return ""


def preroll_factor(first: str) -> float:
    """Return multiplier for g2p_preroll_ms based on next-line leading character."""
    if not first:
        return 0.0
    if first in SIBILANT_CHARS:
        return 1.0
    if first in NASAL_LATERAL_CHARS:
        return 0.6
    if first in VOWEL_START_CHARS:
        return 0.3
    # Latin fallback for unit tests / mixed lyrics
    ch = first.lower()
    if ch in frozenset("tcszqxykj"):
        return 1.0
    if ch in frozenset("mnl"):
        return 0.6
    if ch in frozenset("aeiou"):
        return 0.3
    return 0.3


def lookup_preroll_ms(next_line_text: str, g2p_preroll_ms: int) -> float:
    """Return effective preroll window in ms; 0 when disabled."""
    if g2p_preroll_ms <= 0:
        return 0.0
    factor = preroll_factor(first_char(next_line_text))
    return float(g2p_preroll_ms) * factor
