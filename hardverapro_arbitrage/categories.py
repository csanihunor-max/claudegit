"""Human-readable labels for hardverapro.hu category URLs, for display
(dashboard, notifications) — purely cosmetic, no effect on scraping or
pricing logic. Also the canonical list of category URLs this bot tracks
by default, so it only needs updating in one place (previously duplicated
into the hourly Routine's own prompt text, which drifted from this file).

Every electronics/computing department's browse category is tracked
(hardver, mobil, notebook, pc_szerver, szoftver_jatek, hazimozi_hifi,
foto_video) except each department's own "boltok_szervizek" (shops/
services storefronts, not individual product listings), "pc_szerver/
domain" (domain names for sale, not a physical product with a meaningful
resale/retail comparison), and "pc_szerver/szoftver" (PC software --
almost entirely license keys/digital codes, the same non-physical-good
problem as individual digital listings within the gaming categories, see
scraper/normalize.py's is_digital_good, except here it's ~the whole
category rather than a few listings within an otherwise-physical one).
hardverapro.hu's "egyeb" (misc) department -- cars, fashion, home goods,
coupons, services -- is deliberately NOT tracked: it's explicitly the
site's general-classifieds overflow, not part of "hardver" at all, and
this bot's whole comparison logic (title normalization, used-median
pricing) is built for electronics, not arbitrary goods.
"""
from __future__ import annotations

# Matched by substring against the configured search URL, longest match
# first, so a more specific path (checked first) wins over a shorter one.
_LABELS: dict[str, str] = {
    "szoftver_jatek/asus_rog": "ROG Ally / Xbox Ally",
    "szoftver_jatek/steam_deck": "Steam Deck",
    "szoftver_jatek/lenovo": "Lenovo Legion Go",
    "szoftver_jatek/msi_claw": "MSI Claw",
    "szoftver_jatek/playstation": "PlayStation",
    "szoftver_jatek/nintendo": "Nintendo",
    "szoftver_jatek/xbox": "Xbox",
    "szoftver_jatek/retro_egyeb_konzol": "Retro / Other Consoles",
    "hardver/vr": "VR headsets",
    "szoftver_jatek/vr": "VR headsets",
    "mobil/tablet": "Tablets",
    "mobil/mobil": "Phones",
    "mobil/okosora_okosgyuru": "Smartwatches",
    "mobil/ekonyv_olvaso": "E-Readers",
    "mobil/tartozekok_alkatreszek": "Phone Accessories",
    "pc_szerver/apple_mac_imac": "Mac / iMac",
    "pc_szerver/asztali_gep": "Desktop PCs",
    "pc_szerver/banyaszgep": "Mining Rigs",
    "pc_szerver/kartyameretu_pc_raspberry_stb": "Single-Board PCs",
    "pc_szerver/szerver": "Servers",
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
    "hardver/3d_nyomtatas": "3D Printing",
    "hardver/adathordozo": "USB Drives / Memory Cards",
    "hardver/billentyuzet_eger_pad": "Keyboards / Mice",
    "hardver/egyeb_hardverek": "Other Hardware",
    "hardver/halozati_termekek": "Networking",
    "hardver/jatekvezerlo": "Game Controllers",
    "hardver/nyomtato_szkenner": "Printers / Scanners",
    "hardver/retro_hardver": "Retro Hardware",
    "hazimozi_hifi/tv_projektor": "TVs / Projectors",
    "hazimozi_hifi/fejhallgato_fulhallgato": "Headphones",
    "hazimozi_hifi/auto_hifi": "Car Audio",
    "hazimozi_hifi/dac_kulso_hangkartya": "DACs / Sound Cards",
    "hazimozi_hifi/dj_studio_cuccok": "DJ / Studio Gear",
    "hazimozi_hifi/egyeb_szorakoztato_elektronika": "Other Entertainment Electronics",
    "hazimozi_hifi/erositok_hangfalak": "Amplifiers / Speakers",
    "hazimozi_hifi/filmek_zenek": "Movies / Music",
    "hazimozi_hifi/hangszer": "Musical Instruments",
    "hazimozi_hifi/kabelek": "Cables",
    "hazimozi_hifi/medialejatszok": "Media Players",
    "hazimozi_hifi/mikrofonok": "Microphones",
    "foto_video/fenykepezogep": "Cameras",
    "foto_video/tartozekok_alkatreszek": "Camera Accessories",
    "foto_video/video": "Camcorders / Video",
}

