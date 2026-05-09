import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from shapely.geometry import Point, Polygon, shape

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

@dataclass(frozen=True)
class Shelter:
    id: str
    name: str
    district: str
    capacity: int
    type: str
    lon: float
    lat: float

    @property
    def point(self) -> Point:
        return Point(self.lon, self.lat)

@dataclass(frozen=True)
class RiskZone:
    id: str
    name: str
    risk_level: str
    risk_score: float
    primary_hazard: str
    notes: str
    polygon: Polygon

@dataclass(frozen=True)
class Landmark:
    name: str
    aliases: tuple[str, ...]
    lon: float
    lat: float
    district: str

def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_shelters() -> list[Shelter]:
    raw = _load_json(DATA_DIR / "shelters_istanbul.geojson")
    out = []
    for feat in raw["features"]:
        props = feat["properties"]
        lon, lat = feat["geometry"]["coordinates"]
        out.append(Shelter(id=props["id"], name=props["name"], district=props["district"], 
                           capacity=int(props["capacity"]), type=props["type"], lon=lon, lat=lat))
    return out

def load_risk_zones() -> list[RiskZone]:
    raw = _load_json(DATA_DIR / "risk_zones.geojson")
    out = []
    for feat in raw["features"]:
        props = feat["properties"]
        out.append(RiskZone(id=props["id"], name=props["name"], risk_level=props["risk_level"], 
                            risk_score=float(props["risk_score"]), primary_hazard=props["primary_hazard"], 
                            notes=props.get("notes", ""), polygon=shape(feat["geometry"])))
    return out

def load_landmarks() -> list[Landmark]:
    raw = _load_json(DATA_DIR / "landmarks.json")
    out = []
    for entry in raw["landmarks"]:
        out.append(Landmark(name=entry["name"], aliases=tuple(entry.get("aliases", [])), 
                            lon=entry["lon"], lat=entry["lat"], district=entry["district"]))
    return out