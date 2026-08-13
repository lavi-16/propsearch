"""
Pull Gemeinde tax / financial / population series from data.tg.ch for the
pilot Gemeinden.

This is the first NON-SPATIAL source in the pipeline. It joins to the
spatial layers on BFS-Nr, which is `gemcode` in Landwertzonen and the
`t_id` prefix in Bauzonen.

Confirmed against the live portal (2026-08-13) -- all four datasets exist,
carry `bfs_nr_gemeinde` + `gemeinde_name` + `jahr`, and return an equal
row count for each of the five pilot Gemeinden (no Gemeinde missing):

  sk-stat-70  Gesamtsteuerfüsse                     115 rows  2004-2026
  sk-stat-4   Gemeindefinanzkennzahlen               30 rows  2019-2024
  sk-stat-56  Ständige Wohnbevölkerung               95 rows  2007-2025
  sk-stat-58  Wohnbevölkerung nach Geschlecht/Alter 2090 rows 2015-2025

These are TIME SERIES, not current-state snapshots -- every dataset has
one row per Gemeinde per year (sk-stat-58 further split by sex and
five-year age band). Nothing here is deduplicated to a "latest" row; that
is a silver/gold decision, and the history is exactly the signal the spec
says gets thrown away today.

Note the differing coverage windows above: any cross-dataset join by year
will be limited by sk-stat-4 (2019-2024), the narrowest.
"""

from pathlib import Path

from propsearch_data.ingest import opendata

# Confirmed against hoheitsgrenzen WFS ms:Gemeinden_Layer; all Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

BFS_COLUMN = "bfs_nr_gemeinde"

# dataset id -> local file stem / bronze table suffix
DATASETS = {
    "sk-stat-70": "steuerfuss",
    "sk-stat-4": "finanzkennzahlen",
    "sk-stat-56": "bevoelkerung",
    "sk-stat-58": "bevoelkerung_alter",
}

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"


def pilot_where() -> str:
    return opendata.bfs_in(BFS_COLUMN, PILOT_BFS.values())


def source_path(stem: str) -> Path:
    return OUTPUT_DIR / f"gemeindestats_{stem}_pilot.json"


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    where = pilot_where()
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    for dataset_id, stem in DATASETS.items():
        records = opendata.export(dataset_id, where)
        if not records:
            print(f"[warn] {dataset_id}: no records returned\n")
            continue

        out_file = source_path(stem)
        opendata.save_json(records, out_file)

        gemeinden = {r.get("gemeinde_name") for r in records}
        years = sorted({str(r.get("jahr")) for r in records})
        missing = set(PILOT_BFS) - gemeinden
        print(f"[ok] {dataset_id} ({stem}): {len(records)} records -> {out_file.name}")
        print(f"     jahr {years[0]}-{years[-1]} | {len(gemeinden)}/5 Gemeinden")
        if missing:
            print(f"     [warn] no rows for: {', '.join(sorted(missing))}")
        print()
