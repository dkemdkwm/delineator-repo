import streamlit as st
from app import delineate, estimated_concentration_times, hypsometric_curve, parameters_view
import base64
from pathlib import Path
from app.morphometry import compute
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

def image_to_base64(path: str) -> str:
    with open(path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

logo1_base64 = image_to_base64("app/cunLogo.png")
logo2_base64 = image_to_base64("app/consultoraLogo.png")

st.markdown(
    f"""
    <style>
    /* Lower z-index of Streamlit's top header bar using stable selector */
    header[data-testid="stHeader"] {{
        z-index: 0 !important;
    }}

    /* Push main content below the custom header */
    .main .block-container {{
        padding-top: 100px;
    }}

    /* Fixed custom header layout */
    .custom-header {{
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        background-color: white;
        padding: 10px 40px;
        z-index: 99999;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid #eee;
    }}

    .custom-header .title {{
        font-size: 20px;
        font-weight: 700;
        text-align: center;
        flex-grow: 1;
        color: #222;
    }}

    .custom-header img {{
        height: 55px;
    }}
    </style>

    <div class="custom-header">
        <img src="data:image/png;base64,{logo1_base64}" />
        <div class="title">
            Delimitación de cuencas hidrográficas<br/>
            <span style="font-weight: 400; font-size: 15px;">
                Selecciona un punto en el mapa para delimitar una cuenca hidrográfica 🗺️
            </span>
        </div>
        <img src="data:image/png;base64,{logo2_base64}" />
    </div>
    """,
    unsafe_allow_html=True
)

with st.sidebar:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            margin-top: 100px;
            background-color: white;
            padding: 0;
            left: 10px;
            border-radius: 8px;
        }

        .sidebar-section {
            padding: 0.2rem 0;
        }

        .section-title {
            font-size: 18px;
            font-weight: 600;
            color: #444;
            margin-bottom: 0.75rem;
        }

        .field-row {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }

        .field-icon {
            width: 1.5rem;
            font-size: 16px;
            text-align: center;
            color: #888;
        }
        div[data-testid="stSidebarHeader"] {
            display: none;
        }
        div[data-testid="stSidebarUserContent"] {
            padding: 0;
        }
        .stTextInput>div>input,
        .stNumberInput>div>input {
            border: 1px solid #ccc;
            border-radius: 6px;
            padding: 0.4rem 0.6rem;
        }

        .stTextInput>div>input:focus,
        .stNumberInput>div>input:focus {
            border-color: #555;
        }

        .stButton>button {
            width: 100%;
            border-radius: 6px;
            padding: 0.5rem;
            background-color: #000;
            color: white;
            font-weight: 500;
            border: none;
        }

        .stDownloadButton>button {
            width: 100%;
            border-radius: 6px;
            padding: 0.5rem;
            font-weight: 500;
            border: 1px solid #ccc;
            background: white;
            color: #333;
        }

        .stDownloadButton>button:hover {
            border-color: #222;
        }
        div[data-testid="stMainBlockContainer"] {
            padding-left: 2rem;
            padding-right: 1rem;
            padding: 4.8rem 2rem 10rem;
        }
        div[data-testid="stApp"] {
            background-color: rgb(248 248 248);
        }
        div[data-testid="stAppHeader"] {
            display: none;
        }
        button[role="tab"][aria-selected="true"] > div[data-testid="stMarkdownContainer"] > p {
            color: rgba(35, 113, 38, 1);
            font-weight: 600;
        }
        button[role="tab"]:hover > div[data-testid="stMarkdownContainer"] > p {
            color: rgba(35, 113, 38, 0.8);
        }

        button[role="tab"]:focus > div[data-testid="stMarkdownContainer"] > p {
            outline: none;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # --- Delineation ---
    st.markdown('<div class="sidebar-section section-title">🛰️ Controles y filtros</div>', unsafe_allow_html=True)

    # Watershed ID
    wid = st.text_input("Watershed ID", value="custom", key="wid", label_visibility="collapsed")

    # Latitude input
    lat = st.number_input(
        "Latitude",
        value=st.session_state.get("lat", None),
        format="%.6f",
        placeholder="Latitud",
        key="input_lat",
        label_visibility="collapsed"
    )

    # Longitude input
    lon = st.number_input(
        "Longitude",
        value=st.session_state.get("lon", None),
        format="%.6f",
        placeholder="Longitud",
        key="input_lon",
        label_visibility="collapsed"
    )

    # If click exists, autofill lat/lon if inputs are still empty
    if st.session_state.get("last_click"):
        st.session_state["lat"] = st.session_state["last_click"]["lat"]
        st.session_state["lon"] = st.session_state["last_click"]["lng"]
    
    # Delineate button
    if st.button("🚀 Delinear"):
        from delineator import delineate_point
        import geopandas as gpd
        import fiona

        lat = lat or st.session_state.get("lat")
        lon = lon or st.session_state.get("lon")

        if lat and lon:
            st.session_state["lat"], st.session_state["lon"] = lat, lon
            st.success(f"📍 lat={lat}, lon={lon}")

            with st.spinner("Running delineator…"):
                gpkg_path = delineate_point(lat, lon, wid, None)

            if not Path(gpkg_path).exists():
                st.error(f"❌ GPKG file not created: {gpkg_path}")
            else:
                st.session_state["gpkg_path"] = gpkg_path

                try:
                    watershed_gdf = gpd.read_file(gpkg_path)
                    st.session_state["geojson"] = watershed_gdf.to_json()

                    for layer, key in [
                        ("streams", "streams"),
                        ("snap_point", "snap_point"),
                        ("pour_point", "requested_point")
                    ]:
                        try:
                            st.session_state[key] = gpd.read_file(gpkg_path, layer=layer).to_json()
                        except:
                            pass
                    # --------------  NEW: compute morphometry --------------
                    try:
                        streams_gdf = gpd.read_file(gpkg_path, layer="streams")
                    except Exception:
                        streams_gdf = None

                    st.session_state["morpho"] = compute(watershed_gdf, streams_gdf)
                    # --------------------------------------------------------
                    bounds = watershed_gdf.total_bounds
                    if not any(map(lambda x: x is None or x != x, bounds)):
                        center_lat = (bounds[1] + bounds[3]) / 2
                        center_lon = (bounds[0] + bounds[2]) / 2
                        st.session_state["map_center"] = [center_lat, center_lon]
                        st.session_state["map_bounds"] = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

                except Exception as e:
                    st.error(f"⚠️ Error loading GPKG: {e}")
        else:
            st.warning("Por favor proporciona latitud y longitud.")

    st.markdown('</div>', unsafe_allow_html=True)


    # --- Downloads ---

    st.markdown('<div class="section-title">📦 Descargas</div>', unsafe_allow_html=True)

    if "gpkg_path" in st.session_state:
        st.download_button(
            "📥 GeoPackage",
            open(st.session_state["gpkg_path"], "rb").read(),
            file_name=Path(st.session_state["gpkg_path"]).name,
        )

    if "geojson" in st.session_state:
        st.download_button(
            "🧾 GeoJSON",
            data=st.session_state["geojson"],
            file_name=f"{wid}.geojson",
            mime="application/geo+json",
        )

    st.markdown('</div>', unsafe_allow_html=True)

tabs = st.tabs(["🌍 Mapa de Delimitación", "📊 Parámetros Morfométricos","⏱️ Estimacion tiempos de concentracion","📈 Curva Hipsométrica" ])

with tabs[0]:
    delineate.render()

with tabs[1]:
    parameters_view.render()

with tabs[2]:
    estimated_concentration_times.render()

with tabs[3]:
    hypsometric_curve.render()
