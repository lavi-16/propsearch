"""
Pull the Sonnendach roof solar-potential layer for the pilot area.

This is the SECOND building-level source, after GWR, and the first from
docs/gebaeudedaten-bronze-specs-en.md to land via the federal BGDI bulk
route. The layer is BFE `ch.bfe.solarenergie-eignung-daecher` -- one
MultiPolygon per roof plane, with a modelled annual electricity/heat
yield, orientation, tilt, area, and a 1-5 suitability class.

WHY THE BULK GEOPACKAGE, NOT api3.geo.admin.ch. See ingest/bgdi.py for
the full record. In short, confirmed live 2026-08-14: MapServer/find is
disabled for this layer (HTTP 502/504), MapServer/identify caps at 201
results with unstable offset paging so a sweep cannot be proven complete,
and there is no WFS reachable from here. The STAC bulk GeoPackage is the
only route that yields a complete, reproducible pilot cut.

THE JOIN KEY IS GWR_EGID, NOT building_id. The spec assumed the layer's
`building_id` would be the EGID. It is not: the api3 `identify` response
carries BOTH a swisstopo `building_id` AND a separate `gwr_egid`, with
different values and different cardinality. The bulk GeoPackage settles it
-- it carries `GWR_EGID` and no `building_id` column at all. GWR_EGID is
the same federal building id as bronze.gwr_gebaeude.egid, so Sonnendach
joins to the building layer by attribute, and through it to the parcel.

SELECTION IS SPATIAL, like Gefahrenkarte and unlike GWR. The roof planes
carry no Gemeinde attribute, so the five pilot boundaries are fetched from
`hoheitsgrenzen` (`ms:Gemeinden_Layer`), their bbox drives a windowed read
of the GeoPackage (fast: the GPKG carries an RTree, so a pilot-window read
is ~1 s over the 10-million-feature national layer), and the result is
narrowed to rows intersecting a pilot Gemeinde. That last step is ROW
SELECTION ONLY -- geometries are never clipped, per the bronze contract.

A THIRD GRAIN, one level BELOW the building. The register chain is
parcel (E-GRID) -> building (EGID) -> ROOF PLANE. The unique key here is
DF_UID (one row per roof plane); a building has ~3 planes because a roof
is split by orientation and pitch (the south-facing pitch rated apart from
the north). `(GWR_EGID, DF_NUMMER)` is NOT unique -- DF_UID is. Joining
this table straight to the 9,879-row parcel spine would fan out twice
over: once building-per-parcel (up to 29, per the GWR notes) and again
plane-per-building. Aggregate to EGID first, or keep it a separate fact.

Confirmed against the live download / build (2026-08-17):

  layer SOLKAT_CH_DACH  10,071,755 roof planes canton-independent (all CH),
                        34,358 intersecting a pilot Gemeinde, MultiPolygon,
                        EPSG:2056.
  per Gemeinde          Bottighofen 2,464 | Ermatingen 5,230 |
                        Kreuzlingen 17,033 | Münsterlingen 4,077 |
                        Tägerwilen 5,565 -- none empty.
  GWR_EGID              filled on 93.7% of pilot planes; a null is a roof
                        the survey rated but could not link to the
                        register -- "unlinked", not "no roof". Kept.
  join                  7,415 of 10,392 existing (GSTAT 1004) pilot
                        buildings (71.4%) carry >=1 roof plane. The ~29%
                        without are small/minor structures the survey
                        excludes -- normal coverage, not a defect.
  invalid geometries    69 of the 34,358 (all self-intersections), landed
                        as-is per the bronze contract; silver ST_MakeValid.

KLASSE is a 1-5 ordinal, worst-to-best, decoded by the file's own
EIGNUNG_DACH lookup (fid = KLASSE): 1 gering (<800 kWh/m2/yr),
2 mittel (800-1000), 3 gut (1000-1200), 4 sehr gut (1200-1400),
5 top (>=1400). SB_OBJEKTART is the swisstopo object type (fid = code:
1 Gebaeude Einzelhaus, 2 Hochhaus, ...). Both lookups ship as extra layers
in the GeoPackage; they are NOT landed here (24 tiny legend rows with
awkward column names -- the gwr_wohnung precedent: fetched but not landed,
one script away if silver wants them). The decode above is the record.

VINTAGE. Per-plane DATUM_ERSTELLUNG/DATUM_AENDERUNG carry the survey date;
the STAC collection `updated` stamp is the publication vintage. Recorded
via provenance at load.
"""

from pathlib import Path

import geopandas as gpd
import pyogrio

from propsearch_data.ingest import bgdi, wfs

