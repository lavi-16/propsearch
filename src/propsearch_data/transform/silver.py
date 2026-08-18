"""
Build the silver layer from bronze.

Runs every .sql file in sql/schema/silver/ in filename order, each in its
own transaction. Numeric prefixes encode the dependency order (dimensions
before facts, spine before the tables that reference it), so ordering is
visible in the directory listing rather than hidden in this module.

WHY SQL FILES AND NOT PANDAS. Bronze loads through geopandas because it is
reading files. Silver is a pure database-to-database transform -- pulling
9,879 parcels and 6,422 hazard polygons into Python only to write them back
would be slower and would lose the constraints. The constraints are the
actual deliverable here: each one makes a documented trap unreachable, and
a violated CHECK fails the build loudly instead of quietly producing a
plausible wrong number. See sql/schema/silver/00_schema.sql for the list.

Reload semantics are full replace, matching bronze -- every file starts
with DROP TABLE IF EXISTS ... CASCADE. These are snapshot pulls with no
incremental path to preserve.
"""

from pathlib import Path

from sqlalchemy import text

from propsearch_data import bronze
from propsearch_data.db import get_engine

SCHEMA = "silver"
SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "schema" / "silver"


def sql_files() -> list[Path]:
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"no .sql files in {SQL_DIR}")
    return files


def build() -> None:
    """Execute every silver DDL file in order."""
    engine = get_engine()
    for path in sql_files():
        statement = path.read_text()
        print(f"  {path.name} ...", end="", flush=True)
        with engine.begin() as conn:
            conn.execute(text(statement))
        print(" ok")


def summarise() -> None:
    """Row counts, plus the distributions that are easy to get wrong."""
    for table in (
        "gemeinde",
        "zone",
        "bodenpreis",
        "gemeinde_steuerfuss",
        "gemeinde_finanzkennzahlen",
        "gemeinde_bevoelkerung",
        "gemeinde_bevoelkerung_alter",
        "oereb_extract_sample",
        "parcel_restriction_sample",
    ):
        bronze.summarise_table(table, schema=SCHEMA)

    bronze.summarise("parcel", schema=SCHEMA, geom_col="geom")
    bronze.summarise("hazard_zone", schema=SCHEMA, geom_col="geom", group_by="source_layer")

    bronze.summarise_table("parcel_zone", schema=SCHEMA)
    bronze.summarise_table("parcel_hazard", schema=SCHEMA, group_by="source_layer")
    bronze.summarise_table(
        "parcel_hazard_synoptic", schema=SCHEMA, group_by="hazard_surveyed"
    )

    # Building layer (a grain below the parcel) and the two facts beneath it.
    bronze.summarise("building", schema=SCHEMA, geom_col="geom", group_by="is_existing")
    bronze.summarise("roof_plane", schema=SCHEMA, geom_col="geom", group_by="klasse")
    bronze.summarise_table("building_solar", schema=SCHEMA)
    bronze.summarise("rail_noise", schema=SCHEMA, geom_col="geom")
    bronze.summarise_table(
        "building_noise", schema=SCHEMA, group_by="road_noise_modelled"
    )

    engine = get_engine()
    with engine.connect() as conn:
        # The two numbers most worth eyeballing after a rebuild, because
        # both encode a distinction that is easy to collapse.
        print("\n  hazard: surveyed-and-clear vs outside the perimeter")
        for grade, n in conn.execute(
            text(
                "SELECT coalesce(gefahrenstufe, '(not surveyed)'), count(*) "
                f"FROM {SCHEMA}.parcel_hazard_synoptic GROUP BY 1 ORDER BY 2 DESC"
            )
        ):
            print(f"    {grade:<16} {n}")

        print("\n  bodenpreise: price presence vs market-based flag")
        for market, priced, n in conn.execute(
            text(
                "SELECT is_market_based, price_min_chf_m2 IS NOT NULL, count(*) "
                f"FROM {SCHEMA}.bodenpreis GROUP BY 1, 2 ORDER BY 1, 2"
            )
        ):
            print(
                f"    is_market_based={str(market):<5} has_price={str(priced):<5} {n}"
            )


if __name__ == "__main__":
    print(f"Building {SCHEMA} from bronze ...\n")
    build()
    summarise()
    print()
