"""
Load the Bauzonen WFS pull into `bronze.bauzonen`.

See propsearch_data.bronze for the bronze contract this follows.

Indexed on `t_id` (the natural key -- `gml_id` is empty on this layer) and
on the geometry, which to_postgis creates. The geometry index is the one
that matters here: unlike Landwertzonen, zoning has no E-GRID and can only
be attached to a parcel spatially.

GEOMETRY FIDELITY CAVEAT: the WFS returns 1,568 Polygon + 41 MultiPolygon,
but the table lands as 1,609 MULTIPOLYGON. The promotion happens in GDAL's
GPKG writer during the data/bronze/ staging step -- a GPKG layer declares a
single geometry type -- so it is already done before this module sees the
data. It is lossless and harmless for spatial joins, but it does mean the
staged file is not geometry-faithful to the WFS. Same family of caveat as
the GDAL type inference described in propsearch_data.bronze: what lands is
GDAL's rendering of the source, not the source verbatim.
"""

from pathlib import Path

import geopandas as gpd

from propsearch_data import bronze
from propsearch_data.ingest.discover_bauzonen import (
    OUTPUT_DIR,
    PILOT_BFS,
    SERVICE_URL,
    TYPENAMES,
)

TABLE = "bauzonen"


def _source_files() -> list[tuple[str, Path]]:
    return [
        (t, OUTPUT_DIR / f"bauzonen_{t.split(':')[-1]}_pilot.gpkg") for t in TYPENAMES
    ]


def read_pull() -> gpd.GeoDataFrame:
    frames = []
    for typename, path in _source_files():
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing -- run discover_bauzonen.py first"
            )
        gdf = gpd.read_file(path)
        frames.append(
            bronze.tag_provenance(gdf, typename, SERVICE_URL, path.name)
        )
        print(f"  read {len(gdf):>5} from {path.name}")
    return bronze.combine(frames)


if __name__ == "__main__":
    print("Reading WFS pull from data/bronze/ ...")
    gdf = read_pull()

    print(f"\nLoading {len(gdf)} rows into {bronze.SCHEMA}.{TABLE} ...")
    bronze.load(gdf, TABLE, index_columns=["t_id"])

    bronze.summarise(
        TABLE,
        group_by="split_part(t_id, '_', 1)",
        label_map={str(v): k for k, v in PILOT_BFS.items()},
    )
