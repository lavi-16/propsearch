"""
Shared client for the BFS MADD public download -- the federal GWR
(Gebäude- und Wohnungsregister).

This is the project's FOURTH access pattern, after WFS (ingest/wfs.py),
Opendatasoft (ingest/opendata.py) and the ÖREB webservice
(ingest/oereb.py). It is a bulk zip of tab-delimited CSVs, not an API:
there is no server-side filter, so the whole canton is downloaded and the
pilot slice is cut locally.

WHY NOT data.tg.ch. The bronze spec proposed dataset `sk-stat-113` on
data.tg.ch, on the theory that TG republishes the federal GWR through the
same Opendatasoft API as the existing sk-stat-* sources. It does not.
`sk-stat-113` is a METADATA-ONLY CATALOG STUB -- confirmed live
(2026-08-14): has_records = false, records_count = 0, zero fields, zero
attachments, zero alternative_exports; both /records and /exports/json
return empty. It carries a title, a long description, keywords, a licence
and a publisher, so it looks entirely alive from the catalogue. Its
`references` field points here, to housing-stat.ch/madd. See the
data.tg.ch section of CLAUDE.md for the standing check this motivated.

WHY NOT THE BFS ACCESS REQUEST. The spec's actual goal was to avoid the
housing-stat.ch login and data-protection agreement. This route does that:
the public MADD download needs no credentials at all.

WHY NOT THE KANTON TG WFS. ows.geo.tg.ch/geofy_access_proxy/gwr is live
and serves ms:gwr_gebaeude with native Point geometry, but its
`gemeindename` is TRUNCATED TO 10 CHARACTERS and it carries no BFS-Nr at
all, so the established property_equals_any() selection silently returns
a fraction of a Gemeinde. See the GWR section of CLAUDE.md.

Confirmed against the live download (2026-08-14):

  - https://public.madd.bfs.admin.ch/tg.zip -- HTTP 200, no auth, 34.9 MB.
    Per-canton zips use the lowercase canton abbreviation; ch.zip is the
    whole country (945 MB).
  - Refreshed daily. Every row carries an export-date column (GEXPDAT /
    WEXPDAT / DEXPDAT) stamping the vintage.
  - CSVs are TAB-DELIMITED with a utf-8 BOM. Not comma-delimited, despite
    the .csv extension.
  - The zip also holds buildings.geojson, entrances.geojson and
    data.sqlite. IGNORE THEM: the geojson is Points (the same GKODE/GKODN
    coordinates) but a renamed, energy-focused SUBSET -- no EGRID, no
    GBAUJ, no GAREA, no GANZWHG. The CSVs are the complete record.
"""

import zipfile
from pathlib import Path

import pandas as pd
import requests

BASE = "https://public.madd.bfs.admin.ch"

# Members of the per-canton zip. GWR is a three-level model -- building,
# dwelling, entrance -- plus one shared code lookup.
FILES = {
    "gebaeude": "gebaeude_batiment_edificio.csv",
    "wohnung": "wohnung_logement_abitazione.csv",
    "eingang": "eingang_entree_entrata.csv",
    "kodes": "kodes_codes_codici.csv",
}


def download(dest: Path, canton: str = "tg", force: bool = False) -> Path:
    """Fetch <canton>.zip to `dest`, skipping the download if it exists.

    Streamed rather than held in memory: the TG zip is ~35 MB and ch.zip
    is ~945 MB. The file is kept so the load step can be re-run without
    re-hitting BFS, mirroring the fetch/load split used by every other
    source here.
    """
    if dest.exists() and not force:
        mb = dest.stat().st_size / 1_048_576
        print(f"  {dest.name} already present ({mb:.1f} MB) -- skipping download")
        return dest

    url = f"{BASE}/{canton.lower()}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url} ...")
    with requests.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    print(f"  wrote {dest.name} ({dest.stat().st_size / 1_048_576:.1f} MB)")
    return dest


def read_csv(zip_path: Path, key: str) -> pd.DataFrame:
    """Read one member of the MADD zip as an all-string DataFrame.

    EVERY COLUMN IS READ AS str, deliberately. GEBNR and LPARZ hold values
    like '1/721' and '1/.146'; pandas' type inference mangles some of
    those and would silently turn a numeric-looking parcel number into a
    float. Casting belongs to silver anyway -- bronze preserves the
    source's own representation.
    """
    member = FILES[key]
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(member) as fh:
            df = pd.read_csv(
                fh,
                sep="\t",
                dtype=str,
                keep_default_na=False,
                encoding="utf-8-sig",
            )
    print(f"  read {len(df):>7,} rows x {len(df.columns)} cols from {member}")
    return df
