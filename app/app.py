import streamlit as st
from streamlit_folium import st_folium
import folium
import geopandas as gpd
from pathlib import Path
from delineator import delineate_point
import fiona
from datetime import datetime
import base64

def image_to_base64(path: str) -> str:
    with open(path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()
    
logo1_base64 = image_to_base64("app/cunLogo.png")
logo2_base64 = image_to_base64("app/consultoraLogo.png")

st.markdown(
    f"""
    <div style="display: flex; align-items: center; justify-content: space-between; padding: 1rem 0;">
        <img src="data:image/png;base64,{logo1_base64}" width="240" style="margin-right: 20px;" />
        <div style="flex-grow: 1; text-align: center;">
            <h2 style="margin: 0;">Delimitación de cuencas hidrográficas</h2>
            <h4 style="margin: 0; color: #555;">
                Selecciona un punto en el mapa para delimitar una cuenca hidrográfica 🗺️ 
            </h4>
        </div>
        <img src="data:image/png;base64,{logo2_base64}" width="240" style="margin-left: 20px;" />
    </div>
    """,
    unsafe_allow_html=True
)

st.set_page_config(page_title="Watershed Delineator", layout="wide")


# --- Reset button ---
if st.sidebar.button("🔁 Reset session"):
    st.session_state.clear()
    st.experimental_rerun()

# --- Session state for click memory ---
if "last_click" not in st.session_state:
    st.session_state["last_click"] = None

# --- Sidebar params ---
st.sidebar.header("Parameters")
wid = st.sidebar.text_input("Watershed ID", value="custom")
area = st.sidebar.number_input(
    "(Optional) Known upstream area (km²)",
    value=None, format="%.1f",
    placeholder="leave blank if unknown"
)

# --- Run delineator ---
if st.session_state["last_click"] and st.button("Delineate"):
    lat, lon = st.session_state["last_click"]["lat"], st.session_state["last_click"]["lng"]
    st.write(f"📍 Selected point: lat={lat}, lon={lon}")

    with st.spinner("Running delineator… this can take a few minutes ⏳"):
        gpkg_path = delineate_point(lat, lon, wid, area)

    if not Path(gpkg_path).exists():
        st.error(f"❌ GPKG file was not created: {gpkg_path}")
    else:
        st.success("✅ Delineation complete!")
        st.write(f"📦 Output file: `{gpkg_path}`")
        st.session_state["gpkg_path"] = gpkg_path

        try:
            # DEBUG: Show available layers
            available_layers = fiona.listlayers(gpkg_path)
            st.write("📄 Available layers in GPKG:", available_layers)

            # Read default watershed layer (no layer name specified)
            watershed_gdf = gpd.read_file(gpkg_path)
            st.session_state["geojson"] = watershed_gdf.to_json()

            # Optional layers with fallback
            try:
                st.session_state["streams"] = gpd.read_file(gpkg_path, layer="streams").to_json()
            except Exception:
                st.warning("⚠️ Streams layer not found.")

            try:
                st.session_state["snap_point"] = gpd.read_file(gpkg_path, layer="snap_point").to_json()
            except Exception:
                st.warning("⚠️ Snap point layer not found.")

            try:
                st.session_state["requested_point"] = gpd.read_file(gpkg_path, layer="pour_point").to_json()
            except Exception:
                st.warning("⚠️ Requested point layer not found.")

            # Bounding box
            bounds = watershed_gdf.total_bounds
            if any(map(lambda x: x is None or x != x, bounds)):  # NaN check
                st.warning("⚠️ Watershed has invalid bounds.")
            else:
                center_lat = (bounds[1] + bounds[3]) / 2
                center_lon = (bounds[0] + bounds[2]) / 2
                st.session_state["map_center"] = [center_lat, center_lon]
                st.session_state["map_bounds"] = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
                st.write(f"🗺️ Center: {st.session_state['map_center']}")
                st.write(f"📐 Bounds: {st.session_state['map_bounds']}")

        except Exception as e:
            st.error(f"⚠️ Failed to load output layers: {e}")

# --- Map setup ---
map_location = st.session_state.get("map_center", [4.6, -74.1])
m = folium.Map(location=map_location, zoom_start=9, tiles="OpenStreetMap")
folium.LatLngPopup().add_to(m)

# --- Add layers if available ---
if "geojson" in st.session_state:
    folium.GeoJson(
        st.session_state["geojson"],
        name="Watershed",
        style_function=lambda _: {
            "fillColor": "#fdd",
            "color": "red",
            "weight": 3,
            "fillOpacity": 0.4
        },
        tooltip="Watershed"
    ).add_to(m)

if "streams" in st.session_state:
    folium.GeoJson(
        st.session_state["streams"],
        name="Rivers",
        style_function=lambda _: {
            "color": "blue",
            "weight": 2
        },
        tooltip="Rivers"
    ).add_to(m)

if "requested_point" in st.session_state:
    folium.GeoJson(
        st.session_state["requested_point"],
        name="Requested",
        marker=folium.CircleMarker(radius=6, color="cyan", fill=True, fill_opacity=1),
        tooltip="Requested outlet"
    ).add_to(m)

if "snap_point" in st.session_state:
    folium.GeoJson(
        st.session_state["snap_point"],
        name="Snapped to river centerline",
        marker=folium.CircleMarker(radius=6, color="magenta", fill=True, fill_opacity=1),
        tooltip="Snapped outlet"
    ).add_to(m)

# --- Fit bounds if available and valid ---
if "map_bounds" in st.session_state:
    try:
        m.fit_bounds(st.session_state["map_bounds"])
    except Exception as e:
        st.warning(f"Could not fit bounds: {e}")

# --- Map display ---
folium.LayerControl().add_to(m)
result = st_folium(m, height=600, width="100%")

# --- Click capture ---
if result["last_clicked"]:
    st.session_state["last_click"] = result["last_clicked"]

# --- Downloads ---
if "gpkg_path" in st.session_state:
    st.download_button(
        "Download GeoPackage",
        open(st.session_state["gpkg_path"], "rb").read(),
        file_name=Path(st.session_state["gpkg_path"]).name
    )

if "geojson" in st.session_state:
    st.download_button(
        "Download GeoJSON",
        data=st.session_state["geojson"],
        file_name=f"{wid}.geojson",
        mime="application/geo+json"
    )
