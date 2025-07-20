import os
import streamlit as st
import geopandas as gpd
import rasterio
import numpy as np
from pathlib import Path
from rasterio.mask import mask
from shapely.geometry import box
import matplotlib.pyplot as plt
import pandas as pd
from rasterio.crs import CRS
from math import cos, radians

# ============================================================
# CONFIGURACIÓN
# ============================================================
DEM_SEARCH_FOLDERS = [
    "data/raster/dem",
    "data/raster/dem_flt_n00w090",
    "data/raster/accum_basins",
    "data/raster"
]
EXCLUDE_TOKENS = ("accum", "flowdir", "flow_dir", "hand", "slope", "dir", "fac")
ASSUMED_RASTER_EPSG = 4326          # MERIT DEM (cuando falta CRS)
REVERSE_NORMALIZED_FOR_TOP = False  # False => la línea punteada coincide en forma con la azul

# ============================================================
# HELPERS CRS / ÁREA DE PÍXEL
# ============================================================
def _ensure_gdf_crs(gdf: gpd.GeoDataFrame, epsg=ASSUMED_RASTER_EPSG):
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=epsg)
    return gdf

def _approx_pixel_area_m2(transform, lat_center_deg: float):
    """Aproxima área de píxel si el DEM está en grados."""
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * cos(radians(lat_center_deg))
    pw_deg = abs(transform.a)
    ph_deg = abs(transform.e)
    return pw_deg * m_per_deg_lon * ph_deg * m_per_deg_lat

