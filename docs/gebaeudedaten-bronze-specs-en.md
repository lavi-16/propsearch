# Bronze Ingestion Specs: Building Data (3 Sources)

**Context:** Extension to the existing PropSearch pipeline (bronze → silver → gold, Supabase/PostGIS).
Existing bronze sources: `landwertzonen`, `bauzonen`, `gefahrenkarte` (all WFS-based).
These three specs add building-level data — the step from "value per zone" to "value for a specific building."

**Suggested order:** GWR first (simplest access, highest value, fits an established ingestion pattern) →
Sonnendach (WFS-like, but a new join key: EGID) → SonBase last (data format needs clarifying first, may require
a genuinely new ingestion pattern).

---

## 1. GWR — Federal Register of Buildings and Dwellings

**Goal:** Building attributes (year built, floor area, number of units, heating type) per building. The highest-leverage
of the three sources, since it moves from a zone-average benchmark to a building-specific valuation basis.

**Source & access — good news:** Kanton Thurgau already publishes the federal GWR openly on `data.tg.ch` as
dataset **`sk-stat-113`**, via the same Opendatasoft API you already use for your existing `sk-stat-*` sources
(Gemeinde statistics). → No need for the federal BFS access request (login + data-protection agreement via
housing-stat.ch, which is otherwise the normal path). Same ingestion pattern as your existing tabular ingestion
from data.tg.ch.

**Known fields** (per the BFS Merkmalskatalog / feature catalog, verify against the actual dataset):
`EGID` / `EWID` (unique building/dwelling ID), geocoded address (SNV standard 612040), building coordinates,
year built, building category, number of dwellings, heating type/energy source (reintroduced since 2015),
parcel number.

**Important caveat from BFS documentation:** GWR data is raw register data — "not corrected, imputed, or
statistically supplemented." Fine for analysis, but flag it explicitly as a raw register in the silver layer,
not as cleaned statistics (consistent with your existing principle that bronze holds the source's raw
representation, not asserted truth).

**Target table:** `bronze.gwr`, keyed on `EGID`.

**Join key:** `EGID` — a new key alongside your existing `gs_egris_egrid` (parcel). One parcel can contain
multiple buildings/EGIDs; the EGID↔EGRID relationship needs to be established explicitly (likely via the
parcel-number field in the GWR dataset, otherwise via a spatial join).

**First task for CC:**
1. Inspect `sk-stat-113` on data.tg.ch — pull the full field list
2. Confirm it can be filtered by Gemeinde/BFS-Nr (same as your existing `sk-stat-*` sources)
3. Check whether a parcel number/EGRID is present in the dataset, or whether a spatial join against
   `bronze.landwertzonen` will be needed

**Acceptance criterion:** For the 5 pilot Gemeinden, a building table exists where at least 90% of rows can be
matched to an EGRID.

---

## 2. Sonnendach.ch — Roof Solar Potential

**Goal:** Solar potential per building as an additional market/amenity dimension.

**Source & access:** BFE (Swiss Federal Office of Energy), federal geoportal layer
**`ch.bfe.solarenergie-eignung-daecher`**. Accessed via the same `api3.geo.admin.ch` API family you already
use for the federal geocoder:
- `SearchServer` for address → coordinate (already in use)
- `MapServer/identify` for the roof at a given coordinate
- `MapServer/find` with `searchField=building_id`, to fetch all roof planes for a building

Alternative: bulk download as GPKG/Filegeodatabase via opendata.swiss, if bulk ingestion is preferred over
point-by-point lookup.

**Confirmed structure:** Geometry is MultiPolygon per roof plane, with a `building_id` field present — likely
the EGID, to be verified against the GWR ingestion (item 1 above). Includes monthly yield values and area,
among other fields.

**Scope:** The 5 pilot Gemeinden only — bbox or Gemeinde boundary clip, same as `bauzonen`.

**Target table:** `bronze.sonnendach`
- Geometry: MultiPolygon, SRID 2056
- Fields: `building_id`, yield class/kWh estimate, roof area, other fields per the API response

**Join key:** `building_id` → to be confirmed as EGID. If confirmed, this becomes a second building-level key
alongside `gs_egris_egrid`, and the same key as GWR.

**First task for CC:** Pull `identify`/`find` responses for 2-3 known addresses in the pilot area, document the
field set, confirm whether `building_id` matches the GWR `EGID`.

**Acceptance criterion:** For a test building in the pilot area, the query returns a plausible roof area +
yield class, linkable via the building ID.

---

## 3. SonBase (BAFU) — Noise Exposure

**Goal:** Noise exposure (road, optionally rail) as a risk/livability signal, analogous to the hazard layer.

**Source:** BAFU (Federal Office for the Environment), layers `ch.bafu.laerm-strassenlaerm_tag` /
`ch.bafu.laerm-strassenlaerm_nacht` (rail noise analogously: `ch.bafu.laerm-eisenbahnlaerm_tag` / `_nacht`).

**Key difference from your existing sources:** This layer is published as **WMTS (raster tiles)**, not WFS —
unlike Gefahrenkarte, Bauzonen, and Landwertzonen, which are all vector WFS. That means `ingest/wfs.py` likely
**cannot** be reused directly here. Two options CC should weigh before building anything:

- **(a) Point sampling:** an `identify` query per building coordinate (from GWR/Sonnendach) — similar pattern
  to your existing geocoding lookups, not a bulk table.
- **(b) Check for a vector alternative:** BAFU may also offer structured downloads (e.g. a noise cadastre per
  building along cantonal roads) — if it exists, that's closer to your existing bulk pattern.

**Scope:** Road noise, day + night, for the 5 pilot Gemeinden; rail noise as a nice-to-have if effort is low.

**Target table:** Proposed `bronze.laerm_punkte` (point value per building coordinate) instead of the bulk-area
pattern used elsewhere — a deliberate deviation from the established pattern that CC should document explicitly.

**Join key:** Spatial (point at building coordinate, or nearest raster cell to the parcel), not attribute-based
like the existing tabular joins.

**First task for CC:** Check the documentation/metadata for `ch.bafu.laerm-*` (GetCapabilities or STAC entry),
determine whether only raster tiles exist or whether structured point/download data is also available, **before**
committing to an ingestion pattern. If unclear, report back to Lavi for a decision rather than committing
unilaterally.

**Acceptance criterion:** For a test building, the query returns an Lr-day and Lr-night value in dB.
