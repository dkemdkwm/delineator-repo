import os
import csv
from pathlib import Path
import fiona
import geopandas as gpd
from delineator import delineate_point

# --- Load first pour point from CSV ---
csv_path = "src/delineator/outlets_colombia.csv"

if not Path(csv_path).exists():
    print(f"❌ ERROR: File not found: {csv_path}")
    exit(1)

with open(csv_path, newline="") as f:
    reader = csv.DictReader(f)
    first_row = next(reader)
    lat = float(first_row["lat"])
    lon = float(first_row["lng"])
    wid = first_row["id"]
    area = float(first_row["area"]) if "area" in first_row and first_row["area"] else None

print(f"📌 Using first pour point from {csv_path}")
print(f"🧭 ID: {wid} | lat: {lat} | lon: {lon} | area: {area}")

# --- Run delineation ---
print("\n🔁 Running delineate_point()...")
delineate_point(lat, lon, wid, area)

# --- Use fixed known path ---
gpkg_path = Path("output/custom.gpkg")

print(f"\n📍 Using expected output path: {gpkg_path}")
exists = gpkg_path.exists()
print(f"✅ Exists? {exists}")

print("\n📁 Contents of 'output/' directory:")
os.system("ls -lh output")

# --- Check if delineator reported 0 basins ---
output_csv = Path("output/OUTPUT.csv")
if output_csv.exists():
    with open(output_csv, "r") as f:
        content = f.read()
        if "0 basin" in content.lower():
            print("\n🚨 WARNING: No watershed was found for this point. Try another location.")
        else:
            print("\n✅ OUTPUT.csv indicates a valid delineation.")
else:
    print("\n⚠️ WARNING: output/OUTPUT.csv was not found. Something went wrong during delineation.")

# --- Check if .gpkg file was created ---
if not exists:
    print(f"\n❌ ERROR: File not found at {gpkg_path}")
    exit(1)

# --- List layers inside the GPKG ---
try:
    layers = fiona.listlayers(gpkg_path)
    print(f"\n📄 Layers inside {gpkg_path}:")
    for layer in layers:
        print(f" - {layer}")

    # --- Check for expected optional layers ---
    expected_layers = ["streams", "snap_point", "pour_point"]
    missing_layers = [l for l in expected_layers if l not in layers]
    if missing_layers:
        print(f"\n⚠️ Missing expected layers: {', '.join(missing_layers)}")
    else:
        print("\n✅ All expected layers are present.")

except Exception as e:
    print(f"\n❌ ERROR reading layers: {e}")

# --- Preview first layer content ---
try:
    gdf = gpd.read_file(gpkg_path)
    print(f"\n✅ First layer loaded successfully. Rows: {len(gdf)}")
    print(gdf.head())
    print("\n🧾 Geometry types in layer:")
    print(gdf.geom_type.value_counts())
except Exception as e:
    print(f"\n❌ ERROR loading GPKG content: {e}")