# ============================================================
# RENDER PRINCIPAL
# ============================================================
def render():
    st.title("⛰️ Curva Hipsométrica")

    gpkg_path = st.session_state.get("gpkg_path")
    if not gpkg_path:
        st.info("⚠️ Delimita una cuenca primero.")
        return

    try:
        gdf = gpd.read_file(gpkg_path)
    except Exception as e:
        st.error(f"No se pudo leer la cuenca: {e}")
        return

    gdf = _ensure_gdf_crs(gdf)

    # ---------------- DEM selection ----------------
    debug = st.sidebar.checkbox("Mostrar DEBUG DEM", value=False)
    forced_dem = st.sidebar.text_input("Forzar DEM (ruta opcional)", value="", help="Dejar vacío para autoselección.")
    dem_path = None

    existing = st.session_state.get("dem_path")
    if existing and Path(existing).exists() and not forced_dem:
        dem_path = existing
        if debug:
            st.write(f"**[DEBUG] Reutilizando DEM previo:** {dem_path}")
    elif forced_dem:
        if Path(forced_dem).exists():
            dem_path = forced_dem
            st.success(f"DEM forzado: `{dem_path}`")
        else:
            st.error("Ruta forzada no existe.")
            return
    else:
        dem_path = _autoselect_dem_debug(gdf, debug=debug)
        if dem_path:
            st.session_state["dem_path"] = dem_path

    if not dem_path:
        st.error("❌ No se encontró un DEM que cubra la cuenca (ver debug).")
        return
    else:
        st.success(f"✅ DEM usado: `{os.path.basename(dem_path)}`")

    # ---------------- Parámetros UI ----------------
    esquema = st.sidebar.selectbox(
        "Esquema de clases",
        ("arcgis (100 m)", "intervalos iguales", "cuantiles"),
        help="ArcGIS: primer tramo hasta ...99 y luego pasos de 100 m."
    )
    num_clases = st.sidebar.number_input(
        "Número de clases (para 'intervalos iguales' o 'cuantiles')",
        min_value=5, max_value=50, value=12, step=1
    )
    orientacion = st.sidebar.selectbox(
        "Orientación de curva",
        ("Área desde abajo", "Área desde arriba (ArcGIS)"),
        help="% acumulado ascendiendo (abajo) o remanente (arriba)."
    )
    mostrar_normalizada = st.sidebar.checkbox("Añadir curva normalizada h/H", True)

    # ---------------- Cargar elevaciones ----------------
    elev, transform, src_crs = _load_and_clip_dem(gdf, dem_path)
    if elev.size == 0:
        st.error("DEM vacío tras recorte.")
        return

    z_min_real = float(np.nanmin(elev))
    z_max_real = float(np.nanmax(elev))

    if debug:
        st.write(f"**[DEBUG] Elevación min/max:** {z_min_real} / {z_max_real}")
        st.write(f"**[DEBUG] CRS DEM:** {src_crs}")

    # ---------------- Tabla base (ascendente) ----------------
    tabla_base = _hypsometric_table(
        elev,
        transform,
        num_clases=num_clases,
        method=esquema,
        polygon_gdf=gdf,
        dem_crs=src_crs
    )
    if tabla_base.empty:
        st.error("Tabla hipsométrica vacía (posible problema en histogramado).")
        return

    # =========================================================
    # AJUSTE ORIENTACIÓN
    # =========================================================
    if orientacion.startswith("Área desde arriba"):
        # 1. Reordenar de mayor a menor cota
        tabla_desc = tabla_base.sort_values("Límite Inferior (m)", ascending=False).reset_index(drop=True)
        # 2. Recalcular acumulado remanente (conforme descendemos)
        area_km2_desc = tabla_desc["Área (km²)"].to_numpy()
        cum_top_km2 = np.cumsum(area_km2_desc)
        total_km2 = cum_top_km2[-1]
        cum_top_pct = (cum_top_km2 / total_km2) * 100

        tabla_desc["Área Acumulada (km²) desde Arriba"] = cum_top_km2
        tabla_desc["Área Acumulada desde Arriba (%)"] = cum_top_pct
        # Invalidar campos “desde abajo” (no aplican en este orden)
        tabla_desc["Área Acumulada (km²) desde Abajo"] = np.nan
        tabla_desc["Área Acumulada desde Abajo (%)"] = np.nan

        # 3. Curva
        x_vals = cum_top_pct
        x_label = "Área acumulada desde arriba (%)"
        y_vals = tabla_desc["Altura Media de Clase (m)"].to_numpy()

        # 4. Normalizada (misma forma que y_vals)
        if z_max_real > z_min_real:
            h_norm_full = (y_vals - z_min_real) / (z_max_real - z_min_real)
        else:
            h_norm_full = np.zeros_like(y_vals)
        h_norm_plot = (1 - h_norm_full) if REVERSE_NORMALIZED_FOR_TOP else h_norm_full

        tabla_para_mostrar = tabla_desc

    else:
        # Orientación estándar (ascendente)
        x_vals = tabla_base["Área Acumulada desde Abajo (%)"].to_numpy()
        x_label = "Área acumulada desde abajo (%)"
        y_vals = tabla_base["Altura Media de Clase (m)"].to_numpy()

        if z_max_real > z_min_real:
            h_norm_plot = (y_vals - z_min_real) / (z_max_real - z_min_real)
        else:
            h_norm_plot = np.zeros_like(y_vals)

        tabla_para_mostrar = tabla_base
    st.session_state["hypsometric_table"] = tabla_para_mostrar
    # ---------------- Gráfico ----------------
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(x_vals, y_vals, linewidth=2, color="steelblue")
    ax.set_xlabel(x_label, fontsize=13, fontweight="bold")
    ax.set_ylabel("Altura media de clase (m)", fontsize=13, fontweight="bold")
    ax.set_title("Curva Hipsométrica", fontsize=15, fontweight="bold")
    ax.set_xlim(0, 100)
    ax.set_ylim(z_min_real, z_max_real)
    ax.grid(True, linestyle="--", alpha=0.5)

    if mostrar_normalizada:
        ax2 = ax.twinx()
        ax2.plot(x_vals, h_norm_plot, linestyle="--", color="black", label="h/H")
        ax2.set_ylabel("Elevación normalizada (h/H)")
        ax2.set_ylim(0, 1)
        ax2.tick_params(labelsize=9)

    st.pyplot(fig)

    # ---------------- Índice hipsométrico ----------------
    hi = _hypsometric_integral(elev)
    st.info(f"Índice Hipsométrico (HI) = **{hi:.3f}**")

    # ---------------- Tabla final ----------------
    cols_order = [
        "N° Clase", "Límite Inferior (m)", "Límite Superior (m)",
        "Altura Media de Clase (m)",
        "Área (m²)", "Área (km²)",
        "Área Acumulada (km²) desde Abajo", "Área Acumulada (km²) desde Arriba",
        "Área Acumulada desde Abajo (%)", "Área Acumulada desde Arriba (%)",
        "Área % de cada clase"
    ]
    # Quitar duplicados solo por seguridad
    cols_unique = [c for c in cols_order if c in tabla_para_mostrar.columns]
    tabla_mostrar = tabla_para_mostrar[cols_unique]

    st.subheader("Tabla hipsométrica")
    st.dataframe(
        tabla_mostrar.style.format({
            "Altura Media de Clase (m)": "{:.1f}",
            "Área (m²)": "{:,.0f}",
            "Área (km²)": "{:.2f}",
            "Área Acumulada (km²) desde Abajo": "{:.2f}",
            "Área Acumulada (km²) desde Arriba": "{:.2f}",
            "Área Acumulada desde Abajo (%)": "{:.2f}",
            "Área Acumulada desde Arriba (%)": "{:.2f}",
            "Área % de cada clase": "{:.2f}"
        })
    )

    st.download_button(
        "⬇️ Descargar tabla (CSV)",
        data=tabla_mostrar.to_csv(index=False).encode("utf-8"),
        file_name="tabla_hipsometrica.csv",
        mime="text/csv"
    )

    with st.expander("Ver tabla con fórmulas (documentación)"):
        st.dataframe(_annotated_formulas(tabla_para_mostrar))

    st.success(
        f"Elevación mínima: {z_min_real:.1f} m · máxima: {z_max_real:.1f} m · píxeles usados: {len(elev):,}"
    )

