"""Human-readable labels for hardverapro.hu category URLs, for display
(dashboard, notifications) — purely cosmetic, no effect on scraping or
pricing logic.
"""
from __future__ import annotations

# Matched by substring against the configured search URL, longest match
# first, so a more specific path (checked first) wins over a shorter one.
_LABELS: dict[str, str] = {
    "szoftver_jatek/asus_rog": "ROG Ally / Xbox Ally",
    "szoftver_jatek/steam_deck": "Steam Deck",
    "szoftver_jatek/playstation": "PlayStation",
    "szoftver_jatek/nintendo": "Nintendo",
    "szoftver_jatek/xbox": "Xbox",
    "hardver/vr": "VR headsets",
    "szoftver_jatek/vr": "VR headsets",
    "mobil/tablet": "Tablets",
    "mobil/mobil": "Phones",
    "pc_szerver/apple_mac_imac": "Mac / iMac",
    "pc_szerver/asztali_gep": "Desktop PCs",
    "notebook/apple": "MacBooks",
    "notebook/pc": "Laptops",
}


def label_for_url(url: str) -> str:
    """Best-effort display label for a configured search URL. Falls back
    to the last meaningful path segment, title-cased, for anything not in
    the map above — never raises, worst case looks a bit generic.
    """
    for slug, label in _LABELS.items():
        if slug in url:
            return label

    segments = [seg for seg in url.split("/") if seg and seg not in ("index.html", "keres.php")]
    if segments:
        return segments[-1].replace("_", " ").title()
    return url
