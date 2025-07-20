# delineate.py
import streamlit as st
from streamlit_folium import st_folium
import folium

def render():
    if "last_click" not in st.session_state:
        st.session_state["last_click"] = None

    map_location = st.session_state.get("map_center", [4.6, -74.1])
    m = folium.Map(location=map_location, zoom_start=9, tiles="OpenStreetMap")
    folium.LatLngPopup().add_to(m)

    if "geojson" in st.session_state:
        folium.GeoJson(
            st.session_state["geojson"],
            name="Watershed",
            style_function=lambda _: {
                "fillColor": "#fdd", "color": "red", "weight": 3, "fillOpacity": 0.4
            },
            tooltip="Watershed"
        ).add_to(m)

    if "streams" in st.session_state:
        folium.GeoJson(
            st.session_state["streams"],
            name="Rivers",
            style_function=lambda _: {
                "color": "blue", "weight": 2
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

    if "map_bounds" in st.session_state:
        try:
            m.fit_bounds(st.session_state["map_bounds"])
        except Exception as e:
            st.warning(f"Could not fit bounds: {e}")

    folium.LayerControl().add_to(m)
    result = st_folium(m, height=600, width="100%")

    if result["last_clicked"]:
        st.session_state["last_click"] = result["last_clicked"]