# ============================================================
# DEM Selection
# ============================================================
def _list_candidate_dems(folders):
    candidates = []
    for folder in folders:
        p = Path(folder)
        if not p.is_dir():
            continue
        for f in p.rglob("*"):
            if f.suffix.lower() in {".tif", ".flt"}:
                low = f.name.lower()
                if any(tok in low for tok in EXCLUDE_TOKENS):
                    continue
                if f.suffix.lower() == ".flt" and not f.with_suffix(".hdr").exists():
                    continue
                candidates.append(f)
    return candidates

def _autoselect_dem_debug(gdf, debug=False):
    gdf = _ensure_gdf_crs(gdf)
    candidates = _list_candidate_dems(DEM_SEARCH_FOLDERS)
    if debug:
        st.write("**[DEBUG] Candidatos DEM:**", [str(c) for c in candidates])
        st.write("**[DEBUG] CRS cuenca:**", gdf.crs)
        st.write("**[DEBUG] Bounds cuenca:**", gdf.total_bounds.tolist())

    if not candidates:
        return None

    for path in sorted(candidates):
        try:
            with rasterio.open(path) as src:
                r_crs = src.crs if src.crs else CRS.from_epsg(ASSUMED_RASTER_EPSG)
                ws_proj = gdf.to_crs(r_crs).unary_union
                raster_bbox = box(*src.bounds)
                if not ws_proj.intersects(raster_bbox):
                    if debug:
                        st.write(f"[DEBUG] Sin intersección bbox: {path}")
                    continue
                mask(src, [ws_proj], crop=True)
                if debug:
                    st.write(f"[DEBUG] Seleccionado DEM: {path}")
                return str(path)
        except Exception as e:
            if debug:
                st.write(f"[DEBUG] Falló {path}: {e}")
            continue
    return None

# ============================================================
# Cargar y recortar DEM
# ============================================================
def _load_and_clip_dem(poly_gdf, dem_path):
    poly_gdf = _ensure_gdf_crs(poly_gdf)
    with rasterio.open(dem_path) as src:
        r_crs = src.crs if src.crs else CRS.from_epsg(ASSUMED_RASTER_EPSG)
        pg = poly_gdf.to_crs(r_crs) if poly_gdf.crs != r_crs else poly_gdf
        out, _ = mask(src, pg.geometry, crop=True)
        arr = out[0].astype("float32")
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        # arr[arr == 0] = np.nan  # Descomenta si 0 es mar/nodata
        return arr[~np.isnan(arr)], src.transform, r_crs

