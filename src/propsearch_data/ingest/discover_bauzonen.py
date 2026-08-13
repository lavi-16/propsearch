"""
Pull Thurgau Bauzonen (zoning) for the pilot Gemeinden via WFS.

Confirmed against the live service (2026-08-13):

- Service `oereb_ortsplanung_bauzonen` carries the whole Ortsplanung, not
  just Bauzonen. `ms:bau` is the current zoning layer; siblings include
  `ms:landwirt` (Landwirtschaftszonen), `ms:ueberlagernd` (overlays) and
  `ms:les` (Lärmempfindlichkeitsstufen). Adding one is a line in
  TYPENAMES -- see the note there before you do.
- Layers suffixed `_vx` are PENDING AMENDMENTS, not current state. They
  are excluded deliberately.
- Selection is on the `t_id` prefix, which is the BFS-Nr. Verified
  exhaustively: the 19,425 canton-wide features carry exactly 80 distinct
  prefixes, matching the 80 Gemeinden in the hoheitsgrenzen WFS one for
  one, with no unknown prefixes and no Gemeinde unrepresented. So a
  prefix filter is equivalent to selecting by Gemeinde.

HOW THIS DIFFERS FROM LANDWERTZONEN -- matters for the eventual join:
- Geometry is Polygon/MultiPolygon, not Point.
- There is NO E-GRID. Zoning attaches to a parcel spatially
  (point-in-polygon), not by key. PostGIS is doing real work here.
- `gml_id` is empty on every feature. The natural key is `t_id`, which is
  unique per feature.

Careful with the name columns: `gn_kantname` and `gn_gmdname` are the
canton's and the Gemeinde's name for the ZONE TYPE (e.g. "Wohn- und
Arbeitszone 3"), not Gemeinde names. `gn_kuerzel` is the short zone code
(e.g. "WA105") and is null on a few features.
"""

from pathlib import Path

from propsearch_data.ingest import wfs

SERVICE_URL = "https://ows.geo.tg.ch/geofy_access_proxy/oereb_ortsplanung_bauzonen"

# Confirmed against hoheitsgrenzen WFS ms:Gemeinden_Layer; all Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

# Only current-state Bauzonen for now. The sibling layers (ms:landwirt,
# ms:ueberlagernd, ms:les) share this code path, but each needs its own
# check that `t_id` is present and prefixed the same way before being
# added here -- don't assume it carries across layers.
TYPENAMES = ["ms:bau"]

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"


def pilot_filter() -> str:
    return wfs.property_like_any("t_id", [f"{bfs}_*" for bfs in sorted(PILOT_BFS.values())])


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fes = pilot_filter()
    print(f"Pilot Gemeinden: {', '.join(f'{n} ({b})' for n, b in PILOT_BFS.items())}\n")

    for typename in TYPENAMES:
        expected = wfs.count(SERVICE_URL, typename, fes)
        gdf = wfs.fetch(SERVICE_URL, typename, fes, work_dir=OUTPUT_DIR)
        short = typename.split(":")[-1]

        if gdf.empty:
            print(f"[warn] {short}: no features returned\n")
            continue

        if expected.isdigit() and int(expected) != len(gdf):
            raise RuntimeError(
                f"{short}: server reported {expected} features, fetched {len(gdf)}"
            )

        out_file = OUTPUT_DIR / f"bauzonen_{short}_pilot.gpkg"
        gdf.to_file(out_file, driver="GPKG", layer=short)

        bfs_of = gdf["t_id"].astype(str).str.split("_").str[0]
        by_gem = bfs_of.value_counts().sort_index()
        name_of = {str(v): k for k, v in PILOT_BFS.items()}
        print(f"[ok] {short}: {len(gdf)} features -> {out_file}")
        print(f"     CRS={gdf.crs}  geom={sorted(gdf.geometry.geom_type.unique())}")
        print(
            "     "
            + ", ".join(f"{name_of.get(b, b)}={n}" for b, n in by_gem.items())
            + "\n"
        )
