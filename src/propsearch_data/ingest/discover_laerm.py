"""
Pull the SonBase / BAFU noise-exposure layers for the pilot area.

This is the THIRD and last building-level source from
docs/gebaeudedaten-bronze-specs-en.md (SS 3). The spec called it "SonBase"
and warned the format needed clarifying before committing to a pattern; the
federal legend confirms it IS *sonBASE*, BAFU's area-wide noise-exposure
model. Two noise dimensions land here:

  ROAD noise (the spec's primary goal) -- ch.bafu.laerm-strassenlaerm_tag /
    _nacht. A Cloud-Optimized GeoTIFF (COG) per period, one Float64 band
    whose pixel value is the Beurteilungspegel Lr in dB(A) DIRECTLY (no
    class lookup, unlike Sonnendach's KLASSE), NODATA -9999, 10 m grid,
    EPSG:2056. A COG supports HTTP range reads, so a windowed /vsicurl/
    read of the pilot bbox pulls only the covering tiles (~16 MB) rather
    than the 553 MB national raster -- the raster analogue of Sonnendach's
    windowed GPKG bbox read. The clipped window is written to data/bronze/
    and sampled at building points in the load step.

  RAIL noise -- ch.bav.laermbelastung-eisenbahn_immissionen. Richer than
    the spec knew: a 60 MB vector GeoPackage (not a raster), so no raster
    reader is needed for it. Layer immission_railway_pointofdetermination
    is Point-per-facade with Lr_day / Lr_night in dB, landed as-is at its
    native point grain (like Sonnendach roof planes).

WHY THE BGDI/STAC ROUTE, NOT api3.geo.admin.ch. The spec named
MapServer/identify on the WMTS layer; layersConfig confirms that is the
PNG *display* layer (type=wmts), not a data route. The data is the STAC
bulk asset on data.geo.admin.ch, resolved through the same ingest/bgdi.py
client Sonnendach uses -- which was scoped for exactly this second consumer.

SELECTION IS SPATIAL, like Sonnendach and Gefahrenkarte. Neither the COG
nor the rail points carry a Gemeinde attribute, so the five pilot polygons
come from `hoheitsgrenzen` (`ms:Gemeinden_Layer`), their padded bbox drives
the windowed reads, and rail rows are narrowed to those intersecting a
pilot Gemeinde. Row selection only -- geometries are never clipped.

RAIL EGID TRAP, grounded 2026-08-18: the rail point layer HAS an `EGID`
field, but it is 0% populated in the pilot (every value NaN). So rail does
NOT join to buildings by attribute here; the building link is spatial and
belongs in silver. Kept as-is per the bronze contract, emptiness recorded.

Confirmed against the live download (2026-08-18):

  road COG (tag)   1 band Float64, NODATA -9999, 10 m, EPSG:2056; pilot
                   window 1015 x 1920 px, ~57% valid, dB 0.0 .. 84.8.
                   Vintage (STAC) 2021-12-31. A pixel value of 0.0 is a
                   computed "negligible" reading; -9999 is "outside the
                   modelled area" -> NULL. The two are kept distinct.
  rail points      222,335 national, 937 inside the pilot polygons,
                   Lr_day 24.1 .. 55.3 dB. Vintage 2023-04-18.
"""

import os
from pathlib import Path

# Stop GDAL probing for PAM/.aux sidecars over /vsicurl/ -- those requests
# 404/403 harmlessly but spew RuntimeWarnings on every remote read.
os.environ.setdefault("GDAL_PAM_ENABLED", "NO")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

import geopandas as gpd  # noqa: E402
import pyogrio  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

from propsearch_data.ingest import bgdi, wfs  # noqa: E402

# --- road (raster COG) ---
ROAD_COLLECTIONS = {
    "tag": "ch.bafu.laerm-strassenlaerm_tag",
    "nacht": "ch.bafu.laerm-strassenlaerm_nacht",
}
ROAD_ASSET = {
    "tag": "laerm-strassenlaerm_tag_2056.tif",
    "nacht": "laerm-strassenlaerm_nacht_2056.tif",
}

# --- rail (vector GeoPackage) ---
RAIL_COLLECTION = "ch.bav.laermbelastung-eisenbahn_immissionen"
RAIL_ASSET = "laermbelastung-eisenbahn_immissionen_2056.gpkg"
RAIL_LAYER = "immission_railway_pointofdetermination"

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

# Pad the pilot bbox so a building sitting right on a Gemeinde edge still
# falls inside the clipped raster window it will be sampled against.
BBOX_PAD_M = 250

# The source's NODATA sentinel. Distinct from a genuine 0.0 dB reading,
# which is a computed "negligible" value that must survive.
ROAD_NODATA = -9999.0

# Plausibility band for a road-noise dB(A) pixel -- a sanity check the COG
# still means what it meant, not a filter.
ROAD_DB_RANGE = (0.0, 120.0)

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"
ROAD_FILE = {p: OUTPUT_DIR / f"laerm_strasse_{p}_pilot.tif" for p in ROAD_COLLECTIONS}
RAIL_FILE = OUTPUT_DIR / "laerm_bahn_pilot.gpkg"

# Observed 2026-08-18 (rail points intersecting a pilot Gemeinde). Centre of
# a tolerance band, not an equality: the cadastre is periodically recomputed.
BASELINE_RAIL_POINTS = 937
TOLERANCE = 0.15

RAIL_LR_COLUMNS = ("Lr_day", "Lr_night")


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


