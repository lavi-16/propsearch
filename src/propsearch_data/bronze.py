"""
Shared bronze-layer load helper.

BRONZE CONTRACT -- deliberately minimal shaping:
  - Source attribute names and types are preserved exactly as the WFS
    returned them. No renaming, no casting, no unit fixes, no dropping of
    columns that look redundant. If a value looks wrong, it stays wrong
    here; correcting it is silver's job.
  - The only additions are provenance columns, prefixed `_`.
  - The only removals are GML transport plumbing, dropped upstream in
    ingest/wfs.py.

Deliberately NOT done here: any gold-shaped modelling. Target schemas
shouldn't be frozen until the remaining pilot sources are landed and can
be checked against each other.

FIDELITY CAVEAT: the WFS XSDs declare most attributes as `string`, but
GDAL's GML reader infers types on read, so bronze lands GDAL-typed rather
than byte-faithful to the XSD. Silver should assert types explicitly
rather than trusting these.

Reload semantics: full replace. These are manual, snapshot-style pulls,
so there is no incremental path to preserve.
"""

from datetime import datetime, timezone

import geopandas as gpd
import pandas as pd
from sqlalchemy import text

from propsearch_data.db import get_engine

SCHEMA = "bronze"
GEOM_COL = "geometry"
SRID = 2056


def tag_provenance(
    df,
    source_layer: str,
    source_url: str,
    source_file: str,
    ingested_at: datetime | None = None,
):
    """Attach provenance columns. Works for DataFrame and GeoDataFrame alike."""
    df = df.copy()
    df["_source_layer"] = source_layer
    df["_source_url"] = source_url
    df["_source_file"] = source_file
    df["_ingested_at"] = ingested_at or datetime.now(timezone.utc)
    return df


def combine(frames: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry=GEOM_COL, crs=frames[0].crs
    )
    if combined.crs is None or combined.crs.to_epsg() != SRID:
        raise ValueError(f"expected EPSG:{SRID}, got {combined.crs}")
    return combined


def load(gdf: gpd.GeoDataFrame, table: str, index_columns: list[str] | None = None):
    """Replace `bronze.<table>` with `gdf` and index the given columns."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    gdf.to_postgis(
        table, engine, schema=SCHEMA, if_exists="replace", index=False, chunksize=2000
    )

    # to_postgis already builds the GIST index on the geometry column
    # (idx_<table>_<geom>), so only attribute indexes are needed here.
    with engine.begin() as conn:
        for col in index_columns or []:
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {table}_{col}_idx "
                    f"ON {SCHEMA}.{table} ({col})"
                )
            )
    return engine


def load_table(
    df: pd.DataFrame,
    table: str,
    index_columns: list[str] | None = None,
    dtype: dict | None = None,
):
    """Replace `bronze.<table>` with a non-spatial DataFrame.

    `dtype` is passed through to to_sql -- used to land raw API documents
    as JSONB rather than text.
    """
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    df.to_sql(
        table,
        engine,
        schema=SCHEMA,
        if_exists="replace",
        index=False,
        chunksize=2000,
        dtype=dtype,
    )

    with engine.begin() as conn:
        for col in index_columns or []:
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS {table}_{col}_idx "
                    f"ON {SCHEMA}.{table} ({col})"
                )
            )
    return engine


def summarise_table(table: str, group_by: str | None = None, label_map: dict | None = None):
    """Row count and optional group breakdown for a non-spatial bronze table."""
    engine = get_engine()
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar()
        print(f"\n{SCHEMA}.{table}: {total} rows")
        if group_by:
            rows = conn.execute(
                text(
                    f"SELECT {group_by}, count(*) FROM {SCHEMA}.{table} "
                    "GROUP BY 1 ORDER BY 1"
                )
            ).all()
            print(
                "  "
                + ", ".join(f"{(label_map or {}).get(k, k)}={n}" for k, n in rows)
            )


def summarise(table: str, group_by: str | None = None, label_map: dict | None = None):
    """Print row count, SRID, geometry types and an optional group breakdown."""
    engine = get_engine()
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar()
        srid = (
            conn.execute(
                text(f"SELECT DISTINCT ST_SRID({GEOM_COL}) FROM {SCHEMA}.{table}")
            )
            .scalars()
            .all()
        )
        nulls = conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {GEOM_COL} IS NULL")
        ).scalar()
        geom_types = conn.execute(
            text(
                f"SELECT GeometryType({GEOM_COL}), count(*) FROM {SCHEMA}.{table} "
                "GROUP BY 1 ORDER BY 1"
            )
        ).all()
        invalid = conn.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.{table} "
                f"WHERE NOT ST_IsValid({GEOM_COL})"
            )
        ).scalar()

        print(f"\n{SCHEMA}.{table}: {total} rows | SRID {srid} | null geom: {nulls}")
        print(
            "  geometry: "
            + ", ".join(f"{t}={n}" for t, n in geom_types)
            + f" | invalid: {invalid}"
        )

        if group_by:
            rows = conn.execute(
                text(
                    f"SELECT {group_by}, count(*) FROM {SCHEMA}.{table} "
                    "GROUP BY 1 ORDER BY 1"
                )
            ).all()
            print(
                "  "
                + ", ".join(
                    f"{(label_map or {}).get(k, k)}={n}" for k, n in rows
                )
            )
