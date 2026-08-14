"""
Pull the federal GWR (Gebäude- und Wohnungsregister) for the pilot
Gemeinden from the BFS MADD public download.

See ingest/madd.py for why this source rather than data.tg.ch
`sk-stat-113` (a metadata-only stub) or the Kanton TG `gwr` WFS
(10-character truncated Gemeinde name, no BFS-Nr).

This is the first BUILDING-level source. Everything landed so far is
either parcel-level (landwertzonen, keyed on E-GRID) or Gemeinde-level
(the sk-stat-* series). EGID is a new grain one level BELOW the parcel:
2,435 pilot parcels carry more than one building, up to 29. Any rollup to
the parcel therefore fans out -- the same hazard as the Gefahrenkarte
2.97x fan-out, and the reason gold's grain guarantee exists.

Confirmed against the live download (2026-08-14):

  gebaeude  124,073 canton-wide, 11,217 in the pilot, 47 columns
  eingang   126,158 canton-wide, 11,489 in the pilot, 17 columns
  kodes         405 rows, canton-independent

THE PARCEL JOIN IS AN ATTRIBUTE JOIN, NOT A SPATIAL ONE. The building
record carries EGRID directly, in the same federal form as
bronze.landwertzonen.gs_egris_egrid ('CH627735262052'). Measured against
the built silver.parcel: 10,834 of 11,217 pilot buildings (96.6%) carry
an EGRID, and 10,344 (92.2%) join to a pilot parcel. The bronze spec's
acceptance criterion was 90% -- met without any point-in-polygon step.
6,641 of 9,879 pilot parcels (67.2%) carry at least one building.

WHY EINGANG IS LANDED TOO. docs/spec.md records address -> parcel as only
partly resolved: coordinate -> E-GRID works via the ÖREB getegrid route,
but address -> coordinate "still needs a geocoder -- no landed source
provides one". The entrance table IS that source, for the pilot at least.
Measured: 10,286 distinct (street, house number, PLZ) keys, of which
exactly ONE resolves to more than one EGRID; 9,803 (95.3%) resolve to a
single EGRID that exists in silver.parcel. DKODE/DKODN give the LV95
coordinate directly on 97.7% of rows. So inside the pilot a table lookup
replaces both the geocoder and the ÖREB round-trip. A geocode cache is
still needed, but only for the residual: new construction not yet in the
register, non-official entrances, and anything outside these 5 Gemeinden.

SELECTION IS BY BFS-Nr, and there is no server-side filter -- the whole
canton is downloaded and cut locally. Note GGDENR is TEXT in the CSV
(every column is read as str), so the filter compares strings. Same type
trap as `bfs_nr_gemeinde` on data.tg.ch, in a new place. `eingang` carries
no Gemeinde column at all, so it is filtered on the pilot EGID set
instead.

COUNTS ARE CHECKED AS A RANGE, NOT AN EQUALITY. GEXPDAT is stamped daily
and buildings are added and demolished, so asserting == 11217 would fail
on a routine rerun because the data moved rather than because anything
broke. What is asserted exactly is the failure mode that matters: no
Gemeinde may come back empty.
"""

from pathlib import Path

import geopandas as gpd

from propsearch_data.ingest import madd
from propsearch_data.ingest.discover_gemeindestats import PILOT_BFS

BFS_COLUMN = "GGDENR"
EGRID_COLUMN = "EGRID"

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"
ZIP_FILE = OUTPUT_DIR / "madd_tg.zip"
GEBAEUDE_FILE = OUTPUT_DIR / "gwr_gebaeude_pilot.gpkg"
EINGANG_FILE = OUTPUT_DIR / "gwr_eingang_pilot.json"
KODES_FILE = OUTPUT_DIR / "gwr_kodes.json"

# Observed 2026-08-14. Used as the centre of a tolerance band, not as an
# assertion -- see the module docstring.
BASELINE_GEBAEUDE = 11_217
TOLERANCE = 0.10

# Extent of the five pilot Gemeinden in EPSG:2056, derived from the
# 2026-08-14 pull and padded by 2 km. A sanity check on the constructed
# geometry, not a selection filter: selection is by BFS-Nr above. Guards
# against a swapped easting/northing, which would otherwise land a
# plausible-looking Point in the wrong half of the country.
PILOT_ENVELOPE = (2_719_900, 1_273_650, 2_739_100, 1_283_800)

# Columns whose fill rate is worth printing: GWR is a RAW REGISTER, "not
# corrected, imputed, or statistically supplemented" per BFS, so sparse
# columns are the norm and a null means unrecorded -- not zero, and not
# "no such feature".
FILL_REPORT = [
    "EGRID", "LPARZ", "GBAUJ", "GBAUP", "GAREA",
    "GASTW", "GANZWHG", "GEBF", "GVOL", "GENH1",
]


