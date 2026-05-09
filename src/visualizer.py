from pathlib import Path
import folium
from folium.plugins import MiniMap
from .agent import AgentResult
from .data_loader import load_risk_zones, load_shelters

RISK_COLORS = {"very_high": "#7a0d0d", "high": "#c0392b", "moderate": "#e67e22"}

def render_map(result: AgentResult, output_path: str | Path) -> Path:
    output_path = Path(output_path)
    center = [41.04, 28.99] if result.start is None else [result.start["lat"], result.start["lon"]]
    fmap = folium.Map(location=center, zoom_start=12, tiles="OpenStreetMap", control_scale=True)

    risk_layer = folium.FeatureGroup(name="Seismic risk zones", show=True)
    for zone in load_risk_zones():
        coords = [(lat, lon) for lon, lat in zone.polygon.exterior.coords]
        folium.Polygon(locations=coords, color=RISK_COLORS.get(zone.risk_level, "#888"), weight=1, fill=True,
                       fill_opacity=0.35, popup=folium.Popup(f"<b>{zone.name}</b><br/>{zone.risk_level} risk", max_width=200)).add_to(risk_layer)
    risk_layer.add_to(fmap)

    shelters_layer = folium.FeatureGroup(name="Assembly points", show=False)
    for s in load_shelters():
        folium.CircleMarker(location=[s.lat, s.lon], radius=4, color="green", fill=True, fill_opacity=0.6,
                            popup=folium.Popup(f"{s.name} ({s.capacity})", max_width=200)).add_to(shelters_layer)
    shelters_layer.add_to(fmap)

    if result.candidate_shelters:
        for cand in result.candidate_shelters:
            folium.Marker(location=[cand["lat"], cand["lon"]], icon=folium.Icon(color="gray", icon="info-sign"),
                          popup=folium.Popup(f"Candidate: {cand['name']}", max_width=200)).add_to(fmap)

    if result.selected_route:
        route_coords = [[lat, lon] for lon, lat in result.selected_route["coords"]]
        risk_color = "green"
        if result.selected_risk:
            if result.selected_risk["verdict"] == "moderate": risk_color = "orange"
            elif result.selected_risk["verdict"] == "dangerous": risk_color = "red"
        folium.PolyLine(locations=route_coords, color=risk_color, weight=5, opacity=0.8).add_to(fmap)

    if result.selected_shelter:
        sh = result.selected_shelter
        folium.Marker(location=[sh["lat"], sh["lon"]], icon=folium.Icon(color="green", icon="star"),
                      popup=folium.Popup(f"<b>Recommended shelter</b><br/>{sh['name']}<br/>{sh['district']} · capacity {sh['capacity']:,}", max_width=300)).add_to(fmap)

    if result.start is not None:
        folium.Marker(location=[result.start["lat"], result.start["lon"]], icon=folium.Icon(color="red", icon="user", prefix="fa"),
                      popup=folium.Popup(f"<b>Your location</b><br/>{result.start['matched'].title()} ({result.start['district']})", max_width=260)).add_to(fmap)

    if result.narrative:
        header_html = f"""
        <div style="position: fixed; top: 12px; left: 60px; z-index: 9999; background: white; padding: 12px 16px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); max-width: 460px; font-family: -apple-system, Segoe UI, sans-serif; font-size: 13px;">
          <div style="font-weight: 600; margin-bottom: 4px;">AfetRota — {result.mode.upper()}</div>
          <div>{result.narrative}</div>
        </div>
        """
        fmap.get_root().html.add_child(folium.Element(header_html))

    folium.LayerControl().add_to(fmap)
    MiniMap(toggle_display=True, position="bottomleft").add_to(fmap)
    fmap.save(str(output_path))
    return output_path