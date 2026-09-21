"""Best-effort distance-from-Budapest for a listing's free-text location.

Requested specifically to gauge pickup feasibility: how far is this from
Budapest, and is it in Pest county (effectively the commuter/day-trip
area around the capital) or somewhere further out. There's no geocoding
API call here on purpose -- the retail (árukereső.hu) feature already hit
one external site that turned out to be unusable (a Cloudflare JS
challenge), so this is a small static table of known settlements'
coordinates instead: no network dependency, nothing that can start
failing if a third-party service changes or blocks requests.

Coverage is necessarily partial -- every Pest county town isn't listed,
and Hungary has thousands of settlements. It's built from every town that
showed up in real scraped listings so far, plus every Pest county town
and every county-seat city that's likely to reasonably. A location that
doesn't match any entry here returns None rather than guessing.
"""
from __future__ import annotations

import math
import re
import unicodedata

_BUDAPEST = (47.4979, 19.0402)

_KERULET_RE = re.compile(r"ker[uü]let|\bbp\.?\b", re.IGNORECASE)

# name (accent/case-folded) -> (latitude, longitude, is_pest_county)
_SETTLEMENTS: dict[str, tuple[float, float, bool]] = {
    # Pest county (the commuter/day-trip ring around Budapest)
    "erd": (47.39, 18.92, True),
    "szentendre": (47.67, 19.08, True),
    "vac": (47.78, 19.13, True),
    "godollo": (47.60, 19.35, True),
    "dunakeszi": (47.63, 19.13, True),
    "cegled": (47.17, 19.80, True),
    "budaors": (47.46, 18.96, True),
    "szigetszentmiklos": (47.34, 19.05, True),
    "nagykoros": (47.03, 19.78, True),
    "vecses": (47.42, 19.27, True),
    "dunaharaszti": (47.34, 19.09, True),
    "gyal": (47.38, 19.22, True),
    "monor": (47.35, 19.45, True),
    "pecel": (47.49, 19.33, True),
    "rackeve": (47.17, 18.95, True),
    "aszod": (47.65, 19.47, True),
    "abony": (47.19, 19.79, True),
    "nagykata": (47.42, 19.75, True),
    "torokbalint": (47.43, 18.92, True),
    "biatorbagy": (47.48, 18.82, True),
    "diosd": (47.41, 18.93, True),
    "halasztelek": (47.36, 19.00, True),
    "szigethalom": (47.31, 19.00, True),
    "solymar": (47.58, 18.93, True),
    "pilisvorosvar": (47.63, 18.90, True),
    "veresegyhaz": (47.65, 19.28, True),
    "fot": (47.62, 19.19, True),
    "isaszeg": (47.55, 19.38, True),
    "ullo": (47.39, 19.35, True),
    "maglod": (47.43, 19.36, True),
    "ecser": (47.41, 19.31, True),
    "kistarcsa": (47.55, 19.25, True),
    "csomor": (47.54, 19.19, True),
    "dabas": (47.18, 19.31, True),
    "gyomro": (47.40, 19.40, True),
    "albertirsa": (47.25, 19.60, True),
    "pilis": (47.29, 19.55, True),
    "orkeny": (47.15, 19.44, True),
    "inarcs": (47.24, 19.36, True),
    "alsonemedi": (47.30, 19.15, True),
    "tokol": (47.29, 18.97, True),
    "kerepes": (47.55, 19.30, True),
    "nagytarcsa": (47.53, 19.29, True),
    "sulysap": (47.44, 19.55, True),
    "tapioszele": (47.35, 19.90, True),
    "tapioszentmarton": (47.32, 19.87, True),
    "ocsa": (47.30, 19.23, True),
    "bugyi": (47.24, 19.13, True),
    "delegyhaza": (47.24, 19.03, True),
    "soskut": (47.36, 18.86, True),
    "pusztazamor": (47.42, 18.83, True),
    # Other counties -- county-seat cities and other towns known to have
    # appeared in real scraped listings
    "debrecen": (47.53, 21.64, False),
    "szeged": (46.25, 20.15, False),
    "miskolc": (48.10, 20.78, False),
    "pecs": (46.07, 18.23, False),
    "gyor": (47.68, 17.63, False),
    "nyiregyhaza": (47.96, 21.72, False),
    "kecskemet": (46.91, 19.69, False),
    "szekesfehervar": (47.19, 18.41, False),
    "szombathely": (47.23, 16.62, False),
    "szolnok": (47.17, 20.18, False),
    "tatabanya": (47.57, 18.40, False),
    "kaposvar": (46.36, 17.80, False),
    "bekescsaba": (46.68, 21.09, False),
    "zalaegerszeg": (46.84, 16.85, False),
    "eger": (47.90, 20.38, False),
    "nagykanizsa": (46.46, 17.00, False),
    "dunaujvaros": (46.96, 18.93, False),
    "mor": (47.38, 18.20, False),
    "sopron": (47.68, 16.59, False),
    "veszprem": (47.09, 17.91, False),
    "salgotarjan": (48.10, 19.80, False),
    "hodmezovasarhely": (46.42, 20.33, False),
    "baja": (46.18, 18.95, False),
    "gyula": (46.65, 21.28, False),
    "esztergom": (47.79, 18.74, False),
    "komarom": (47.74, 18.12, False),
    "tata": (47.65, 18.32, False),
    "ajka": (47.11, 17.56, False),
    "siofok": (46.90, 18.05, False),
    "keszthely": (46.77, 17.25, False),
    "balatonfured": (46.96, 17.89, False),
    "paks": (46.62, 18.86, False),
    "kalocsa": (46.53, 18.98, False),
    "oroshaza": (46.56, 20.67, False),
    "szentes": (46.65, 20.26, False),
    "mako": (46.22, 20.48, False),
    "mezotur": (47.00, 20.63, False),
    "karcag": (47.32, 20.93, False),
    "jaszbereny": (47.50, 19.92, False),
    "gyongyos": (47.78, 19.93, False),
    "ozd": (48.22, 20.30, False),
    "kazincbarcika": (48.25, 20.63, False),
    "tiszaujvaros": (47.94, 21.05, False),
    "satoraljaujhely": (48.40, 21.65, False),
    "nyirbator": (47.84, 22.13, False),
    "mateszalka": (47.95, 22.32, False),
    "vasarosnameny": (48.13, 22.31, False),
    "berettyoujfalu": (47.22, 21.55, False),
    "hajduszoboszlo": (47.44, 21.40, False),
    "hajduboszormeny": (47.67, 21.52, False),
    "mezobereny": (46.83, 21.03, False),
    "gyomaendrod": (46.93, 20.83, False),
    "szarvas": (46.86, 20.55, False),
    "komlo": (46.20, 18.27, False),
    "mohacs": (45.99, 18.68, False),
    "szigetvar": (46.05, 17.80, False),
    "bonyhad": (46.30, 18.53, False),
    "tamasi": (46.63, 18.29, False),
    "dombovar": (46.38, 18.13, False),
    "siklos": (45.85, 18.30, False),
    "marcali": (46.58, 17.42, False),
    "nagyatad": (46.23, 17.36, False),
    "csurgo": (46.26, 17.10, False),
    "barcs": (45.96, 17.46, False),
    "sarvar": (47.25, 16.93, False),
    "celldomolk": (47.25, 17.15, False),
    "koszeg": (47.39, 16.54, False),
    "mosonmagyarovar": (47.87, 17.27, False),
    "csorna": (47.61, 17.25, False),
    "dunafoldvar": (46.81, 18.93, False),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0  # Earth's mean radius, km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def describe_location(location: str | None) -> dict | None:
    """Best-effort {"distance_km": float, "region": "Budapest" | "Pest county" | "Other"}
    for a listing's free-text location, or None if nothing in it is
    recognized. A location can list several places (a seller offering
    pickup at more than one spot) -- every comma-separated token is
    checked, and the closest match to Budapest wins, since that's what
    actually determines pickup feasibility.
    """
    if not location:
        return None

    best: dict | None = None
    for token in location.split(","):
        token = token.strip()
        if not token:
            continue

        if _KERULET_RE.search(token) or _fold(token) == "budapest":
            candidate = {"distance_km": 0.0, "region": "Budapest"}
        else:
            entry = _SETTLEMENTS.get(_fold(token))
            if entry is None:
                continue
            lat, lon, is_pest_county = entry
            candidate = {
                "distance_km": round(_haversine_km(*_BUDAPEST, lat, lon), 1),
                "region": "Pest county" if is_pest_county else "Other",
            }

        if best is None or candidate["distance_km"] < best["distance_km"]:
            best = candidate

    return best
