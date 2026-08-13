"""
Load the data.tg.ch Gemeinde series into `bronze.gemeinde_*`.

See propsearch_data.bronze for the bronze contract this follows.

FOUR TABLES, not one. Unlike the three Landwertzonen layers -- which share
a column set and so were folded into one table with a `_source_layer`
discriminator -- these datasets have genuinely different schemas and
different grains (per Gemeinde-year vs. per Gemeinde-year-sex-agegroup).
Stacking them would mean a mostly-null table and a lost grain.

These are non-spatial, so they go through bronze.load_table (to_sql)
rather than bronze.load (to_postgis). They join to the spatial layers on
BFS-Nr: `gemcode` in bronze.landwertzonen, the `t_id` prefix in
bronze.bauzonen.

TYPE NOTE: `bfs_nr_gemeinde` arrives as text and is left as text, per the
bronze contract. The spatial tables key on an integer BFS, so a join
across the two needs an explicit cast -- silver's problem, but don't be
surprised by it.
"""

import json

import pandas as pd

from propsearch_data import bronze
from propsearch_data.ingest.discover_gemeindestats import (
    BFS_COLUMN,
    DATASETS,
    PILOT_BFS,
    source_path,
)
from propsearch_data.ingest.opendata import BASE

TABLE_PREFIX = "gemeinde_"


def read_pull(dataset_id: str, stem: str) -> pd.DataFrame:
    path = source_path(stem)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing -- run discover_gemeindestats.py first"
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    print(f"  read {len(df):>5} from {path.name}")
    return bronze.tag_provenance(
        df, dataset_id, f"{BASE}/{dataset_id}/exports/json", path.name
    )


if __name__ == "__main__":
    print("Reading data.tg.ch pull from data/bronze/ ...\n")
    name_of = {str(v): k for k, v in PILOT_BFS.items()}

    for dataset_id, stem in DATASETS.items():
        df = read_pull(dataset_id, stem)
        table = f"{TABLE_PREFIX}{stem}"

        print(f"  loading {len(df)} rows into {bronze.SCHEMA}.{table} ...")
        bronze.load_table(df, table, index_columns=[BFS_COLUMN, "jahr"])
        bronze.summarise_table(table, group_by=BFS_COLUMN, label_map=name_of)
        print()
