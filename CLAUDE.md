# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

POC data pipeline (`propsearch-data`, v0.1) that joins Kanton Thurgau open geodata + statistics
into a single queryable "parcel record" for property due diligence. Pilot geography is the
Bodensee-front cluster in Bezirk Kreuzlingen (Kreuzlingen, Tägerwilen, Bottighofen,
Münsterlingen, Ermatingen) — canton-wide coverage is explicitly a v2 non-goal.

Read `docs/spec.md` (scope, non-goals, open questions) and `docs/adr/0001-tech-stack.md`
before proposing architecture. The spec's non-goals are deliberate: no scraping integration,
no UI, no scheduling/orchestration, no MCP server. Don't build them.

## Commands

```bash
make setup       # uv sync
make discover    # dump WFS GetCapabilities to docs/wfs-capabilities/
make bronze      # full refresh: pull both sources from WFS and load them
```

Individual steps: `make landwertzonen` / `make bauzonen` / `make bodenpreise`, then
`make bronze-landwertzonen` / `make bronze-bauzonen` (GPKG → Postgres). Fetch and load are
separate so you can iterate on the load without re-hitting the WFS.

Ingest modules import from the package, so run them with `-m`
(`uv run python -m propsearch_data.ingest.load_bronze_bauzonen`), not by file path.

## data.tg.ch (Opendatasoft) — `ingest/opendata.py`

Reachable from the shell, contrary to the original README note. 447 datasets.

- Use `/api/explore/v2.1/catalog/datasets/{id}/exports/json`, **not** `/records` — `/records`
  caps at `limit=100` with an offset ceiling; `exports` streams the whole filtered result.
- Filter with ODSQL via `where`.
- **Type trap:** `bfs_nr_gemeinde` is declared **text** on every dataset checked, so an
  unquoted `IN (4671, …)` fails with `IncompatibleTypesInComparisonFilter`. Use
  `opendata.bfs_in()`. `jahr` is a `date` field, not an integer year.
- These are **time series** (one row per Gemeinde per year), not current-state snapshots.
  Nothing is deduplicated to a "latest" row — the history is the signal the spec wants.
- Coverage windows differ: sk-stat-70 2004–2026, sk-stat-56 2007–2025, sk-stat-58 2015–2025,
  **sk-stat-4 only 2019–2024** — the narrowest, and the binding constraint on any
  cross-dataset join by year.
- Tabular sources land via `bronze.load_table()` (to_sql), not `bronze.load()` (to_postgis).
  `bfs_nr_gemeinde` stays text, so joining to the spatial tables needs an explicit `::int`.

## Bodenpreise (`dfs-sv-1`) — Gemeinde-level CHF context

`ingest/discover_bodenpreise.py`. Steuerverwaltung TG, 8,294 rows canton-wide 2012–2024;
520 in the pilot — a **complete grid** of 5 Gemeinden × 13 years × 8 zone categories, no
nulls. CHF/m² bands for unbuilt, serviced building land, per Gemeinde × zone category × year.

**This is not the parcel-level price path** — `bronze.landwertzonen` already carries CHF/m²
per parcel (see below). Use `dfs-sv-1` for Gemeinde-level context, historical trend, and as a
cross-check on parcel values; not as the primary way to price a parcel.

- **Six-year trailing window, not a spot price.** The 2024 row covers the Bemessungsperiode
  2017-01-01 → 2023-12-31. Consecutive years overlap heavily, so the series is smoothed by
  construction and adjacent-year deltas are not market moves. Some series repeat verbatim
  across two years.
- **There is no median column.** The dataset description explains the Zentralwert at length
  and defines `minimum`/`maximum` as the quartiles around it (deciles where a quartile would
  breach the effective bound) — but only `minimum` and `maximum` are published. `(min+max)/2`
  does **not** recover the median; the bounds are quantiles.
- **Zero is a "no data" sentinel, not a price.** 40 of 520 pilot rows have
  `minimum = maximum = 0`, every one with `markt_ja_nein = 'n'`; no `'j'` row is ever zero.
- `markt_ja_nein` flags a sample of ≥4 transactions. The pilot is 230 `'j'` / 290 `'n'` —
  **most cells are thin**, so `'n'` rows are indicative, not market prices.
