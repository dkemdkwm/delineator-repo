# app/app.py  ───────────────────────────────────────────────────────────────
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from delineator import delineate_point        # wrapper in core/__init__.py

st.set_page_config(page_title="Watershed Delineator", layout="wide")
st.title("🗺️ Click on the map to delineate a watershed")

# ── 1. Base map --------------------------------------------------------------
base_map = folium.Map(location=[4.6, -74.1], zoom_start=5, tiles="OpenStreetMap")
folium.LatLngPopup().add_to(base_map)
res_base = st_folium(base_map, height=600, width="100%", key="basemap")

click = res_base["last_clicked"] or st.session_state.get("last_click")
if click:
    st.session_state["last_click"] = click     # persist last location

# ── 2. Sidebar parameters ----------------------------------------------------
st.sidebar.header("Parameters")
wid  = st.sidebar.text_input("Watershed ID", "custom")
area = st.sidebar.number_input("Known upstream area (km²)",
                               value=None, format="%.1f",
                               placeholder="leave blank")

# ── 3. Run delineation -------------------------------------------------------
if st.button("Delineate", disabled=click is None):
    lat, lon = click["lat"], click["lng"]

    with st.spinner("Running delineator – this can take a minute ⏳"):
        outfile = delineate_point(lat, lon, wid, area)

    st.sidebar.success(
        f"File written → `{outfile}`  "
        f"({Path(outfile).stat().st_size/1e6:.2f} MB)"
    )

    # ── 4. Load file (CSV, SHP, or GPKG) ------------------------------------
    if outfile.endswith(".csv"):
        df = pd.read_csv(outfile)
        if {"lon", "lat"}.issubset(df.columns):
            gdf = gpd.GeoDataFrame(
                df,
                geometry=gpd.points_from_xy(df["lon"], df["lat"]),
                crs=4326,
            )
        else:
            st.error("CSV lacks 'lon' and 'lat' columns – cannot plot."); st.stop()
    elif outfile.endswith(".gpkg"):
        import fiona
        layer = fiona.listlayers(outfile)[0]
        gdf = gpd.read_file(outfile, layer=layer)
    else:                                    # SHP or anything GeoPandas reads
        gdf = gpd.read_file(outfile)

    if gdf.empty:
        st.error("GeoDataFrame is empty – nothing to draw."); st.stop()

    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)

    # keep only polygon geometries
    poly = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    if poly.empty:
        st.error("No polygon geometry found – cannot plot."); st.stop()

    # ── 5. Draw result on a fresh map ---------------------------------------
    centroid = poly.unary_union.centroid
    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=8,
                   tiles="OpenStreetMap")

    folium.GeoJson(
        poly.__geo_interface__,
        name="Watershed",
        style_function=lambda _: {
            "fillColor": "#3388ff",
            "color": "#e31a1c",
            "weight": 2,
            "fillOpacity": 0.35,
        },
    ).add_to(m)

    xmin, ymin, xmax, ymax = poly.total_bounds
    m.fit_bounds([[ymin, xmin], [ymax, xmax]])

    st_folium(
        m,
        height=600,
        width="100%",
        key=f"map_{wid}_{xmin:.4f}_{ymin:.4f}_{xmax:.4f}_{ymax:.4f}",  # UNIQUE
    )

    # ── 6. Download buttons --------------------------------------------------
    st.download_button(
        "Download original file",
        Path(outfile).read_bytes(),
        file_name=Path(outfile).name,
    )
    st.download_button(
        "Download GeoJSON",
        poly.to_json(),
        file_name=f"{wid}.geojson",
        mime="application/geo+json",
    )
