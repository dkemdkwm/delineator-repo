import streamlit as st
import pandas as pd
import numpy as np

def render():
    st.title("⏱️ Estimación de Tiempos de Concentración")

    morpho = st.session_state.get("morpho")
    if not morpho:
        st.warning("❗ Primero delimita una cuenca para calcular los parámetros morfométricos.")
        return

    # Claves posibles de longitud principal
    length_keys = [
        "Longitud del cauce principal (km)",
        "Longitud CP (km)",
        "Longitud CP_L (km)"  # fallback extremo
    ]
    length_km = next((morpho.get(k) for k in length_keys if morpho.get(k) not in (None, np.nan)), None)

    area = morpho.get("Área de la cuenca (km²)")
    slope_percent = morpho.get("Pendiente media (%)")
    height_diff = morpho.get("Diferencia altitudinal (m)")

    warnings = []

    # Fallback para slope si falta pero tenemos delta_h y longitud
    if (slope_percent is None or np.isnan(slope_percent)) and height_diff and length_km and length_km > 0:
        slope_percent = (height_diff / (length_km * 1000)) * 100
        warnings.append("Pendiente derivada de Δh / L (no venía de DEM).")

    if any(x in (None, np.nan) for x in [area, length_km, slope_percent, height_diff]) or height_diff == 0:
        st.error("🚫 Faltan datos válidos (área, longitud, pendiente o Δh).")
        if warnings:
            st.info(" | ".join(warnings))
        return

    # Longitud en pies y pendiente en fracción
    length_ft = length_km * 1000 * 3.28084
    slope_m_per_m = slope_percent / 100.0
    if slope_m_per_m <= 0:
        st.error("🚫 Pendiente no positiva: no se pueden calcular algunas fórmulas.")
        return

    try:
        giandotti = (4 * np.sqrt(area) + 1.5 * length_km) / (0.8 * np.sqrt(height_diff))
        bransby_williams = (14.6 * length_km * area ** -0.1 * slope_m_per_m ** -0.2) / 60
        california = ((0.87075 * (length_km ** 3)) / height_diff) ** 0.385
        clark = 0.335 * ((area / (slope_m_per_m ** 0.5)) ** 0.593)
        passini = (0.108 * ((area * length_km) ** (1/3))) / (slope_m_per_m ** 0.5)
        pilgrim_mcdermott = 0.76 * area ** 0.38
        valencia_zuluaga = 1.7694 * area ** 0.325 * length_km ** -0.096 * slope_percent ** -0.29
        kirpich = ((0.0078 * length_ft ** 0.77) * slope_m_per_m ** -0.385) / 60
        temez = 0.3 * ((length_km / (slope_m_per_m ** 0.25)) ** 0.76)
    except Exception as e:
        st.error(f"❌ Error en el cálculo: {e}")
        return

    results = pd.DataFrame([{
        "Giandotti": giandotti,
        "Bransby-Williams": bransby_williams,
        "California Culvert Practice": california,
        "Clark": clark,
        "Passini": passini,
        "Pilgrim-McDermott": pilgrim_mcdermott,
        "Valencia-Zuluaga": valencia_zuluaga,
        "Kirpich": kirpich,
        "Temez": temez
    }])
    st.session_state["tc_results"] = results
    st.subheader("Resultados de Tiempo de Concentración (min)")
    st.dataframe(results.style.format("{:.2f}"))

    if warnings:
        st.info("⚠️ " + " | ".join(warnings))

    st.download_button(
        "📥 Descargar resultados CSV",
        data=results.to_csv(index=False).encode("utf-8"),
        file_name="tiempos_concentracion.csv",
        mime="text/csv"
    )
