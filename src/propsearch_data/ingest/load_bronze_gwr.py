"""
Load the GWR pull into `bronze.gwr_gebaeude`, `bronze.gwr_eingang` and
`bronze.gwr_kodes`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_gwr.py for why the source is the federal MADD download rather
than data.tg.ch or the Kanton TG WFS.

THREE TABLES, NOT ONE. GWR is a three-level model and the levels have
genuinely different grains -- building (EGID), entrance (EGID, EDID),
plus a shared code lookup. Same reasoning as the four gemeinde_* tables:
stacking different grains gives a mostly-null table and loses the grain.
The dwelling level (EGID, EWID) is deliberately not landed yet; nothing
currently open needs per-dwelling area or room counts.

COLUMN NAMES ARE LOWER-CASED HERE. This is the one deliberate exception
to the contract's "no renaming", and it is mechanical rather than
semantic: GDAL lower-cases on read, so every existing bronze table is
lower-case, while the MADD CSVs are UPPER-CASE. Left alone, to_sql would
create quoted upper-case identifiers and every downstream query would
have to spell `"EGID"`. Lower-casing keeps one convention across the
schema. Nothing else about the values is touched -- GKAT stays 1020,
GSTAT stays 1004, and the zero-padded, slash-bearing parcel numbers stay
strings.

CODES STAY RAW. `bronze.gwr_kodes` carries the source's own lookup (405
rows, keyed on the code plus the attribute it belongs to), so silver can
decode 1020 -> "Gebäude ausschliesslich für Wohnnutzung" from the
publisher's table instead of a hand-built mapping. That is the
gn_kantname precedent: where the source publishes its own classification,
use it.

JOINS TO A PARCEL BY ATTRIBUTE, not spatially. `egrid` is the same
federal parcel ID as bronze.landwertzonen.gs_egris_egrid -- 92.2% of
pilot buildings join straight to silver.parcel. The Point geometry is
built from GKODE/GKODN and is there for mapping and for the buildings
with no EGRID, not because the join needs it.

GRAIN WARNING FOR SILVER: EGID sits one level BELOW the parcel. 2,435
pilot parcels carry more than one building (max 29), so joining this
table to the 9,879-row parcel spine multiplies it. Aggregate first, or
keep it as a separate fact.

STATUS WARNING FOR SILVER: bronze keeps every GSTAT -- 10,392 existing
(1004), 700 demolished (1007), 125 projected/approved/under construction.
A demolished building's row looks completely normal; every other column
is populated exactly as it was the day it came down. Presenting one as a
parcel's current state would be a real correctness bug, so silver must
filter or carry the status explicitly rather than ignoring it.
"""

import json

import geopandas as gpd
import pandas as pd

from propsearch_data import bronze
from propsearch_data.ingest import madd
from propsearch_data.ingest.discover_gwr import (
    EINGANG_FILE,
    GEBAEUDE_FILE,
    KODES_FILE,
)

SOURCE_URL = f"{madd.BASE}/tg.zip"
SOURCE_FILE = "madd_tg.zip"


def lower_columns(df):
    """Lower-case the column names -- see the module docstring."""
    return df.rename(columns={c: c.lower() for c in df.columns})


def read_gebaeude() -> gpd.GeoDataFrame:
    if not GEBAEUDE_FILE.exists():
        raise FileNotFoundError(f"{GEBAEUDE_FILE} missing -- run discover_gwr.py first")
    gdf = gpd.read_file(GEBAEUDE_FILE)
    print(f"  read {len(gdf):>6,} from {GEBAEUDE_FILE.name}")
    gdf = lower_columns(gdf)
    return bronze.tag_provenance(
        gdf, madd.FILES["gebaeude"], SOURCE_URL, SOURCE_FILE
    )


def read_json(path, key: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing -- run discover_gwr.py first")
    df = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")), dtype=str)
    print(f"  read {len(df):>6,} from {path.name}")
    df = lower_columns(df)
    return bronze.tag_provenance(df, madd.FILES[key], SOURCE_URL, SOURCE_FILE)


if __name__ == "__main__":
    print("Reading GWR pull from data/bronze/ ...\n")

    gebaeude = read_gebaeude()
    eingang = read_json(EINGANG_FILE, "eingang")
    kodes = read_json(KODES_FILE, "kodes")

    print(f"\n  loading {len(gebaeude):,} buildings into {bronze.SCHEMA}.gwr_gebaeude ...")
    bronze.load(gebaeude, "gwr_gebaeude", index_columns=["egid", "egrid", "ggdenr"])
    bronze.summarise("gwr_gebaeude", group_by="ggdenr")
    bronze.summarise("gwr_gebaeude", group_by="gstat")

    print(f"\n  loading {len(eingang):,} entrances into {bronze.SCHEMA}.gwr_eingang ...")
    bronze.load_table(
        eingang, "gwr_eingang", index_columns=["egid", "strname", "dplz4", "egaid"]
    )
    bronze.summarise_table("gwr_eingang", group_by="dplz4")

    print(f"\n  loading {len(kodes):,} codes into {bronze.SCHEMA}.gwr_kodes ...")
    bronze.load_table(kodes, "gwr_kodes", index_columns=["cmerkm"])
    bronze.summarise_table("gwr_kodes")
    print()
