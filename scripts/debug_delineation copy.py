import geopandas as gpd
import pandas as pd

# Load GeoJSON file
gdf = gpd.read_file("/mnt/data/MGN_MUNICIPIOS_2024.geojson")

# Convert geometries to centroids manually and avoid triggering array interface issues
rows = []

for _, row in gdf.iterrows():
    try:
        municipio_id = row["MUNICIPIO"] if "MUNICIPIO" in row else row["MPIO_CCDGO"]
        municipio_name = row["MPIOCNMBR"]
        departamento_code = row["DPTO_CCDGO"]

        centroid = row.geometry.centroid
        area = row.geometry.area  # still in degrees, approximate

        id_combined = f"{municipio_id}_{departamento_code}"

        rows.append({
            "id": id_combined,
            "lat": centroid.y,
            "lng": centroid.x,
            "name": municipio_name,
            "area": round(area, 2)
        })
    except Exception as e:
        print(f"Skipping row due to error: {e}")

# Save results
df = pd.DataFrame(rows)
output_path = "/mnt/data/colombia_municipios.csv"
df.to_csv(output_path, index=False)

output_path