# ============================================================
# Bins estilo ArcGIS
# ============================================================
def _arcgis_bins(zmin, zmax):
    zmin_i = int(np.floor(zmin))
    zmax_i = int(np.ceil(zmax))
    first_upper = (zmin_i // 100) * 100 + 99
    edges = [zmin_i]
    if first_upper >= zmax_i:
        edges.append(zmax_i)
        return np.array(edges, dtype=float)
    edges.append(first_upper)
    current_low = first_upper + 1
    while current_low <= zmax_i:
        upper = min(current_low + 99, zmax_i)
        edges.append(upper)
        current_low = upper + 1
    return np.array(edges, dtype=float)

# ============================================================
# Tabla hipsométrica (ascendente base)
# ============================================================
def _hypsometric_table(elev, transform, num_clases=12, method="arcgis (100 m)",
                       polygon_gdf=None, dem_crs=None):
    elev = elev[~np.isnan(elev)]
    if elev.size == 0:
        return pd.DataFrame()

    z_min_real, z_max_real = float(np.min(elev)), float(np.max(elev))

    if dem_crs and dem_crs.is_geographic and polygon_gdf is not None:
        lat_center = polygon_gdf.geometry.unary_union.centroid.y
        pixel_area_m2 = _approx_pixel_area_m2(transform, lat_center)
    else:
        pixel_area_m2 = abs(transform.a) * abs(transform.e)

    if method.startswith("arcgis"):
        edges = _arcgis_bins(z_min_real, z_max_real)
    elif method == "cuantiles":
        qs = np.linspace(0, 1, num_clases + 1)
        edges = np.unique(np.quantile(elev, qs))
        if len(edges) - 1 < num_clases:
            edges = np.linspace(z_min_real, z_max_real, num_clases + 1)
    else:
        edges = np.linspace(z_min_real, z_max_real, num_clases + 1)

    edges = np.sort(edges)
    counts, h_edges = np.histogram(elev, bins=edges)

    area_m2 = counts * pixel_area_m2
    area_km2 = area_m2 / 1_000_000.0
    total_km2 = area_km2.sum()
    if total_km2 == 0:
        return pd.DataFrame()

    cum_down_km2 = np.cumsum(area_km2)
    cum_up_km2 = np.cumsum(area_km2[::-1])[::-1]
    cum_down_pct = (cum_down_km2 / total_km2) * 100
    cum_up_pct = (cum_up_km2 / total_km2) * 100
    pct_class = (area_km2 / total_km2) * 100

    rows = []
    for i in range(len(counts)):
        lower = h_edges[i]
        upper = h_edges[i + 1]
        mid = (lower + upper) / 2
        rows.append({
            "N° Clase": i + 1,
            "Límite Inferior (m)": lower,
            "Límite Superior (m)": upper,
            "Altura Media de Clase (m)": mid,
            "Área (m²)": area_m2[i],
            "Área (km²)": area_km2[i],
            "Área Acumulada (km²) desde Abajo": cum_down_km2[i],
            "Área Acumulada (km²) desde Arriba": cum_up_km2[i],
            "Área Acumulada desde Abajo (%)": cum_down_pct[i],
            "Área Acumulada desde Arriba (%)": cum_up_pct[i],
            "Área % de cada clase": pct_class[i]
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.at[df.index[-1], "Área Acumulada desde Abajo (%)"] = 100.0
        df.at[df.index[0],  "Área Acumulada desde Arriba (%)"] = 100.0
    return df

# ============================================================
# Tabla de fórmulas (documentación)
# ============================================================
def _annotated_formulas(df):
    out = []
    for _, r in df.iterrows():
        out.append({
            "N° Clase": r.get("N° Clase"),
            "Fórmula Altura Media": "=(LímiteInferior + LímiteSuperior)/2",
            "Fórmula Área (m²)": "=CuentaPixelesClase * ÁreaPixel",
            "Fórmula Área (km²)": "=Área(m²)/1,000,000",
            "Fórmula % clase": "=ÁreaClase(km²)/ÁreaTotal(km²)*100",
            "Fórmula Acum abajo (%)": "Σ % clase desde mínima",
            "Fórmula Acum arriba (%)": "Σ % clase desde esa hasta máxima"
        })
    return pd.DataFrame(out)

# ============================================================
# Índice hipsométrico
# ============================================================
def _hypsometric_integral(elev):
    elev = elev[~np.isnan(elev)]
    if elev.size == 0:
        return np.nan
    z_mean = np.mean(elev)
    z_min = np.min(elev)
    z_max = np.max(elev)
    if z_max == z_min:
        return np.nan
    return (z_mean - z_min) / (z_max - z_min)