- **`bauzone` is NOT the zone code in `bronze.bauzonen`.** This dataset uses 8 coarse
  tax-valuation categories (`1 Kern`, `2 Dorf`, `3 MFH`, `4 EFH`, `5 W+G`, `6 Gewerbe`,
  `7 Industrie`, `8 Weiler`); `bronze.bauzonen` carries 79 distinct municipal codes in the
  pilot alone (`W80`, `WA105`, `W 1.6`, `D`, `StB`…), not even normalised between Gemeinden
  (`W1.6` vs `W 1.6`, `FH` vs `Fh`, `oeBA` vs `OeBA`). No shared key, no published crosswalk —
  the Schätzer-Handbuch PDF attached to the dataset does **not** contain one (checked; it is
  valuation methodology and never mentions these categories). So `dfs-sv-1` joins cleanly on
  (BFS-Nr, jahr) but not to a zone polygon. This is no longer blocking, since parcel pricing
  goes through Landwertzonen instead.

## Landwertzonen carries parcel-level CHF/m² — `lwz` is an index, not a rank

`bronze.landwertzonen` is **not** a rank-only classification. It carries 15 price columns:
`efh_landwertzone1..7`, `ewg_landwertzone1..7` (both CHF/m²) and `gewerbe_industrie`.
Per the Schätzer-Handbuch §2, these are *parzellenscharfe Baulandpreise* produced for the
Steuerverwaltung by Wüest Partner, in three use classes — **EWG** (dense residential: MFH,
Stockwerkeigentum), **EFH** (detached housing), **Gewerbe/Industrie** (no residential share).

**`lwz` (1–7) is the index selecting which band applies to that parcel**, so the price is
`(ARRAY[efh_landwertzone1, …, efh_landwertzone7])[lwz::int]`. It is an **inverse** ordinal:
**1 is the priciest zone**, 7 the cheapest. Verified across all 9,879 pilot rows — `lwz` is
integral 1–7 (76 nulls) and `zone1 ≥ zone2 ≥ … ≥ zone7` holds with zero violations.

That inversion is why a naive `avg(lwz)` looks uncorrelated with price. Don't average `lwz`;
resolve it to CHF first.

Resolved per-Gemeinde EFH means land inside the matching `dfs-sv-1` 2024 band for 4 of 5
pilot Gemeinden. The exception is Münsterlingen (686 vs 852–1113) — which is exactly the cell
flagged `markt_ja_nein = 'n'` (thin sample). Treat that as a consistency check, not proof: it
compares a mean of parcel values against quartile bounds from a different method and vintage.

So the two sources are complementary: **Landwertzonen prices the parcel** (direct on E-GRID,
no spatial join needed), `dfs-sv-1` gives Gemeinde-level bands and history.

## Gefahrenkarte (`bronze.gefahrenkarte`) — the graded hazard layer

`ingest/discover_gefahrenkarte.py`. Three services, one table, 6,422 features in the pilot.
This is what ÖREB can't answer (see the ÖREB section): actual grading, not a presence flag.

| Column | Domain (as landed in the pilot) |
|---|---|
| `gefahrenstufe` | `erheblich` 554, `mittel` 1511, `gering` 2798, `keine` 1519, `Restgefahr` 40 |
| `matrixfeld` | `MF0`–`MF9`, `MF99` — the intensity × probability matrix |
| `prozess_massgebend` | `Seehochwasser_Thurhochwasser`, `Wasser_mitGewaesser.Ueberflutung` / `.Ufererosion`, `Oberflaechenabfluss`, `Rutschung.spontan` / `.permanent`, `kein_Prozess` |

- **Selection is spatial, uniquely among the WFS sources.** These layers carry no Gemeinde
  attribute at all — no `gemcode`, no `t_id`. `discover_gefahrenkarte.py` fetches the five
  pilot polygons from `hoheitsgrenzen` `ms:Gemeinden_Layer`, derives the bbox from them at
  runtime, filters server-side with `wfs.bbox()`, then narrows to rows intersecting a pilot
  Gemeinde. That last step is **row selection only — geometries are never clipped.**
  Don't hardcode the bbox; deriving it is what stops a repeat of the `PILOT_BBOX` miss.
- **The three layers overlap each other, but not themselves.** Verified on the landed data:
  within a layer every matched parcel gets exactly one grading (max = avg = 1.000 for all
  three); across layers a parcel averages 2.97 rows, up to 3. **Filter to one `_source_layer`
  before aggregating** or every parcel triplicates. `_synoptisch` is the combined view;
  `_wasser` and `_rutschungen` are per-process detail over the same ground.
