from pathlib import Path
import json

import pandas as pd
import geopandas as gpd
import folium
from folium.elements import MacroElement
import streamlit as st
from streamlit_folium import st_folium
from delineator import delineate_point
from jinja2 import Template


# ────────────────────────────────────────────────────────────────────────────
#  JS helper: click → popup with a “Delineate here” button
#  The button uses parent.postMessage; streamlit-folium surfaces it.
# ────────────────────────────────────────────────────────────────────────────
class PopupButton(MacroElement):
    _template = Template(
        """
{% macro script(this, kwargs) %}
(function () {
  const map = {{ this._parent.get_name() }};

  function addPopup(e) {
    const lat = e.latlng.lat.toFixed(6);
    const lon = e.latlng.lng.toFixed(6);

    const html =
      '<button style="background:#3388ff;color:#fff;border:none;' +
      'padding:6px 10px;border-radius:4px;cursor:pointer;" ' +
      'onclick="parent.postMessage(' +
      '{event:\\'delineate\\',lat:'+lat+',lon:'+lon+'},\\'*\\')">' +
      'Delineate here</button><br><small>' + lat + ', ' + lon + '</small>';

    L.popup().setLatLng(e.latlng).setContent(html).openOn(map);
  }

  map.on('click', addPopup);
})();
{% endmacro %}
"""
    )


# ─────────────────────────── Streamlit page setup ───────────────────────────
st.set_page_config(page_title="Watershed Delineator", layout="wide")
st.title("🗺️ Click anywhere, then press **Delineate here** in the popup")

st.sidebar.header("Parameters")
wid = st.sidebar.text_input("Watershed ID", "custom")
area = st.sidebar.number_input(
    "(Optional) Known upstream area (km²)", value=None, format="%.1f",
    placeholder="leave blank"
)

# ────────────────────────────── Base map ──────────────────────────────────
base = folium.Map(location=[4.6, -74.1], zoom_start=5, tiles="OpenStreetMap")
base.add_child(PopupButton())
result = st_folium(base, height=600, width="100%", key="basemap")

# ─────────────────── Helper: extract coordinates from result dict ──────────
def get_click(res: dict | None):
    if not isinstance(res, dict):
        return None
    # 1️⃣ newer streamlit-folium (<0.18)
    if "last_message" in res and isinstance(res["last_message"], dict):
        return res["last_message"]
    # 2️⃣ v0.17: last_component_value is a JSON string
    if "last_component_value" in res:
        try:
            msg = json.loads(res["last_component_value"])
            return msg if isinstance(msg, dict) else None
        except json.JSONDecodeError:
            pass
    return None


msg = get_click(result)

# ─────────────────── Delineate when button pressed ─────────────────────────
if msg and msg.get("event") == "delineate":
    lat, lon = float(msg["lat"]), float(msg["lon"])

    # quick outlet preview
    preview = folium.Map(location=[lat, lon], zoom_start=11, tiles="OpenStreetMap")
    folium.Marker([lat, lon], tooltip="Outlet").add_to(preview)
    st_folium(preview, height=300, width="100%", key=f"marker_{lat}_{lon}")

    with st.spinner("Running delineator … this can take a minute ⏳"):
        outfile = delineate_point(lat, lon, wid, area)

    # -------- load output agnostic of extension ---------------------------
    def load_vector(path: str) -> gpd.GeoDataFrame:
        if path.endswith(".csv"):
            df = pd.read_csv(path)
            return gpd.GeoDataFrame(df,
                       geometry=gpd.points_from_xy(df.lon, df.lat),
                       crs=4326)
        elif path.endswith(".gpkg"):
            import fiona
            return gpd.read_file(path, layer=fiona.listlayers(path)[0])
        return gpd.read_file(path)

    gdf = load_vector(outfile)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    poly = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if poly.empty:
        st.error("No polygon geometry returned."); st.stop()

    # -------- draw watershed ---------------------------------------------
    xmin, ymin, xmax, ymax = poly.total_bounds
    wmap = folium.Map()
    folium.GeoJson(
        poly.__geo_interface__,
        style_function=lambda _: {
            "fillColor": "#3388ff",
            "color": "#e31a1c",
            "weight": 2,
            "fillOpacity": 0.35,
        },
    ).add_to(wmap)
    wmap.fit_bounds([[ymin, xmin], [ymax, xmax]])
    folium.Marker([lat, lon], tooltip="Outlet",
                  icon=folium.Icon(color="blue")).add_to(wmap)

    st_folium(wmap, height=600, width="100%",
              key=f"watershed_{lat:.4f}_{lon:.4f}")

    # -------- downloads ---------------------------------------------------
    st.download_button("Download GeoJSON",
                       poly.to_json(),
                       file_name=f"{wid}.geojson",
                       mime="application/geo+json")