def padded_bbox(boundaries: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = boundaries.total_bounds
    return (minx - BBOX_PAD_M, miny - BBOX_PAD_M, maxx + BBOX_PAD_M, maxy + BBOX_PAD_M)


def clip_road_cog(period: str, href: str, bbox, dest: Path) -> None:
    """Windowed /vsicurl/ read of the pilot bbox, written as a small COG clip.

    Only the tiles covering the bbox are fetched, so this reads ~16 MB of a
    553 MB national raster. The clip keeps the source's georeferencing so the
    load step can sample it at building coordinates.
    """
    with rasterio.open(f"/vsicurl/{href}") as src:
        if src.count != 1 or src.dtypes[0] != "float64":
            raise ValueError(
                f"{period}: expected 1 Float64 band, got "
                f"{src.count} x {src.dtypes}"
            )
        if src.nodata != ROAD_NODATA:
            raise ValueError(
                f"{period}: expected NODATA {ROAD_NODATA}, got {src.nodata}"
            )
        # Snap to the pixel grid (defaults: floor offsets, ceil lengths) so
        # the clip fully covers the bbox and stays byte-aligned to the source.
        window = from_bounds(*bbox, transform=src.transform)
        window = window.round_offsets().round_lengths()
        arr = src.read(1, window=window)
        transform = src.window_transform(window)

        valid = arr[arr != ROAD_NODATA]
        if valid.size == 0:
            raise ValueError(f"{period}: no valid pixels in the pilot window")
        lo, hi = ROAD_DB_RANGE
        if valid.min() < lo or valid.max() > hi:
            raise ValueError(
                f"{period}: dB out of band {ROAD_DB_RANGE}: "
                f"{float(valid.min())}..{float(valid.max())}"
            )

        profile = src.profile | {
            "driver": "GTiff",
            "height": arr.shape[0],
            "width": arr.shape[1],
            "transform": transform,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }

    with rasterio.open(dest, "w", **profile) as out:
        out.write(arr, 1)

    pct = 100 * valid.size / arr.size
    print(
        f"  road/{period}: {arr.shape[1]}x{arr.shape[0]} px, "
        f"{pct:.0f}% valid, dB {valid.min():.1f}..{valid.max():.1f} -> {dest.name}"
    )


def fetch_rail(href: str, bbox, boundaries: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Windowed read of the rail immission points, narrowed to pilot polygons."""
    window = pyogrio.read_dataframe(
        f"/vsicurl/{href}", layer=RAIL_LAYER, bbox=bbox
    )
    pilot_union = boundaries.geometry.union_all()
    pilot = window[window.geometry.intersects(pilot_union)].reset_index(drop=True)
    print(f"  rail: {len(window):,} in bbox -> {len(pilot):,} intersect a pilot Gemeinde")
    return pilot


def check_rail(gdf: gpd.GeoDataFrame, boundaries: gpd.GeoDataFrame) -> None:
    """Fail loudly on a silent zero or a shifted count; tolerate recomputes."""
    # bfsnr compared as strings -- GML type inference may render
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
        raise ValueError(f"no rail points returned for: {', '.join(empty)}")

    lo = int(BASELINE_RAIL_POINTS * (1 - TOLERANCE))
    hi = int(BASELINE_RAIL_POINTS * (1 + TOLERANCE))
    if not lo <= len(gdf) <= hi:
        raise ValueError(
            f"{len(gdf)} rail points is outside the expected band {lo}-{hi} "
            f"(baseline {BASELINE_RAIL_POINTS} observed 2026-08-18) -- "
            "the cadastre may have been recomputed or changed shape"
        )
    print("  " + ", ".join(parts))


def report_rail(gdf: gpd.GeoDataFrame) -> None:
    for col in RAIL_LR_COLUMNS:
        s = gdf[col].astype(float)
        print(f"  {col}: {s.notna().sum()}/{len(gdf)} present, "
              f"dB {s.min():.1f}..{s.max():.1f}")
    filled = int(gdf["EGID"].notna().sum())
    print(f"  EGID present: {filled}/{len(gdf)} "
          "(0 expected -- rail links to buildings spatially, in silver)")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    boundaries = pilot_boundaries(OUTPUT_DIR)
    bbox = padded_bbox(boundaries)
    print(f"Pilot bbox (padded {BBOX_PAD_M} m): "
          f"E {bbox[0]:.0f}-{bbox[2]:.0f} N {bbox[1]:.0f}-{bbox[3]:.0f}\n")

    print("Road noise (COG windows):")
    for period, collection in ROAD_COLLECTIONS.items():
        available = bgdi.assets(collection)
        asset = ROAD_ASSET[period]
        if asset not in available:
            raise RuntimeError(
                f"asset {asset!r} not in {collection}; available: "
                f"{sorted(available)} -- swisstopo may have renamed it"
            )
        clip_road_cog(period, available[asset], bbox, ROAD_FILE[period])
        print(f"    STAC vintage: {bgdi.collection_updated(collection)}")

    print("\nRail noise (vector GeoPackage):")
    rail_assets = bgdi.assets(RAIL_COLLECTION)
    if RAIL_ASSET not in rail_assets:
        raise RuntimeError(
            f"asset {RAIL_ASSET!r} not in {RAIL_COLLECTION}; available: "
            f"{sorted(rail_assets)}"
        )
    rail = fetch_rail(rail_assets[RAIL_ASSET], bbox, boundaries)
    check_rail(rail, boundaries)
    report_rail(rail)
    invalid = int((~rail.geometry.is_valid).sum())
    print(f"  invalid geometries: {invalid}")
    print(f"  STAC vintage: {bgdi.collection_updated(RAIL_COLLECTION)}")
    rail.to_file(RAIL_FILE, driver="GPKG")

    print()
    print(f"[ok] road clips -> {', '.join(f.name for f in ROAD_FILE.values())}")
    print(f"     rail points -> {RAIL_FILE.name} ({len(rail):,} rows, CRS {rail.crs})")
