import streamlit as st
from streamlit_folium import st_folium
import folium
from folium import TileLayer, Tooltip
from geopandas import gpd
import pandas as pd
from folium import CustomIcon
import json
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points

def _stream_style_for_row(row):
    is_main = bool(row.get("is_main"))
    color = "#0077b6" if is_main else "#00b4d8"
    weight = 4 if is_main else 2
    return color, weight

def _gdf_from_geojson_str(geojson_str: str) -> gpd.GeoDataFrame:
    feat = json.loads(geojson_str)
    crs = "EPSG:4326"
    return gpd.GeoDataFrame.from_features(feat["features"], crs=crs)

def _nearest_stream_row(point: Point, lines_gdf: gpd.GeoDataFrame):
    idx = lines_gdf.distance(point).idxmin()
    return lines_gdf.loc[idx]

def _connector_to_line(point: Point, line_geom) -> LineString | None:
    if point.is_empty or line_geom is None or line_geom.is_empty:
        return None
    p_on = line_geom.interpolate(line_geom.project(point))
    if p_on.is_empty:
        return None
    return LineString([point, p_on])


def _as_ws_geom(geojson_any):
    """Return a valid unary union of watershed geometry (Polygon/MultiPolygon) from any GeoJSON form."""
    gj = json.loads(geojson_any) if isinstance(geojson_any, str) else geojson_any
    t = gj.get("type")
    geoms = []
    if t == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in gj.get("features", []) if f.get("geometry")]
    elif t == "Feature":
        if gj.get("geometry"): geoms = [shape(gj["geometry"])]
    else:
        geoms = [shape(gj)]  # raw geometry dict
    if not geoms:
        return None
    u = unary_union(geoms)
    # fix self-intersections
    try:
        u = u.buffer(0)
    except Exception:
        pass
    return u

