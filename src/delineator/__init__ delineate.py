# core/__init__.py
"""
Public helpers for the Streamlit wrapper.
"""

import importlib
import os
import pandas as pd
import tempfile
from pathlib import Path

from . import _engine, config as cfg               # ← local modules
from ._engine import validate                      # re-export if you need it


def delineate_point(
    lat: float,
    lon: float,
    wid: str = "custom",
    area: float | None = None,
) -> str:
    """
    Delineate a watershed for a single map-click.

    Creates a **one-row CSV** with the clicked point, sets
    ``cfg.OUTLETS_CSV`` to that temp file, reloads `_engine`
    so it picks up the new value, runs the heavy routine, and
    returns the path to the generated GeoPackage (or shapefile,
    depending on your ``cfg.OUTPUT_EXT`` setting).

    Parameters
    ----------
    lat, lon : float
        Geographic coordinates in *decimal degrees*.
    wid : str, default ``"custom"``
        Watershed ID – becomes the output filename stem.
    area : float | None, default ``None``
        Known upstream area in km²; leave ``None`` if unknown.

    Returns
    -------
    str
        Absolute path to the output file.
    """
    # ── 1. build a temporary CSV ───────────────────────────────────────────
    tmp_csv = Path(tempfile.mkstemp(suffix=".csv")[1])
    cols    = ["id", "lat", "lng"] + (["area"] if area is not None else [])
    row     = [wid,  lat,  lon]    + ([area] if area is not None else [])
    pd.DataFrame([row], columns=cols).to_csv(tmp_csv, index=False)

    # ── 2. patch the runtime configuration *in-memory* ─────────────────────
    cfg.OUTLETS_CSV = str(tmp_csv)       # tell delineator to use our CSV
    cfg.MAKE_MAP    = False              # we’ll visualise in Streamlit
    # IMPORTANT: do **not** reload(cfg) – that would wipe the change

    # ── 3. reload _engine so it sees the new OUTLETS_CSV ───────────────────
    importlib.reload(_engine)

    # ── 4. run the delineation ─────────────────────────────────────────────
    _engine.delineate()                  # outputs to cfg.OUTPUT_DIR

    # ── 5. return the resulting file path ──────────────────────────────────
    return os.path.join(cfg.OUTPUT_DIR, f"{wid}.{cfg.OUTPUT_EXT}")
