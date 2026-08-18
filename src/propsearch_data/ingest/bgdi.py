"""
Shared client for the federal geodata infrastructure (BGDI) bulk assets,
served by swisstopo/opendata.swiss through the STAC API on
data.geo.admin.ch.

This is the project's FIFTH access pattern, after WFS (ingest/wfs.py),
Opendatasoft (ingest/opendata.py), the OEREB webservice (ingest/oereb.py)
and the BFS MADD download (ingest/madd.py). Like MADD it is a bulk file
with no server-side filter, so the whole of Switzerland comes down and the
pilot slice is cut locally -- but the file is a single GeoPackage inside a
zip, not a folder of CSVs, and the collection/asset URLs are resolved from
STAC rather than hard-coded.

It is scoped to "federal BGDI bulk asset via STAC", not to any one layer,
because the building-data spec (docs/gebaeudedaten-bronze-specs-en.md) has
a second federal source behind this same API -- SonBase / BAFU noise -- so
the resolution and download logic is worth sharing rather than copying.
That second consumer has since landed: ingest/discover_laerm.py reuses
`assets()` / `collection_updated()` here for both the road-noise COG and the
BAV rail-noise GeoPackage (the road COG is read through a windowed
/vsicurl/ clip rather than `download()`, since a COG needs no full pull).

WHY BULK, NOT THE api3.geo.admin.ch REST ROUTE. The spec proposed reaching
Sonnendach through `MapServer/identify` / `MapServer/find`. Confirmed live
(2026-08-14), that route cannot produce a defensible pilot slice:

  - `MapServer/find` is dead for ch.bfe.solarenergie-eignung-daecher: the
    layer is `"searchable": false` in layersConfig and find returns
    HTTP 502/504.
  - `MapServer/identify` works but caps at 201 results regardless of area
    (a +/-200 m, +/-400 m and +/-800 m envelope all return exactly 201),
    and `offset` paging has UNSTABLE ordering -- adjacent pages overlap by
    17 and 34 rows -- so a sweep cannot be proven complete.
  - There is no WFS: wfs.geo.admin.ch does not resolve from this
    environment, and ows.geo.tg.ch/geofy_access_proxy/solarenergie is a
    pass-through to the federal WMS with WFS disabled, not cantonal data.

The STAC bulk GeoPackage is the only route that yields a complete,
reproducible pilot cut.

Confirmed against the live STAC API (2026-08-17):

  - Collection ch.bfe.solarenergie-eignung-daecher has ONE item with six
    assets: full and generalized geometry, plus a monthly-data variant,
    each as both .gpkg.zip and .gdb.zip. The full .gpkg.zip is 1.5 GB and
    holds a single member SOLKAT_DACH.gpkg (4.58 GB uncompressed).
  - The zip stores its member DEFLATED, so /vsizip//vsicurl/ has to
    inflate the whole stream to reach any page and is not usable for a
    remote schema peek -- extract once and read the local file instead.
  - The member is compressed with DEFLATE64 (method 9, "enhanced
    deflate"), which the standard library's `zipfile` cannot decode
    (NotImplementedError) and which no `unzip`/`7z`/`bsdtar` binary is
    installed to handle. `zipfile_deflate64` is a drop-in ZipFile that
    adds method 9, so it is a real dependency, not a convenience.
"""

from pathlib import Path

import requests
import zipfile_deflate64 as zipfile

BASE = "https://data.geo.admin.ch"
STAC = f"{BASE}/api/stac/v0.9"


def assets(collection_id: str) -> dict[str, str]:
    """Map asset name -> href for a STAC collection's single item.

    swisstopo publishes one item per collection carrying every download
    variant as a named asset, so the caller picks the variant by name
    rather than guessing a URL.
    """
    url = f"{STAC}/collections/{collection_id}/items"
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        raise RuntimeError(f"STAC collection {collection_id} has no items")
    return {
        name: asset["href"]
        for feature in features
        for name, asset in feature.get("assets", {}).items()
    }


def collection_updated(collection_id: str) -> str:
    """The collection's `updated` timestamp -- the dataset vintage.

    The features carry their own per-roof survey dates too; this is the
    publication vintage of the whole layer, recorded alongside as
    provenance.
    """
    url = f"{STAC}/collections/{collection_id}"
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.json().get("updated", "")


def download(url: str, dest: Path, force: bool = False) -> Path:
    """Stream `url` to `dest`, skipping if it already exists.

    Streamed rather than held in memory -- the Sonnendach zip is 1.5 GB.
    The file is kept so the extract/load steps can be re-run without
    re-hitting the CDN, mirroring the fetch/load split every source here
    uses. Takes a URL rather than building one, since STAC supplies the
    href (see `assets`).
    """
    if dest.exists() and not force:
        mb = dest.stat().st_size / 1_048_576
        print(f"  {dest.name} already present ({mb:.1f} MB) -- skipping download")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url} ...")
    with requests.get(url, stream=True, timeout=1800) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    print(f"  wrote {dest.name} ({dest.stat().st_size / 1_048_576:.1f} MB)")
    return dest


def extract_member(zip_path: Path, member: str, dest_dir: Path, force: bool = False) -> Path:
    """Extract one member of a zip to `dest_dir`, skipping if present.

    Kept as a separate cached step because the member is a multi-GB
    GeoPackage: /vsizip//vsicurl/ over the deflated stream is unusably
    slow, so it is inflated to disk once and then read with the normal
    GDAL/pyogrio path (whose GPKG RTree index makes a windowed bbox read
    fast).
    """
    out = dest_dir / member
    if out.exists() and not force:
        gb = out.stat().st_size / 1_073_741_824
        print(f"  {out.name} already extracted ({gb:.1f} GB) -- skipping")
        return out

    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"  extracting {member} from {zip_path.name} ...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract(member, dest_dir)
    print(f"  wrote {out.name} ({out.stat().st_size / 1_073_741_824:.1f} GB)")
    return out
