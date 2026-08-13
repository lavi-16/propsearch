"""
Client for the Thurgau ÖREB-Kataster webservice (the federal M2M
interface for public-law restrictions on landownership).

Base: https://map.geo.tg.ch/services/oereb/   -- version "extract-2.0"

This is a DIFFERENT ACCESS PATTERN from everything else in the pipeline:
one HTTP request per parcel, returning a ~175 KB nested JSON document,
rather than one bulk request returning many features. It does not support
"give me all restrictions for a Gemeinde" -- you must already know which
parcels you care about. That is why ingestion here is a sample of test
parcels, not a full pilot-area pull.

ROUTES -- TG deviates from the federal spec, confirmed by probing:
  - GetVersions       /versions/json
  - GetCapabilities   /capabilities/json      (33 themes)
  - GetEGRID          /getegrid/json/?<selector>
  - GetExtractById    /extract/json/?EGRID=<egrid>

  The federal spec's `/extract/reduced/json/{egrid}` path form is NOT
  supported here -- the router rejects it with "Unknown action requested:
  reduced". Only `/extract/{format}/?EGRID=` works, and the flavour
  (reduced/full/signed/embeddable) cannot be selected.

GetEGRID selectors, confirmed:
  - EN=<easting>,<northing>   works -- LV95 / EPSG:2056
  - GNSS=<lat>,<lon>          works -- WGS84, and note the order is
                              LAT,LON. Reversed (lon,lat) silently
                              returns 204 rather than erroring. This is
                              the selector to use downstream of a
                              geocoder, which will hand you WGS84.
  - XY=<x>,<y>                returns HTTP 204. XY is the old LV03 frame;
                              passing LV95 coordinates to it silently
                              yields "no content", not an error.
  - IDENTDN=TG<bfs>&NUMBER=<parcel number>   works

  Note IDENTDN is "TG" + BFS-Nr, matching `gemnf_nbident` in the
  hoheitsgrenzen WFS, and NUMBER matches `gs_nummer` in
  bronze.landwertzonen. All three selectors were cross-checked against
  one parcel and returned the same EGRID, which also matched
  `gs_egris_egrid` in bronze.landwertzonen.

A parcel with no restrictions still returns a valid extract; "no data"
for a parcel shows up as HTTP 204 with an empty body, which is why
callers must treat 204 as a miss rather than an error.
"""

import time

import requests

BASE = "https://map.geo.tg.ch/services/oereb"


class OerebMiss(Exception):
    """Service answered 204 -- no parcel matched the selector."""


def _get(path: str, params: dict, timeout: int) -> dict:
    resp = requests.get(f"{BASE}{path}", params=params, timeout=timeout)
    if resp.status_code == 204 or not resp.content:
        raise OerebMiss(f"no content for {params}")
    resp.raise_for_status()
    return resp.json()


def versions(timeout: int = 30) -> dict:
    return _get("/versions/json", {}, timeout)


def capabilities(timeout: int = 30) -> dict:
    return _get("/capabilities/json", {}, timeout)


def topics(timeout: int = 30) -> list[str]:
    caps = capabilities(timeout)
    return [t["Code"] for t in caps["GetCapabilitiesResponse"]["topic"]]


def get_egrid_by_coordinate(easting: float, northing: float, timeout: int = 30) -> dict:
    """Resolve an LV95 (EPSG:2056) coordinate to a parcel. Uses EN=, not XY=."""
    return _get("/getegrid/json/", {"EN": f"{easting},{northing}"}, timeout)


def get_egrid_by_gnss(lat: float, lon: float, timeout: int = 30) -> dict:
    """Resolve a WGS84 coordinate to a parcel. Order is LAT,LON -- reversed
    arguments return an empty 204 rather than an error."""
    return _get("/getegrid/json/", {"GNSS": f"{lat},{lon}"}, timeout)


def get_egrid_by_number(bfs: int, number: str, timeout: int = 30) -> dict:
    """Resolve BFS-Nr + parcel number to a parcel."""
    return _get(
        "/getegrid/json/", {"IDENTDN": f"TG{bfs}", "NUMBER": str(number)}, timeout
    )


def extract(egrid: str, geometry: bool = False, timeout: int = 90) -> dict:
    """Full ÖREB extract document for one parcel.

    `geometry=True` adds restriction geometries -- roughly 175 KB -> 248 KB
    per parcel. Off by default: the restriction geometries are not needed
    to know *which* restrictions apply, and the volume adds up fast on a
    per-parcel endpoint.
    """
    params = {"EGRID": egrid}
    if geometry:
        params["GEOMETRY"] = "true"
    return _get("/extract/json/", params, timeout)


def extract_many(
    egrids, delay: float = 0.5, timeout: int = 90, quiet: bool = False
) -> tuple[list[dict], list[str]]:
    """Fetch extracts one parcel at a time. Returns (documents, missed egrids).

    `delay` throttles between requests -- this is a per-parcel endpoint on
    a cantonal service, so don't hammer it.
    """
    docs, missed = [], []
    for i, egrid in enumerate(egrids, 1):
        try:
            docs.append(extract(egrid, timeout=timeout))
            if not quiet:
                print(f"  [{i}/{len(egrids)}] {egrid}: ok")
        except OerebMiss:
            missed.append(egrid)
            if not quiet:
                print(f"  [{i}/{len(egrids)}] {egrid}: no extract (204)")
        if delay:
            time.sleep(delay)
    return docs, missed
