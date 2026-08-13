"""
Shared client for data.tg.ch (an Opendatasoft "Explore" portal).

Confirmed against the live portal (2026-08-13):

- The portal IS reachable from a normal network and from Claude Code's
  shell, contrary to the original README note. 447 datasets published.
- Explore API v2.1 is available at
  /api/explore/v2.1/catalog/datasets/{id}. The legacy
  /api/records/1.0/search/ endpoint also still answers, but v2.1 is the
  one to build on.
- Use the `/exports/json` endpoint, not `/records`. `/records` caps at
  limit=100 with an offset ceiling, so bulk pulls need paging;
  `/exports/json` streams the whole filtered result in one request.
- Filtering uses ODSQL via the `where` parameter.

TYPE TRAP: `bfs_nr_gemeinde` is declared **text**, not int, on every
dataset checked. An unquoted `IN (4671, ...)` fails with
IncompatibleTypesInComparisonFilter. `bfs_in()` below quotes correctly.
`jahr` is likewise a `date` field, not an integer year.
"""

import json
from pathlib import Path

import pandas as pd
import requests

BASE = "https://data.tg.ch/api/explore/v2.1/catalog/datasets"


def bfs_in(column: str, bfs_numbers) -> str:
    """ODSQL predicate matching a text BFS column against the given numbers."""
    quoted = ", ".join(f'"{b}"' for b in sorted(bfs_numbers))
    return f"{column} IN ({quoted})"


def metadata(dataset_id: str, timeout: int = 60) -> dict:
    resp = requests.get(f"{BASE}/{dataset_id}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def field_types(dataset_id: str) -> dict[str, str]:
    return {f["name"]: f["type"] for f in metadata(dataset_id).get("fields", [])}


def export(
    dataset_id: str, where: str | None = None, timeout: int = 180
) -> list[dict]:
    """Full filtered export as a list of records."""
    params = {}
    if where:
        params["where"] = where
    resp = requests.get(
        f"{BASE}/{dataset_id}/exports/json", params=params, timeout=timeout
    )
    if resp.status_code == 400:
        # ODSQL errors come back as structured JSON; surface them usefully.
        try:
            err = resp.json()
            raise RuntimeError(
                f"{dataset_id}: {err.get('error_code')} -- {err.get('message')}"
            )
        except ValueError:
            pass
    resp.raise_for_status()
    return resp.json()


def export_frame(dataset_id: str, where: str | None = None) -> pd.DataFrame:
    return pd.DataFrame(export(dataset_id, where))


def save_json(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