- **`keine` ≠ no match.** 9,005 of 9,879 pilot parcels fall inside the synoptic layer. A
  parcel graded `keine` was surveyed and is clear; a parcel with no match is outside the
  surveyed perimeter — **unknown, not safe.** These are different facts; don't merge them.
- **84 of 6,422 geometries are invalid** (all `Ring Self-intersection`). They land as-is per
  the bronze contract. `ST_Intersects` tolerates them, but silver should `ST_MakeValid`
  before any area or overlay arithmetic.
- Perimeter/metadata layers (`ms:Perimeter_*`, `ms:Hauptprozesse`,
  `ms:Hinweise_auf_bestehende_Gefahrenkarten`, `ms:technische_berichte_gefahrenkartierung`)
  are survey extents, not gradings — deliberately not ingested.

## ÖREB webservice — `ingest/oereb.py`

Base `https://map.geo.tg.ch/services/oereb/`, version `extract-2.0`, 32 themes. This is the
**Restrictions** layer and it is a fundamentally different access pattern: one request per
parcel returning ~175 KB of nested JSON, with no bulk "everything in this Gemeinde" call.
That is why ingestion is a deterministic sample (`PARCELS_PER_GEMEINDE`), not a full pull —
the pilot's 7,296 Bauzonen parcels would be 7,296 requests and >1 GB.

Routes — **TG deviates from the federal spec**:
- `/extract/json/?EGRID=<egrid>` works. The spec's `/extract/reduced/json/{egrid}` path form
  does **not** — the router rejects it with `Unknown action requested: reduced`, and the
  flavour (reduced/full/signed) can't be selected.
- `/getegrid/json/?` accepts three working selectors: `EN=<easting>,<northing>` (**LV95**),
  `GNSS=<lat>,<lon>` (**WGS84, lat first**), and `IDENTDN=TG<bfs>&NUMBER=<parcel>`.
  `XY=` is the old **LV03** frame and returns a silent HTTP 204 for LV95 input.
- `GEOMETRY=true` on the extract adds restriction geometries (175 KB → 248 KB per parcel).
  Off by default in `oereb.extract()`.
- Treat HTTP 204 as a miss throughout; the service uses it for "no match" — including for a
  correct-but-reversed `GNSS=lon,lat`, which fails silently rather than erroring.

**Resolves the spec's "address → parcel resolution" open question:** coordinate → E-GRID works
via `EN=` (LV95) or `GNSS=` (WGS84). `GNSS` is the one to use downstream of a geocoder, since
geocoders return WGS84. (Address → coordinate still needs a geocoder.)

**JSONB gotcha:** pass the Python dict to a JSONB column, never `json.dumps(...)` of it.
A pre-encoded string lands as a JSON *string* scalar, and every `->` lookup then silently
returns NULL rather than erroring. Check with `jsonb_typeof(...) = 'object'`.

**`municipality_code` is not always a Swiss BFS-Nr.** Two sampled Tägerwilen parcels come back
as municipality `Tägermoos` with code `8274` — Tägermoos is Swiss territory administered from
Konstanz. Don't key Gemeinde joins on the ÖREB municipality field; use the BFS-Nr carried
alongside from the source layer.

## Adding a new source

The client modules and `bronze.py` hold the shared plumbing; a source module should be thin
config on top of them, not a new copy of the fetch loop.

- `ingest/wfs.py` — `fetch()` (paging, GML→GeoDataFrame, `.gfs` cleanup, ExceptionReport
  sniffing), `property_equals_any()` / `property_like_any()` (FES 2.0 filters), `count()`
  (`RESULTTYPE=hits`, used to assert the fetch got everything)
- `ingest/opendata.py` — `export()` / `export_frame()`, `bfs_in()`, `field_types()`
- `ingest/oereb.py` — `extract()` / `extract_many()`, `get_egrid_by_coordinate()` /
  `_by_number()`, `topics()`
- `bronze.py` — `tag_provenance()`, `combine()`, `load()` (spatial), `load_table()`
  (non-spatial, with `dtype` passthrough for JSONB), `summarise()` / `summarise_table()`

Pattern: `discover_<source>.py` fetches to `data/bronze/`, `load_bronze_<source>.py` loads
that into `bronze.<table>`. Fetch and load are separate so the load can be iterated on
without re-hitting the upstream service.

`propsearch_data.db.get_engine()` anchors `.env` to the repo root, not the cwd — scripts work
from any directory.

No test suite, linter, or formatter is configured yet. Dependencies are managed with `uv`
(`uv add <pkg>`), not pip.