def pilot_bfs() -> set[str]:
    """The pilot BFS numbers as strings -- GGDENR is text in the CSV."""
    return {str(b) for b in PILOT_BFS.values()}


def to_points(df) -> gpd.GeoDataFrame:
    """Build the Point geometry from the GKODE/GKODN LV95 coordinate pair."""
    easting = df["GKODE"].astype(float)
    northing = df["GKODN"].astype(float)
    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(easting, northing),
        crs="EPSG:2056",
    )


def check_extent(gdf: gpd.GeoDataFrame) -> None:
    minx, miny, maxx, maxy = gdf.total_bounds
    lo_x, lo_y, hi_x, hi_y = PILOT_ENVELOPE
    if not (lo_x <= minx and maxx <= hi_x and lo_y <= miny and maxy <= hi_y):
        raise ValueError(
            f"geometry falls outside the pilot envelope {PILOT_ENVELOPE}: "
            f"({minx:.0f}, {miny:.0f}, {maxx:.0f}, {maxy:.0f}) -- "
            "check for a swapped GKODE/GKODN"
        )
    print(f"  extent ok: ({minx:.0f}, {miny:.0f}) .. ({maxx:.0f}, {maxy:.0f})")


def check_counts(gdf: gpd.GeoDataFrame) -> None:
    """Fail loudly on a silent zero; tolerate ordinary daily drift."""
    name_of = {str(v): k for k, v in PILOT_BFS.items()}
    per_gemeinde = gdf[BFS_COLUMN].value_counts()

    missing = sorted(name_of[b] for b in pilot_bfs() - set(per_gemeinde.index))
    if missing:
        raise ValueError(f"no buildings returned for: {', '.join(missing)}")

    lo = int(BASELINE_GEBAEUDE * (1 - TOLERANCE))
    hi = int(BASELINE_GEBAEUDE * (1 + TOLERANCE))
    if not lo <= len(gdf) <= hi:
        raise ValueError(
            f"{len(gdf)} buildings is outside the expected band {lo}-{hi} "
            f"(baseline {BASELINE_GEBAEUDE:,} observed 2026-08-14) -- "
            "the source may have changed shape"
        )

    duplicates = len(gdf) - gdf["EGID"].nunique()
    if duplicates:
        raise ValueError(f"EGID is not unique: {duplicates} duplicate rows")

    print(
        "  "
        + ", ".join(
            f"{name_of[b]}={per_gemeinde[b]}" for b in sorted(per_gemeinde.index)
        )
    )


def report_fill(df) -> None:
    total = len(df)
    print("  fill rates (raw register -- sparse is expected):")
    for col in FILL_REPORT:
        filled = (df[col].str.strip() != "").sum()
        print(f"    {col:<9} {filled:>6,}/{total:,} = {100 * filled / total:5.1f}%")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    madd.download(ZIP_FILE, canton="tg")
    print()

    gebaeude = madd.read_csv(ZIP_FILE, "gebaeude")
    pilot = gebaeude[gebaeude[BFS_COLUMN].isin(pilot_bfs())].reset_index(drop=True)
    print(f"  pilot slice: {len(pilot):,} of {len(gebaeude):,} buildings")

    gdf = to_points(pilot)
    check_extent(gdf)
    check_counts(gdf)
    report_fill(pilot)

    vintages = sorted(pilot["GEXPDAT"].unique())
    print(f"  GEXPDAT: {', '.join(vintages)}")

    # `eingang` carries no Gemeinde column -- cut it on the pilot EGID set.
    egids = set(pilot["EGID"])
    eingang_all = madd.read_csv(ZIP_FILE, "eingang")
    eingang = eingang_all[eingang_all["EGID"].isin(egids)].reset_index(drop=True)
    covered = eingang["EGID"].nunique()
    print(
        f"  pilot slice: {len(eingang):,} entrances covering "
        f"{covered:,}/{len(pilot):,} buildings "
        f"({100 * covered / len(pilot):.1f}%)"
    )

    kodes = madd.read_csv(ZIP_FILE, "kodes")

    gdf.to_file(GEBAEUDE_FILE, driver="GPKG")
    eingang.to_json(EINGANG_FILE, orient="records", force_ascii=False, indent=1)
    kodes.to_json(KODES_FILE, orient="records", force_ascii=False, indent=1)

    print()
    print(f"[ok] {len(gdf):,} buildings  -> {GEBAEUDE_FILE.name}")
    print(f"[ok] {len(eingang):,} entrances -> {EINGANG_FILE.name}")
    print(f"[ok] {len(kodes):,} codes     -> {KODES_FILE.name}")
