import streamlit as st
import geopandas as gpd

def render():
    st.title("📋 Análisis morfométrico")
    gpkg_path = st.session_state.get("gpkg_path")
    if not gpkg_path:
        st.info("⚠️ Delimita una cuenca primero.")
        return
    morpho = st.session_state.get("morpho", {})
    lat = st.session_state.get("lat", "—")
    lon = st.session_state.get("lon", "—")

    # Intentar determinar municipios desde cuenca y shapefile
    municipios = "—"
    try:
        if "geojson" in st.session_state:
            cuenca = gpd.read_file(st.session_state["geojson"])

            gdf_mpios = gpd.read_file("data/shp/municipios/MGN_ADM_MPIO_GRAFICO.shp")
            gdf_mpios = gdf_mpios.to_crs(cuenca.crs)

            joined = gpd.sjoin(gdf_mpios, cuenca, predicate="intersects")

            municipio_field = "mpio_cnmbr"
            municipios_nombres = list(joined[municipio_field].unique())
            municipios_nombres = sorted(set(filter(lambda x: isinstance(x, str) and x.strip() != "", municipios_nombres)))

            if len(municipios_nombres) == 1:
                municipios = municipios_nombres[0]
            elif len(municipios_nombres) == 2:
                municipios = f"{municipios_nombres[0]} y {municipios_nombres[1]}"
            elif len(municipios_nombres) > 2:
                municipios = ", ".join(municipios_nombres[:2]) + f" y {municipios_nombres[2]}"

    except Exception as e:
        municipios = "—"

    # Morfometría básica
    area = morpho.get("Área de la cuenca (km²)", "—")
    clasif = morpho.get("Clasificación por área", "—")
    tipo_cuenca = morpho.get("Tipo de cuenca", "—")
    forma_cuenca = morpho.get("Forma de la cuenca", "—")
    alt_min = morpho.get("Cota mínima (msnm)", "—")
    alt_max = morpho.get("Cota máxima (msnm)", "—")

    estaciones = st.session_state.get("estaciones_filtradas", [])

    st.markdown(f"""
    Esta cuenca se delimitó a partir del punto de desfogue ingresado en las coordenadas **Latitud: {lat}**, **Longitud: {lon}** bajo el sistema de referencia espacial WGS 84.

    La cuenca abarca los municipios de **{municipios}**, tiene un área total de aproximadamente **{area} km²**, lo que permite clasificarla según su tamaño como una cuenca **{clasif.lower()}**.

    Desde el punto de vista morfométrico, puede considerarse una cuenca de tipo **{tipo_cuenca}**, con una forma **{forma_cuenca.lower()}**, que influye directamente en sus características de escorrentía y respuesta hidrológica.

    El relieve de la cuenca presenta un rango altitudinal que va desde los **{alt_min} msnm** hasta los **{alt_max} msnm**, lo cual influye en la dinámica del escurrimiento superficial, el tiempo de concentración y los procesos de erosión dentro de la cuenca.

    En un radio de 15 km desde el punto de desfogue, se identificaron **{len(estaciones)} estaciones** registradas por el IDEAM, la cuales son:
    """)

    def get_value_any_case(d, *keys):
        for key in keys:
            if key in d:
                return d[key]
        return "—"

    if estaciones:
        for est in estaciones:
            nombre = get_value_any_case(est, "NOMBRE", "Nombre", "nombre")
            st.markdown(f"- {nombre}")
    else:
        st.info("No se encontraron estaciones cercanas registradas por el IDEAM.")

    st.markdown("""
    Para consultar más detalles sobre estas estaciones y descargar sus datos, puedes ingresar al siguiente enlace del visor del IDEAM:

    👉 [http://dhime.ideam.gov.co/atencionciudadano/](http://dhime.ideam.gov.co/atencionciudadano/)
    """)
