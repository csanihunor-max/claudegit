"""A short, cleaned snippet of an ad's description for the dashboard.

Only the watch-related text survives: contact details (phone numbers, e-mail
addresses, links) are cut out, and so are whole sentences that are about
getting in touch or signing off, since those are where sellers put their names.
"""

from __future__ import annotations

import re
import unicodedata

SUMMARY_CHARS = 240

_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
# Hungarian and international phone numbers: 7+ digits with optional separators.
_PHONE = re.compile(r"(?:\+|00)?\d(?:[\s./\-()]*\d){6,}")
# Sentence ends, line breaks and bullet marks ("*Eredeti tok *Szép plexi").
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\s*\n+\s*|\s*[•*]+\s*|\s+[-–]\s+")
_WORD = re.compile(r"\w+")
# Sentences mentioning these are about the seller, not the watch.
_PERSONAL = re.compile(
    r"\b(?:h[ií]v|telefon|tel\b|mobil|sms|e-?mail|viber|whats ?app|messenger|facebook|instagram|"
    r"keress|keressen|[ií]rj|[ií]rjon|[uü]zenet|[eé]rdekl[oöő]d|nevem|vagyok|[uü]dv|szia|hello|hell[oó]|"
    r"k[oö]sz[oö]n|call|contact|my name|regards|thanks)",
    re.I,
)


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def short_description(details: str | None, title: str = "", limit: int = SUMMARY_CHARS) -> str | None:
    """The first `limit` characters of the ad text that describe the watch, or None."""
    if not details:
        return None
    text = _URL.sub(" ", _EMAIL.sub(" ", details))
    title_words = set(_WORD.findall(_fold(title)))
    kept: list[str] = []
    for sentence in _SENTENCE.split(text):
        sentence = " ".join(sentence.split()).strip(" ,;:")
        if not sentence or _PERSONAL.search(sentence) or _PHONE.search(sentence):
            continue
        if not kept and title_words:
            # Many ads open by repeating the title (sometimes reworded); skip it.
            folded = _fold(sentence)
            if folded.startswith(_fold(title.strip())):
                sentence = sentence[len(title.strip()):].lstrip(" .,:;-–")
            else:
                words = _WORD.findall(folded)
                if words and sum(w in title_words for w in words) >= 0.7 * len(words):
                    continue
            if not sentence:
                continue
        kept.append(sentence)
    # Bullet points read as a list: "works well · original case · new strap".
    text = ""
    for piece in kept:
        text += piece if not text else (" " if text[-1] in ".!?" else " · ") + piece
    text = text.strip()
    if len(text) < 12:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" .,:;-–")
    return cut + "…"
