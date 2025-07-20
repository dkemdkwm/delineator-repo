"""
Faster Dissolve All with GeoPandas

For a layer with many polygons, it can be slow to dissolve to get the "outer boundary" or "outer perimeter"
using GeoPandas

I found a method that works a little bit more quickly.

(1) create a new rectangle out of the bounding box around all the features. 
(2) clip the rectangle using the input layer (containing polygons).


input: a geopandas dataframe with multiple polygons.
output: a geopandas dataseries with a single polygon
with no internal rings or "donut holes," which is what I was looking for
with my watershed boundaries. 

"""

import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
gpd.options.use_pygeos = False


def buffer(poly: Polygon) -> Polygon:
    """
    Little trick that works wonders to remove slivers, dangles
    and other weird errors in a shapely polygon. We do a series of
    2 buffers, out and then in, and it magically fixes issues.

    """
    dist = 0.00001
    return poly.buffer(dist, join_style=2).buffer(-dist, join_style=2)


def close_holes(poly: Polygon | MultiPolygon, area_max: float) -> Polygon | MultiPolygon:
    """
    Close polygon holes by removing internal rings ("donut holes") smaller than area_max.
    Supports both Polygon and MultiPolygon geometries.
    """
    def filter_holes(polygon: Polygon) -> Polygon:
        if area_max == 0:
            return Polygon(polygon.exterior)
        else:
            valid_holes = [hole for hole in polygon.interiors if Polygon(hole).area > area_max]
            return Polygon(polygon.exterior, holes=valid_holes)

    if isinstance(poly, Polygon):
        return filter_holes(poly)

    elif isinstance(poly, MultiPolygon):
        return MultiPolygon([filter_holes(p) for p in poly.geoms])

    else:
        return poly  # Return as-is if not a Polygon or MultiPolygon




def dissolve_shp(shp: str) -> gpd.GeoDataFrame:
    """
    input is the path to a shapefile on disk. 
    
    Returns a GeoPandas dataframe containing the dissolved
    geometry
    """
    df = gpd.read_file(shp)
    return dissolve_geopandas(df)


def fill_geopandas(gdf: gpd.GeoDataFrame, area_max: float) -> gpd.GeoDataFrame:
    filled = gdf.geometry.apply(lambda p: close_holes(p, area_max) if p and not p.is_empty else p)
    return filled


def dissolve_geopandas(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    input is a Geopandas dataframe with multiple polygons that you want 
      to merge and dissolve into a single polygon
      
    output is a Geopandas dataframe containing a single polygon

    This method is much faster than using GeoPandas dissolve()

    It creates a box around the polygons, then clips the box to
    that poly. The result is one feature instead of many.
    """
    
    [left, bottom, right, top] = df.total_bounds
    left -= 1
    right += 1
    top += 1
    bottom -= 1

    lat_point_list = [left, right, right, left, left]
    lon_point_list = [top, top, bottom, bottom, top]


    polygon_geom = Polygon(zip(lat_point_list, lon_point_list))
    rect = gpd.GeoDataFrame(index=[0], crs=df.crs, geometry=[polygon_geom])
    clipped = gpd.clip(rect, df)
    # This removes some weird artifacts that result from Merit-BASINS having lots
    # of little topology issues.

    clipped = clipped.geometry.apply(lambda p: buffer(p))

    return clipped
    