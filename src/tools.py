from __future__ import annotations
import requests
import math
import os
import unicodedata
from dataclasses import asdict
from functools import lru_cache
from typing import Any
from shapely.geometry import LineString, Point

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(fn=None, **_kwargs):
        if fn is None: return lambda f: f
        return fn

from .data_loader import (Landmark, RiskZone, Shelter, load_landmarks, load_risk_zones, load_shelters)

@lru_cache(maxsize=1)
def _shelters() -> list[Shelter]:
    return load_shelters()

@lru_cache(maxsize=1)
def _risk_zones() -> list[RiskZone]:
    return load_risk_zones()

@lru_cache(maxsize=1)
def _landmarks() -> list[Landmark]:
    return load_landmarks()

def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_text.lower().replace("ı", "i").split())

def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

def _build_route_geometry(lon1: float, lat1: float, lon2: float, lat2: float, n_waypoints: int = 12) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    norm = math.hypot(dlon, dlat) or 1.0
    perp_lon = -dlat / norm
    perp_lat = dlon / norm
    bend = 0.05 * norm 
    for i in range(n_waypoints + 1):
        t = i / n_waypoints
        bend_factor = 4 * t * (1 - t) * bend
        lon = lon1 + dlon * t + perp_lon * bend_factor
        lat = lat1 + dlat * t + perp_lat * bend_factor
        coords.append((lon, lat))
    return coords

