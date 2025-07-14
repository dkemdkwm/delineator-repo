# streamlit_app/app.py
import streamlit as st
from streamlit_folium import st_folium
import folium
import geopandas as gpd
from pathlib import Path
# from delineator.core import delineate_point
from delineator import delineate_point 

st.set_page_config(page_title="Watershed Delineator", layout="wide")

st.title("🗺️ Click on the map to delineate a watershed")

# --- 1  Draw the base map ----------------------------------------------------
m = folium.Map(location=[4.6, -74.1], zoom_start=5, tiles="OpenStreetMap")
folium.LatLngPopup().add_to(m)   # left-click → popup shows lat/lon
result = st_folium(m, height=600, width="100%")

# --- 2  Capture the click ----------------------------------------------------
if "last_click" not in st.session_state:
    st.session_state["last_click"] = None

if result["last_clicked"]:
    st.session_state["last_click"] = result["last_clicked"]

click = st.session_state["last_click"]

# --- 3  Optional parameters --------------------------------------------------
st.sidebar.header("Parameters")
wid  = st.sidebar.text_input("Watershed ID", value="custom")
area = st.sidebar.number_input("(Optional) Known upstream area (km²)",
                               value=None, format="%.1f",
                               placeholder="leave blank if unknown")

# --- 4  Run delineation ------------------------------------------------------
if st.button("Delineate", disabled=click is None):
    lat, lon = click["lat"], click["lng"]
    with st.spinner("Running delineator… this can take a few minutes ⏳"):
        gpkg_path = delineate_point(lat, lon, wid, area)
    st.success("Done!")

    # --- 5  Show & download result ------------------------------------------
    gdf          = gpd.read_file(gpkg_path)
    geojson      = gdf.to_json()
    folium.GeoJson(geojson, name="Watershed").add_to(m)
    st_folium(m, height=600, width="100%")

    # download buttons
    st.download_button("Download GeoPackage", open(gpkg_path, "rb").read(),
                       file_name=Path(gpkg_path).name)
    st.download_button("Download GeoJSON",
                       data=geojson, file_name=f"{wid}.geojson",
                       mime="application/geo+json")
