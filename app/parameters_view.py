from pathlib import Path


def render():
    import streamlit as st
    import geopandas as gpd
    import pandas as pd
    import re, unicodedata

    st.set_page_config(page_title="Parámetros Morfométricos", layout="wide")
    st.title("📊 Visualización de parámetros morfométricos")

    if not (st.session_state.get("gpkg_path") and Path(st.session_state["gpkg_path"]).exists()):
        st.markdown("""
        Aquí podrás visualizar, analizar y comparar parámetros como:
        - Área de la cuenca
        - Longitud del cauce principal
        - Pendiente media
        - Coeficientes de forma y compacidad
        - Índices de bifurcación
        - ¡Y más!
        """)

    if "morpho" not in st.session_state:
        st.info("🔍 Delimita una cuenca para ver sus parámetros.")
        return

    params = st.session_state.get("morpho")
    if not params:   # covers: key missing, None, empty dict
        st.info("🔍 Delimita una cuenca para ver sus parámetros (o fueron omitidos por un error numérico).")
        return

    if isinstance(params, dict):
        df = pd.DataFrame({"Parámetro": list(params.keys()),
                           "Valor": list(params.values())})
    elif isinstance(params, pd.DataFrame):
        df = params.copy()
    else:
        st.warning(f"No se reconoce el formato de parámetros: {type(params)}")
        return


    # ---------------- helpers ----------------
    def _fmt(v):
        try:
            return float(v)
        except Exception:
            return v

    def _norm(s: str) -> str:
        # normaliza acentos, espacios, signos y mayúsculas
        s = unicodedata.normalize("NFKD", str(s))
        s = "".join(ch for ch in s if not unicodedata.combining(ch))
        s = s.lower()
        s = re.sub(r"[\s\-./()%°]+", "_", s)
        s = re.sub(r"__+", "_", s).strip("_")
        return s

    ORDER = {
        "Cuenca": [
            "Área de la cuenca (km²)",
            "Área de la cuenca (ha)",
            "Perímetro de la cuenca (km)",
            "Clasificación por área",
            "Índice de compacidad",
            "Tipo de cuenca",
            "Longitud Cuenca (km)",
            "Factor de forma",
            "Forma de la cuenca",
        ],
        "Cauce principal": [
            "Longitud CP_L (km)",
            "Longitud CP (km)",
            "Factor de sinuosidad",
            "Clasificación de sinuosidad",
        ],
        "Drenajes": [
            "Longitud total de cauces (km)",
            "Densidad de drenajes (km/km²)",
            "Clasificación de densidad",
            "Número de drenajes",
        ],
        "Altura": [
            "Cota mínima (msnm)",
            "Cota máxima (msnm)",
            "Diferencia altitudinal (m)",
            "Pendiente media (°)",
            "Pendiente media (%)",
        ],
    }

    ALIASES = {
        # --- Cuenca ---
        "area_de_la_cuenca_km2": "Área de la cuenca (km²)",
        "area_cuenca_km2": "Área de la cuenca (km²)",
        "area_km2": "Área de la cuenca (km²)",

        "area_de_la_cuenca_ha": "Área de la cuenca (ha)",
        "area_cuenca_ha": "Área de la cuenca (ha)",
        "area_ha": "Área de la cuenca (ha)",

        "perimetro_de_la_cuenca_km": "Perímetro de la cuenca (km)",
        "perimetro_cuenca_km": "Perímetro de la cuenca (km)",
        "perimetro_km": "Perímetro de la cuenca (km)",
        "per_km": "Perímetro de la cuenca (km)",

        "clasificacion_por_area": "Clasificación por área",

        "indice_de_compacidad": "Índice de compacidad",
        "indice_compacidad": "Índice de compacidad",

        "tipo_de_cuenca": "Tipo de cuenca",
        "tipo_cuenca": "Tipo de cuenca",

        "longitud_cuenca_km": "Longitud Cuenca (km)",
        "longitud_de_la_cuenca_km": "Longitud Cuenca (km)",
        "longitud_del_cauce_km": "Longitud Cuenca (km)",
        "longitud_del_cauce": "Longitud Cuenca (km)",
        "longitud_cuenca": "Longitud Cuenca (km)",

        "factor_de_forma": "Factor de forma",
        "factor_forma": "Factor de forma",

        "forma_de_la_cuenca": "Forma de la cuenca",
        "forma_cuenca": "Forma de la cuenca",

        # --- Cauce principal ---
        "longitud_cp_l_km": "Longitud CP_L (km)",
        "longitud_cauce_principal_l_km": "Longitud CP_L (km)",
        "longitud_cauce_principal_l": "Longitud CP_L (km)",
        "longitud_cauce_l_km": "Longitud CP_L (km)",

        "longitud_cp_km": "Longitud CP (km)",
        "longitud_cauce_principal_km": "Longitud CP (km)",
        "longitud_cauce_principal": "Longitud CP (km)",
        "longitud_cp": "Longitud CP (km)",

        "factor_de_sinuosidad": "Factor de sinuosidad",
        "factor_sinuosidad": "Factor de sinuosidad",

        "clasificacion_de_sinuosidad": "Clasificación de sinuosidad",
        "clasificacion_sinuosidad": "Clasificación de sinuosidad",

        # --- Drenajes ---
        "longitud_total_de_cauces_km": "Longitud total de cauces (km)",
        "longitud_total_de_cauces": "Longitud total de cauces (km)",
        "longitud_total_cauces": "Longitud total de cauces (km)",

        "densidad_de_drenajes_km_km2": "Densidad de drenajes (km/km²)",
        "densidad_de_drenajes": "Densidad de drenajes (km/km²)",
        "densidad_drenajes": "Densidad de drenajes (km/km²)",
        "densi_corrientes": "Densidad de drenajes (km/km²)",  # alias legacy

        "clasificacion_de_densidad": "Clasificación de densidad",
        "clasificacion_densidad": "Clasificación de densidad",

        "numero_de_drenajes": "Número de drenajes",
        "numero_drenajes": "Número de drenajes",

        # --- Altura ---
        "cota_minima_msnm": "Cota mínima (msnm)",
        "cota_minima": "Cota mínima (msnm)",
        "cota_min": "Cota mínima (msnm)",

        "cota_maxima_msnm": "Cota máxima (msnm)",
        "cota_maxima": "Cota máxima (msnm)",
        "cota_max": "Cota máxima (msnm)",

        "diferencia_altitudinal_m": "Diferencia altitudinal (m)",
        "diferencia_altitudinal": "Diferencia altitudinal (m)",
        "diferencia_altura": "Diferencia altitudinal (m)",
        "dif_altura": "Diferencia altitudinal (m)",

        "pendiente_media_deg": "Pendiente media (°)",
        "pendiente_media_grados": "Pendiente media (°)",
        "pendiente_grados": "Pendiente media (°)",
        "slope_deg": "Pendiente media (°)",

        "pendiente_media_pct": "Pendiente media (%)",
        "pendiente_porcentaje": "Pendiente media (%)",
        "pendiente_%": "Pendiente media (%)",
        "pendiente_pct": "Pendiente media (%)",
        "slope_pct": "Pendiente media (%)",
    }

    def canonical_key(name: str) -> str:
        n = _norm(name)
        return ALIASES.get(n, n)

    def detect_group(key: str) -> str:
        for g, keys in ORDER.items():
            if key in keys:
                return g
        return "Altura"

    rank = {k: i for keys in ORDER.values() for i, k in enumerate(keys)}

    # ---------------- build dataframe ----------------
    params = st.session_state["morpho"]
    if isinstance(params, dict):
        df = pd.DataFrame({"Parámetro": list(params.keys()),
                           "Valor": [ _fmt(v) for v in params.values() ]})
    elif isinstance(params, pd.DataFrame):
        df = params.copy()
        df["Valor"] = df["Valor"].map(_fmt)
    else:
        st.warning(f"No se reconoce el formato de parámetros: {type(params)}")
        return

    # canonical key + group + order rank
    df["__key"] = df["Parámetro"].map(canonical_key)
    df["__group"] = df["__key"].map(detect_group)
    df["__rank"] = df["__key"].map(lambda k: rank.get(k, 10_000))

    # numeric column for proper sorting in UI
    df["Valor"] = pd.to_numeric(df["Valor"], errors="ignore")

    GROUP_ORDER = ["Cuenca", "Cauce principal", "Drenajes", "Altura", "Otros"]

    # sort by group and our desired rank
    df_sorted = (
        df.sort_values(["__group", "__rank", "Parámetro"], kind="stable")
        .copy()
    )

    # build a single table with header rows per group
    rows = []
    for g in GROUP_ORDER:
        block = df_sorted[df_sorted["__group"] == g][["Parámetro", "Valor"]]
        if block.empty:
            continue
        # label row (separator)
        rows.append({"Parámetro": g, "Valor": "", "__is_label": True})
        # data rows
        for _, r in block.iterrows():
            rows.append({
                "Parámetro": r["Parámetro"],
                "Valor": r["Valor"],
                "__is_label": False
            })

    full_table = pd.DataFrame(rows, columns=["Parámetro", "Valor", "__is_label"])

    mask = full_table["__is_label"].to_numpy()
    styles = pd.DataFrame("", index=full_table.index, columns=["Parámetro", "Valor"])

    style_str = (
        "font-weight:700; background: rgb(120 195 123);"
        "border-top:1px solid #e9e4e4; border-bottom:1px solid #e9e4e4; color: white;"
    )
    styles.loc[mask, ["Parámetro", "Valor"]] = style_str

    visible = full_table.drop(columns="__is_label")

    styled = (
        visible
        .style
        .apply(lambda _: styles, axis=None)
        .hide(axis="index")
        .set_table_styles([
            {"selector": "th.row_heading",       "props": "display:none;"},
            {"selector": "th.blank",             "props": "display:none;"},
            {"selector": "tbody th",             "props": "display:none;"},
        ])
    )

    st.table(styled)


    st.markdown("""
        <style>
        /* Increase font size in the modern Glide-style DataFrame editor */
        div[data-testid="stElementContainer"] {
           font-size: 18px !important;
        }        
        .stDataFrameGlideDataEditor {
            font-size: 18px !important;
        }

        /* Optional: make column headers larger */
        .stDataFrameGlideDataEditor th {
            font-size: 18px !important;
            font-weight: bold !important;
        }

        /* Optional: padding to make rows taller */
        .stDataFrameGlideDataEditor td {
            padding: 12px 10px !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.download_button(
        "📥 Descargar parámetros CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="parametros_morfometricos.csv",
        mime="text/csv"
    )

    st.success("✅ Parámetros actualizados automáticamente.")
