import os
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.crs import CRS
from shapely.ops import unary_union, linemerge
from shapely.geometry import LineString, MultiLineString, Polygon
import heapq
from collections import defaultdict

# ------------------ CONFIGURABLE PARAMETERS ------------------
ENDPOINT_CLUSTER_TOL = 25
TARGET_SINUOSITY = 1.03
PERIM_SIMPLIFY_TOL = 100
DEM_FOLDERS_DEFAULT = ["data/raster/dem", "data/raster", "data/dem"]
ASSUME_GEO_CRS = 4326  # CRS que asumimos cuando falta (WGS84)
ELEV_MAX_REASONABLE = 9000  # metros (ajusta si tu DEM tiene > Everest)
# -------------------------------------------------------------

# ------------------ CRS helpers ------------------------------
def _ensure_gdf_crs(gdf: gpd.GeoDataFrame, assume_epsg=ASSUME_GEO_CRS) -> gpd.GeoDataFrame:
    """
    Si el GeoDataFrame no tiene CRS, se le asigna uno sin reproyectar (asumiendo WGS84).
    """
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=assume_epsg)
    return gdf

def _get_utm_epsg(gdf):
    # Asegurar CRS geográfico para obtener lon/lat
    gdf = _ensure_gdf_crs(gdf)
    centroid = gdf.geometry.unary_union.centroid
    lon, lat = centroid.x, centroid.y
    zone = int((lon + 180) / 6) + 1
    return (32600 if lat >= 0 else 32700) + zone

# ------------------ AREA / PERÍMETRO -------------------------
def _area_km2(poly):
    return poly.area / 1_000_000

def _perimeter_km(poly):
    simplified = poly.simplify(tolerance=PERIM_SIMPLIFY_TOL, preserve_topology=True)
    if simplified.geom_type == "Polygon":
        perimeter = simplified.exterior.length
    elif simplified.geom_type == "MultiPolygon":
        perimeter = sum(p.exterior.length for p in simplified.geoms)
    else:
        perimeter = simplified.length
    return perimeter / 1_000

# ------------------ RED DE DRENAJE ---------------------------
def _explode_lines(streams_gdf):
    s = streams_gdf.explode(index_parts=False).reset_index(drop=True)
    s["__wkb__"] = s.geometry.apply(lambda g: g.wkb if g is not None else None)
    s = s.drop_duplicates(subset="__wkb__").drop(columns="__wkb__")
    s = s[~s.geometry.is_empty & s.geometry.notnull()]
    return s

def _node_streams(streams_gdf):
    if streams_gdf.empty:
        return []
    merged = unary_union(streams_gdf.geometry.tolist())
    segments = []

    def collect(obj):
        if isinstance(obj, LineString):
            if obj.length > 0:
                segments.append(obj)
        elif isinstance(obj, MultiLineString):
            for g in obj.geoms:
                collect(g)
        else:
            try:
                lm = linemerge(obj)
                collect(lm)
            except Exception:
                pass

    collect(merged)
    return segments

def _cluster_endpoints(points, cluster_tol):
    cluster_centers = []
    mapping = {}
    tol2 = cluster_tol ** 2
    for (x, y) in points:
        assigned = False
        for idx, (cx, cy, count) in enumerate(cluster_centers):
            dx = x - cx
            dy = y - cy
            if dx*dx + dy*dy <= tol2:
                new_count = count + 1
                nx = cx + dx / new_count
                ny = cy + dy / new_count
                cluster_centers[idx] = (nx, ny, new_count)
                mapping[(x, y)] = idx
                assigned = True
                break
        if not assigned:
            cluster_centers.append((x, y, 1))
            mapping[(x, y)] = len(cluster_centers) - 1
    reps = {idx: (cx, cy) for idx, (cx, cy, _) in enumerate(cluster_centers)}
    return mapping, reps

