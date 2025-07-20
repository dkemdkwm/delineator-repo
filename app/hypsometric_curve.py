import os
import streamlit as st
import geopandas as gpd
import rasterio
import numpy as np
from rasterio.mask import mask
from shapely.geometry import box
import matplotlib.pyplot as plt

def render():
    st.title("⛰️ Curva hipsométrica")

    # Step 1: Check if a watershed (cuenca) has been delimited
    gpkg_path = st.session_state.get("gpkg_path")
    if not gpkg_path:
        st.info("⚠️ Delimite una cuenca primero.")
        return

    # Step 2: Load the geopackage and extract the watershed geometry
    gdf = gpd.read_file(gpkg_path)
    watershed_geom = gdf.unary_union

    # Step 3: Search for a DEM that intersects the watershed
    dem_folder = "data/raster/accum_basins"
    selected_dem = None

    for filename in sorted(os.listdir(dem_folder)):
        if not filename.endswith(".tif"):
            continue

        dem_path = os.path.join(dem_folder, filename)
        with rasterio.open(dem_path) as src:
            raster_bounds = box(*src.bounds)  # Convert raster bounds to shapely polygon
            raster_crs = src.crs

        # Reproject watershed to match raster CRS
        watershed_proj = gdf.to_crs(raster_crs).unary_union

        # Check intersection
        if watershed_proj.intersects(raster_bounds):
            selected_dem = dem_path
            break

    if not selected_dem:
        st.error("❌ No se encontró un DEM que cubra la cuenca delimitada.")
        return

    # Step 4: Store selected DEM and notify user
    st.session_state["dem_path"] = selected_dem
    st.success(f"✅ DEM seleccionado automáticamente: `{os.path.basename(selected_dem)}`")

    # Step 5: Load DEM values inside watershed
    elev = _load_dem(gdf)
    if elev.size == 0:
        st.error("❌ DEM vacío o fuera del polígono.")
        return

    # Step 6: Generate hypsometric curve
    x_pct, y_pct = _hypsometric_curve(elev)

    # Step 7: Plot the curve in the same style as your reference image
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.plot(x_pct, y_pct, color="green", linewidth=2)

    ax.set_xlabel("Área acumulada (%)", fontsize=14, fontweight="bold")
    ax.set_ylabel("Altura media de clase (m.s.n.m)", fontsize=14, fontweight="bold")
    ax.set_title("Curva Hipsométrica", fontsize=16, fontweight="bold")
    ax.set_ylim(0, 4000)  # <-- Limit Y-axis to 4000 meters

    ax.tick_params(axis="both", labelsize=12)
    ax.grid(True, color="gray", linestyle="--", linewidth=0.5, alpha=0.7)

    fig.tight_layout()

    st.pyplot(fig)

    # Step 8: Display elevation stats
    st.success(
        f"Elevación mínima: {elev.min():.0f} m · máxima: {elev.max():.0f} m · píxeles: {len(elev):,}"
    )


def _load_dem(poly_gdf):
    """
    Loads and clips the DEM using the watershed polygon.
    Returns the elevation values inside the polygon as a 1D array (excluding nodata).
    """
    dem_path = st.session_state.get("dem_path")
    if not dem_path:
        st.info("⚠️ Falta asociar un DEM a la delimitación.")
        st.stop()

    with rasterio.open(dem_path) as src:
        # Reproject the polygon to match DEM CRS
        poly_gdf = poly_gdf.to_crs(src.crs)

        # Clip the raster to the polygon geometry
        out_image, _ = mask(src, poly_gdf.geometry, crop=True)
        elev = out_image[0].astype("float32")
        nodata = src.nodata

        # Remove nodata and invalid values
        if nodata is not None:
            elev[elev == nodata] = np.nan
        elev[elev == 0] = np.nan  # Sometimes 0 is also invalid in DEMs

    return elev[~np.isnan(elev)]


def _hypsometric_curve(elev):
    """
    Returns the hypsometric curve values: (x_percent, y_percent)
    """
    elev_sorted = np.sort(elev)
    n = len(elev_sorted)
    x_pct = np.linspace(0, 100, n)
    y_pct = elev_sorted  # Use actual elevation values for y-axis
    return x_pct, y_pct
