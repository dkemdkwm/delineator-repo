import streamlit as st
from streamlit_folium import st_folium
import folium
from folium import TileLayer

def render():
    if "last_click" not in st.session_state:
        st.session_state["last_click"] = None

    map_location = st.session_state.get("map_center", [4.6, -74.1])
    selected = st.session_state.get("base_map_choice", "OpenStreetMap")

    # Prevent auto-loading of OpenStreetMap to avoid duplicates
    m = folium.Map(location=map_location, zoom_start=9, control_scale=True, tiles=None)

    # ─────────────────────────────────────────────────────────────────────────────
    # 1. Base map definitions with proper attribution
    # ─────────────────────────────────────────────────────────────────────────────
    base_layers = {
        "OpenStreetMap": {
            "tiles": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "attr": "© OpenStreetMap contributors"
        },
        "Esri Satélite": {
            "tiles": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            "attr": "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye"
        },
        "Stamen Terreno": {
            "tiles": "https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
            "attr": "Map tiles by Stamen Design, CC BY 3.0 — Map data © OpenStreetMap contributors"
        },
        "Stamen Toner": {
            "tiles": "https://stamen-tiles.a.ssl.fastly.net/toner/{z}/{x}/{y}.png",
            "attr": "Map tiles by Stamen Design, CC BY 3.0 — Map data © OpenStreetMap contributors"
        },
        "Carto Claro": {
            "tiles": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
            "attr": "© CARTO — Map data © OpenStreetMap contributors"
        },
        "Carto Oscuro": {
            "tiles": "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            "attr": "© CARTO — Map data © OpenStreetMap contributors"
        }
    }

    # Add all layers, but add the selected one last
    for name, config in base_layers.items():
        if name != selected:
            TileLayer(
                tiles=config["tiles"],
                name=name,
                attr=config["attr"]
            ).add_to(m)

    TileLayer(
        tiles=base_layers[selected]["tiles"],
        name=selected,
        attr=base_layers[selected]["attr"]
    ).add_to(m)

    # Add LatLngPopup for coordinate picking
    folium.LatLngPopup().add_to(m)

    # Marker for selected point
    if st.session_state["last_click"]:
        folium.Marker(
            location=[
                st.session_state["last_click"]["lat"],
                st.session_state["last_click"]["lng"]
            ],
            tooltip="Punto seleccionado",
            icon=folium.Icon(color="green", icon="map-pin", prefix="fa")
        ).add_to(m)

    # Add overlays
    if st.session_state.get("show_watershed") and "geojson" in st.session_state:
        folium.GeoJson(
            st.session_state["geojson"],
            name="Cuenca hidrográfica",
            style_function=lambda _: {
                "fillColor": "#fdd", "color": "red", "weight": 3, "fillOpacity": 0.4
            },
            tooltip="Cuenca hidrográfica"
        ).add_to(m)

    if st.session_state.get("show_streams") and "streams" in st.session_state:
        folium.GeoJson(
            st.session_state["streams"],
            name="Ríos",
            style_function=lambda _: {"color": "blue", "weight": 2},
            tooltip="Ríos"
        ).add_to(m)

    if st.session_state.get("show_requested_pt") and "requested_point" in st.session_state:
        folium.GeoJson(
            st.session_state["requested_point"],
            name="Punto solicitado",
            marker=folium.CircleMarker(radius=6, color="cyan", fill=True, fill_opacity=1),
            tooltip="Punto de solicitud"
        ).add_to(m)

    if st.session_state.get("show_snapped_pt") and "snap_point" in st.session_state:
        folium.GeoJson(
            st.session_state["snap_point"],
            name="Punto ajustado al cauce",
            marker=folium.CircleMarker(radius=6, color="magenta", fill=True, fill_opacity=1),
            tooltip="Punto de desfogue"
        ).add_to(m)

    if "map_bounds" in st.session_state:
        try:
            m.fit_bounds(st.session_state["map_bounds"])
        except Exception as e:
            st.warning(f"No se pudo ajustar límites del mapa: {e}")

    # Layer control: right and initially invisible
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    # Map render
    result = st_folium(m, height=600, width="100%")

    if result["last_clicked"]:
        st.session_state["last_click"] = result["last_clicked"]

    # Inject CSS for hover-only visibility
    st.markdown("""
        <style>
        /* Hide control completely */
        .leaflet-top.leaflet-right {
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease-in-out;
        }

        .leaflet-top.leaflet-right:hover {
            opacity: 1;
            pointer-events: auto;
        }

        /* Optional: fix z-index to ensure it's on top */
        .leaflet-control-layers {
            z-index: 9999;
        }

        /* Optional: force hide the collapsed button until hover */
        .leaflet-control-layers-toggle {
            display: none !important;
        }

        .leaflet-top.leaflet-right:hover .leaflet-control-layers-toggle {
            display: block !important;
        }
        </style>
    """, unsafe_allow_html=True)