def _polyline_length_m(coords: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(coords, coords[1:]):
        total += haversine_m(lon1, lat1, lon2, lat2)
    return total

def geocode_address_impl(query: str) -> dict[str, Any]:
    if not query or not query.strip(): return {"ok": False, "error": "empty query"}
    norm_q = _normalize(query)
    best: tuple[Landmark, int] | None = None
    
    for lm in _landmarks():
        candidates = [lm.name, *lm.aliases]
        for cand in candidates:
            ncand = _normalize(cand)
            if ncand == norm_q:
                return {"ok": True, "matched": cand, "lat": lm.lat, "lon": lm.lon, "district": lm.district, "confidence": 1.0}
            if ncand in norm_q or norm_q in ncand:
                score = len(set(ncand.split()) & set(norm_q.split())) + 1
                if best is None or score > best[1]:
                    best = (lm, score)
                    
    if best is not None:
        lm, score = best
        return {"ok": True, "matched": lm.name, "lat": lm.lat, "lon": lm.lon, "district": lm.district, "confidence": min(0.9, 0.5 + 0.1 * score)}
    return {"ok": False, "error": f"no match for '{query}'"}

ANADOLU_YAKASI = ["uskudar", "kadikoy", "maltepe", "kartal", "pendik", "tuzla", "umraniye", "atasehir", "beykoz", "sancaktepe", "cekmekoy", "sultanbeyli", "sile", "adalar"]

def _get_side(district_name: str) -> str:
    norm_name = _normalize(district_name)
    for ilce in ANADOLU_YAKASI:
        if ilce in norm_name: return "Anadolu"
    return "Avrupa"

def find_nearby_shelters_impl(lat: float, lon: float, k: int = 5) -> list[dict[str, Any]]:
    user_side = "Avrupa"
    closest_lm = None
    min_dist = float('inf')
    
    for lm in _landmarks():
        dist = haversine_m(lon, lat, lm.lon, lm.lat)
        if dist < min_dist:
            min_dist = dist
            closest_lm = lm
            
    if closest_lm:
        user_side = _get_side(closest_lm.district)

    ranked = []
    for s in _shelters():
        if _get_side(s.district) != user_side: continue
        dist = haversine_m(lon, lat, s.lon, s.lat)
        ranked.append({**asdict(s), "distance_m": round(dist, 1)})
        
    ranked.sort(key=lambda r: r["distance_m"])
    
    cleaned = []
    for r in ranked[:k]:
        cleaned.append({"id": r["id"], "name": r["name"], "district": r["district"], "capacity": r["capacity"], "type": r["type"], "lat": r["lat"], "lon": r["lon"], "distance_m": r["distance_m"]})
    return cleaned

def _live_osm_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> dict[str, Any]: 
    import networkx as nx
    import osmnx as ox
    from shapely.geometry import LineString

    ox.settings.use_cache = True
    print("🌐 OSMnx Canlı Harita yükleniyor (Cache boşsa birkaç saniye bekletebilir)...")
    
    north = max(start_lat, end_lat) + 0.01
    south = min(start_lat, end_lat) - 0.01
    east = max(start_lon, end_lon) + 0.01
    west = min(start_lon, end_lon) - 0.01
    
    bbox = (west, south, east, north)
    graph = ox.graph_from_bbox(bbox=bbox, network_type="walk")
    
    zones = _risk_zones()
    for u, v, key, data in graph.edges(keys=True, data=True):
        geom = data['geometry'] if 'geometry' in data else LineString([(graph.nodes[u]['x'], graph.nodes[u]['y']), (graph.nodes[v]['x'], graph.nodes[v]['y'])])
        penalty = 1.0
        for zone in zones:
            if geom.intersects(zone.polygon): penalty += 50.0  
        data['safe_length'] = data.get('length', 1.0) * penalty

    try:
        src = ox.distance.nearest_nodes(graph, X=start_lon, Y=start_lat)
        dst = ox.distance.nearest_nodes(graph, X=end_lon, Y=end_lat)
    except AttributeError:
        src = ox.nearest_nodes(graph, X=start_lon, Y=start_lat)
        dst = ox.nearest_nodes(graph, X=end_lon, Y=end_lat)
    
    try:
        path = nx.shortest_path(graph, src, dst, weight="safe_length")
    except nx.NetworkXNoPath:
        return {"ok": False, "error": "Rota bulunamadi."}
        
    coords = [(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in path]
    distance_m = _polyline_length_m(coords) 
    duration_s = distance_m / (5_000 / 3_600)
    
    print("✅ OSMnx ile riskten kaçan rota başarıyla çizildi!")
    return {"ok": True, "mode": "osm", "coords": coords, "distance_m": round(distance_m, 1), "duration_s": round(duration_s, 1), "duration_min": round(duration_s / 60, 1)}

def compute_route_impl(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> dict:
    if os.getenv("USE_LIVE_OSM", "false").lower() == "true":
        try:
            res = _live_osm_route(start_lat, start_lon, end_lat, end_lon)
            if res.get("ok"):
                return {"ok": True, "coords": res["coords"], "polyline": res["coords"], "distance_m": res["distance_m"], "distance_meters": res["distance_m"], "duration_min": res["duration_min"], "duration_minutes": res["duration_min"]}
        except Exception as e:
            print(f"OSMnx Hata Verdi: {e}")

    url = f"http://router.project-osrm.org/route/v1/foot/{start_lon},{start_lat};{end_lon},{end_lat}"
    params = {"overview": "full", "geometries": "geojson"}
    headers = {"User-Agent": "AfetRota-Agent/1.0 (Student Project)"}
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == "Ok":
                coords = data["routes"][0]["geometry"]["coordinates"]
                if len(coords) > 20:
                    simplified = coords[::5]
                    if simplified[-1] != coords[-1]: simplified.append(coords[-1])
                    coords = simplified

                dist_m = data["routes"][0]["distance"]
                dur_min = data["routes"][0]["duration"] / 60.0
                return {"ok": True, "coords": coords, "polyline": coords, "distance_m": dist_m, "distance_meters": dist_m, "duration_min": dur_min, "duration_minutes": dur_min}
    except Exception as e:
        pass

    coords = _build_route_geometry(start_lon, start_lat, end_lon, end_lat)
    dist_m = _polyline_length_m(coords)
    dur_min = dist_m / 80.0
    return {"ok": True, "coords": coords, "polyline": coords, "distance_m": dist_m, "distance_meters": dist_m, "duration_min": dur_min, "duration_minutes": dur_min}

def score_route_risk_impl(coords: list[tuple[float, float]]) -> dict[str, Any]:
    if len(coords) < 2: return {"ok": False, "error": "route has fewer than 2 vertices"}
    line = LineString(coords)
    total_len_m = _polyline_length_m(coords)
    if total_len_m == 0: return {"ok": False, "error": "zero-length route"}

    crossed: list[dict[str, Any]] = []
    weighted = 0.0
    for zone in _risk_zones():
        if not line.intersects(zone.polygon): continue
        inter = line.intersection(zone.polygon)
        if inter.is_empty: continue
        segs: list[list[tuple[float, float]]] = []
        if inter.geom_type == "LineString": segs.append(list(inter.coords))
        elif inter.geom_type == "MultiLineString":
            for g in inter.geoms: segs.append(list(g.coords))
        else: continue
        seg_len_m = sum(_polyline_length_m(s) for s in segs)
        weighted += seg_len_m * zone.risk_score
        crossed.append({"zone_id": zone.id, "zone_name": zone.name, "risk_level": zone.risk_level, "risk_score": zone.risk_score, "primary_hazard": zone.primary_hazard, "intersected_m": round(seg_len_m, 1)})
        
    overall = weighted / total_len_m
    verdict = "safe" if overall < 0.03 else ("moderate" if overall < 0.08 else "dangerous")
    return {"ok": True, "overall_risk": round(overall, 3), "verdict": verdict, "total_length_m": round(total_len_m, 1), "crossed_zones": crossed}

def shelter_details_impl(shelter_id: str) -> dict[str, Any]:
    for s in _shelters():
        if s.id == shelter_id:
            return {"ok": True, "id": s.id, "name": s.name, "district": s.district, "capacity": s.capacity, "type": s.type, "lat": s.lat, "lon": s.lon}
    return {"ok": False, "error": f"unknown shelter id: {shelter_id}"}

@tool
def geocode_address(query: str) -> dict:
    """Resolve a place name, neighborhood, or landmark in Istanbul to (lat, lon).
    Examples that work: "Taksim", "Kadikoy iskele", "ITU Ayazaga", "Bakirkoy",
    "Sultanahmet". Returns ok=False if the name cannot be resolved.
    """
    return geocode_address_impl(query)

@tool
def find_nearby_shelters(lat: float, lon: float, k: int = 5) -> list:
    """Find the k nearest official emergency assembly points to a coordinate.
    Use this after geocoding the user's location. Returns a list ordered by
    straight-line distance with shelter id, name, district, capacity, type,
    coordinates, and distance in meters.
    """
    return find_nearby_shelters_impl(lat=lat, lon=lon, k=k)

@tool
def compute_route(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> dict:
    """Compute a walking route between two coordinates.
    Returns the route polyline (list of (lon, lat)), distance in meters, and
    estimated walking duration in minutes.
    """
    return compute_route_impl(start_lat, start_lon, end_lat, end_lon)

@tool
def score_route_risk(coords: list) -> dict:
    """Score a route's seismic risk.
    Pass the polyline returned by compute_route (list of [lon, lat] pairs).
    Returns an overall_risk score in [0, 1], a verdict (safe / moderate /
    dangerous), and the list of risk zones the route crosses.
    """
    norm = [(float(c[0]), float(c[1])) for c in coords]
    return score_route_risk_impl(norm)

@tool
def shelter_details(shelter_id: str) -> dict:
    """Get full details for a shelter by its id (e.g. "S007")."""
    return shelter_details_impl(shelter_id)

ALL_TOOLS = [geocode_address, find_nearby_shelters, compute_route, score_route_risk, shelter_details]