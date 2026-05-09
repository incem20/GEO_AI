"""Build the agent's data files from real IBB Open Data downloads.

Inputs (downloaded once via ``scripts/download_ibb_data.py``):

- ``data/raw_ibb_green_areas.geojson``      (1,371 park/green-area polygons)
- ``data/raw_ibb_muhtarlik.geojson``        (963 neighborhood mukhtar points)
- ``data/raw_ibb_deprem_senaryosu.csv``     (M7.5 nighttime damage scenario)

Outputs (committed to the repo, used by the agent at runtime):

- ``data/shelters_istanbul.geojson``   — Top-N largest parks as assembly points
                                         with capacity derived from polygon area
- ``data/risk_zones.geojson``          — High-risk neighborhoods as buffered
                                         polygons with risk_score derived from
                                         the official damage scenario

Run::

    python scripts/build_real_data.py
"""

from __future__ import annotations

import csv
import json
import math
import unicodedata
from pathlib import Path

from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

RAW_GREEN_AREAS = DATA / "raw_ibb_green_areas.geojson"
RAW_MUHTARLIK = DATA / "raw_ibb_muhtarlik.geojson"
RAW_SCENARIO = DATA / "raw_ibb_deprem_senaryosu.csv"

OUT_SHELTERS = DATA / "shelters_istanbul.geojson"
OUT_RISK = DATA / "risk_zones.geojson"

# Assembly-suitable types in the IBB green-areas dataset
ASSEMBLY_TYPES = {"Park", "Mesire Alan", "Spor Alan", "Refj Park"}

# Capacity: ~1 m² per evacuee is the IBB/AFAD planning rule of thumb for
# emergency assembly. We use 0.7 m²/person to be conservative.
M2_PER_PERSON = 0.7

# Top-N largest parks to keep as shelters (keeps the GeoJSON small)
TOP_N_SHELTERS = 60

# How many high-risk neighborhoods to publish as risk zones
TOP_N_RISK = 100

# Buffer radius around each high-risk neighborhood centroid
RISK_BUFFER_DEG = 0.003  # ~333 m at Istanbul's latitude


def _title_ascii(s) -> str:
    """ASCII-folded title-case name (no diacritics, no combining-dot artifacts)."""
    if s is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    asc = "".join(c for c in nfkd if not unicodedata.combining(c))
    asc = asc.replace("ı", "i").replace("İ", "I")
    return asc.lower().title()


def _norm(s: str) -> str:
    """Normalize Turkish neighborhood/district names for joining."""
    if s is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s))
    asc = "".join(c for c in nfkd if not unicodedata.combining(c))
    return (
        asc.upper()
        .replace("İ", "I")
        .replace("I", "I")
        .replace("Ğ", "G")
        .replace("Ü", "U")
        .replace("Ş", "S")
        .replace("Ö", "O")
        .replace("Ç", "C")
        .strip()
    )


def _polygon_area_m2(poly: Polygon) -> float:
    """Approximate polygon area in m² using a local equirectangular projection."""
    if poly.is_empty:
        return 0.0
    cy = poly.centroid.y
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(cy))
    coords = [(x * m_per_deg_lon, y * m_per_deg_lat) for x, y in poly.exterior.coords]
    if len(coords) < 3:
        return 0.0
    s = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


# ---------------------------------------------------------------------------
# 1. Load IBB green areas, build shelters
# ---------------------------------------------------------------------------


