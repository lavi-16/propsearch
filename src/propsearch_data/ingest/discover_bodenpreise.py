"""
Pull the Thurgauer Bodenpreis-Basisdaten (TGB) from data.tg.ch for the
pilot Gemeinden.

Dataset `dfs-sv-1`, published by the Steuerverwaltung Kanton Thurgau.
8,294 rows canton-wide, 2012-2024; 520 for the pilot.

CHF/m2 bands for unbuilt, serviced building land (unbebautes und
erschlossenes Bauland), by Gemeinde x Bauzone-category x year.

NOT the parcel-level price path. bronze.landwertzonen already carries
parcel-precise CHF/m2 (efh_landwertzone1..7 / ewg_landwertzone1..7 /
gewerbe_industrie, selected by the `lwz` index). Use this dataset for
Gemeinde-level context, historical trend, and as a cross-check on those
parcel values -- not as the primary way to price a parcel.

Confirmed against the live portal (2026-08-13):

  - The pilot slice is a COMPLETE GRID: 5 Gemeinden x 13 years x 8 zone
    categories = 520 rows, no gaps and no nulls in any column.
  - Fields: gemeinde, bfs_nr_gemeinde, bezirk, bfs_nr_bezirk, jahr,
    bauzone, minimum, maximum, markt_ja_nein.

GRAIN AND LAG -- each row is a six-year trailing window, not a spot price.
The 2024 row is computed over the Bemessungsperiode 2017-01-01 to
2023-12-31. So consecutive years overlap heavily and the series is
smoothed by construction; adjacent-year "changes" are not year-on-year
market moves. Several series repeat a value across two years (Kreuzlingen
"4 EFH" is 817-1514 in both 2023 and 2024).

NO MEDIAN COLUMN. The dataset description explains at length how the
Zentralwert (median) is derived, and that minimum/maximum are the
quartiles around it (falling back to deciles where quartiles would breach
the effective min/max) -- but the published export carries only `minimum`
and `maximum`. The median itself is NOT in the data. Don't assume
(min+max)/2 recovers it; the bounds are quantiles, so that midpoint is not
the median unless the distribution is symmetric.

ZERO IS A "NO DATA" SENTINEL, NOT A PRICE. 40 of the 520 pilot rows carry
minimum = maximum = 0, and every one of them has markt_ja_nein = 'n'. No
row with markt_ja_nein = 'j' is ever zero. Per the bronze contract the
zeros land as-is; silver should null them.

`markt_ja_nein` ('j'/'n') flags whether the zone-Gemeinde cell had a
sample of at least four transactions. 230 'j' / 290 'n' in the pilot, so
MOST CELLS ARE THIN -- treat 'n' rows as indicative, not as market prices.

JOIN CAVEAT -- `bauzone` here is NOT the zone code in bronze.bauzonen.
This dataset uses 8 coarse tax-valuation categories:

    1 Kern, 2 Dorf, 3 MFH, 4 EFH, 5 W+G, 6 Gewerbe, 7 Industrie, 8 Weiler

while bronze.bauzonen carries 79 distinct municipal codes for the pilot
alone (W80, WA105, W 1.6, D, StB, ...), which are not even normalised
between Gemeinden ('W1.6' vs 'W 1.6', 'FH' vs 'Fh', 'oeBA' vs 'OeBA').
There is no shared key and no published crosswalk. The Schätzer-Handbuch
PDF attached to this dataset does NOT supply one either (checked: it is
valuation methodology and never names these 8 categories; "TGB" appears
once, in the abbreviations glossary).

So this source joins cleanly on (BFS-Nr, jahr) but not to a zone polygon.
That is not blocking -- parcel pricing goes through bronze.landwertzonen,
which needs no crosswalk.
"""

from pathlib import Path

from propsearch_data.ingest import opendata

DATASET_ID = "dfs-sv-1"

# Confirmed against hoheitsgrenzen WFS ms:Gemeinden_Layer; all Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

BFS_COLUMN = "bfs_nr_gemeinde"

# The 8 categories this dataset uses. Recorded so the load can assert the
# taxonomy hasn't shifted under us, not to constrain the fetch.
ZONE_CATEGORIES = (
    "1 Kern",
    "2 Dorf",
    "3 MFH",
    "4 EFH",
    "5 W+G",
    "6 Gewerbe",
    "7 Industrie",
    "8 Weiler",
)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"


def pilot_where() -> str:
    return opendata.bfs_in(BFS_COLUMN, PILOT_BFS.values())


def source_path() -> Path:
    return OUTPUT_DIR / "bodenpreise_pilot.json"


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    records = opendata.export(DATASET_ID, pilot_where())
    if not records:
        raise SystemExit(f"[fail] {DATASET_ID}: no records returned")

    out_file = source_path()
    opendata.save_json(records, out_file)

    gemeinden = {r.get("gemeinde") for r in records}
    years = sorted({str(r.get("jahr"))[:4] for r in records})
    zones = sorted({r.get("bauzone") for r in records})
    missing = set(PILOT_BFS) - gemeinden
    thin = sum(1 for r in records if r.get("markt_ja_nein") == "n")
    zeros = sum(1 for r in records if r.get("maximum") == 0)

    print(f"[ok] {DATASET_ID}: {len(records)} records -> {out_file.name}")
    print(f"     jahr {years[0]}-{years[-1]} | {len(gemeinden)}/5 Gemeinden "
          f"| {len(zones)} zone categories")
    print(f"     markt='n' (thin sample): {thin} | zero-valued: {zeros}")

    expected = len(PILOT_BFS) * len(years) * len(zones)
    if len(records) != expected:
        print(f"     [warn] expected a complete {len(PILOT_BFS)}x{len(years)}"
              f"x{len(zones)} grid = {expected}, got {len(records)}")
    if missing:
        print(f"     [warn] no rows for: {', '.join(sorted(missing))}")
    if set(zones) - set(ZONE_CATEGORIES):
        print(f"     [warn] unrecognised zone categories: "
              f"{sorted(set(zones) - set(ZONE_CATEGORIES))}")
