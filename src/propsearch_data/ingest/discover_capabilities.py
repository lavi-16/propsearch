"""
Pulls GetCapabilities (and layer listings) from the Thurgau geodata
services we know about, and dumps them to docs/wfs-capabilities/ so the
gold-layer schema can be designed from real field names instead of
guesses.

Run this from an unrestricted network - ows.geo.tg.ch and data.tg.ch
block bot/proxy traffic, so this won't work from a sandboxed environment.
Once it runs, share docs/wfs-capabilities/ back so the schema can be
designed against it.
"""

from pathlib import Path

from owslib.wfs import WebFeatureService

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "wfs-capabilities"

_BASE = "https://ows.geo.tg.ch/geofy_access_proxy"

# Confirmed live 2026-08-13. Unknown slugs answer "Access Denied" / HTTP 401,
# so adding a candidate here is a cheap way to test it.
#
# The Gefahrenkarte layers are served as WFS (not WMS-only, as originally
# assumed), so they fit this same code path. Slug pattern is
# `ng_gefahrenkarte_<process>` -- found via the canton's geoservice listing.
ENDPOINTS = {
    "oereb_datensammelstellen": f"{_BASE}/datensammelstellen",
    "oereb_ortsplanung_bauzonen": f"{_BASE}/oereb_ortsplanung_bauzonen",
    "gewaesserkataster_gewaesser": f"{_BASE}/gewaesserkataster_gewaesser",
    "landwertzonen": f"{_BASE}/landwertzonen",
    "hoheitsgrenzen": f"{_BASE}/hoheitsgrenzen",  # ms:Gemeinden_Layer -> BFS-Nr lookup
    # Naturgefahren / Gefahrenkarte -- the spec's "Hazard" layer.
    "ng_gefahrenkarte_synoptisch": f"{_BASE}/ng_gefahrenkarte_synoptisch",
    "ng_gefahrenkarte_wasser": f"{_BASE}/ng_gefahrenkarte_wasser",
    "ng_gefahrenkarte_rutschungen": f"{_BASE}/ng_gefahrenkarte_rutschungen",
    "ng_gefahrenkarte_erhebungsgebiet": f"{_BASE}/ng_gefahrenkarte_erhebungsgebiet",
    # Confirmed live while scoping the silver layer. Serves ms:raum, the
    # bulk source for the ch.Gewaesserraum OEREB theme.
    "oereb_gewaesserraum": f"{_BASE}/oereb_gewaesserraum",
}


def dump_capabilities(name: str, base_url: str) -> None:
    out_file = OUTPUT_DIR / f"{name}_capabilities.txt"
    try:
        wfs = WebFeatureService(url=base_url, version="2.0.0")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"Service: {base_url}\n")
            f.write(f"Title: {wfs.identification.title}\n")
            f.write(f"Abstract: {wfs.identification.abstract}\n\n")
            f.write("Layers:\n")
            for layer_name in list(wfs.contents):
                layer = wfs.contents[layer_name]
                f.write(f"- {layer_name}: {layer.title}\n")
        print(f"[ok] {name} -> {out_file}")
    except Exception as e:
        print(f"[fail] {name}: {e}")


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for svc_name, url in ENDPOINTS.items():
        dump_capabilities(svc_name, url)
