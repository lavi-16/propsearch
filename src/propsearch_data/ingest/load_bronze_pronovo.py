"""
Load the BFE/Pronovo plant pull into `bronze.stromproduktion`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_pronovo.py for why the source is the federal BGDI bulk GeoPackage,
why the collection id is ASCII (`elektrizitaetsproduktionsanlagen`), and how
PV is identified (SubCategory = 'subcat_2').

ALL SUBCATEGORIES LAND RAW. Bronze keeps every plant in the pilot window --
hydro, wind, biomass, PV -- per the "no dropping rows" contract; silver
filters to PV (subcat_2). The table name `stromproduktion` reflects that it
is the whole production registry, not a PV-only cut.

COLUMN NAMES ARE LOWER-CASED HERE, the same one deliberate exception to
"no renaming" that load_bronze_gwr / load_bronze_sonnendach make. The
GeoPackage stores mixed/UpperCamelCase columns (XTF_ID as xtf_id already, but
SubCategory, TotalPower, BeginningOfOperation, ...); GDAL preserves that case
on read, so without lower-casing every downstream query would have to quote
"SubCategory". Nothing else is touched -- the coded category values
(subcat_2, maincat_2, plantcat_8) stay raw and are decoded in silver.

NO EGID: the building link is spatial and lives in silver (nearest existing
building within a radius -- the rail-noise precedent). This table is the raw
plant grain (PK xtf_id), the silver.rail_noise analogue.
"""

import geopandas as gpd

from propsearch_data import bronze
from propsearch_data.ingest import bgdi
from propsearch_data.ingest.discover_pronovo import ASSET, COLLECTION, OUTPUT_FILE

SOURCE_URL = f"{bgdi.STAC}/collections/{COLLECTION}"
SOURCE_FILE = ASSET


def lower_columns(gdf):
    """Lower-case the column names -- see the module docstring."""
    return gdf.rename(columns={c: c.lower() for c in gdf.columns})


def read_pronovo() -> gpd.GeoDataFrame:
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"{OUTPUT_FILE} missing -- run discover_pronovo.py first"
        )
    gdf = gpd.read_file(OUTPUT_FILE)
    print(f"  read {len(gdf):>6,} from {OUTPUT_FILE.name}")
    gdf = lower_columns(gdf)
    return bronze.tag_provenance(gdf, "ElectricityProductionPlant", SOURCE_URL, SOURCE_FILE)


if __name__ == "__main__":
    print("Reading Pronovo pull from data/bronze/ ...\n")

    plants = read_pronovo()

    print(
        f"\n  loading {len(plants):,} plants into "
        f"{bronze.SCHEMA}.stromproduktion ..."
    )
    bronze.load(plants, "stromproduktion", index_columns=["xtf_id", "subcategory"])
    bronze.summarise("stromproduktion", group_by="subcategory")
    print()
