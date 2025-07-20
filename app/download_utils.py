from pathlib import Path
import io, zipfile, math, base64
import pandas as pd
import geopandas as gpd
from typing import List, Optional, Tuple

# ==========================================================
# Selección dinámica de engine Excel
# ==========================================================
def _pick_excel_engine():
    try:
        return "xlsxwriter"
    except ImportError:
        try:
            return "openpyxl"
        except ImportError:
            return None

# ==========================================================
# Normalizar tabla de tiempos de concentración
# ==========================================================
def _normalize_tc_df(tc_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Si la tabla viene como una sola fila (métodos en columnas),
    retorna un DataFrame 'Método' | 'Tiempo (min)'.
    Si ya está larga, la deja igual.
    """
    if tc_df is None or tc_df.empty:
        return tc_df
    if tc_df.shape[0] == 1:  # ancho (pivot)
        row = tc_df.iloc[0]
        return pd.DataFrame({"Método": row.index, "Tiempo (min)": row.values})
    # Si ya tiene columna método (en cualquiera de sus variantes)
    cols_low = [c.lower() for c in tc_df.columns]
    if "método" in cols_low or "metodo" in cols_low:
        return tc_df
    return tc_df  # Se asume ya es usable

# ==========================================================
# Asegurar columna normalizada hipsométrica
# ==========================================================
def _ensure_hypso_normalized(hypso_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """
    Añade 'Elevación normalizada (h/H)' si no existe.
    Se normaliza usando la columna de altura media de clase.
    """
    if hypso_df is None or hypso_df.empty:
        return hypso_df
    # Ya existe alguna forma de normalizada
    for c in hypso_df.columns:
        lc = c.lower()
        if "normalizada" in lc or "h/h" in lc:
            return hypso_df
    altura_col = next(
        (c for c in hypso_df.columns
         if "altura media" in c.lower() and "(m" in c.lower()),
        None
    )
    if altura_col is None:
        return hypso_df
    vals = hypso_df[altura_col].to_numpy()
    if len(vals) == 0:
        return hypso_df
    zmin, zmax = float(vals.min()), float(vals.max())
    if zmax > zmin:
        hypso_df["Elevación normalizada (h/H)"] = (vals - zmin) / (zmax - zmin)
    else:
        hypso_df["Elevación normalizada (h/H)"] = 0.0
    return hypso_df

# ==========================================================
# Clip DEM
# ==========================================================
def clip_dem(watershed_gpkg_path: str, dem_path: str) -> Tuple[bytes | None, dict]:
    """
    Recorta el DEM a la geometría de la cuenca y devuelve
    (bytes_geotiff, stats_dict) o (None, {"clip_error": ...}).
    """
    try:
        import rasterio
        from rasterio.mask import mask
        from rasterio.crs import CRS
        import numpy as np

        if not Path(watershed_gpkg_path).exists():
            return None, {"clip_error": "GPKG no existe"}
        if not Path(dem_path).exists():
            return None, {"clip_error": "DEM no existe"}

        ws = gpd.read_file(watershed_gpkg_path)
        if ws.empty:
            return None, {"clip_error": "Watershed vacía"}

        with rasterio.open(dem_path) as src:
            dem_crs = src.crs or CRS.from_epsg(4326)

            if ws.crs is None:
                ws = ws.set_crs(dem_crs)
            elif ws.crs != dem_crs:
                ws = ws.to_crs(dem_crs)

            geoms = [g for g in ws.geometry if g and not g.is_empty]
            if not geoms:
                return None, {"clip_error": "Geometría inválida"}

            out_arr, out_transform = mask(src, geoms, crop=True)
            band = out_arr[0].astype("float32")
            nodata = src.nodata
            if nodata is not None:
                band[band == nodata] = float("nan")

            valid = band[~pd.isna(band)]
            stats = {
                "width": band.shape[1],
                "height": band.shape[0],
                "pixels_valid": int(valid.size),
                "pixels_total": int(band.size),
                "nodata": nodata,
                "min": float(valid.min()) if valid.size else None,
                "max": float(valid.max()) if valid.size else None,
                "mean": float(valid.mean()) if valid.size else None,
                "std": float(valid.std()) if valid.size else None,
                "crs": str(dem_crs),
                "transform_a": out_transform.a,
                "transform_b": out_transform.b,
                "transform_c": out_transform.c,
                "transform_d": out_transform.d,
                "transform_e": out_transform.e,
                "transform_f": out_transform.f,
                "res_x": abs(out_transform.a),
                "res_y": abs(out_transform.e)
            }

            # Guardar clip en memoria
            mem = io.BytesIO()
            profile = src.profile.copy()
            profile.update({
                "height": band.shape[0],
                "width": band.shape[1],
                "transform": out_transform,
                "driver": "GTiff"
            })
            if nodata is not None:
                profile["nodata"] = nodata
            with rasterio.open(mem, "w", **profile) as dst:
                dst.write(out_arr)
            mem.seek(0)

            # Área si CRS proyectado
            try:
                if dem_crs and not dem_crs.is_geographic:
                    pixel_area = abs(out_transform.a) * abs(out_transform.e)
                    stats["pixel_area_m2"] = pixel_area
                    stats["area_clip_km2"] = (pixel_area * stats["pixels_valid"]) / 1e6
            except Exception:
                pass

            return mem.getvalue(), stats
    except Exception as e:
        return None, {"clip_error": str(e)}

# ==========================================================
# Excel principal
# ==========================================================
def build_excel_bytes(
    morpho_dict: dict | None,
    morpho_df: pd.DataFrame | None,
    tc_df: pd.DataFrame | None,
    hypso_df: pd.DataFrame | None,
    watershed_gpkg_path: str | None,
    dem_path: str | None,
    include_wkt: bool = True,
    wkt_trunc: int = 30000,
    embed_dem_clip: bool = True,
    embed_dem_base64: bool = True,
    base64_chunk_len: int = 30000,
    add_hypso_chart: bool = True,
    add_tc_chart: bool = True,
    add_hypso_image: bool = False,  # (gancho futuro)
    add_tc_image: bool = False      # (gancho futuro)
) -> bytes:
    """
    Genera un Excel con:
      - Parametros
      - Tiempos_Concentracion (+ chart)
      - Curva_Hipsometrica (+ chart + columna normalizada)
      - Geometria_Metadatos
      - DEM_Clip (+ DEM_Clip_B64 opcional)
    """
    engine = _pick_excel_engine()
    if engine is None:
        raise RuntimeError("Instala 'xlsxwriter' o 'openpyxl' para generar Excel.")

    # Clip DEM
    dem_clip_bytes, dem_clip_stats = (None, {})
    if embed_dem_clip and watershed_gpkg_path and dem_path:
        dem_clip_bytes, dem_clip_stats = clip_dem(watershed_gpkg_path, dem_path)

    # Normalizar tiempos y asegurar normalización hipso
    tc_df_norm = _normalize_tc_df(tc_df)
    hypso_df = _ensure_hypso_normalized(hypso_df)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine=engine) as writer:

        # Parámetros
        if morpho_df is not None and not morpho_df.empty:
            dfp = morpho_df.copy()
            if dfp.shape[1] == 2 and list(dfp.columns) != ["Parámetro", "Valor"]:
                dfp.columns = ["Parámetro", "Valor"]
            dfp.sort_values(dfp.columns[0]).to_excel(writer, "Parametros", index=False)
        elif morpho_dict:
            pd.DataFrame(
                {"Parámetro": list(morpho_dict.keys()), "Valor": list(morpho_dict.values())}
            ).sort_values("Parámetro").to_excel(writer, "Parametros", index=False)

        # Tiempos de Concentración
        have_tc = tc_df_norm is not None and not tc_df_norm.empty
        if have_tc:
            tc_df_norm.to_excel(writer, "Tiempos_Concentracion", index=False)

        # Curva Hipsométrica
        have_hypso = hypso_df is not None and not hypso_df.empty
        if have_hypso:
            hypso_df.to_excel(writer, "Curva_Hipsometrica", index=False)

        # Geometría / Metadatos
        meta_rows = []
        if watershed_gpkg_path and Path(watershed_gpkg_path).exists():
            try:
                ws = gpd.read_file(watershed_gpkg_path)
                ws4326 = ws.to_crs(4326)
                geom_union = ws4326.geometry.unary_union
                centroid = geom_union.centroid
                area_km2 = ws.to_crs(3857).area.sum() / 1e6
                wkt_val = geom_union.wkt if include_wkt else ""
                if wkt_trunc and len(wkt_val) > wkt_trunc:
                    wkt_val = wkt_val[:wkt_trunc] + "...(trunc)"
                meta_rows.append({
                    "gpkg": Path(watershed_gpkg_path).name,
                    "features": len(ws),
                    "centroid_lat": centroid.y,
                    "centroid_lon": centroid.x,
                    "area_km2_geom": area_km2,
                    "wkt": wkt_val
                })
            except Exception as e:
                meta_rows.append({"gpkg_error": str(e)})
        if dem_path and Path(dem_path).exists():
            if not meta_rows:
                meta_rows.append({})
            meta_rows[0]["dem_file"] = Path(dem_path).name
        if meta_rows:
            pd.DataFrame(meta_rows).to_excel(writer, "Geometria_Metadatos", index=False)

        # DEM Clip
        if embed_dem_clip and (dem_clip_bytes or dem_clip_stats):
            rename_map = {
                "transform_c": "origin_x",
                "transform_f": "origin_y",
                "transform_a": "pixel_width",
                "transform_e": "pixel_height",
                "transform_b": "rotation_x",
                "transform_d": "rotation_y"
            }
            stats_row = {rename_map.get(k, k): v for k, v in dem_clip_stats.items()}
            if dem_clip_bytes:
                stats_row["clip_bytes"] = len(dem_clip_bytes)
            pd.DataFrame([stats_row]).to_excel(writer, "DEM_Clip", index=False)

            if dem_clip_bytes and embed_dem_base64:
                b64 = base64.b64encode(dem_clip_bytes).decode("ascii")
                if engine == "xlsxwriter":
                    ws = writer.book.add_worksheet("DEM_Clip_B64")
                    ws.write_row(0, 0, ["Descripcion", "Valor"])
                    ws.write(1, 0, "total_length"); ws.write(1, 1, len(b64))
                    ws.write(2, 0, "chunk_len");    ws.write(2, 1, base64_chunk_len)
                    n_chunks = math.ceil(len(b64) / base64_chunk_len)
                    ws.write(3, 0, "num_chunks");   ws.write(3, 1, n_chunks)
                    ws.write_row(5, 0, ["chunk_index", "b64_data"])
                    r = 6
                    for i in range(n_chunks):
                        part = b64[i*base64_chunk_len:(i+1)*base64_chunk_len]
                        ws.write(r, 0, i)
                        ws.write(r, 1, part)
                        r += 1
                else:
                    max_len = 30000
                    trunc = b64[:max_len] + ("...(trunc)" if len(b64) > max_len else "")
                    pd.DataFrame([{
                        "b64_truncated": trunc,
                        "full_length": len(b64)
                    }]).to_excel(writer, "DEM_Clip_B64", index=False)

        # --------------------------------------------------
        # Charts (solo xlsxwriter)
        # --------------------------------------------------
        if engine == "xlsxwriter":
            # Curva hipsométrica
            if have_hypso and add_hypso_chart:
                sheet = writer.sheets["Curva_Hipsometrica"]
                cols = hypso_df.columns.tolist()
                x_candidates = [
                    "Área Acumulada desde Abajo (%)",
                    "Área Acumulada desde Arriba (%)",
                    "Área Acumulada (%)"
                ]
                y_candidates = [
                    "Altura Media de Clase (m)",
                    "Altura media de clase (m)",
                    "Altura Media"
                ]

                def find_idx(cands):
                    for c in cands:
                        if c in cols:
                            return cols.index(c)
                    return None

                x_idx = find_idx(x_candidates)
                y_idx = find_idx(y_candidates)
                if x_idx is not None and y_idx is not None:
                    n = len(hypso_df)
                    chart = writer.book.add_chart({"type": "line"})
                    chart.add_series({
                        "name": "Curva",
                        "categories": ["Curva_Hipsometrica", 1, x_idx, n, x_idx],
                        "values": ["Curva_Hipsometrica", 1, y_idx, n, y_idx],
                        "line": {"color": "#1f77b4", "width": 1.75}
                    })
                    # Serie normalizada
                    norm_col = next((c for c in cols if "normalizada" in c.lower() or "h/h" in c.lower()), None)
                    if norm_col:
                        ni = cols.index(norm_col)
                        chart.add_series({
                            "name": "h/H",
                            "categories": ["Curva_Hipsometrica", 1, x_idx, n, x_idx],
                            "values": ["Curva_Hipsometrica", 1, ni, n, ni],
                            "line": {"color": "#333333", "dash_type": "dash"}
                        })
                    chart.set_title({"name": "Curva Hipsométrica"})
                    chart.set_x_axis({"name": cols[x_idx]})
                    chart.set_y_axis({"name": cols[y_idx]})
                    chart.set_legend({"position": "bottom"})
                    insert_col = max(len(cols) + 1, 8)
                    sheet.insert_chart(1, insert_col, chart)

            # Tiempos de concentración
            if have_tc and add_tc_chart:
                sheet = writer.sheets["Tiempos_Concentracion"]
                # Buscamos columnas exactamente normalizadas
                if list(tc_df_norm.columns[:2]) == ["Método", "Tiempo (min)"]:
                    n = len(tc_df_norm)
                    chart = writer.book.add_chart({"type": "column"})
                    chart.add_series({
                        "name": "Tiempo de Concentración",
                        "categories": ["Tiempos_Concentracion", 1, 0, n, 0],
                        "values": ["Tiempos_Concentracion", 1, 1, n, 1],
                        "data_labels": {"value": True}
                    })
                    chart.set_title({"name": "Tiempos de Concentración"})
                    chart.set_x_axis({"name": "Método", "num_font": {"rotation": -45}})
                    chart.set_y_axis({"name": "Tiempo (min)"})
                    chart.set_legend({"position": "none"})
                    sheet.insert_chart(1, 3, chart)

    output.seek(0)
    return output.getvalue()

# ==========================================================
# Shapefile ZIP
# ==========================================================
def build_watershed_shapefile_zip(gpkg_path: str, layers: Optional[List[str]] = None) -> bytes:
    import tempfile
    if not gpkg_path or not Path(gpkg_path).exists():
        raise FileNotFoundError("GeoPackage no encontrado.")

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:

        def _write_one(gdf: gpd.GeoDataFrame, base: str, tmpdir: Path):
            shp = tmpdir / f"{base}.shp"
            gdf.to_file(shp)
            for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
                fe = shp.with_suffix(ext)
                if fe.exists():
                    zf.write(fe, arcname=f"{base}{ext}")

        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            if layers:
                for lyr in layers:
                    try:
                        gdf = gpd.read_file(gpkg_path, layer=lyr)
                        _write_one(gdf, lyr, tdp)
                    except Exception:
                        pass
            else:
                gdf = gpd.read_file(gpkg_path)
                _write_one(gdf, "watershed", tdp)

    mem_zip.seek(0)
    return mem_zip.getvalue()

# ==========================================================
# DEM (descarga directa o empaquetado FLT+HDR)
# ==========================================================
def package_dem_if_needed(dem_path: str) -> tuple[bytes, str]:
    p = Path(dem_path)
    if not p.exists():
        raise FileNotFoundError("DEM no encontrado.")
    if p.suffix.lower() == ".flt":
        hdr = p.with_suffix(".hdr")
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(p, arcname=p.name)
            if hdr.exists():
                zf.write(hdr, arcname=hdr.name)
        mem.seek(0)
        return mem.getvalue(), f"{p.stem}.zip"
    return p.read_bytes(), p.name