def _first_point_lonlat(geojson_obj_or_str):
    """Return (lon, lat) of the first Point in a GeoJSON Feature/FeatureCollection."""
    try:
        gj = json.loads(geojson_obj_or_str) if isinstance(geojson_obj_or_str, str) else geojson_obj_or_str
    except Exception:
        return None

    def find_point_coords(g):
        t = g.get("type")
        if t == "FeatureCollection":
            for f in g.get("features", []):
                coords = find_point_coords(f)
                if coords: return coords
        elif t == "Feature":
            return find_point_coords(g.get("geometry") or {})
        elif t == "Point":
            c = g.get("coordinates")
            if isinstance(c, (list, tuple)) and len(c) == 2:
                return (float(c[0]), float(c[1]))  # (lon, lat)
        return None

    return find_point_coords(gj)


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
    # if st.session_state["last_click"]:
    #     folium.Marker(
    #         location=[
    #             st.session_state["last_click"]["lat"],
    #             st.session_state["last_click"]["lng"]
    #         ],
    #         tooltip="Punto seleccionado",
    #         icon=folium.Icon(color="green", icon="map-pin", prefix="fa")
    #     ).add_to(m)
    # Add marker for selected point
    if st.session_state["last_click"]:
        folium.Marker(
            location=[
                st.session_state["last_click"]["lat"],
                st.session_state["last_click"]["lng"]
            ],
            tooltip="Punto seleccionado",
            icon=folium.Icon(color="green", icon="map-pin", prefix="fa")
        ).add_to(m)

    # Load and render shapefile (only nearby features)
    shapefile_path = "data/shp/cne_ideam/CNE_IDEAM.shp"
    try:
        gdf_cne = gpd.read_file(shapefile_path)

        # Ensure CRS is defined and correct
        if gdf_cne.crs is None:
            gdf_cne.set_crs("EPSG:4326", inplace=True)
        elif gdf_cne.crs.to_string() != "EPSG:4326":
            gdf_cne = gdf_cne.to_crs("EPSG:4326")

        # Convert columns to string to avoid serialization issues
        for col in gdf_cne.columns:
            if pd.api.types.is_object_dtype(gdf_cne[col]) or pd.api.types.is_datetime64_any_dtype(gdf_cne[col]):
                gdf_cne[col] = gdf_cne[col].astype(str)

        # # Filter by proximity if point is selected
        # if st.session_state["last_click"]:
        #     click_point = Point(
        #         st.session_state["last_click"]["lng"],
        #         st.session_state["last_click"]["lat"]
        #     )

        #     buffer_radius_degrees = 0.15  # ~1km radius at equator (adjust if needed)
        #     point_buffer = click_point.buffer(buffer_radius_degrees)
        #     gdf_filtered = gdf_cne[gdf_cne.geometry.intersects(point_buffer)]
        #     icon_url = "app/cloudSunIcon.png"
        #     if not gdf_filtered.empty:
        #         # folium.GeoJson(
        #         #     data=gdf_filtered.__geo_interface__,
        #         #     name="CNE IDEAM (filtrado)",
        #         #     style_function=lambda feature: {
        #         #         "fillColor": "#3388ff",
        #         #         "color": "#2255aa",
        #         #         "weight": 2,
        #         #         "fillOpacity": 0.3,
        #         #     },
        #         #     tooltip=folium.GeoJsonTooltip(
        #         #         fields=["NOMBRE", "CODIGO"] if "NOMBRE" in gdf_filtered.columns and "CODIGO" in gdf_filtered.columns
        #         #         else gdf_filtered.columns[:2].tolist()
        #         #     )
        #         # ).add_to(m)
        #         st.session_state["estaciones_filtradas"] = gdf_filtered.to_dict("records")
        #         for _, row in gdf_filtered.iterrows():
        #             geom = row.geometry
        #             if geom.geom_type == "Point":
        #                 # Try alternate keys if NOMBRE or CODIGO are not exact
        #                 nombre = str(row.get("NOMBRE") or row.get("Nombre") or row.get("nombre") or "").strip()
        #                 codigo = str(row.get("CODIGO") or row.get("Codigo") or row.get("codigo") or "").strip()
        #                 tooltip_html = f"""
        #                 <b>NOMBRE:</b> {nombre}<br>
        #                 <b>CODIGO:</b> {codigo}
        #                 """
        #                 folium.Marker(
        #                     location=[geom.y, geom.x],
        #                     icon=CustomIcon(
        #                         icon_image=icon_url,
        #                         icon_size=(60, 60),
        #                         icon_anchor=(20, 20)
        #                     ),
        #                     tooltip=Tooltip(tooltip_html)
        #                 ).add_to(m)
        #     else:
        #         st.warning("⚠️ No se encontraron entidades CNE_IDEAM cercanas al punto seleccionado.")
        # else:
        #     # Show bounding box only when no point is selected
        #     bounds = gdf_cne.total_bounds
        #     m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
        # ── Filter CNE by watershed with tolerance (proximity to basin) ──────────────
        if st.session_state.get("show_cne", True):
            if st.session_state.get("geojson"):
                try:
                    ws_union = _as_ws_geom(st.session_state["geojson"])
                    if not ws_union or ws_union.is_empty:
                        st.warning("⚠️ GeoJSON de cuenca inválido o vacío.")
                    else:
                        # === TOLERANCE (km) → degrees ===
                        buffer_km = 5  # 🔧 change this to taste (e.g., 0.2–2.0 km)
                        deg_tol = buffer_km / 111.0  # ~111 km per degree latitude

                        # Buffer OUTWARD so “nearby” stations are included (like click buffer)
                        ws_buffered = ws_union.buffer(deg_tol)

                        # Quick bbox prefilter for speed
                        minx, miny, maxx, maxy = ws_buffered.bounds
                        cne_bbox = gdf_cne[
                            (gdf_cne.geometry.x >= minx) & (gdf_cne.geometry.x <= maxx) &
                            (gdf_cne.geometry.y >= miny) & (gdf_cne.geometry.y <= maxy)
                        ].copy()

                        # Proximity predicate: intersects buffered basin
                        gdf_filtered = cne_bbox[cne_bbox.geometry.intersects(ws_buffered)]

                        icon_url = "app/cloudSunIcon.png"
                        if not gdf_filtered.empty:
                            st.session_state["estaciones_filtradas"] = gdf_filtered.to_dict("records")

                            # Optional: group layer
                            fg_ws = folium.FeatureGroup(
                                name=f"CNE IDEAM (dentro o a ≤{buffer_km} km de la cuenca)",
                                show=True
                            )

                            for _, row in gdf_filtered.iterrows():
                                p = row.geometry
                                nombre = str(row.get("NOMBRE") or row.get("Nombre") or row.get("nombre") or "").strip()
                                codigo = str(row.get("CODIGO") or row.get("Codigo") or row.get("codigo") or "").strip()
                                tooltip_html = f"<b>NOMBRE:</b> {nombre}<br><b>CODIGO:</b> {codigo}"

                                folium.Marker(
                                    location=[p.y, p.x],
                                    icon=CustomIcon(icon_image=icon_url, icon_size=(60, 60), icon_anchor=(20, 20)),
                                    tooltip=Tooltip(tooltip_html)
                                ).add_to(fg_ws)

                            fg_ws.add_to(m)
                        else:
                            st.warning(f"⚠️ No se encontraron entidades CNE_IDEAM a ≤{buffer_km} km de la cuenca.")
                except Exception as e:
                    st.warning(f"⚠️ No se pudo procesar estaciones respecto a la cuenca: {e}")
    except Exception as e:
        st.warning(f"⚠️ No se pudo procesar el shapefile CNE_IDEAM: {e}")

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
            style_function=lambda feat: {
                "color": "#0077b6" if feat["properties"].get("is_main") else "#00b4d8",
                "weight": 4 if feat["properties"].get("is_main") else 2,
                "opacity": 1.0 if feat["properties"].get("is_main") else 0.9
            },
            tooltip="Ríos"
        ).add_to(m)

        streams_gdf = None
        for candidate in ("streams_hr", "streams", "streams_main"):
            if st.session_state.get(candidate):
                streams_gdf = _gdf_from_geojson_str(st.session_state[candidate])
                if not streams_gdf.empty:
                    break

        if st.session_state.get("show_requested_pt") and "requested_point" in st.session_state:
            pt_req = _first_point_lonlat(st.session_state["requested_point"])
            if pt_req and streams_gdf is not None:
                lon_r, lat_r = pt_req
                req_pt = Point(lon_r, lat_r)

                # If snapped exists, draw requested → snapped with stream style of the nearest segment to snapped
                snapped_xy = _first_point_lonlat(st.session_state.get("snap_point"))
                if snapped_xy:
                    lon_s, lat_s = snapped_xy
                    snap_pt = Point(lon_s, lat_s)
                    nearest_row = _nearest_stream_row(snap_pt, streams_gdf)
                    color, weight = _stream_style_for_row(nearest_row)
                    folium.PolyLine([(lat_r, lon_r), (lat_s, lon_s)], weight=weight, opacity=0.95, color=color).add_to(m)

                # requested → river
                if streams_gdf is not None:
                    nearest_row = _nearest_stream_row(req_pt, streams_gdf)
                    conn = _connector_to_line(req_pt, nearest_row.geometry)
                    if conn and conn.length > 0:
                        color, weight = _stream_style_for_row(nearest_row)
                        folium.PolyLine([(y, x) for x, y in conn.coords], weight=weight, opacity=0.95, color=color).add_to(m)

        # SNAPPED/POUR point (magenta) → river
        if st.session_state.get("show_snapped_pt") and "snap_point" in st.session_state:
            pt_snap = _first_point_lonlat(st.session_state["snap_point"])
            if pt_snap and streams_gdf is not None:
                lon_s, lat_s = pt_snap
                snap_pt = Point(lon_s, lat_s)

                # marker + circle (you already have these)
                folium.Marker(location=[lat_s, lon_s],
                            tooltip="Punto de desfogue (ajustado)",
                            icon=folium.Icon(color="purple", icon="tint", prefix="fa")).add_to(m)
                folium.CircleMarker(location=[lat_s, lon_s], radius=6, color="magenta", fill=True, fill_opacity=1).add_to(m)

                # snapped → river (only if slight gap)
                nearest_row = _nearest_stream_row(snap_pt, streams_gdf)
                conn = _connector_to_line(snap_pt, nearest_row.geometry)
                if conn and conn.length > 0:
                    color, weight = _stream_style_for_row(nearest_row)
                    folium.PolyLine([(y, x) for x, y in conn.coords], weight=weight, opacity=0.95, color=color).add_to(m)


    # if st.session_state.get("show_requested_pt") and "requested_point" in st.session_state:
    #     folium.GeoJson(
    #         st.session_state["requested_point"],
    #         name="Punto solicitado",
    #         marker=folium.CircleMarker(radius=6, color="lightgreen", fill=True, fill_opacity=1),
    #         tooltip="Punto de solicitud"
    #     ).add_to(m)

    #     if st.session_state.get("show_snapped_pt") and "snap_point" in st.session_state:
    #         pt = _first_point_lonlat(st.session_state["snap_point"])
    #         if pt:
    #             lon, lat = pt
    #             folium.Marker(
    #                 location=[lat, lon],
    #                 tooltip="Punto de desfogue (ajustado)",
    #                 icon=folium.Icon(color="purple", icon="tint", prefix="fa")
    #             ).add_to(m)

    #             folium.CircleMarker(
    #                 location=[lat, lon],
    #                 radius=6,
    #                 color="magenta",
    #                 fill=True,
    #                 fill_opacity=1
    #             ).add_to(m)

    #         else:
    #             st.warning("⚠️ No se pudo leer el punto ajustado (GeoJSON inválido).")


    if "map_bounds" in st.session_state:
        try:
            m.fit_bounds(st.session_state["map_bounds"])
        except Exception as e:
            st.warning(f"No se pudo ajustar límites del mapa: {e}")

    # Layer control: right and initially invisible
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    if not st.session_state.get("geojson"):
        st.markdown(
            """
            <div class="title-map">
                Selecciona un punto en el mapa para delimitar una cuenca hidrográfica 🗺️
            </div>
            """,
            unsafe_allow_html=True
        )
    # Map render
    result = st_folium(m, width="100%", returned_objects=["last_clicked"], use_container_width=True)


    if result["last_clicked"]:
        st.session_state["last_click"] = result["last_clicked"]

    # Inject CSS for hover-only visibility
    st.markdown("""
        <style>
        .title-map {
            font-weight: 400;
            font-size: 15px;
            margin-bottom: 10px;
        }

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

        iframe[title="streamlit_folium"] {
            height: calc(100vh - 130px) !important;
            min-height: 500px !important;
            max-height: calc(100vh - 130px) !important;
            width: 100% !important;
            border: none !important;
            display: block;
        }

        .element-container:has(iframe[title="streamlit_folium"]) {
            margin-bottom: 0px !important;
            padding-bottom: 0px !important;
            height: calc(100vh - 130px) !important;
        }

        div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 0px !important;
            padding-bottom: 0px !important;
        }

        .block-container {
            padding-bottom: 0px !important;
            margin-bottom: 3rem !important;
        }
        .stApp iframe {
            display: block;
        }
        div[data-testid="stVerticalBlock"] {
            background-color: transparent !important;
        }
        </style>
    """, unsafe_allow_html=True)

