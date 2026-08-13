"""
Pull the Naturgefahren / Gefahrenkarte layers for the pilot area.

This is the spec's HAZARD layer, and the last of the five to land.

WHY THIS EXISTS SEPARATELY FROM OEREB: ÖREB does not answer the hazard
question. `ch.Gefahrenzone` is not among the TG service's 32 themes at
all; hazard reaches ÖREB only as a `ch.Nutzungsplanung` overlay *label*
("Gefahrenzone", "Gebiete mit Hochwasserschutz"), which is a binary
presence flag with an empty TypeCode -- no intensity, no return period.
These layers carry the graded classification instead:

  gefahrenstufe       erheblich | mittel | gering | keine
  matrixfeld          MF1..MF9, MF99  (the intensity x probability matrix)
  prozess_massgebend  the governing process, e.g.
                      Seehochwasser_Thurhochwasser, Ueberflutung,
                      Ufererosion, Oberflaechenabfluss, kein_Prozess

Three services, one table -- all three layers share an identical column
set, so they fold together with a `_source_layer` discriminator the same
way the three Landwertzonen layers do. `_synoptisch` is the combined
view; `_wasser` and `_rutschungen` are the per-process detail and overlap
it by design, so DO NOT sum across layers.

SELECTION IS SPATIAL, unlike every other WFS source here. These layers
carry no Gemeinde attribute -- no `gemcode`, no `t_id` prefix -- so there
is nothing to filter on. Instead:

  1. the five pilot Gemeinde polygons are fetched from `hoheitsgrenzen`
     (`ms:Gemeinden_Layer`), the authoritative boundary layer;
  2. their union bbox drives a server-side FES BBOX filter;
  3. the bbox result is then narrowed to rows that actually intersect a
     pilot Gemeinde, since a bbox is a rectangle and catches neighbours.

Step 3 is ROW SELECTION ONLY -- geometries are never clipped, so what
lands is still whole source features, per the bronze contract. The bbox is
derived at runtime from real boundaries rather than typed in; a
hand-written bbox can silently select nothing (see the PILOT_BBOX history
in discover_landwertzonen.py).

Perimeter layers (`ms:Perimeter_*`, `ms:Hauptprozesse`,
`ms:Hinweise_auf_bestehende_Gefahrenkarten`,
`ms:technische_berichte_gefahrenkartierung`) are survey-extent and
metadata layers, not gradings. Not ingested; add them only with a reason.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from propsearch_data.ingest import wfs

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

# service slug -> typename. Identical schemas; see module docstring.
LAYERS = {
    "ng_gefahrenkarte_synoptisch": "ms:Gefaehrdung_synoptisch",
    "ng_gefahrenkarte_wasser": "ms:Gefaehrdung_Wasser",
    "ng_gefahrenkarte_rutschungen": "ms:Gefaehrdung_Rutschungen",
}

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"
OUTPUT_FILE = OUTPUT_DIR / "gefahrenkarte_pilot.gpkg"


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


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    boundaries = pilot_boundaries(OUTPUT_DIR)
    minx, miny, maxx, maxy = boundaries.total_bounds
    print(
        f"Pilot bbox from {BOUNDARY_TYPENAME}: "
        f"E {minx:.0f}-{maxx:.0f} N {miny:.0f}-{maxy:.0f}\n"
    )
    area_filter = wfs.bbox(minx, miny, maxx, maxy)
    pilot_union = boundaries.geometry.union_all()

    frames = []
    for slug, typename in LAYERS.items():
        service = f"{BASE}/{slug}"
        expected = wfs.count(service, typename, area_filter)
        gdf = wfs.fetch(service, typename, area_filter, work_dir=OUTPUT_DIR)

        if expected.isdigit() and len(gdf) != int(expected):
            raise RuntimeError(
                f"{typename}: fetched {len(gdf)} but server matched {expected}"
            )

        # Narrow the rectangle to the actual Gemeinden. Row selection only --
        # geometries are not clipped.
        in_pilot = gdf[gdf.geometry.intersects(pilot_union)].copy()
        in_pilot["_source_layer"] = typename
        frames.append(in_pilot)
        print(
            f"  {typename}: {len(gdf)} in bbox -> {len(in_pilot)} intersect a "
            f"pilot Gemeinde\n"
        )

    combined = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=frames[0].crs
    )
    combined.to_file(OUTPUT_FILE, driver="GPKG")

    print(f"[ok] {len(combined)} features -> {OUTPUT_FILE.name}")
    print(f"     CRS {combined.crs}")
    for col in ("gefahrenstufe", "matrixfeld", "prozess_massgebend"):
        vals = sorted(combined[col].dropna().astype(str).unique())
        print(f"     {col}: {vals}")