## Database connection (Supabase)

Use `propsearch_data.db.get_engine()` rather than building an engine ad hoc — it encodes two
gotchas that otherwise cost an hour each:

- SQLAlchemy resolves bare `postgresql://` to **psycopg2**, which isn't installed; the project
  uses psycopg 3. `get_engine()` rewrites the scheme to `postgresql+psycopg://`.
- The Supabase **direct** host `db.<ref>.supabase.co` is **IPv6-only** and unreachable from
  this WSL environment. Use the Supavisor pooler (`aws-0-<region>.pooler.supabase.com`, user
  `postgres.<ref>`) on **port 5432 / session mode** — port 6543 is transaction mode and breaks
  prepared statements used by bulk loads. This project is on `eu-central-1`.
- `<ref>.supabase.co` *without* the `db.` prefix is the Cloudflare REST endpoint, not Postgres.
  Pointing `DATABASE_URL` there times out on 5432 with no useful error.

Server is Postgres 17.6 with PostGIS 3.3.7 already installed.

## Network access

`ows.geo.tg.ch` **is reachable from Claude Code's Bash tool** (verified 2026-08-13 — WFS
GetCapabilities, DescribeFeatureType and GetFeature all succeed via `curl`/`requests`). The
README's claim that the sandbox is blocked applies to the web-fetch tool honouring robots.txt,
not to Bash. Discovery and ingestion can be run and verified here directly; don't hand these
scripts back to the user unrun.

Unknown slugs return HTTP 401, so probing candidates is cheap and safe.

## Bronze/gold sequencing (explicit user decision, 2026-08-13)

Bronze tables now; **the gold schema is not to be designed yet**. Shaping a gold table around
one source in isolation would lock in a shape before it's known what the other four sources
need to join against. Gold-schema design is its own step, once Landwertzonen plus a couple of
other bronze sources have landed and can be checked against each other. Do not create
`parcel_land_value`-style tables ahead of that.

Landed so far — all five spec layers now have a bronze source:

| Table | Rows | Source | Access pattern |
|---|---|---|---|
| `bronze.landwertzonen` | 9,879 | `landwertzonen` WFS | bulk, spatial (Point) |
| `bronze.bauzonen` | 1,609 | `oereb_ortsplanung_bauzonen` WFS | bulk, spatial (MultiPolygon) |
| `bronze.gemeinde_steuerfuss` | 115 | data.tg.ch `sk-stat-70` | bulk, tabular |
| `bronze.gemeinde_finanzkennzahlen` | 30 | data.tg.ch `sk-stat-4` | bulk, tabular |
| `bronze.gemeinde_bevoelkerung` | 95 | data.tg.ch `sk-stat-56` | bulk, tabular |
| `bronze.gemeinde_bevoelkerung_alter` | 2,090 | data.tg.ch `sk-stat-58` | bulk, tabular |
| `bronze.bodenpreise` | 520 | data.tg.ch `dfs-sv-1` | bulk, tabular |
| `bronze.gefahrenkarte` | 6,422 | 3 × `ng_gefahrenkarte_*` WFS | bulk, spatial (MultiPolygon) |
| `bronze.oereb_extract` | 25 | ÖREB webservice | **per-parcel query** |
| `bronze.oereb_restriction` | 80 | (unnested from above) | — |

Bronze contract, as applied in `propsearch_data/bronze.py`:
- Source names and types preserved — no renaming, casting, unit fixes, or dropping
  redundant-looking columns. Wrong values stay wrong in bronze; silver corrects them.
- Only additions are provenance columns prefixed `_` (`_source_layer`, `_source_url`,
  `_source_file`, `_ingested_at`).
- Only removals are GML transport plumbing (`lowerCorner`/`upperCorner`).
- Reload is full-replace of the pilot slice — these are manual snapshot pulls.

**Fidelity caveats — what lands is GDAL's rendering of the source, not the source verbatim:**
- The WFS XSDs declare most attributes `string`, but GDAL's GML reader infers types on read,
  so bronze lands GDAL-typed (mostly integer, `lwz` as double precision).
- GDAL's **GPKG writer** promotes Polygon→MultiPolygon at the `data/bronze/` staging step,
  because a GPKG layer declares one geometry type. `ms:bau` arrives from the WFS as 1,568
  Polygon + 41 MultiPolygon and lands as 1,609 MULTIPOLYGON. Lossless, but not faithful.

Silver should assert types and geometry explicitly rather than trusting these.