def build_shelters() -> list[dict]:
    print(f"[shelters] reading {RAW_GREEN_AREAS.name} ...")
    with RAW_GREEN_AREAS.open("rb") as f:
        gj = json.load(f)
    print(f"[shelters] {len(gj['features'])} raw features")

    candidates = []
    for feat in gj["features"]:
        props = feat.get("properties", {}) or {}
        geom = feat.get("geometry")
        if geom is None:
            continue
        # Property keys are mojibake'd (Latin-1 reading of UTF-8). Use known position.
        # The actual keys in the file are: MAHALLE, TUR, ILCE, WKT_GEOM
        # We accept any key whose UPPER form matches.
        norm_props = {}
        for k, v in props.items():
            try:
                # Re-encode mojibake key
                fixed = k.encode("latin-1").decode("utf-8")
            except Exception:
                fixed = k
            norm_props[fixed.upper()] = v
        tur = str(norm_props.get("TUR", "") or "")
        # Filter assembly-suitable types
        if not any(t.lower() in tur.lower() for t in ASSEMBLY_TYPES):
            continue

        try:
            poly = shape(geom)
        except Exception:
            continue
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)
        if poly.geom_type != "Polygon" or poly.is_empty:
            continue

        area_m2 = _polygon_area_m2(poly)
        if area_m2 < 5_000:  # ignore parks < 0.5 ha
            continue

        candidates.append(
            {
                "name": _title_ascii(norm_props.get("MAHALLE", "")),
                "district": _title_ascii(norm_props.get("ILCE", "")),
                "type": tur,
                "area_m2": round(area_m2, 1),
                "capacity": int(area_m2 / M2_PER_PERSON),
                "centroid": (poly.centroid.x, poly.centroid.y),
                "polygon": poly,
            }
        )

    print(f"[shelters] {len(candidates)} candidates after type/area filter")
    candidates.sort(key=lambda c: -c["area_m2"])
    keep = candidates[:TOP_N_SHELTERS]

    features = []
    for i, c in enumerate(keep, start=1):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": f"S{i:03d}",
                    "name": c["name"],
                    "district": c["district"],
                    "capacity": c["capacity"],
                    "area_m2": c["area_m2"],
                    "type": "park",
                    "source": "IBB Open Data — Kentsel Açık ve Yeşil Alan Koordinatları",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [c["centroid"][0], c["centroid"][1]],
                },
            }
        )

    out = {
        "type": "FeatureCollection",
        "name": "istanbul_emergency_assembly_points_real",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    OUT_SHELTERS.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[shelters] wrote {OUT_SHELTERS} ({len(features)} features)")
    return keep


# ---------------------------------------------------------------------------
# 2. Load Muhtarlık + Scenario, build risk zones
# ---------------------------------------------------------------------------


def build_risk_zones() -> None:
    print(f"[risk] reading {RAW_MUHTARLIK.name} ...")
    with RAW_MUHTARLIK.open("rb") as f:
        mu = json.load(f)
    # Build (DISTRICT, MAHALLE) -> (lon, lat). Keys in source: 'İlçe Adı',
    # 'Mahalle Adı', 'Longtitude', 'Latitude'. Match by ASCII-folded substring
    # so Turkish dotted-I lower-casing artifacts don't cause misses.
    locs: dict[tuple[str, str], tuple[float, float]] = {}
    for feat in mu["features"]:
        props = feat.get("properties", {}) or {}
        district = mahalle = None
        lon = lat = None
        for k, v in props.items():
            kn = _norm(k)  # uppercase ASCII-folded
            if "ILCE" in kn:
                district = v
            elif "MAHALLE" in kn and "MUHTARL" not in kn:
                mahalle = v
            elif "LONGT" in kn or kn == "LON":
                lon = v
            elif "LATIT" in kn or kn == "LAT":
                lat = v
        if district is None or mahalle is None or lon is None or lat is None:
            continue
        district_n = _norm(district)
        mahalle_n = _norm(mahalle)
        try:
            locs[(district_n, mahalle_n)] = (float(lon), float(lat))
        except (TypeError, ValueError):
            continue
    print(f"[risk] {len(locs)} mukhtar locations")

    print(f"[risk] reading {RAW_SCENARIO.name} ...")
    rows: list[dict] = []
    with RAW_SCENARIO.open("r", encoding="cp1254") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            try:
                vh = int(r["cok_agir_hasarli_bina_sayisi"])
                h = int(r["agir_hasarli_bina_sayisi"])
                m = int(r["orta_hasarli_bina_sayisi"])
                light = int(r["hafif_hasarli_bina_sayisi"])
                deaths = int(r["can_kaybi_sayisi"])
            except (KeyError, ValueError):
                continue
            total_buildings = vh + h + m + light
            if total_buildings == 0:
                continue
            severe_rate = (vh + h) / total_buildings  # in [0, 1]
            district_n = _norm(r.get("ilce_adi", ""))
            mahalle_n = _norm(r.get("mahalle_adi", ""))
            rows.append(
                {
                    "district": district_n,
                    "mahalle": mahalle_n,
                    "very_heavy": vh,
                    "heavy": h,
                    "moderate": m,
                    "light": light,
                    "deaths": deaths,
                    "total": total_buildings,
                    "severe_rate": severe_rate,
                }
            )
    print(f"[risk] {len(rows)} scenario rows")

    # Join scenario rows with mukhtar coordinates
    joined: list[dict] = []
    misses = 0
    for r in rows:
        key = (r["district"], r["mahalle"])
        loc = locs.get(key)
        if loc is None:
            misses += 1
            continue
        r2 = dict(r)
        r2["lon"], r2["lat"] = loc
        joined.append(r2)
    print(f"[risk] joined {len(joined)} rows ({misses} missed)")

    # Sort by severe_rate desc, take TOP_N_RISK
    joined.sort(key=lambda r: -r["severe_rate"])
    top = joined[:TOP_N_RISK]
    print(f"[risk] top severe_rate: {top[0]['severe_rate']:.3f}, "
          f"bottom of top-{TOP_N_RISK}: {top[-1]['severe_rate']:.3f}")

    # Build buffered polygon zones
    features = []
    for i, r in enumerate(top, start=1):
        center = Point(r["lon"], r["lat"])
        # Square buffer (axis-aligned) for clear demo visualization
        b = RISK_BUFFER_DEG
        poly = Polygon([
            (center.x - b, center.y - b),
            (center.x + b, center.y - b),
            (center.x + b, center.y + b),
            (center.x - b, center.y + b),
        ])
        score = round(r["severe_rate"], 3)
        # Calibrated to the IBB M7.5 nighttime scenario distribution:
        # 95th percentile = 0.182, max = 0.297. Anything above 25% is rare.
        if score >= 0.25:
            level = "very_high"
        elif score >= 0.20:
            level = "high"
        else:
            level = "moderate"
        features.append({
            "type": "Feature",
            "properties": {
                "id": f"R{i:03d}",
                "name": f"{_title_ascii(r['mahalle'])} ({_title_ascii(r['district'])})",
                "risk_level": level,
                "risk_score": score,
                "primary_hazard": "scenario_severe_damage",
                "very_heavy_damage": r["very_heavy"],
                "heavy_damage": r["heavy"],
                "expected_deaths": r["deaths"],
                "total_buildings_in_scenario": r["total"],
                "notes": (
                    f"Severe-damage rate (very-heavy + heavy) / total = "
                    f"{score:.1%} from IBB M7.5 nighttime scenario."
                ),
                "source": "IBB Open Data — Deprem Senaryosu Analiz Sonuçları",
            },
            "geometry": mapping(poly),
        })

    out = {
        "type": "FeatureCollection",
        "name": "istanbul_seismic_risk_zones_real",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    OUT_RISK.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[risk] wrote {OUT_RISK} ({len(features)} features)")


if __name__ == "__main__":
    build_shelters()
    build_risk_zones()
