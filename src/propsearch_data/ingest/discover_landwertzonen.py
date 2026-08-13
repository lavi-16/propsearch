"""
Bronze ingestion for Thurgau Landwertzonen (land value zones) via WFS.

Everything below is CONFIRMED against the live service (2026-08-13), not
guessed. What was verified, and what it corrected:

- Slug `landwertzonen` is real. The service answers at
  ows.geo.tg.ch/geofy_access_proxy/landwertzonen from a normal network.
- The service serves GML only. `application/json` is rejected with
  InvalidParameterValue, so the old json/r.json() path could never work.
  We request GML and parse via geopandas instead.
- Three feature types exist, not one (see TYPENAMES).
- `gemcode` is the BFS-Nr. Confirmed by cross-referencing the
  hoheitsgrenzen WFS (ms:Gemeinden_Layer, field `gemeinde_bfsnr`) --
  e.g. Kreuzlingen = 4671 in both. This resolves the "Gemeinde-ID
  reconciliation" open question in docs/spec.md for this layer.
- `gs_egris_egrid` carries the federal E-GRID parcel identifier on every
  feature (no nulls in sample). Land value therefore joins to a parcel
  directly on EGRID -- no point-in-polygon step needed for this layer.
- Geometry is POINT, one per parcel -- not zone polygons, as the spec
  assumed. Plan joins accordingly.
- Native CRS is EPSG:2056 (LV95), as required.

Selection is by BFS-Nr via a server-side attribute filter, not by bounding
box. The previous PILOT_BBOX was wrong: it started at E 2740000, roughly
5 km east of Muensterlingen, so it covered none of the pilot cluster and
returned 268 unrelated features. Filtering on gemcode is exact and can't
drift like that.
"""

from pathlib import Path

from propsearch_data.ingest import wfs

SERVICE_URL = "https://ows.geo.tg.ch/geofy_access_proxy/landwertzonen"

# Confirmed against hoheitsgrenzen WFS ms:Gemeinden_Layer; all five are
# Bezirk Kreuzlingen.
PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

TYPENAMES = [
    "ms:Landwertzonen_Bauz",  # Landwertzonen in Bauzonen
    "ms:Landwertzonen_aus_Bau",  # ... ausserhalb Bauzonen
    "ms:Landwertzonen_Strasse",  # ... Strassen und Sonstige
]

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"


def pilot_filter() -> str:
    return wfs.property_equals_any("gemcode", sorted(PILOT_BFS.values()))


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

        out_file = OUTPUT_DIR / f"{short.lower()}_pilot.gpkg"
        gdf.to_file(out_file, driver="GPKG", layer=short.lower())

        per_gemeinde = gdf["gemcode"].value_counts().sort_index()
        bfs_to_name = {v: k for k, v in PILOT_BFS.items()}
        breakdown = ", ".join(
            f"{bfs_to_name.get(code, code)}={n}" for code, n in per_gemeinde.items()
        )
        print(f"[ok] {short}: {len(gdf)} features -> {out_file}")
        print(f"     CRS={gdf.crs}  {breakdown}\n")