## The grounding rule

The gold-layer schema is intentionally unwritten. `src/propsearch_data/models.py` and
`sql/schema/` are empty placeholders, and they stay that way until real field names are
confirmed via WFS `DescribeFeatureType` output. Do not invent column names, types, or
service slugs — the discovery scripts exist specifically to replace guesses with confirmed
values.

Confirmed so far:
- URL pattern `https://ows.geo.tg.ch/geofy_access_proxy/{slug}` is real. Live slugs:
  `datensammelstellen`, `oereb_ortsplanung_bauzonen`, `gewaesserkataster_gewaesser`,
  `landwertzonen`, `hoheitsgrenzen`
- Layer names are prefixed `ms:` (e.g. `ms:DS_Oereb`)
- **These services serve GML only** — `OUTPUTFORMAT=application/json` is rejected with
  `InvalidParameterValue`. Read responses with `geopandas.read_file()`, never `r.json()`.
- Server-side OGC Filter Encoding 2.0 (`FILTER=<fes:Filter>…`) works, as do `RESULTTYPE=hits`
  and `COUNT`/`STARTINDEX` paging. Prefer an attribute filter over a bbox for area selection.
- `ms:Gemeinden_Layer` on `hoheitsgrenzen` is the authoritative Gemeinde reference
  (`gemeinde_name`, `gemeinde_bfsnr`, `bezirk`; 80 rows). Use it instead of hardcoding BFS
  numbers from memory.

**Gefahrenkarte is WFS**, not WMS-only as originally assumed — so it fits the existing
`wfs.py` code path. Slug pattern `ng_gefahrenkarte_<process>`; live services are
`_synoptisch` (`ms:Gefaehrdung_synoptisch`, `ms:Hauptprozesse`, perimeters), `_wasser`
(`ms:Gefaehrdung_Wasser`), `_rutschungen` (`ms:Gefaehrdung_Rutschungen`) and
`_erhebungsgebiet`. Ingested — see the Gefahrenkarte section above.

Add newly confirmed endpoints to the `ENDPOINTS` dict in `ingest/discover_capabilities.py`.

Resolved spec open questions (update `docs/spec.md` as these land):
- **Gemeinde-ID reconciliation** — `gemcode` in the Landwertzonen layers *is* the BFS-Nr,
  cross-checked against `gemeinde_bfsnr` (Kreuzlingen = 4671 in both).
- **Parcel resolution** — features carry `gs_egris_egrid`, the federal E-GRID parcel ID, with
  no nulls. Land value joins to a parcel directly on EGRID; no point-in-polygon needed there.
  Note the geometry is a **Point per parcel**, not zone polygons as the spec assumed.
- **Land value in CHF** — carried per parcel by `bronze.landwertzonen` itself
  (`efh_landwertzone1..7` / `ewg_landwertzone1..7` / `gewerbe_industrie`, selected by `lwz`),
  so no zone-code crosswalk is needed to price a parcel.

Pilot Gemeinden (verified, all Bezirk Kreuzlingen): Bottighofen 4643, Ermatingen 4646,
Kreuzlingen 4671, Münsterlingen 4691, Tägerwilen 4696.

## Join strategy differs per layer — check before assuming

The two layers inspected so far do *not* share a join key, so there is no single approach:

| Layer | Geometry | Key | Join |
|---|---|---|---|
| `landwertzonen` (`ms:Landwertzonen_*`) | Point, one per parcel | `gs_egris_egrid`, `gemcode` | direct on E-GRID (carries CHF/m², see above) |
| `oereb_ortsplanung_bauzonen` (`ms:bau`) | Polygon | no E-GRID; `t_id` is `<bfs>_<id>` | spatial (point-in-polygon) |
| `ng_gefahrenkarte_*` | Polygon | **no Gemeinde key at all** | spatial both ways: bbox to select, point-in-polygon to join |

In `bronze.landwertzonen`, `gs_egris_egrid` is **unique across all 9,879 rows** — the three
source layers partition the parcel space with zero overlap, so there is exactly one land-value
row per parcel. Single vintage so far (`jahr` = 2024), no null E-GRIDs.

In `bronze.bauzonen`, `gml_id` is **empty on every feature** — the natural key is `t_id`
(unique, formatted `<bfs>_<id>`). Selection uses a `t_id` prefix filter, verified exhaustively:
the 19,425 canton-wide features carry exactly 80 distinct prefixes, matching the 80 Gemeinden
in `hoheitsgrenzen` one for one. So a prefix filter is equivalent to selecting by Gemeinde.

