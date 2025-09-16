import streamlit as st
from app import conclusions_data, delineate, estimated_concentration_times, hypsometric_curve, parameters_view
import base64
from pathlib import Path
from app.download_utils import (
    build_excel_bytes,
    build_watershed_shapefile_zip,
    package_dem_if_needed
)
from app.morphometry import compute
import sys
import os
import pandas as pd
import geopandas as gpd
from shapely import wkt
import json
from shapely.geometry import Point, shape as gj_shape

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

# ------------------------------------------------------------------
# Utilidades de imagen (logos)
# ------------------------------------------------------------------
def image_to_base64(path: str) -> str:
    with open(path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

logo1_base64 = image_to_base64("app/cunLogo.png")
logo2_base64 = image_to_base64("app/consultoraLogo.png")

# ------------------------------------------------------------------
# Estilos / encabezado
# ------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    header[data-testid="stHeader"] {{ z-index: 0 !important; }}
    .main .block-container {{ padding-top: 100px; }}
    .custom-header {{
        position: fixed; top: 0; left: 0; right: 0;
        background-color: white; padding: 10px 40px;
        z-index: 99999; display: flex; align-items: center;
        justify-content: space-between; border-bottom: 1px solid #eee;
    }}
    .custom-header .title {{
        font-size: 20px; font-weight: 700; text-align: center;
        flex-grow: 1; color: #222;
    }}
    .custom-header img {{ height: 55px; }}
    </style>
    <div class="custom-header">
        <img src="data:image/png;base64,{logo1_base64}" style="width: 130px; height: 60px;" />
        <div class="title">
            Delimitación de cuencas hidrográficas<br/>
        </div>
        <img src="data:image/png;base64,{logo2_base64}" />
    </div>
    """,
    unsafe_allow_html=True
)

# ------------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] {
            margin-top: 100px; background-color: white; padding: 0;
            left: 10px; border-radius: 8px;
        }
        .sidebar-section { padding: 0.2rem 0; }
        .section-title { font-size: 18px; font-weight: 600; color: #444; margin-bottom: 0.75rem; }
        div[data-testid="stSidebarHeader"] { display: none; }
        div[data-testid="stSidebarUserContent"] { padding: 0; }
        .stTextInput>div>input, .stNumberInput>div>input {
            border: 1px solid #ccc; border-radius: 6px; padding: 0.4rem 0.6rem;
        }
        .stTextInput>div>input:focus, .stNumberInput>div>input:focus { border-color: #555; }
        .stButton>button {
            width: 100%; border-radius: 6px; padding: 0.5rem;
            background-color: #000; color: white; font-weight: 500; border: none;
        }
        .stDownloadButton>button {
            width: 100%; border-radius: 6px; padding: 0.5rem;
            font-weight: 500; border: 1px solid #ccc; background: white; color: #333;
        }
        .stDownloadButton>button:hover { border-color: #222; }
        div[data-testid="stMainBlockContainer"] {
            padding-left: 2rem; padding-right: 1rem; padding: 4.8rem 2rem 10rem;
        }
        div[data-testid="stApp"] { background-color: rgb(248 248 248); }
        div[data-testid="stAppHeader"] { display: none; }
        button[role="tab"][aria-selected="true"] > div[data-testid="stMarkdownContainer"] > p {
            color: rgba(35, 113, 38, 1); font-weight: 600;
        }
        button[role="tab"]:hover > div[data-testid="stMarkdownContainer"] > p {
            color: rgba(35, 113, 38, 0.8);
        }
        button[role="tab"]:focus > div[data-testid="stMarkdownContainer"] > p { outline: none; }
        </style>
        """,
        unsafe_allow_html=True
    )

    # --- Controles de Delineación ---
    st.markdown('<div class="sidebar-section section-title">🛰️ Controles y filtros</div>', unsafe_allow_html=True)

    # wid = st.text_input("ID de cuenca", value="custom", key="wid", label_visibility="collapsed")
    wid = "custom"
    lat = st.number_input(
        "Latitud",
        value=st.session_state.get("lat", None),
        format="%.6f",
        placeholder="Latitud",
        key="input_lat",
        label_visibility="collapsed"
    )

    lon = st.number_input(
        "Longitud",
        value=st.session_state.get("lon", None),
        format="%.6f",
        placeholder="Longitud",
        key="input_lon",
        label_visibility="collapsed"
    )

    if st.session_state.get("last_click"):
        st.session_state["lat"] = st.session_state["last_click"]["lat"]
        st.session_state["lon"] = st.session_state["last_click"]["lng"]

    if st.button("🚀 Delimitar"):
        from delineator import delineate_point
        import geopandas as gpd

        lat = lat or st.session_state.get("lat")
        lon = lon or st.session_state.get("lon") 

        if lat and lon:

            with st.spinner("Ejecutando delimitación…"):
                gpkg_path = delineate_point(lat, lon, wid, None)

            if not Path(gpkg_path).exists():
                st.error(f"❌ No se creó el GeoPackage: {gpkg_path}")
            else:
                st.session_state["gpkg_path"] = gpkg_path
                try:
                    watershed_gdf = gpd.read_file(gpkg_path, layer="watershed")
                    st.session_state["geojson"] = watershed_gdf.to_json()

                    for layer, key in [
                        ("streams", "streams"),
                        ("streams_main", "streams_main"),
                        ("streams_tribs", "streams_tribs"),
                        ("pour_point", "pour_point"),
                        ("snap_point", "snap_point"),
                        ("streams_hr", "streams_hr"),
                    ]:
                        try:
                            st.session_state[key] = gpd.read_file(gpkg_path, layer=layer).to_json()
                        except Exception:
                            pass

                    try:
                        streams_gdf = gpd.read_file(gpkg_path, layer="streams")
                    except Exception:
                        streams_gdf = None
                    st.session_state["morpho"] = compute(watershed_gdf, streams_gdf)

                    bounds = watershed_gdf.total_bounds
                    if not any(x is None or x != x for x in bounds):
                        center_lat = (bounds[1] + bounds[3]) / 2
                        center_lon = (bounds[0] + bounds[2]) / 2
                        st.session_state["map_center"] = [center_lat, center_lon]
                        st.session_state["map_bounds"] = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
                    if "pour_point" in st.session_state and st.session_state.get("pour_point"):
                        st.session_state["requested_point"] = st.session_state["pour_point"]
                    st.markdown("**🔭 Coordenadas**")

                    # Punto solicitado (tolerante a vacíos)
                    if st.session_state.get("requested_point"):
                        lon_r, lat_r = (None, None)
                        try:
                            lon_r, lat_r = delineate._first_point_lonlat(st.session_state["requested_point"])
                        except Exception:
                            pass
                        if lat_r is not None and lon_r is not None:
                            st.write(f"🟢 Solicitado: lat={lat_r:.6f}, lon={lon_r:.6f}")

                    # Punto ajustado al cauce (tolerante a vacíos)
                    if st.session_state.get("snap_point"):
                        lon_s, lat_s = (None, None)
                        try:
                            lon_s, lat_s = delineate._first_point_lonlat(st.session_state["snap_point"])
                        except Exception:
                            pass
                        if lat_s is not None and lon_s is not None:
                            st.write(f"🟣 Ajustado:   lat={lat_s:.6f}, lon={lon_s:.6f}")
                            st.session_state["snap_lat"] = float(lat_s)
                            st.session_state["snap_lon"] = float(lon_s)
                except Exception as e:
                    st.error(f"⚠️ Error cargando GPKG: {e}")
        else:
            st.warning("Por favor proporciona latitud y longitud.")

    gpkg_path = st.session_state.get("gpkg_path")
    if gpkg_path and Path(gpkg_path).exists():
        with st.expander("🗺️ Configuración de capas y mapa base", expanded=True):

            st.markdown("### 🗺️ Capas")
            st.session_state.setdefault("show_watershed", True)
            st.session_state.setdefault("show_streams", True)
            st.session_state.setdefault("show_requested_pt", True)
            st.session_state.setdefault("show_snapped_pt", True)

            st.session_state.show_watershed = st.checkbox(
                "Cuenca", value=st.session_state.show_watershed, key="cb_cuenca"
            )
            st.session_state.show_streams = st.checkbox(
                "Drenajes", value=st.session_state.show_streams, key="cb_rios"
            )
            st.session_state.show_requested_pt = st.checkbox(
                "Punto solicitado", value=st.session_state.show_requested_pt, key="cb_pt_req"
            )
            st.session_state.show_snapped_pt = st.checkbox(
                "Punto ajustado al cauce", value=st.session_state.show_snapped_pt, key="cb_pt_snap"
            )
            st.session_state.setdefault("show_cne", True)

            st.session_state.show_cne = st.checkbox(
                "Estaciones Meteorológicas",
                value=st.session_state.show_cne,
                key="cb_cne"
            )
            st.markdown("### 🌐 Mapa base")
            base_options = [
                "OpenStreetMap",
                "Esri Satélite",
                "Stamen Terreno",
                "Stamen Toner",
                "Carto Claro",
                "Carto Oscuro"
            ]
            st.session_state.setdefault("base_map_choice", "OpenStreetMap")
            st.session_state.base_map_choice = st.selectbox(
                "Selecciona mapa base",
                base_options,
                index=base_options.index(st.session_state.base_map_choice)
            )

    st.markdown('<div class="section-title">📦 Descargas</div>', unsafe_allow_html=True)

    gpkg_path = st.session_state.get("gpkg_path")
    if gpkg_path and Path(gpkg_path).exists():
        st.download_button(
            "📥 GeoPackage",
            open(gpkg_path, "rb").read(),
            file_name=Path(gpkg_path).name,
        )

    if "geojson" in st.session_state:
        st.download_button(
            "🧾 GeoJSON",
            data=st.session_state["geojson"],
            file_name=f"{wid}.geojson",
            mime="application/geo+json",
        )

    morpho_dict = st.session_state.get("morpho")
    morpho_df = st.session_state.get("morpho_table")
    tc_df = st.session_state.get("tc_results")
    hypso_df = st.session_state.get("hypsometric_table")
    dem_path = st.session_state.get("dem_path")

    if morpho_dict and gpkg_path:
        try:
            excel_bytes = build_excel_bytes(
                morpho_dict,
                morpho_df,
                tc_df,
                hypso_df,
                gpkg_path,
                dem_path,
                include_wkt=True,
                embed_dem_clip=True,
                embed_dem_base64=True,
                base64_chunk_len=30000,
                add_hypso_chart=True,
                add_tc_chart=True
            )
            st.download_button(
                "📑 Excel (todas las tablas)",
                data=excel_bytes,
                file_name="resumen_cuenca.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.warning(f"No se pudo generar Excel: {e}")

        if gpkg_path:
            try:
                # Layers that live inside the GPKG
                gpkg_layers = ["watershed", "streams", "streams_main", "pour_point", "snap_point"]

                # Build an extra layer for CNE stations (from session state)
                extra = {}

                if st.session_state.get("estaciones_filtradas"):
                    try:
                        df = pd.DataFrame(st.session_state["estaciones_filtradas"])

                        def to_geom(val):
                            # Already a shapely geometry
                            if hasattr(val, "geom_type"):
                                return val
                            # WKT string
                            if isinstance(val, str):
                                try:
                                    return wkt.loads(val)
                                except Exception:
                                    try:
                                        return gj_shape(json.loads(val))
                                    except Exception:
                                        return None
                            # Raw GeoJSON dict
                            if isinstance(val, dict):
                                try:
                                    return gj_shape(val)
                                except Exception:
                                    return None
                            return None

                        if "geometry" in df.columns:
                            df["geometry"] = df["geometry"].apply(to_geom)
                        elif {"lon", "lat"}.issubset(df.columns):
                            df["geometry"] = [Point(xy) for xy in zip(df["lon"], df["lat"])]
                        elif {"longitude", "latitude"}.issubset(df.columns):
                            df["geometry"] = [Point(xy) for xy in zip(df["longitude"], df["latitude"])]

                        df = df[df["geometry"].notna()].copy()

                        if not df.empty:
                            gdf_cne = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
                            extra["cne_stations"] = gdf_cne
                    except Exception as e:
                        st.warning(f"No se pudo reconstruir estaciones CNE: {e}")


                shp_zip = build_watershed_shapefile_zip(
                    gpkg_path,
                    layers=gpkg_layers,
                    extra_layers=extra,  # NEW
                )
                st.download_button(
                    "🗺️ Shapefile (ZIP)",
                    data=shp_zip,
                    file_name="cuenca_y_capas.zip",
                    mime="application/zip"
                )
            except Exception as e:
                st.warning(f"No se pudo exportar Shapefile: {e}")



# ------------------------------------------------------------------
# TABS
# ------------------------------------------------------------------
tabs = st.tabs([
    "🌍 Mapa de Delimitación",
    "📊 Parámetros Morfométricos",
    "⏱️ Estimación tiempos de concentración",
    "📈 Curva Hipsométrica",
    "📋 Análisis morfométrico"
])

with tabs[0]:
    delineate.render()

with tabs[1]:
    parameters_view.render()

with tabs[2]:
    estimated_concentration_times.render()

with tabs[3]:
    hypsometric_curve.render()

with tabs[4]:
    conclusions_data.render()

# ------------------------------------------------------------------
# Footer - Autores
# ------------------------------------------------------------------
st.markdown(
    """
    <div style="
        margin-top: 3rem;
        padding: 1rem;
        border-top: 1px solid #ddd;
        background-color: #fff;
        border-radius: 8px;
        box-shadow: 0 0 5px rgba(0,0,0,0.05);
    ">
        <p style="font-weight: bold; font-size: 14px; margin-bottom: 0.5rem;">Autores:</p>
        <ul style="list-style-type: circle; padding-left: 1rem; margin: 0;">
            <li> Ingeniera Ambiental <strong>Laura Julieth Rodriguez Ramirez</strong><br>
                <a href="mailto:laurajuliethrodriguez@ucundinamarca.edu.co" style="font-size: 13px; color: #0066cc;">laurajuliethrodriguez@ucundinamarca.edu.co</a>
            </li>
            <li> MSc. Ing. <strong>Karel Aldrin Sánchez Hernández</strong><br>
                <a href="mailto:kasanchez@ucundinamarca.edu.co" style="font-size: 13px; color: #0066cc;">kasanchez@ucundinamarca.edu.co</a>
            </li>
            <li> Ingeniero de Sistemas <strong>Harold Stick Fique Ramirez</strong><br>
                <a href="mailto:hfique@unundinamarca.edu.co" style="font-size: 13px; color: #0066cc;">hfique@unundinamarca.edu.co</a>
            </li>
        </ul>
    </div>
    """,
    unsafe_allow_html=True
)