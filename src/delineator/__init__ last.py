"""
Public helpers for the Streamlit wrapper.
Keeps the original engine untouched while letting Streamlit feed a single point.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

import pandas as pd

from . import _engine, config as cfg          # local modules
from ._engine import validate                 # re-export if you need it


def delineate_point(
    lat: float,
    lon: float,
    wid: str = "custom",
    area: float | None = None,
) -> str:
    """
    Delineate a single watershed and return the path to the output file.
    """
    # ── 1  make a one-row CSV ------------------------------------------------
    tmp_csv = Path(tempfile.mkstemp(suffix=".csv")[1])
    cols    = ["id", "lat", "lng"] + (["area"] if area is not None else [])
    row     = [wid, lat, lon]      + ([area] if area is not None else [])
    pd.DataFrame([row], columns=cols).to_csv(tmp_csv, index=False)

    # ── 2  patch runtime config (do *not* reload cfg) ------------------------
    cfg.OUTLETS_CSV = str(tmp_csv)     # tell engine to use our temp CSV
    cfg.MAKE_MAP    = False            # we draw in Streamlit

    # ── 3  reload engine so it re-reads cfg.OUTLETS_CSV ----------------------
    importlib.reload(_engine)

    # ── 3.1  guarantee globals the engine expects ---------------------------
    _engine.OUTPUT_CSV = (cfg.OUTPUT_EXT.lower() == "csv")

    # engine prints a summary line that references this var even
    # when OUTPUT_CSV is False, so make sure it exists
    if not hasattr(_engine, "output_csv_filename"):
        _engine.output_csv_filename = ""

    # optional: silence banner
    _engine.VERBOSE = False

    # ── 4  run the heavy routine --------------------------------------------
    _engine.delineate()                # writes into cfg.OUTPUT_DIR

    # ── 4.1  console feedback -----------------------------------------------
    out_file = os.path.join(cfg.OUTPUT_DIR, f"{wid}.{cfg.OUTPUT_EXT}")
    try:
        import geopandas as gpd
        gdf = gpd.read_file(out_file)
        area_km2 = (
            gdf["area"].sum()
            if "area" in gdf.columns and gdf["area"].dtype != object
            else "NA"
        )
    except Exception:
        area_km2 = "NA"

    print(f"[delineate_point] ✅ {wid} → {out_file}  (area {area_km2})")

    # ── 5  return full path to the file -------------------------------------
    return out_file
