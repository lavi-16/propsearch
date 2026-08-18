"""
Pull the BFE/Pronovo electricity-production-plant registry for the pilot area.

This is the source that unblocks the neoteq "good roof, no PV" candidate
list: without it a candidate that already has PV can't be excluded, which
would be a bad look on first contact. The layer is BFE
`ch.bfe.elektrizitaetsproduktionsanlagen` -- one Point per registered
electricity production plant (all plants >30 kVA, plus voluntarily
registered small plants >2 kW), from the Swiss guarantee-of-origin system
via Pronovo.

NOTE THE ASCII COLLECTION ID. The neoteq context file spells the layer
`elektrizitätsproduktionsanlagen` (umlaut); the actual federal STAC id is
`elektrizitaetsproduktionsanlagen` (ae). Same class of spec-vs-reality gap
as Sonnendach's building_id -- confirmed live before committing.

WHY THE BULK GEOPACKAGE. Same federal BGDI/STAC route as Sonnendach and the
BAV rail noise, via ingest/bgdi.py. STAC collection -> one item -> asset
`elektrizitaetsproduktionsanlagen_2056.gpkg` (88 MB, UNCOMPRESSED, EPSG:2056,
333,313 plants national). Uncompressed and RTree-backed, so -- like the rail
GeoPackage and unlike the DEFLATE64 Sonnendach zip -- it is read directly
through a windowed /vsicurl/ bbox read (no download, no extract). The pilot
window returns ~1,962 plants in ~19 s.

SELECTION IS SPATIAL, like Sonnendach and the rail noise. The plants carry
Municipality/PostCode text but no BFS-Nr, so the five pilot polygons come
from `hoheitsgrenzen` (`ms:Gemeinden_Layer`), their bbox drives the windowed
read, and rows are narrowed to those intersecting a pilot Gemeinde. Row
selection only -- geometries are never clipped, per the bronze contract.

THE CATEGORY IS CODED, decoded by the file's own catalogue layers
(MainCategoryCatalogue / SubCategoryCatalogue / PlantCategoryCatalogue).
Confirmed live: PV is SUBCATEGORY = 'subcat_2' (Photovoltaik). MainCategory
'maincat_2' is the coarser "Übrige erneuerbare Energien"; PlantCategory is
the mount type (plantcat_8 Angebaut, plantcat_9 Integriert, plantcat_10
Freistehend). 1,961 of 1,962 pilot plants are PV; the one non-PV is
'subcat_4' Biomass. Bronze lands ALL subcategories raw per the contract --
silver filters to subcat_2. The catalogue layers are NOT landed (tiny legend
tables, the EIGNUNG_DACH / gwr_wohnung precedent); the decode above is the
record. The PlantDetail sub-array layer is skipped like Sonnendach's
_monthlydata.

NO EGID -> THE BUILDING LINK IS SPATIAL, and it belongs in silver (the rail
noise precedent). Grounded 2026-08-18, plant-point -> nearest existing
building distance is bimodal: p50 5.6 m / p75 8.7 m (geocoded to ~the
building), then jumps to p90 668 m / p95 1002 m -- ~15% of plants are
geocoded only to a PLZ/municipality centroid. 286 PV plants sit >50 m from
any building and cannot be attached to one; within 50 m: ~1,675 plants ->
~1,497 distinct existing buildings. That residual is a documented caveat on
the exclusion, not something to force onto a building.

VINTAGE. Per-plant BeginningOfOperation carries the commissioning date; the
STAC collection `updated` stamp (2026-08-06) is the publication vintage.
Recorded via provenance at load.
"""

from pathlib import Path

import geopandas as gpd
import pyogrio

from propsearch_data.ingest import bgdi, wfs

COLLECTION = "ch.bfe.elektrizitaetsproduktionsanlagen"
ASSET = "elektrizitaetsproduktionsanlagen_2056.gpkg"
LAYER = "ElectricityProductionPlant"

BASE = "https://ows.geo.tg.ch/geofy_access_proxy"
BOUNDARY_SERVICE = f"{BASE}/hoheitsgrenzen"
BOUNDARY_TYPENAME = "ms:Gemeinden_Layer"

# Confirmed against ms:Gemeinden_Layer; all Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"
OUTPUT_FILE = OUTPUT_DIR / "pronovo_pilot.gpkg"

# Observed 2026-08-18 (plants of ANY subcategory intersecting a pilot
# Gemeinde -- 1,675 PV + 1 biomass). Centre of a tolerance band, not an
# equality: the registry is refreshed (STAC updated 2026-08-06 and plants are
# added continuously), so an exact count would fail on a routine refresh. What
# is asserted exactly is the failure mode that matters -- no Gemeinde may come
# back empty.
BASELINE_PLANTS = 1_676
TOLERANCE = 0.15

# Extent of the five pilot Gemeinden in EPSG:2056, padded ~2 km. A sanity
# check on the selected geometry (guards a swapped easting/northing), not a
# filter -- selection is spatial via the boundaries.
PILOT_ENVELOPE = (2_719_900, 1_273_650, 2_739_100, 1_283_800)

GRAIN_KEY = "xtf_id"
PV_SUBCATEGORY = "subcat_2"  # Photovoltaik -- silver filters on this