COLLECTION = "ch.bfe.solarenergie-eignung-daecher"
ASSET = "solarenergie-eignung-daecher_2056.gpkg.zip"
MEMBER = "SOLKAT_DACH.gpkg"
LAYER = "SOLKAT_CH_DACH"

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
ZIP_FILE = OUTPUT_DIR / "solkat_dach_ch.gpkg.zip"
OUTPUT_FILE = OUTPUT_DIR / "sonnendach_pilot.gpkg"

# Observed 2026-08-17 (roof planes intersecting a pilot Gemeinde). Centre
# of a tolerance band, not an equality: the national layer is periodically
# re-flown and re-published, so an exact count would fail on a routine
# refresh. What is asserted exactly is the failure mode that matters -- no
# Gemeinde may come back empty.
BASELINE_PLANES = 34_358
TOLERANCE = 0.10

# Extent of the five pilot Gemeinden in EPSG:2056, padded ~2 km. A sanity
# check on the selected geometry, not a filter (selection is spatial via
# the boundaries below). Guards a swapped easting/northing.
PILOT_ENVELOPE = (2_719_900, 1_273_650, 2_739_100, 1_283_800)

GRAIN_KEY = "DF_UID"
EGID_COLUMN = "GWR_EGID"


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
    """Fail loudly on a silent zero or a lost grain; tolerate re-flights."""
    # Compare bfsnr as strings on both sides: GML type inference may render
    # gemeinde_bfsnr as int or text, and an int==text mask is silently empty
    # (the bfs_nr_gemeinde type trap CLAUDE.md flags across sources).
    bfsnr = boundaries["gemeinde_bfsnr"].astype(str)
    empty = []
    parts = []
    for name, bfs in PILOT_BFS.items():
        poly = boundaries[bfsnr == str(bfs)].geometry.union_all()
        n = int(gdf.geometry.intersects(poly).sum())
        parts.append(f"{name}={n}")
        if n == 0:
            empty.append(name)
    if empty:
        raise ValueError(f"no roof planes returned for: {', '.join(empty)}")

    lo = int(BASELINE_PLANES * (1 - TOLERANCE))
    hi = int(BASELINE_PLANES * (1 + TOLERANCE))
    if not lo <= len(gdf) <= hi:
        raise ValueError(
            f"{len(gdf)} roof planes is outside the expected band {lo}-{hi} "
            f"(baseline {BASELINE_PLANES:,} observed 2026-08-17) -- "
            "the source may have been re-flown or changed shape"
        )

    duplicates = len(gdf) - gdf[GRAIN_KEY].nunique()
    if duplicates:
        raise ValueError(f"{GRAIN_KEY} is not unique: {duplicates} duplicate rows")

    print("  " + ", ".join(parts))


def report_link(gdf: gpd.GeoDataFrame) -> None:
    total = len(gdf)
    filled = int(gdf[EGID_COLUMN].notna().sum())
    print(
        f"  {EGID_COLUMN} filled: {filled:,}/{total:,} = "
        f"{100 * filled / total:.1f}% (a null is an unlinked roof, kept)"
    )
    klasse = gdf["KLASSE"].value_counts().sort_index()
    print("  KLASSE (1 gering .. 5 top): "
          + ", ".join(f"{int(k)}={v}" for k, v in klasse.items()))


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    available = bgdi.assets(COLLECTION)
    if ASSET not in available:
        raise RuntimeError(
            f"asset {ASSET!r} not in {COLLECTION}; available: "
            f"{sorted(available)} -- swisstopo may have renamed it"
        )
    bgdi.download(available[ASSET], ZIP_FILE)
    gpkg = bgdi.extract_member(ZIP_FILE, MEMBER, OUTPUT_DIR)
    print()

    boundaries = pilot_boundaries(OUTPUT_DIR)
    minx, miny, maxx, maxy = boundaries.total_bounds
    print(
        f"Pilot bbox from {BOUNDARY_TYPENAME}: "
        f"E {minx:.0f}-{maxx:.0f} N {miny:.0f}-{maxy:.0f}"
    )

    window = pyogrio.read_dataframe(gpkg, layer=LAYER, bbox=(minx, miny, maxx, maxy))
    pilot_union = boundaries.geometry.union_all()
    pilot = window[window.geometry.intersects(pilot_union)].reset_index(drop=True)
    print(f"  {len(window):,} in bbox -> {len(pilot):,} intersect a pilot Gemeinde\n")

    check_extent(pilot)
    check_counts(pilot, boundaries)
    report_link(pilot)

    invalid = int((~pilot.geometry.is_valid).sum())
    print(f"  invalid geometries (landed as-is; silver ST_MakeValid): {invalid}")

    vintage = bgdi.collection_updated(COLLECTION)
    print(f"  STAC collection updated: {vintage}")

    pilot.to_file(OUTPUT_FILE, driver="GPKG")

    print()
    print(f"[ok] {len(pilot):,} roof planes -> {OUTPUT_FILE.name}")
    print(f"     CRS {pilot.crs}")
