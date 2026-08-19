"""
Load the Energiefoerderprogramm pull (div-energie-2) into
`bronze.gemeinde_energiefoerderung`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_divenergie.py for the source's grain and the "context, not
per-building" caveat.

Non-spatial, so this goes through bronze.load_table (to_sql) rather than
bronze.load (to_postgis).

TYPE NOTE: `bfs_nr_gemeinde` arrives as text and stays text, and `jahr` is an
Opendatasoft `date` field arriving as a 'YYYY' string -- both left as-is per
the bronze contract, consistent with the other data.tg.ch tables. Silver casts.
"""

import json

import pandas as pd

from propsearch_data import bronze
from propsearch_data.ingest.discover_divenergie import (
    BFS_COLUMN,
    DATASET_ID,
    PILOT_BFS,
    source_path,
)
from propsearch_data.ingest.opendata import BASE

TABLE = "gemeinde_energiefoerderung"


def read_pull() -> pd.DataFrame:
    path = source_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing -- run discover_divenergie.py first"
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    print(f"  read {len(df):>5} from {path.name}")
    return bronze.tag_provenance(
        df, DATASET_ID, f"{BASE}/{DATASET_ID}/exports/json", path.name
    )


if __name__ == "__main__":
    print("Reading Energiefoerderprogramm pull from data/bronze/ ...\n")
    df = read_pull()

    print(f"  loading {len(df)} rows into {bronze.SCHEMA}.{TABLE} ...")
    bronze.load_table(df, TABLE, index_columns=[BFS_COLUMN, "jahr"])

    name_of = {str(v): k for k, v in PILOT_BFS.items()}
    bronze.summarise_table(TABLE, group_by=BFS_COLUMN, label_map=name_of)
    print()
