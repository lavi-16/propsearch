"""
Load the SonBase / BAFU noise pulls into `bronze.laerm_strasse` (road) and
`bronze.laerm_bahn` (rail).

See propsearch_data.bronze for the bronze contract, and discover_laerm.py for
why the road source is a Cloud-Optimized GeoTIFF sampled at building points
while the rail source is a vector cadastre landed as-is.

TWO TABLES, TWO LANDING PHILOSOPHIES -- both deliberate:

  bronze.laerm_strasse  DERIVED. A raster cannot become a table without
    sampling it somewhere, so the two road COGs (day + night) are read at
    each pilot building's coordinate from bronze.gwr_gebaeude, yielding one
    row per building (EGID) with `lr_tag` / `lr_nacht` in dB(A). This is the
    spec's endorsed `laerm_punkte` deviation from "bronze lands the source
    verbatim" -- flagged here rather than hidden. A NODATA (-9999) pixel
    lands as NULL, meaning "outside the modelled noise area", NOT 0 dB; a
    genuine 0.0 reading (a computed "negligible" value) survives as 0.0. The
    two are kept distinct, the hazard_surveyed measured-absence distinction.

  bronze.laerm_bahn     RAW. The BAV rail immission points are landed exactly
    as delivered, at their native facade-point grain (`xtf_id`), like
    Sonnendach roof planes. The building link is spatial and deferred to
    silver: the `EGID` field is present but 0% populated in the pilot.

GSTAT IS NOT FILTERED HERE. All 11,217 pilot buildings are sampled, including
the 700 demolished (GSTAT 1007) and the projected ones -- bronze keeps them,
per the GWR contract; GSTAT filtering is silver's job.

COLUMN NAMES ARE LOWER-CASED for the rail GeoPackage, the same one deliberate
exception load_bronze_gwr / load_bronze_sonnendach make (the GPKG stores
`Lr_day`, `EGID`, `ES_Katalog_de`, ... mixed-case; GDAL preserves that on
read). The road table is assembled here, so its names are lower-case already.
"""

import geopandas as gpd
import numpy as np
import rasterio

from propsearch_data import bronze
from propsearch_data.db import get_engine
from propsearch_data.ingest import bgdi
from propsearch_data.ingest.discover_laerm import (
    RAIL_COLLECTION,
    RAIL_FILE,
    ROAD_COLLECTIONS,
    ROAD_FILE,
    ROAD_NODATA,
)

ROAD_SOURCE_URL = f"{bgdi.STAC}/collections/{ROAD_COLLECTIONS['tag']}"
RAIL_SOURCE_URL = f"{bgdi.STAC}/collections/{RAIL_COLLECTION}"


def lower_columns(gdf):
    """Lower-case the column names -- see the module docstring."""
    return gdf.rename(columns={c: c.lower() for c in gdf.columns})


def sample_road() -> gpd.GeoDataFrame:
    """Sample the two road-noise clips at every pilot building point."""
    for period, path in ROAD_FILE.items():
        if not path.exists():
            raise FileNotFoundError(
                f"{path} missing -- run discover_laerm.py first"
            )

    engine = get_engine()
    with engine.connect() as conn:
        buildings = gpd.read_postgis(
            "SELECT egid, egrid, geometry FROM bronze.gwr_gebaeude "
            "WHERE geometry IS NOT NULL",
            conn,
            geom_col="geometry",
        )
    print(f"  read {len(buildings):>6,} building points from bronze.gwr_gebaeude")

    coords = list(zip(buildings.geometry.x, buildings.geometry.y))
    for period, path in ROAD_FILE.items():
        with rasterio.open(path) as src:
            vals = np.array([v[0] for v in src.sample(coords)], dtype="float64")
        vals[vals == ROAD_NODATA] = np.nan
        buildings[f"lr_{period}"] = vals
        modelled = int(np.isfinite(vals).sum())
        rng = (
            f"{np.nanmin(vals):.1f}..{np.nanmax(vals):.1f}"
            if modelled
            else "n/a"
        )
        print(
            f"  lr_{period}: {modelled:>6,}/{len(buildings):,} in the modelled "
            f"area (rest NULL), dB {rng}"
        )

    return bronze.tag_provenance(
        buildings,
        "ch.bafu.laerm-strassenlaerm_{tag,nacht}",
        ROAD_SOURCE_URL,
        ", ".join(p.name for p in ROAD_FILE.values()),
    )


def read_rail() -> gpd.GeoDataFrame:
    if not RAIL_FILE.exists():
        raise FileNotFoundError(f"{RAIL_FILE} missing -- run discover_laerm.py first")
    gdf = gpd.read_file(RAIL_FILE)
    print(f"  read {len(gdf):>6,} rail points from {RAIL_FILE.name}")
    gdf = lower_columns(gdf)
    return bronze.tag_provenance(
        gdf, "immission_railway_pointofdetermination", RAIL_SOURCE_URL, RAIL_FILE.name
    )


if __name__ == "__main__":
    print("Loading SonBase / Lärm pulls into bronze ...\n")

    print("Road noise (sampled at building points):")
    road = sample_road()
    print(f"\n  loading {len(road):,} buildings into {bronze.SCHEMA}.laerm_strasse ...")
    bronze.load(road, "laerm_strasse", index_columns=["egid", "egrid"])
    bronze.summarise("laerm_strasse")

    print("\nRail noise (raw facade points):")
    rail = read_rail()
    print(f"\n  loading {len(rail):,} points into {bronze.SCHEMA}.laerm_bahn ...")
    bronze.load(rail, "laerm_bahn", index_columns=["xtf_id", "egid"])
    bronze.summarise("laerm_bahn")
    print()
