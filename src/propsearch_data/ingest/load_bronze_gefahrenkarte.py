"""
Load the Gefahrenkarte pull into `bronze.gefahrenkarte`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_gefahrenkarte.py for why selection here is spatial rather than
by attribute.

ONE TABLE, THREE LAYERS. `ms:Gefaehrdung_synoptisch`,
`ms:Gefaehrdung_Wasser` and `ms:Gefaehrdung_Rutschungen` share an
identical column set, so they stack with `_source_layer` as the
discriminator -- same treatment as the three Landwertzonen layers.

THE LAYERS OVERLAP BY DESIGN. `_synoptisch` is the combined view across
processes; `_wasser` and `_rutschungen` are the per-process detail
covering much of the same ground. Never aggregate across `_source_layer`
without filtering to one first, or every overlapping area is
double-counted.

Joins to a parcel by point-in-polygon against `bronze.landwertzonen`
(Point per parcel), the same access path as `bronze.bauzonen`.

Verified against the landed data: WITHIN a layer the polygons do not
overlap -- every matched parcel gets exactly one grading per layer
(max = avg = 1.000 for all three). ACROSS layers a parcel gets up to 3
rows, one per layer, averaging 2.97. So filter to a single `_source_layer`
and the join is one-to-one; forget to, and every parcel triplicates.

Coverage is not universal: 9,005 of 9,879 pilot parcels fall inside the
synoptic layer. The layers include explicit `gefahrenstufe = 'keine'`
polygons, so a matched parcel graded "keine" means surveyed-and-clear,
whereas no match at all means outside the surveyed perimeter -- unknown,
not safe. Don't collapse those two into one "no hazard" bucket.

GEOMETRY CAVEAT: 84 of the 6,422 features are invalid (all "Ring
Self-intersection"). They land as-is per the bronze contract -- wrong
values stay wrong here. ST_Intersects tolerates them in practice (the
join above returns sane counts), but silver should run ST_MakeValid
before relying on area or overlay arithmetic.
"""

import geopandas as gpd

from propsearch_data import bronze
from propsearch_data.ingest.discover_gefahrenkarte import (
    BASE,
    LAYERS,
    OUTPUT_FILE,
)

TABLE = "gefahrenkarte"


def read_pull() -> gpd.GeoDataFrame:
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"{OUTPUT_FILE} missing -- run discover_gefahrenkarte.py first"
        )
    gdf = gpd.read_file(OUTPUT_FILE)
    print(f"  read {len(gdf):>5} from {OUTPUT_FILE.name}")

    # `_source_layer` is already set per row by the discover step, so
    # provenance is tagged per layer rather than for the file as a whole.
    slug_of = {tn: slug for slug, tn in LAYERS.items()}
    frames = []
    for typename, part in gdf.groupby("_source_layer", sort=False):
        frames.append(
            bronze.tag_provenance(
                part.drop(columns=["_source_layer"]),
                typename,
                f"{BASE}/{slug_of[typename]}",
                OUTPUT_FILE.name,
            )
        )
    return bronze.combine(frames)


if __name__ == "__main__":
    print("Reading Gefahrenkarte pull from data/bronze/ ...\n")
    gdf = read_pull()

    print(f"  loading {len(gdf)} features into {bronze.SCHEMA}.{TABLE} ...")
    bronze.load(
        gdf, TABLE, index_columns=["gefahrenstufe", "matrixfeld", "_source_layer"]
    )
    bronze.summarise(TABLE, group_by="_source_layer")
    bronze.summarise(TABLE, group_by="gefahrenstufe")
    print()
