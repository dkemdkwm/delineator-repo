# app/hypsometric_curve.py

import streamlit as st
import geopandas as gpd
import rasterio
import rasterio.mask
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import os
from shapely.geometry import box
import pandas as pd
from scipy.interpolate import make_interp_spline  # ✅ NEW


def _load_dem(poly_gdf):
    dem_path = st.session_state.get("dem_path")
    if not dem_path:
        st.info("⚠️ Falta asociar un DEM a la delimitación.")
        st.stop()

    with rasterio.open(dem_path) as src:
        poly_gdf = poly_gdf.to_crs(src.crs)
        out_image, _ = rasterio.mask.mask(src, poly_gdf.geometry, crop=True)
        elev = out_image[0].astype("float32")
        nodata = src.nodata

        if nodata is not None:
            elev[elev == nodata] = np.nan
        elev[elev == 0] = np.nan  # some DEMs use 0 as invalid too

    return elev[~np.isnan(elev)]

def _hypsometric_table_and_curve(elev, num_bins=30):
    """
    Compute hypsometric curve table based on elevation range and pixel count per bin.
    """
    # Only consider valid pixels
    elev = elev[(elev >= 0) & (elev <= 6000)]
    min_elev = np.nanmin(elev)
    max_elev = np.nanmax(elev)

    bins = np.linspace(min_elev, max_elev, num_bins + 1)
    df = pd.DataFrame({'elev': elev})
    df['class'] = pd.cut(df['elev'], bins=bins, include_lowest=True)

    # Group and summarize
    grouped = df.groupby('class')['elev']
    results = pd.DataFrame({
        'Altura media de clase': grouped.mean(),
        'Área (m2)': grouped.count() * 30 * 30,
    }).reset_index()

    # Cumulative area and percentage
    results['Área (km2)'] = results['Área (m2)'] / 1e6
    results['Área acumulada (km2)'] = results['Área (km2)'].cumsum()
    total_area = results['Área (km2)'].sum()
    results['Área acumulada (%)'] = 100 * results['Área acumulada (km2)'] / total_area

    return results

def render():
    st.title("⛰️ Curva hipsométrica")

    gpkg = st.session_state.get("gpkg_path")
    if not gpkg:
        st.info("Delimite una cuenca primero.")
        return

    gdf = gpd.read_file(gpkg)
    dem_folder = "data/raster/accum_basins"
    selected_dem = None

    for filename in sorted(os.listdir(dem_folder)):
        if not filename.endswith(".tif"):
            continue
        dem_path = os.path.join(dem_folder, filename)
        with rasterio.open(dem_path) as src:
            raster_bounds = box(*src.bounds)
            raster_crs = src.crs
        watershed_geom_proj = gdf.to_crs(raster_crs).unary_union
        if watershed_geom_proj.intersects(raster_bounds):
            selected_dem = dem_path
            break

    if not selected_dem:
        st.error("❌ No se encontró un DEM que cubra la cuenca delimitada.")
        return

    st.session_state["dem_path"] = selected_dem
    st.success(f"DEM seleccionado automáticamente: `{os.path.basename(selected_dem)}`")

    elev = _load_dem(gdf)
    if elev.size == 0:
        st.error("DEM vacío o fuera del polígono.")
        return

    df_curve = _hypsometric_table_and_curve(elev, num_bins=30)  # ✅ Adjust bin count

    # --------- Plot ----------
    fig, ax = plt.subplots(figsize=(8, 6), dpi=120)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    x = df_curve["Área acumulada (%)"].values
    y = df_curve["Altura media de clase"].values

    # ✅ Simple line (no smoothing, no markers)
    ax.plot(
        x,
        y,
        color="darkgreen",
        linewidth=2.5
    )

    ax.set_title("Curva Hipsométrica", fontsize=18, fontweight="bold", color="black", pad=15)
    ax.set_xlabel("Área acumulada (%)", fontsize=14, fontweight="bold", color="black", labelpad=10)
    ax.set_ylabel("Altura media de clase (m.s.n.m)", fontsize=14, fontweight="bold", color="black", labelpad=10)

    ax.grid(True, linestyle='--', linewidth=0.6, alpha=0.7)
    ax.tick_params(axis='both', colors='black', labelsize=12)

    # ✅ Match image axis direction
    ax.set_xlim(0, 100)
    ax.set_ylim(0, df_curve["Altura media de clase"].max() + 100)

    for spine in ax.spines.values():
        spine.set_color("black")

    st.pyplot(fig)



    st.dataframe(df_curve)

    st.download_button(
        label="📥 Descargar tabla CSV",
        data=df_curve.to_csv(index=False).encode('utf-8'),
        file_name='curva_hipsometrica.csv',
        mime='text/csv'
    )

    st.success(
        f"Elevación mínima: {elev.min():.0f} m · máxima: {elev.max():.0f} m · píxeles: {len(elev):,}"
    )