def pilot_boundaries(work_dir: Path) -> gpd.GeoDataFrame:
    """The five pilot Gemeinde polygons, from the authoritative layer."""
    gdf = wfs.fetch(
        BOUNDARY_SERVICE,
        BOUNDARY_TYPENAME,
        wfs.property_equals_any("gemeinde_bfsnr", PILOT_BFS.values()),
        work_dir=work_dir,
        quiet=True,
    )
    if len(gdf) != len(PILOT_BFS):
        raise RuntimeError(
            f"expected {len(PILOT_BFS)} Gemeinde polygons, got {len(gdf)}"
        )
    return gdf


def check_extent(gdf: gpd.GeoDataFrame) -> None:
    minx, miny, maxx, maxy = gdf.total_bounds
    lo_x, lo_y, hi_x, hi_y = PILOT_ENVELOPE
    if not (lo_x <= minx and maxx <= hi_x and lo_y <= miny and maxy <= hi_y):
        raise ValueError(
            f"geometry falls outside the pilot envelope {PILOT_ENVELOPE}: "
            f"({minx:.0f}, {miny:.0f}, {maxx:.0f}, {maxy:.0f})"
        )
    print(f"  extent ok: ({minx:.0f}, {miny:.0f}) .. ({maxx:.0f}, {maxy:.0f})")


def check_counts(gdf: gpd.GeoDataFrame, boundaries: gpd.GeoDataFrame) -> None:
    """Fail loudly on a silent zero or a lost grain; tolerate refreshes."""
    # Compare bfsnr as strings on both sides: GML type inference may render
    # gemeinde_bfsnr as int or text, and an int==text mask is silently empty
    # (the bfs_nr_gemeinde type trap CLAUDE.md flags across sources).
    bfsnr = boundaries["gemeinde_bfsnr"].astype(str)
    empty, parts = [], []
    for name, bfs in PILOT_BFS.items():
        poly = boundaries[bfsnr == str(bfs)].geometry.union_all()
        n = int(gdf.geometry.intersects(poly).sum())
        parts.append(f"{name}={n}")
        if n == 0:
            empty.append(name)
    if empty:
        raise ValueError(f"no plants returned for: {', '.join(empty)}")

    lo = int(BASELINE_PLANTS * (1 - TOLERANCE))
    hi = int(BASELINE_PLANTS * (1 + TOLERANCE))
    if not lo <= len(gdf) <= hi:
        raise ValueError(
            f"{len(gdf)} plants is outside the expected band {lo}-{hi} "
            f"(baseline {BASELINE_PLANTS:,} observed 2026-08-18) -- "
            "the registry may have shifted shape or the pilot window changed"
        )

    duplicates = len(gdf) - gdf[GRAIN_KEY].nunique()
    if duplicates:
        raise ValueError(f"{GRAIN_KEY} is not unique: {duplicates} duplicate rows")

    print("  " + ", ".join(parts))


def report_pv(gdf: gpd.GeoDataFrame) -> None:
    """Report the subcategory split -- PV is what silver keeps."""
    counts = gdf["SubCategory"].value_counts(dropna=False)
    print("  SubCategory: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    pv = int((gdf["SubCategory"] == PV_SUBCATEGORY).sum())
    print(
        f"  PV (SubCategory={PV_SUBCATEGORY!r}, Photovoltaik): {pv:,}/{len(gdf):,} "
        "(the rest are non-PV plants, kept raw; silver filters to PV)"
    )


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    available = bgdi.assets(COLLECTION)
    if ASSET not in available:
        raise RuntimeError(
            f"asset {ASSET!r} not in {COLLECTION}; available: "
            f"{sorted(available)} -- swisstopo may have renamed it"
        )
    href = available[ASSET]

    boundaries = pilot_boundaries(OUTPUT_DIR)
    minx, miny, maxx, maxy = boundaries.total_bounds
    print(
        f"Pilot bbox from {BOUNDARY_TYPENAME}: "
        f"E {minx:.0f}-{maxx:.0f} N {miny:.0f}-{maxy:.0f}"
    )

    # Windowed /vsicurl/ read -- the RTree makes this pull only the covering
    # pages of the 88 MB national GeoPackage (no download, the rail precedent).
    window = pyogrio.read_dataframe(
        f"/vsicurl/{href}", layer=LAYER, bbox=(minx, miny, maxx, maxy)
    )
    pilot_union = boundaries.geometry.union_all()
    pilot = window[window.geometry.intersects(pilot_union)].reset_index(drop=True)
    print(f"  {len(window):,} in bbox -> {len(pilot):,} intersect a pilot Gemeinde\n")

    check_extent(pilot)
    check_counts(pilot, boundaries)
    report_pv(pilot)

    invalid = int((~pilot.geometry.is_valid).sum())
    print(f"  invalid geometries (landed as-is): {invalid}")

    vintage = bgdi.collection_updated(COLLECTION)
    print(f"  STAC collection updated: {vintage}")

    pilot.to_file(OUTPUT_FILE, driver="GPKG")

    print()
    print(f"[ok] {len(pilot):,} plants -> {OUTPUT_FILE.name}")
    print(f"     CRS {pilot.crs}")
