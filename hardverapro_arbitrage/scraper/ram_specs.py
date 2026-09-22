"""Best-effort structured spec extraction for RAM listings: memory type,
total kit capacity, and frequency -- the three numbers that actually
determine whether a RAM listing matches what someone's looking for, which
free-text title matching (normalize.py) can't answer on its own.

Deliberately narrow (RAM only, not a general product-attribute parser):
checked against real scraped titles, RAM listings follow a handful of
well-established, near-universal naming conventions (brand, "DDR4"/"DDR5",
a capacity, a frequency in MHz or MT/s, optionally an "AxB GB" kit count) --
unlike, say, phone titles, which normalize.py's own docstring notes were
deliberately NOT parsed this way because getting brand/model extraction
wrong there silently merges different products. This only ever narrows
results shown to a human for them to click through and judge themselves
(see web.py's /ram), never feeds the deal-detection reference-price path,
so a missed or double-counted edge case just means one listing doesn't
show up rather than a false "this is a great deal" claim.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class RamSpec:
    memory_type: str  # "ddr3", "ddr4", "ddr5"
    capacity_gb: int  # total kit capacity, e.g. 32 for a 2x16GB kit
    frequency_mhz: int


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# "DDR4-3200" / "DDR4 3200" / "DDR5-6000" -- JEDEC/marketing shorthand
# that states the frequency right after the memory type with no unit word
# at all. Tried first because it's unambiguous (a bare 3-5 digit number
# glued directly to "ddr4" is never anything else); the [\s-]* means it
# only matches when nothing else -- like "8GB" -- sits between them, so it
# can't accidentally skip over other numbers to reach a real MHz value
# further down the title (that's what _FREQUENCY_RE below is for).
_TYPE_WITH_FREQUENCY_RE = re.compile(r"\bddr([345])[\s-]*(\d{3,5})\b")
_TYPE_RE = re.compile(r"\bddr([345])\b")

# "3200MHz", "3200 MHz", "7400MT/s", "5600MT/s" -- the number must be
# directly adjacent (mere whitespace only) to the unit for a match, so a
# multi-variant listing like ".../3200/3000/2666 MHz" only ever matches
# the one number actually touching "MHz", not any of the others.
_FREQUENCY_RE = re.compile(r"\b(\d{3,5})\s*(?:mhz|mt/s|mts)\b")

# "2x16GB", "2 x 16 GB", "4x8gb" -- a kit's per-stick count and size, from
# which the total capacity is the product, not either number alone.
_KIT_RE = re.compile(r"\b(\d{1,2})\s*x\s*(\d{1,3})\s*gb\b")
_CAPACITY_RE = re.compile(r"\b(\d{1,3})\s*gb\b")


def parse_ram_spec(title: str) -> RamSpec | None:
    """Returns None when the title doesn't clearly state all three of
    memory type, frequency, and capacity -- under-matching (a real RAM
    listing worded unusually gets skipped) rather than guessing, since a
    guess here would show someone a listing that doesn't actually meet
    the spec they asked for.
    """
    text = _strip_accents(title).lower()

    combined = _TYPE_WITH_FREQUENCY_RE.search(text)
    if combined:
        memory_type = f"ddr{combined.group(1)}"
        frequency_mhz = int(combined.group(2))
    else:
        type_match = _TYPE_RE.search(text)
        if type_match is None:
            return None
        memory_type = f"ddr{type_match.group(1)}"
        freq_match = _FREQUENCY_RE.search(text)
        if freq_match is None:
            return None
        frequency_mhz = int(freq_match.group(1))

    kit_match = _KIT_RE.search(text)
    if kit_match:
        capacity_gb = int(kit_match.group(1)) * int(kit_match.group(2))
    else:
        capacity_match = _CAPACITY_RE.search(text)
        if capacity_match is None:
            return None
        capacity_gb = int(capacity_match.group(1))

    return RamSpec(memory_type=memory_type, capacity_gb=capacity_gb, frequency_mhz=frequency_mhz)
