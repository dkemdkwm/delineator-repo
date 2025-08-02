from pathlib import Path


def render():
    import streamlit as st
    import geopandas as gpd
    import pandas as pd

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

    params = st.session_state["morpho"]

    # Show as styled table
    df = pd.DataFrame({
        "Parámetro": list(params.keys()),
        "Valor": list(params.values())
    })

    st.subheader("📋 Tabla de parámetros calculados")
    st.dataframe(df.style.format(precision=3), use_container_width=True)

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
