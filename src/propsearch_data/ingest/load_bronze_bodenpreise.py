"""
Load the Thurgauer Bodenpreis-Basisdaten pull into `bronze.bodenpreise`.

See propsearch_data.bronze for the bronze contract this follows, and
discover_bodenpreise.py for the source's grain, sentinels and join caveat.

Non-spatial, so this goes through bronze.load_table (to_sql) rather than
bronze.load (to_postgis).

TYPE NOTE: `bfs_nr_gemeinde` and `bfs_nr_bezirk` arrive as text and stay
text, per the bronze contract -- the spatial tables key on an integer BFS,
so joining across needs an explicit `::int`. `jahr` is an Opendatasoft
`date` field and arrives as a 'YYYY' string; left as-is for the same
reason, consistent with the other data.tg.ch tables.

Values are left exactly as published, including the 40 rows where
minimum = maximum = 0 (a "no data" sentinel, not a price of zero) and the
markt_ja_nein = 'n' rows drawn from fewer than four transactions.
Correcting either is silver's job.
"""

import json

import pandas as pd

from propsearch_data import bronze
from propsearch_data.ingest.discover_bodenpreise import (
    BFS_COLUMN,
    DATASET_ID,
    PILOT_BFS,
    source_path,
)
from propsearch_data.ingest.opendata import BASE

TABLE = "bodenpreise"


def read_pull() -> pd.DataFrame:
    path = source_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing -- run discover_bodenpreise.py first"
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(records)
    print(f"  read {len(df):>5} from {path.name}")
    return bronze.tag_provenance(
        df, DATASET_ID, f"{BASE}/{DATASET_ID}/exports/json", path.name
    )


if __name__ == "__main__":
    print("Reading Bodenpreise pull from data/bronze/ ...\n")
    df = read_pull()

    print(f"  loading {len(df)} rows into {bronze.SCHEMA}.{TABLE} ...")
    bronze.load_table(
        df, TABLE, index_columns=[BFS_COLUMN, "jahr", "bauzone"]
    )

    name_of = {str(v): k for k, v in PILOT_BFS.items()}
    bronze.summarise_table(TABLE, group_by=BFS_COLUMN, label_map=name_of)
    bronze.summarise_table(TABLE, group_by="bauzone")
    print()
