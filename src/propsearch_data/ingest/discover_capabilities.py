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

# TODO: confirm/complete this list. One endpoint confirmed so far; the rest
# need to be found via map.geo.tg.ch, shop.geo.tg.ch, or geodienste.ch -
# see README.md for how.
ENDPOINTS = {
    "oereb_datensammelstellen": "https://ows.geo.tg.ch/geofy_access_proxy/datensammelstellen",
    # "bauzonen": "TODO",
    # "gefahrenkarte": "TODO",   # likely WMS, not WFS - may need a separate helper
    # "landwertzonen": "TODO",
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
