"""
Shared WFS client for the Thurgau geodata services.

Service quirks this encapsulates (all confirmed against ows.geo.tg.ch):
  - GML is the only usable output. `OUTPUTFORMAT=application/json` is
    rejected with InvalidParameterValue, so responses are written to a
    temp .gml and read with geopandas/GDAL.
  - GDAL leaves a .gfs schema sidecar next to any .gml it reads; both are
    cleaned up here.
  - `numberMatched` is often "unknown", so paging runs until a short page
    comes back rather than trusting a declared total.
  - Errors arrive as HTTP 200 with an ows:ExceptionReport body, so the
    payload has to be sniffed rather than relying on status codes.

Selection is by server-side OGC Filter Encoding 2.0 predicate. Prefer that
over a bounding box: a bbox has to be guessed and can silently miss the
target area entirely (see the PILOT_BBOX history in
discover_landwertzonen.py).
"""

from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import pandas as pd
import requests

FES_NS = "http://www.opengis.net/fes/2.0"
DEFAULT_PAGE_SIZE = 5000

# GML envelope corners -- transport plumbing, not source attributes.
GML_PLUMBING = ("lowerCorner", "upperCorner")


def _wrap(clauses: list[str]) -> str:
    inner = f"<fes:Or>{''.join(clauses)}</fes:Or>" if len(clauses) > 1 else clauses[0]
    return f'<fes:Filter xmlns:fes="{FES_NS}">{inner}</fes:Filter>'


def property_equals_any(prop: str, values) -> str:
    """Filter matching `prop` against any of `values` exactly."""
    return _wrap(
        [
            "<fes:PropertyIsEqualTo>"
            f"<fes:ValueReference>{escape(prop)}</fes:ValueReference>"
            f"<fes:Literal>{escape(str(v))}</fes:Literal>"
            "</fes:PropertyIsEqualTo>"
            for v in values
        ]
    )


def property_like_any(prop: str, patterns) -> str:
    """Filter matching `prop` against any of `patterns` ('*' is the wildcard)."""
    return _wrap(
        [
            '<fes:PropertyIsLike wildCard="*" singleChar="?" escapeChar="!">'
            f"<fes:ValueReference>{escape(prop)}</fes:ValueReference>"
            f"<fes:Literal>{escape(str(p))}</fes:Literal>"
            "</fes:PropertyIsLike>"
            for p in patterns
        ]
    )


def _read_gml(payload: bytes, work_dir: Path, stem: str) -> gpd.GeoDataFrame:
    gml = work_dir / f"_page_{stem}.gml"
    gml.write_bytes(payload)
    try:
        return gpd.read_file(gml)
    finally:
        gml.unlink(missing_ok=True)
        gml.with_suffix(".gfs").unlink(missing_ok=True)


def fetch(
    service_url: str,
    typename: str,
    fes_filter: str | None = None,
    work_dir: Path | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: int = 120,
    quiet: bool = False,
) -> gpd.GeoDataFrame:
    """Page through GetFeature for one typename, returning a GeoDataFrame."""
    work_dir = work_dir or Path(".")
    work_dir.mkdir(parents=True, exist_ok=True)
    short = typename.split(":")[-1]
    frames, start = [], 0

    while True:
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "COUNT": page_size,
            "STARTINDEX": start,
        }
        if fes_filter:
            params["FILTER"] = fes_filter

        resp = requests.get(service_url, params=params, timeout=timeout)
        resp.raise_for_status()
        if b"ExceptionReport" in resp.content[:2000]:
            raise RuntimeError(f"{typename}: WFS exception\n{resp.text[:500]}")

        page = _read_gml(resp.content, work_dir, f"{short}_{start}")
        if page.empty:
            break

        frames.append(page)
        if not quiet:
            print(f"  {typename}: +{len(page)} (offset {start})")
        if len(page) < page_size:
            break
        start += page_size

    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2056")

    out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    return out.drop(columns=[c for c in GML_PLUMBING if c in out.columns])


def count(service_url: str, typename: str, fes_filter: str | None = None) -> str:
    """Server-side match count via RESULTTYPE=hits (may return 'unknown')."""
    import re

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "RESULTTYPE": "hits",
    }
    if fes_filter:
        params["FILTER"] = fes_filter
    resp = requests.get(service_url, params=params, timeout=60)
    resp.raise_for_status()
    m = re.search(r'numberMatched="([^"]+)"', resp.text)
    return m.group(1) if m else "unknown"
