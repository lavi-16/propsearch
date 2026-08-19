"""
Pull the Energiefoerderprogramm Kanton Thurgau -- umgesetzte Projekte in den
Thurgauer Gemeinden -- from data.tg.ch for the pilot Gemeinden.

Dataset `div-energie-2`, published by the Kanton TG. This is the cantonal
energy-subsidy programme, which carries the federal "Gebaeudeprogramm"
measures (Gebaeudehuelle, GEAK): one row per Gemeinde per year, holding a
COUNT of subsidised projects PER MEASURE TYPE (Waermepumpe, Gebaeudehuelle,
GEAK-Sanierung, Solar, ...).

GEMEINDE-LEVEL CONTEXT, NOT PER-BUILDING. This carries no building or parcel
id and is deliberately NOT joined to neoteq.candidate. It is adoption/market
context -- how many heat pumps / envelope renovations were subsidised in a
Gemeinde in a year -- kept as its own reference series. Grain is (BFS-Nr, jahr).

Confirmed against the live portal (2026-08-19):
  - Covers all 5 pilot Gemeinden, jahr 2008-2024 (85 pilot rows).
  - `jahr` is an Opendatasoft date field (arrives 'YYYY'); `bfs_nr_gemeinde`
    is text (the standing data.tg.ch type trap). Every measure column is int
    except `machbarkeitsstudie`, which the portal types as text.
"""

from pathlib import Path

from propsearch_data.ingest import opendata

DATASET_ID = "div-energie-2"

# Confirmed against hoheitsgrenzen WFS ms:Gemeinden_Layer; all Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

BFS_COLUMN = "bfs_nr_gemeinde"

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"


def pilot_where() -> str:
    return opendata.bfs_in(BFS_COLUMN, PILOT_BFS.values())


def source_path() -> Path:
    return OUTPUT_DIR / "divenergie_pilot.json"


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    records = opendata.export(DATASET_ID, pilot_where())
    if not records:
        raise SystemExit(f"[fail] {DATASET_ID}: no records returned")

    out_file = source_path()
    opendata.save_json(records, out_file)

    gemeinden = {r.get("gemeinde_name") for r in records}
    years = sorted({str(r.get("jahr"))[:4] for r in records})
    missing = set(PILOT_BFS) - gemeinden

    print(f"[ok] {DATASET_ID}: {len(records)} records -> {out_file.name}")
    print(f"     jahr {years[0]}-{years[-1]} | {len(gemeinden)}/5 Gemeinden")
    if missing:
        print(f"     [warn] no rows for: {', '.join(sorted(missing))}")