So PostGIS is genuinely required for zoning even though land value alone wouldn't need it.
`ms:bau` also carries `es_txt` (Empfindlichkeitsstufe) and `bezeichnung`/`gn_kuerzel` (zone
code, e.g. `W2a`; null on a few features). Beware `gn_gmdname`/`gn_kantname` — these are the
Gemeinde's vs. canton's *name for the zone type*, not Gemeinde names. Layers suffixed `_vx`
are pending amendments, not current state; exclude them unless you specifically want proposed
changes. `oereb_ortsplanung_bauzonen` also serves `ms:landwirt`, `ms:ueberlagernd` and
`ms:les` — same code path, but each needs its own check that `t_id` is present and prefixed
the same way before being added to `TYPENAMES`.

**Verified cross-source properties** (read-only smoke tests, nothing materialised):
- Bauzonen polygons do not overlap — zero land-value points fall in more than one — so a
  point-in-polygon join yields at most one zone per parcel.
- 99.0% of `Landwertzonen_Bauz` points fall inside a Bauzone; 99.4% of `aus_Bau` fall outside.
  The layer names hold up.
- All 25 ÖREB-sampled E-GRIDs exist in `bronze.landwertzonen`, and ÖREB `Number` matches
  `gs_nummer` 25/25.
- ÖREB `ch.Nutzungsplanung` agrees with the Bauzonen WFS on the base zone for **25/25**
  parcels. When comparing, strip the ` (CODE)` suffix ÖREB appends to `legend_text`
  (`Wohnzone W 1.6 (W 1.6)` vs `Wohnzone W 1.6`) — naive string equality scores 0/39 and looks
  like total disagreement. Remaining differences are overlay restrictions
  (Gestaltungsplanpflicht, Umgebungsschutzzone, Gefahrenzone…), which are additional, not
  contradictory.
- **ÖREB does not answer the hazard question.** `ch.Gefahrenzone` is **not** a TG ÖREB theme —
  it is absent from the service's 32 themes and from both `ConcernedTheme` and
  `ThemeWithoutData` on all 25 sampled parcels. Hazard reaches ÖREB only as a
  `ch.Nutzungsplanung` *overlay label* (`Gefahrenzone`, `Gefahrenzone (GF)`,
  `Gefahrenzonen (Gef)`, `Gebiete mit Hochwasserschutz (Hs)` — three spellings across four
  Gemeinden, unnormalised like the Bauzonen codes). 7 of 25 sampled parcels carry one.
  That is a **binary presence flag**: `type_code` is empty on every such row, and searching
  all 25 extracts for `HQ30`/`HQ100`/`HQ300`, `Wiederkehr`, `Jährlichkeit`, `Intensität`,
  `Gefahrenstufe` returns zero hits. What it does give is `area_share` (m²),
  `part_in_percent`, `lawstatus` and an oereblex link to the ordinance.
  Graded intensity requires `bronze.gefahrenkarte` — see below.
- `ch.Gewaesserraum` is likewise binary (bare `Gewässerraum` legend, empty `TypeCode`), and is
  `ThemeWithoutData` on 24 of 25 parcels — **"no data published", not "no restriction"**.
  Don't read its absence as safety.

When code contains a guess, mark it as one in the docstring or comment the way the existing
scripts do (e.g. `PILOT_BBOX` is flagged as approximate). This repo distinguishes verified
facts from plausible ones on purpose.

## Conventions

- **CRS is EPSG:2056 (LV95)** for all spatial data. Alignment across sources is a stated
  success criterion; don't mix in WGS84 without an explicit reprojection step.
- **Gemeinde joins key on BFS-Nr** — but whether the geodata layers key the same way as the
  statistics tables is still an open question (`docs/spec.md`). Verify before joining.
- Layout: `ingest/` is one module per data source (bronze pulls), `transform/` holds
  bronze → silver → gold logic, `sql/schema/` holds DDL.
- `docs/wfs-capabilities/` is gitignored (dump output), as are `.env` and `data/bronze|silver/`.
  The one checked-in capabilities dump is the confirmed reference sample.
- DB is Postgres + PostGIS via `DATABASE_URL` (Supabase by default, swappable to local).
- Bronze pulls are written to `data/bronze/` as GeoPackage (gitignored). GPKG over GeoJSON
  because it preserves the EPSG:2056 CRS and column types without a reprojection round-trip.
