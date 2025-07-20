# app/morphometry.py
import geopandas as gpd
from shapely.ops import unary_union
import numpy as np

def _kilometers(value_m):
    return value_m / 1_000

def _area_km2(poly):
    return poly.area / 1_000_000          

def _perimeter_km(poly):
    return poly.length / 1_000           

def _main_channel_len_km(streams_gdf):
    if streams_gdf.empty:
        return np.nan
    return streams_gdf.geometry.length.max() / 1_000

def _sinuosity(long_cp_km, long_cp_l_km):
    return long_cp_km / long_cp_l_km if long_cp_l_km else np.nan

def _compactness(perim_km, area_km2):
    return 0.28 * (perim_km / np.sqrt(area_km2))  

def _shape_factor(area_km2, long_cuenca_km):
    return area_km2 / (long_cuenca_km ** 2)       

def _classify_cuenca(area_km2):
    if area_km2 < 25:            return "Microcuenca"
    if area_km2 < 250:           return "Pequeña"
    if area_km2 < 500:           return "Intermedia-Pequeña"
    if area_km2 < 2_500:         return "Intermedia-Grande"
    if area_km2 <= 5_000:        return "Grande"
    return "Muy Grande"

def _classify_shape(factor):
    if factor < 0.22:  return "Muy Alargada"
    if factor < 0.30:  return "Alargada"
    if factor < 0.37:  return "Lig. Alargada"
    if factor < 0.45:  return "Intermedia"
    if factor < 0.60:  return "Lig. Achatada"
    if factor < 0.80:  return "Achatada"
    if factor < 1.20:  return "Muy Achatada"
    return "Redonda"

def _classify_sinuosity(sin):
    if sin < 1.2:   return "Rectilíneo"
    if sin < 1.5:   return "Transicional"
    if sin < 1.7:   return "Regular"
    if sin < 2.1:   return "Irregular"
    return "Tortuoso"

def _classify_densidad(den):
    if den < 1:   return "Baja"
    if den < 2:   return "Moderada"
    if den < 3:   return "Alta"
    return "Muy Alta"

def compute(watershed_gdf: gpd.GeoDataFrame,
            streams_gdf:   gpd.GeoDataFrame | None = None) -> dict:
    """
    Return a dict with all morphometric parameters for UI display.
    """

    # --- STEP 1: Reproject to metric CRS if needed ---
    if watershed_gdf.crs and watershed_gdf.crs.is_geographic:
        watershed_gdf = watershed_gdf.to_crs(epsg=3857)
    if streams_gdf is not None and streams_gdf.crs and streams_gdf.crs.is_geographic:
        streams_gdf = streams_gdf.to_crs(epsg=3857)

    # --- Basic geometry and calculations ---
    poly = unary_union(watershed_gdf.geometry)
    area = _area_km2(poly)
    perim = _perimeter_km(poly)

    long_cuenca = _main_channel_len_km(streams_gdf) if streams_gdf is not None else np.nan
    long_cp_L = long_cuenca * 0.7 if long_cuenca else np.nan

    sinuosity = _sinuosity(long_cuenca, long_cp_L)
    compacidad = _compactness(perim, area)
    factor_forma = _shape_factor(area, long_cuenca) if long_cuenca else np.nan

    densidad_dren = (
        streams_gdf.geometry.length.sum() / 1_000 / area if streams_gdf is not None and area > 0 else np.nan
    )
    num_dren = len(streams_gdf) if streams_gdf is not None else np.nan

    # --- STEP 2: Elevation and slope ---
    min_elev = watershed_gdf.geometry.total_bounds[1]
    max_elev = watershed_gdf.geometry.total_bounds[3]
    delta_h = max_elev - min_elev

    avg_slope_pct = (delta_h / (long_cuenca * 1_000)) * 100 if long_cuenca else np.nan
    avg_slope_deg = np.degrees(np.arctan(delta_h / (long_cuenca * 1_000))) if long_cuenca else np.nan

    return {
        "Área de la cuenca (km²)": round(area, 3),
        "Área de la cuenca (ha)": round(area * 100, 2),
        "Perímetro de la cuenca (km)": round(perim, 2),
        "Clasificación por área": _classify_cuenca(area),
        "Índice de compacidad": round(compacidad, 2),
        "Tipo de cuenca": _classify_shape(compacidad),
        "Longitud del cauce principal (km)": round(long_cuenca, 2),
        "Factor de forma": round(factor_forma, 3),
        "Longitud CP_L (km)": round(long_cp_L, 2),
        "Longitud Cause Principal (km)": round(long_cuenca, 2), 
        "Factor de sinuosidad": round(sinuosity, 2),
        "Clasificación de sinuosidad": _classify_sinuosity(sinuosity),
        "Longitud total de cauces (km)": round(streams_gdf.geometry.length.sum() / 1_000, 2) if streams_gdf is not None else np.nan,
        "Densidad de drenajes (km/km²)": round(densidad_dren, 2),
        "Clasificación de densidad": _classify_densidad(densidad_dren),
        "Cota mínima (msnm)": round(min_elev, 2),
        "Cota máxima (msnm)": round(max_elev, 2),
        "Diferencia altitudinal (m)": round(delta_h, 2),
        "Número de drenajes": int(num_dren) if not np.isnan(num_dren) else np.nan,
        "Densidad de corrientes (km/km²)": round(densidad_dren, 2),  # Alias for densidad drenajes
        "Pendiente media (°)": round(avg_slope_deg, 2),
        "Pendiente media (%)": round(avg_slope_pct, 2),
    }