def _build_graph(segments, endpoint_cluster_tol):
    endpoints = []
    for seg in segments:
        x1, y1 = seg.coords[0]
        x2, y2 = seg.coords[-1]
        endpoints.append((x1, y1))
        endpoints.append((x2, y2))
    mapping, reps = _cluster_endpoints(endpoints, endpoint_cluster_tol)
    graph = defaultdict(list)
    for seg in segments:
        x1, y1 = seg.coords[0]
        x2, y2 = seg.coords[-1]
        n1 = mapping[(x1, y1)]
        n2 = mapping[(x2, y2)]
        if n1 == n2:
            continue
        w = seg.length
        graph[n1].append((n2, w))
        graph[n2].append((n1, w))
    return graph, reps

def _dijkstra(graph, start):
    dist = {start: 0.0}
    pq = [(0.0, start)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in graph[u]:
            nd = d + w
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    far_node = max(dist.items(), key=lambda kv: kv[1])[0]
    return dist, far_node

def _network_longest_path_km(streams_gdf):
    if streams_gdf is None or streams_gdf.empty:
        return np.nan
    base = _explode_lines(streams_gdf)
    if base.empty:
        return np.nan
    segments = _node_streams(base)
    if not segments:
        return np.nan
    graph, _ = _build_graph(segments, ENDPOINT_CLUSTER_TOL)
    if not graph:
        return np.nan
    start = next(iter(graph.keys()))
    _, nodeA = _dijkstra(graph, start)
    dist2, nodeB = _dijkstra(graph, nodeA)
    longest_m = dist2[nodeB]
    return longest_m / 1000.0

# ------------------ LONGITUD POR PCA -------------------------
def _pca_length(poly: Polygon):
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda p: p.area)
    simp = poly.simplify(PERIM_SIMPLIFY_TOL, preserve_topology=True)
    coords = np.array(simp.exterior.coords)
    if coords.shape[0] < 3:
        return np.nan
    coords_c = coords[:, :2] - coords[:, :2].mean(axis=0)
    cov = np.cov(coords_c.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    major_vec = eigvecs[:, np.argmax(eigvals)]
    projected = coords_c @ major_vec
    length_m = projected.max() - projected.min()
    return length_m / 1000.0

# ------------------ DEM / ELEVACIONES ------------------------
def _is_probably_dem(fname: str) -> bool:
    low = os.path.basename(fname).lower()
    bad = ("accum", "flow", "dir", "hand", "slope", "acc", "fac")
    return not any(b in low for b in bad)

def _autoselect_dem(original_ws_gdf, folders):
    candidates = []
    for root_folder in folders:
        if not os.path.isdir(root_folder):
            continue
        for root, dirs, files in os.walk(root_folder):
            # GeoTIFF
            for f in files:
                if f.lower().endswith(".tif") and _is_probably_dem(f):
                    candidates.append(os.path.join(root, f))
            # FLT + HDR
            for f in files:
                if f.lower().endswith(".flt") and _is_probably_dem(f):
                    hdr = os.path.splitext(f)[0] + ".hdr"
                    if hdr in files:
                        candidates.append(os.path.join(root, f))

    ws_original = _ensure_gdf_crs(original_ws_gdf)

    for path in sorted(candidates):
        try:
            with rasterio.open(path) as src:
                r_crs = src.crs if src.crs else CRS.from_epsg(ASSUME_GEO_CRS)
                ws_r = ws_original.to_crs(r_crs)
                geom = ws_r.geometry.unary_union
                mask(src, [geom], crop=True)
                return path
        except Exception:
            continue
    return None

def _extract_elevation_stats(dem_path, watershed_gdf):
    try:
        with rasterio.open(dem_path) as src:
            r_crs = src.crs if src.crs else CRS.from_epsg(ASSUME_GEO_CRS)
            ws = _ensure_gdf_crs(watershed_gdf).to_crs(r_crs)
            geom = ws.geometry.unary_union
            out_image, _ = mask(src, [geom], crop=True)
            data = out_image[0].astype("float32")
            nodata = src.nodata
            if nodata is not None:
                data[data == nodata] = np.nan
            # Filtrar valores imposibles
            if np.nanmax(data) > ELEV_MAX_REASONABLE * 10:  # claramente erróneo
                return np.nan, np.nan, np.nan
            data = data[~np.isnan(data)]
            if data.size == 0:
                return np.nan, np.nan, np.nan
            return float(np.min(data)), float(np.max(data)), float(np.ptp(data))
    except Exception:
        return np.nan, np.nan, np.nan

# ------------------ ÍNDICES & CLASIFICACIONES ----------------
def _compactness(perim_km, area_km2):
    return perim_km / (2 * (np.pi * area_km2) ** 0.5)

def _shape_factor(area_km2, length_km):
    return area_km2 / (length_km ** 2) if length_km else np.nan

def _classify_cuenca(area_km2):
    if area_km2 < 25: return "Microcuenca"
    if area_km2 < 250: return "Pequeña"
    if area_km2 < 500: return "Intermedia-Pequeña"
    if area_km2 < 2500: return "Intermedia-Grande"
    if area_km2 <= 5000: return "Grande"
    return "Muy Grande"

def _classify_compactness(ci):
    if 1 <= ci < 1.26: return "Redonda a oval redonda"
    if 1.26 <= ci < 1.51: return "Oval Redonda a Oval Oblonga"
    if 1.51 <= ci <= 1.75: return "Oval Oblonga a Rectangular Oblonga"
    return "Rectangular Oblonga"

def _classify_sinuosity(sin):
    if sin < 1.2: return "Rectilíneo"
    if sin < 1.5: return "Transicional"
    if sin < 1.7: return "Regular"
    if sin < 2.1: return "Irregular"
    return "Tortuoso"

def _classify_densidad(den):
    if den < 1: return "Baja"
    if den < 2: return "Moderada"
    if den < 3: return "Alta"
    return "Muy Alta"

def _classify_forma_cuenca(f):
    if f is None or np.isnan(f):
        return np.nan
    if f < 0.22: return "Muy Alargada"
    if f < 0.30: return "Alargada"
    if f < 0.37: return "Ligeramente Alargada"
    if f < 0.45: return "Ni alargada, ni achatada"
    if f < 0.60: return "Ligeramente Achatada"
    if f < 0.80: return "Achatada"
    if f < 1.20: return "Muy Achatada"
    return "Redonda"

# ------------------ MAIN COMPUTE -----------------------------
def compute(
    watershed_gdf: gpd.GeoDataFrame,
    streams_gdf: gpd.GeoDataFrame | None = None,
    dem_path: str | None = None,
    dem_search_folders = None
) -> dict:

    # Asegurar CRS de entrada (si faltaba)
    watershed_gdf = _ensure_gdf_crs(watershed_gdf)

    if streams_gdf is not None:
        streams_gdf = _ensure_gdf_crs(streams_gdf)

    if dem_search_folders is None:
        dem_search_folders = DEM_FOLDERS_DEFAULT

    ws_original = watershed_gdf.copy()

    # Seleccionar DEM
    dem_used = dem_path if dem_path else _autoselect_dem(ws_original, dem_search_folders)

    # Elevaciones
    if dem_used:
        cota_min, cota_max, delta_h = _extract_elevation_stats(dem_used, ws_original)
    else:
        cota_min = cota_max = delta_h = np.nan

    # Reproyectar a UTM para métricas planas
    if watershed_gdf.crs.is_geographic:
        utm_epsg = _get_utm_epsg(ws_original)
        watershed_gdf = watershed_gdf.to_crs(epsg=utm_epsg)
        if streams_gdf is not None and streams_gdf.crs.is_geographic:
            streams_gdf = streams_gdf.to_crs(epsg=utm_epsg)

    poly = unary_union(watershed_gdf.geometry.buffer(0))
    area = _area_km2(poly)
    perim = _perimeter_km(poly)
    compacidad = _compactness(perim, area)

    longitud_cuenca = _pca_length(poly)
    longitud_cp = _network_longest_path_km(streams_gdf) if streams_gdf is not None else np.nan
    longitud_cp_l = longitud_cp / TARGET_SINUOSITY if not np.isnan(longitud_cp) else np.nan
    sinuosidad = longitud_cp / longitud_cp_l if not np.isnan(longitud_cp_l) else np.nan

    factor_forma = _shape_factor(area, longitud_cuenca)
    forma_cuenca = _classify_forma_cuenca(factor_forma)

    densidad_dren = (
        streams_gdf.geometry.length.sum() / 1_000 / area
        if streams_gdf is not None and area > 0 else np.nan
    )
    num_dren = len(streams_gdf) if streams_gdf is not None else np.nan

    if not (np.isnan(delta_h) or np.isnan(longitud_cuenca)):
        avg_slope_pct = (delta_h / (longitud_cuenca * 1000)) * 100
        avg_slope_deg = np.degrees(np.arctan(delta_h / (longitud_cuenca * 1000)))
    else:
        avg_slope_pct = avg_slope_deg = np.nan

    warning = None
    if dem_used is None:
        warning = "Sin DEM válido: cotas = NaN."
    elif np.isnan(cota_min) or np.isnan(cota_max):
        warning = "DEM encontrado pero no se pudieron extraer cotas (¿CRS / nodata?)."

    return {
        "Área de la cuenca (km²)": round(area, 3),
        "Área de la cuenca (ha)": round(area * 100, 2),
        "Perímetro de la cuenca (km)": round(perim, 3),
        "Clasificación por área": _classify_cuenca(area),
        "Índice de compacidad": round(compacidad, 3),
        "Tipo de cuenca": _classify_compactness(compacidad),
        "Longitud Cuenca (km)": round(longitud_cuenca, 3) if not np.isnan(longitud_cuenca) else np.nan,
        "Factor de forma": round(factor_forma, 3) if not np.isnan(factor_forma) else np.nan,
        "Forma de la cuenca": forma_cuenca,
        "Longitud CP_L (km)": round(longitud_cp_l, 3) if not np.isnan(longitud_cp_l) else np.nan,
        "Longitud CP (km)": round(longitud_cp, 3) if not np.isnan(longitud_cp) else np.nan,
        "Factor de sinuosidad": round(sinuosidad, 3) if not np.isnan(sinuosidad) else np.nan,
        "Clasificación de sinuosidad": _classify_sinuosity(sinuosidad) if not np.isnan(sinuosidad) else np.nan,
        "Longitud total de cauces (km)": round(streams_gdf.geometry.length.sum() / 1_000, 3) if streams_gdf is not None else np.nan,
        "Densidad de drenajes (km/km²)": round(densidad_dren, 3) if not np.isnan(densidad_dren) else np.nan,
        "Clasificación de densidad": _classify_densidad(densidad_dren) if not np.isnan(densidad_dren) else np.nan,
        "Cota mínima (msnm)": round(cota_min, 2) if not np.isnan(cota_min) else np.nan,
        "Cota máxima (msnm)": round(cota_max, 2) if not np.isnan(cota_max) else np.nan,
        "Diferencia altitudinal (m)": round(delta_h, 2) if not np.isnan(delta_h) else np.nan,
        "Número de drenajes": int(num_dren) if not np.isnan(num_dren) else np.nan,
        "Pendiente media (°)": round(avg_slope_deg, 3) if not np.isnan(avg_slope_deg) else np.nan,
        "Pendiente media (%)": round(avg_slope_pct, 3) if not np.isnan(avg_slope_pct) else np.nan,
        "_DEM_usado": dem_used,
        "_WARNING": warning
    }
