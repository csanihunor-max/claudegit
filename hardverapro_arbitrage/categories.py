"""Human-readable labels for hardverapro.hu category URLs, for display
(dashboard, notifications) — purely cosmetic, no effect on scraping or
pricing logic. Also the canonical list of category URLs this bot tracks
by default, so it only needs updating in one place (previously duplicated
into the hourly Routine's own prompt text, which drifted from this file).
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
    "mobil/okosora_okosgyuru": "Smartwatches",
    "pc_szerver/apple_mac_imac": "Mac / iMac",
    "pc_szerver/asztali_gep": "Desktop PCs",
    "notebook/apple": "MacBooks",
    "notebook/pc": "Laptops",
    "hardver/alaplap": "Motherboards",
    "hardver/videokartya": "Graphics Cards",
    "hardver/processzor": "CPUs",
    "hardver/memoria": "RAM",
    "hardver/merevlemez_ssd": "Storage / SSDs",
    "hardver/haz_tapegyseg": "PSUs / Cases",
    "hardver/hutes": "Cooling",
    "hardver/monitor": "Monitors",
    "hazimozi_hifi/tv_projektor": "TVs / Projectors",
    "hazimozi_hifi/fejhallgato_fulhallgato": "Headphones",
}

# The category browse pages this bot tracks by default -- every slug here
# was checked against a live fetch (HTTP 200) before being added. Order
# matches display order elsewhere (e.g. the Alku Radar artifact's
# category pill list).
DEFAULT_SEARCH_URLS: list[str] = [
    "https://hardverapro.hu/aprok/szoftver_jatek/asus_rog/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/steam_deck/index.html",
    "https://hardverapro.hu/aprok/hardver/vr/index.html",
    "https://hardverapro.hu/aprok/mobil/tablet/index.html",
    "https://hardverapro.hu/aprok/mobil/okosora_okosgyuru/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/apple_mac_imac/index.html",
    "https://hardverapro.hu/aprok/notebook/apple/index.html",
    "https://hardverapro.hu/aprok/notebook/pc/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/playstation/index.html",
    "https://hardverapro.hu/aprok/mobil/mobil/index.html",
    "https://hardverapro.hu/aprok/hardver/alaplap/index.html",
    "https://hardverapro.hu/aprok/hardver/videokartya/index.html",
    "https://hardverapro.hu/aprok/hardver/processzor/index.html",
    "https://hardverapro.hu/aprok/hardver/memoria/index.html",
    "https://hardverapro.hu/aprok/hardver/merevlemez_ssd/index.html",
    "https://hardverapro.hu/aprok/hardver/haz_tapegyseg/index.html",
    "https://hardverapro.hu/aprok/hardver/hutes/index.html",
    "https://hardverapro.hu/aprok/hardver/monitor/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/tv_projektor/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/fejhallgato_fulhallgato/index.html",
]


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
