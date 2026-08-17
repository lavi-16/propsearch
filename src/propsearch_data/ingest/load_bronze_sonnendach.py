"""
Load the Sonnendach pull into `bronze.sonnendach`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_sonnendach.py for why the source is the federal BGDI bulk
GeoPackage rather than the api3.geo.admin.ch REST route, and why the join
key is GWR_EGID rather than the spec's assumed building_id.

COLUMN NAMES ARE LOWER-CASED HERE, the same one deliberate exception to
"no renaming" that load_bronze_gwr makes. The SOLKAT GeoPackage stores its
columns UPPER-CASE (GWR_EGID, DF_UID, KLASSE, FLAECHE, ...); GDAL preserves
that case on read, so without lower-casing every downstream query would
have to spell "GWR_EGID". Nothing else is touched -- KLASSE stays the 1-5
ordinal, the modelled yields stay as delivered.

GWR_EGID ARRIVES AS FLOATING POINT. It is int32 in the source, but 6.3% of
pilot roof planes have no register link, and a nullable integer column is
rendered by GDAL/pandas as float64 with NaN. So `gwr_egid` lands as double
precision with NULLs, the same class of GDAL-rendering caveat as `lwz`
landing double. Silver casts it back to the text E-GID form to join
bronze.gwr_gebaeude.egid -- do NOT read the float straight, `2337457.0`
will not match the text `'2337457'`.

GRAIN WARNING FOR SILVER: DF_UID is the roof-plane key, one level BELOW the
building (EGID), which is itself below the parcel (E-GRID). ~3 planes per
building, up to 29 buildings per parcel, so this table fans out twice over
a naive parcel join. Aggregate to EGID first (max KLASSE, sum FLAECHE /
STROMERTRAG), or keep it a separate fact.

VALIDITY WARNING FOR SILVER: 69 of the pilot geometries are invalid
(self-intersections), landed as-is. ST_MakeValid before any area or
overlay arithmetic, exactly as silver.hazard_zone does for Gefahrenkarte.
"""

import geopandas as gpd

from propsearch_data import bronze
from propsearch_data.ingest import bgdi
from propsearch_data.ingest.discover_sonnendach import COLLECTION, OUTPUT_FILE, ZIP_FILE

SOURCE_URL = f"{bgdi.STAC}/collections/{COLLECTION}"
SOURCE_FILE = ZIP_FILE.name


def lower_columns(gdf):
    """Lower-case the column names -- see the module docstring."""
    return gdf.rename(columns={c: c.lower() for c in gdf.columns})


def read_sonnendach() -> gpd.GeoDataFrame:
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"{OUTPUT_FILE} missing -- run discover_sonnendach.py first"
        )
    gdf = gpd.read_file(OUTPUT_FILE)
    print(f"  read {len(gdf):>6,} from {OUTPUT_FILE.name}")
    gdf = lower_columns(gdf)
    return bronze.tag_provenance(gdf, "SOLKAT_CH_DACH", SOURCE_URL, SOURCE_FILE)


if __name__ == "__main__":
    print("Reading Sonnendach pull from data/bronze/ ...\n")

    sonnendach = read_sonnendach()

    print(
        f"\n  loading {len(sonnendach):,} roof planes into "
        f"{bronze.SCHEMA}.sonnendach ..."
    )
    bronze.load(sonnendach, "sonnendach", index_columns=["gwr_egid", "df_uid"])
    bronze.summarise("sonnendach", group_by="klasse")
    print()
