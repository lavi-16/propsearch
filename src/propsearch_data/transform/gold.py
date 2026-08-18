"""
Build the gold layer from silver.

Runs every .sql file in sql/schema/gold/ in filename order, each in its own
transaction. Numeric prefixes encode the dependency order (gemeinde_year
before the bodenpreis rows that reference it, parcel before parcel_hazard),
so ordering is visible in the directory listing rather than hidden here.

READS SILVER ONLY. Nothing in sql/schema/gold/ mentions bronze. Every
source-fidelity correction -- typing, the 0/0 sentinel, the inverse lwz
index resolved to CHF, ST_MakeValid -- already happened one layer down.
Gold's contribution is a grain guarantee, not another cleanup pass.

WHY PHYSICAL TABLES AND NOT VIEWS. This is NOT silver's reason, and the
distinction matters. Silver is materialised because ST_MakeValid inside a
join predicate defeats the GIST index and exceeded the statement timeout --
a hard performance wall. Gold has no such wall: every join is key-only, with
no spatial predicate anywhere, and would run fine as a view. Gold is
materialised for workflow and testability consistency instead: one build
command, one filename-ordered DDL directory, and PK/FK/CHECK constraints
that only exist on tables. The constraints are the deliverable -- as views,
every grain guarantee would decay back into prose.

Reload semantics are full replace, matching bronze and silver -- every file
starts with DROP TABLE IF EXISTS ... CASCADE.
"""

from pathlib import Path

from sqlalchemy import text

from propsearch_data import bronze
from propsearch_data.db import get_engine

SCHEMA = "gold"
SQL_DIR = Path(__file__).resolve().parents[3] / "sql" / "schema" / "gold"


def sql_files() -> list[Path]:
    files = sorted(SQL_DIR.glob("*.sql"))
    if not files:
        raise FileNotFoundError(f"no .sql files in {SQL_DIR}")
    return files


def build() -> None:
    """Execute every gold DDL file in order."""
    engine = get_engine()
    for path in sql_files():
        statement = path.read_text()
        print(f"  {path.name} ...", end="", flush=True)
        with engine.begin() as conn:
            conn.execute(text(statement))
        print(" ok")


def summarise() -> None:
    """Row counts, plus the distributions where a grain slip would show."""
    bronze.summarise("parcel", schema=SCHEMA, geom_col="geom")
    bronze.summarise("building", schema=SCHEMA, geom_col="geom")
    bronze.summarise_table("parcel_hazard", schema=SCHEMA, group_by="source_layer")
    bronze.summarise_table("gemeinde_year", schema=SCHEMA)
    bronze.summarise_table("gemeinde_bodenpreis", schema=SCHEMA, group_by="zone_category_label")

    engine = get_engine()
    with engine.connect() as conn:
        # gold.parcel must have exactly as many rows as its spine. Four
        # joins went in; if any of them fanned out, it shows here and
        # nowhere else -- no constraint can catch a spine that grew.
        silver_n, gold_n = conn.execute(
            text(
                "SELECT (SELECT count(*) FROM silver.parcel), "
                f"       (SELECT count(*) FROM {SCHEMA}.parcel)"
            )
        ).one()
        verdict = "ok" if silver_n == gold_n else "FAN-OUT"
        print(f"\n  grain: silver.parcel {silver_n} -> gold.parcel {gold_n}  [{verdict}]")

        print("\n  parcel: coverage of each denormalised layer")
        for label, n in conn.execute(
            text(
                "SELECT 'in a Bauzone', count(*) FILTER (WHERE in_bauzone) "
                f"FROM {SCHEMA}.parcel "
                "UNION ALL SELECT 'hazard surveyed', count(*) FILTER (WHERE hazard_surveyed) "
                f"FROM {SCHEMA}.parcel "
                "UNION ALL SELECT 'has EFH price', count(price_efh_chf_m2) "
                f"FROM {SCHEMA}.parcel"
            )
        ):
            print(f"    {label:<18} {n}")

        # Surveyed-and-clear vs never-assessed. The one distinction on this
        # table that a bare NULL would collapse.
        print("\n  parcel: hazard grade, with 'not surveyed' kept distinct")
        for grade, n in conn.execute(
            text(
                "SELECT coalesce(hazard_grade_overall, '(not surveyed)'), count(*) "
                f"FROM {SCHEMA}.parcel GROUP BY 1 ORDER BY 2 DESC"
            )
        ):
            print(f"    {grade:<16} {n}")

        # Ragged by design. A uniform count across years would mean someone
        # inner-joined the series into their 2019-2024 intersection.
        print("\n  gemeinde_year: per-series coverage (NULLs are correct)")
        for row in conn.execute(
            text(
                "SELECT count(*), "
                "       count(steuerfuss_konfessionslos), "
                "       count(selbstfinanzierungsgrad_pct), "
                "       count(einwohner), "
                "       count(pct_65_plus), "
                "       min(jahr), max(jahr) "
                f"FROM {SCHEMA}.gemeinde_year"
            )
        ):
            n, steuer, finanz, bev, alter, y0, y1 = row
            print(f"    rows {n}, years {y0}-{y1}")
            print(f"    steuerfuss {steuer}  finanz {finanz}  einwohner {bev}  shares {alter}")


if __name__ == "__main__":
    print(f"Building {SCHEMA} from silver ...\n")
    build()
    summarise()
    print()
