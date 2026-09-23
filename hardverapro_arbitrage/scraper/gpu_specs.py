"""Best-effort structured spec extraction for graphics-card listings:
chip model and VRAM -- see scraper/ram_specs.py's module docstring for why
this kind of narrow, evidence-based parsing is used here specifically
rather than for titles in general (normalize.py's own docstring explains
why it deliberately avoids this for everything else). Feeds a live spec
browse/filter (web.py's /gpu), never the deal-detection reference-price
path, so an imperfect match just means one listing doesn't show up rather
than a false "this is a great deal" claim.

Checked against real titles from hardverapro.hu's own "Graphics Cards"
category (hardver/videokartya): standalone card listings reliably state
chip family + model number (+ Ti/Super/XT/XTX variant) and VRAM size, in
a small number of consistent forms. Deliberately does NOT match NVIDIA's
professional/workstation naming (RTX A4500, RTX ADA 2000, RTX PRO
2000/500) -- a different product line with completely different pricing
than the same numbers under a consumer RTX/GTX prefix -- because those
names have another word (A/ADA/PRO) sitting between the prefix and the
number, where this parser requires a number directly.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class GpuSpec:
    chip: str  # canonical chip id, e.g. "rtx4070ti", "rx7900xtx", "gtx1660super"
    vram_gb: int


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# NVIDIA: "RTX 3070 Ti", "GTX 1660 Super", "GT 1030" -- the family prefix
# must be directly followed (mere whitespace only) by the model number,
# which is what excludes the professional/workstation lines described
# above (they all have another word between the prefix and the number).
_NVIDIA_RE = re.compile(r"\b(rtx|gtx|gt)\s*(\d{3,4})\s*(ti|super)?\b")

# AMD current: "RX 6600", "RX 7900 XTX", "RX 570".
_AMD_RX_RE = re.compile(r"\brx\s*(\d{3,4})\s*(xtx|xt)?\b")

# AMD's older 3-digit "R5/R7/R9 ###" Radeon naming (R7 250, R9 380, ...)
# -- the fixed 3-digit count is what keeps this from matching a
# same-looking 4-digit Ryzen CPU name (e.g. "R5 5600X").
_AMD_R_SERIES_RE = re.compile(r"\br([579])\s*(\d{3})\b")

_VRAM_RE = re.compile(r"\b(\d{1,2})\s*gb\b")


def parse_gpu_spec(title: str) -> GpuSpec | None:
    """Returns None when the title doesn't clearly state both a
    recognized chip and its VRAM size -- under-matching rather than
    guessing, same rationale as ram_specs.parse_ram_spec."""
    text = _strip_accents(title).lower()

    chip: str | None = None
    match = _NVIDIA_RE.search(text)
    if match:
        family, number, suffix = match.groups()
        chip = f"{family}{number}{suffix or ''}"
    else:
        match = _AMD_RX_RE.search(text)
        if match:
            number, suffix = match.groups()
            chip = f"rx{number}{suffix or ''}"
        else:
            match = _AMD_R_SERIES_RE.search(text)
            if match:
                series, number = match.groups()
                chip = f"r{series}{number}"

    if chip is None:
        return None

    vram_match = _VRAM_RE.search(text)
    if vram_match is None:
        return None

    return GpuSpec(chip=chip, vram_gb=int(vram_match.group(1)))
