import streamlit as st
from streamlit_folium import st_folium
import folium
import geopandas as gpd
from pathlib import Path
from delineator import delineate_point

st.set_page_config(page_title="Watershed Delineator", layout="wide")

st.title("🗺️ Click on the map to delineate a watershed")

# --- Capture the click --------------------------------------------------------
if "last_click" not in st.session_state:
    st.session_state["last_click"] = None

# --- Sidebar parameters -------------------------------------------------------
st.sidebar.header("Parameters")
wid = st.sidebar.text_input("Watershed ID", value="custom")
area = st.sidebar.number_input(
    "(Optional) Known upstream area (km²)",
    value=None, format="%.1f",
    placeholder="leave blank if unknown"
)

# --- Run delineation ----------------------------------------------------------
if st.session_state["last_click"] and st.button("Delineate"):
    lat, lon = st.session_state["last_click"]["lat"], st.session_state["last_click"]["lng"]
    with st.spinner("Running delineator… this can take a few minutes ⏳"):
        gpkg_path = delineate_point(lat, lon, wid, area)
    st.success("Done!")

    # --- Read result and store GeoJSON for later rendering ---
    gdf = gpd.read_file(gpkg_path)
    geojson = gdf.to_json()

    # Save data for rendering
    st.session_state["delineated_geojson"] = geojson
    st.session_state["gpkg_path"] = gpkg_path

# --- Draw map ---------------------------------------------------------------
m = folium.Map(location=[4.6, -74.1], zoom_start=5, tiles="OpenStreetMap")
folium.LatLngPopup().add_to(m)

# Add watershed polygon if delineated
if "delineated_geojson" in st.session_state:
    folium.GeoJson(st.session_state["delineated_geojson"], name="Watershed").add_to(m)

# Show map
result = st_folium(m, height=600, width="100%")

# Update last click
if result["last_clicked"]:
    st.session_state["last_click"] = result["last_clicked"]

# Show download buttons
if "gpkg_path" in st.session_state:
    st.download_button("Download GeoPackage",
                       open(st.session_state["gpkg_path"], "rb").read(),
                       file_name=Path(st.session_state["gpkg_path"]).name)
    st.download_button("Download GeoJSON",
                       data=st.session_state["delineated_geojson"],
                       file_name=f"{wid}.geojson",
                       mime="application/geo+json")