# The category browse pages this bot tracks by default -- every slug here
# was checked against a live fetch (HTTP 200) before being added.
DEFAULT_SEARCH_URLS: list[str] = [
    # Gaming handhelds / consoles (szoftver_jatek)
    "https://hardverapro.hu/aprok/szoftver_jatek/asus_rog/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/steam_deck/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/lenovo/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/msi_claw/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/playstation/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/nintendo/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/xbox/index.html",
    "https://hardverapro.hu/aprok/szoftver_jatek/retro_egyeb_konzol/index.html",
    "https://hardverapro.hu/aprok/hardver/vr/index.html",
    # Mobile (mobil)
    "https://hardverapro.hu/aprok/mobil/mobil/index.html",
    "https://hardverapro.hu/aprok/mobil/tablet/index.html",
    "https://hardverapro.hu/aprok/mobil/okosora_okosgyuru/index.html",
    "https://hardverapro.hu/aprok/mobil/ekonyv_olvaso/index.html",
    "https://hardverapro.hu/aprok/mobil/tartozekok_alkatreszek/index.html",
    # Laptops / desktops / servers (notebook, pc_szerver)
    "https://hardverapro.hu/aprok/notebook/apple/index.html",
    "https://hardverapro.hu/aprok/notebook/pc/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/apple_mac_imac/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/asztali_gep/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/banyaszgep/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/kartyameretu_pc_raspberry_stb/index.html",
    "https://hardverapro.hu/aprok/pc_szerver/szerver/index.html",
    # PC components / peripherals (hardver)
    "https://hardverapro.hu/aprok/hardver/alaplap/index.html",
    "https://hardverapro.hu/aprok/hardver/videokartya/index.html",
    "https://hardverapro.hu/aprok/hardver/processzor/index.html",
    "https://hardverapro.hu/aprok/hardver/memoria/index.html",
    "https://hardverapro.hu/aprok/hardver/merevlemez_ssd/index.html",
    "https://hardverapro.hu/aprok/hardver/haz_tapegyseg/index.html",
    "https://hardverapro.hu/aprok/hardver/hutes/index.html",
    "https://hardverapro.hu/aprok/hardver/monitor/index.html",
    "https://hardverapro.hu/aprok/hardver/billentyuzet_eger_pad/index.html",
    "https://hardverapro.hu/aprok/hardver/halozati_termekek/index.html",
    "https://hardverapro.hu/aprok/hardver/jatekvezerlo/index.html",
    "https://hardverapro.hu/aprok/hardver/nyomtato_szkenner/index.html",
    "https://hardverapro.hu/aprok/hardver/adathordozo/index.html",
    "https://hardverapro.hu/aprok/hardver/3d_nyomtatas/index.html",
    "https://hardverapro.hu/aprok/hardver/retro_hardver/index.html",
    "https://hardverapro.hu/aprok/hardver/egyeb_hardverek/index.html",
    # Home theater / hifi (hazimozi_hifi)
    "https://hardverapro.hu/aprok/hazimozi_hifi/tv_projektor/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/fejhallgato_fulhallgato/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/erositok_hangfalak/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/dac_kulso_hangkartya/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/medialejatszok/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/mikrofonok/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/dj_studio_cuccok/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/auto_hifi/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/kabelek/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/hangszer/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/filmek_zenek/index.html",
    "https://hardverapro.hu/aprok/hazimozi_hifi/egyeb_szorakoztato_elektronika/index.html",
    # Photo / video (foto_video)
    "https://hardverapro.hu/aprok/foto_video/fenykepezogep/index.html",
    "https://hardverapro.hu/aprok/foto_video/video/index.html",
    "https://hardverapro.hu/aprok/foto_video/tartozekok_alkatreszek/index.html",
]


# The classic drop-in PC components: standardized model names (a "Ryzen 5
# 7600X" or "RTX 4070" is already a clean, near-universal title, unlike a
# phone or laptop's freely-worded one), high used-market turnover, and
# real everyday resale demand -- exactly the conditions the used-median
# comparison (pricing/market.py) needs to actually find matching listings.
# Checked against real scraped data: these standardized-name categories
# were disproportionately represented among the handful of normalized
# keys that ever reached 2+ comparable listings at all. Given deeper
# pages per category costs nothing extra for a category that isn't
# actually that deep (pipeline.py stops pagination the moment a page
# introduces no new listings), scraping these specific categories further
# is a direct, low-risk lever for more of the market these five
# categories actually contain.
_LIQUID_HARDWARE_SLUGS = frozenset(
    {
        "hardver/alaplap",
        "hardver/videokartya",
        "hardver/processzor",
        "hardver/memoria",
        "hardver/merevlemez_ssd",
    }
)


def is_liquid_category(url: str) -> bool:
    """True for the handful of PC-component categories worth scraping
    deeper than the rest -- see _LIQUID_HARDWARE_SLUGS above."""
    return any(slug in url for slug in _LIQUID_HARDWARE_SLUGS)


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
