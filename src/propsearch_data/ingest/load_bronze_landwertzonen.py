"""
Load the Landwertzonen WFS pull into `bronze.landwertzonen`.

See propsearch_data.bronze for the bronze contract this follows.

All three feature types share one column set, so they land in one table
discriminated by `_source_layer` rather than three near-identical tables.
`gs_egris_egrid` is unique across the whole combined table -- the three
layers partition the parcel space with no overlap -- so there is exactly
one land-value row per parcel.
"""

from pathlib import Path

import geopandas as gpd

from propsearch_data import bronze
from propsearch_data.ingest.discover_landwertzonen import (
    OUTPUT_DIR,
    PILOT_BFS,
    SERVICE_URL,
    TYPENAMES,
)

TABLE = "landwertzonen"


def _source_files() -> list[tuple[str, Path]]:
    return [
        (t, OUTPUT_DIR / f"{t.split(':')[-1].lower()}_pilot.gpkg") for t in TYPENAMES
    ]


def read_pull() -> gpd.GeoDataFrame:
    frames = []
    for typename, path in _source_files():
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing -- run discover_landwertzonen.py first"
            )
        gdf = gpd.read_file(path)
        frames.append(bronze.tag_provenance(gdf, typename, SERVICE_URL, path.name))
        print(f"  read {len(gdf):>5} from {path.name}")
    return bronze.combine(frames)


if __name__ == "__main__":
    print("Reading WFS pull from data/bronze/ ...")
    gdf = read_pull()

    print(f"\nLoading {len(gdf)} rows into {bronze.SCHEMA}.{TABLE} ...")
    bronze.load(gdf, TABLE, index_columns=["gs_egris_egrid", "gemcode"])

    bronze.summarise(
        TABLE,
        group_by="gemcode",
        label_map={v: k for k, v in PILOT_BFS.items()},
    )
