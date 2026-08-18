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
make silver      # rebuild schema `silver` from bronze (pure DB-to-DB)
make test        # pytest -- read-only assertions against the built silver
```

Individual steps: `make landwertzonen` / `make bauzonen` / `make bodenpreise`, then
`make bronze-landwertzonen` / `make bronze-bauzonen` (GPKG → Postgres). Fetch and load are
separate so you can iterate on the load without re-hitting the WFS.

Ingest modules import from the package, so run them with `-m`
(`uv run python -m propsearch_data.ingest.load_bronze_bauzonen`), not by file path.

## data.tg.ch (Opendatasoft) — `ingest/opendata.py`

Reachable from the shell, contrary to the original README note. 447 datasets.

- **A dataset resolving in the catalogue does NOT mean it has data.** Before treating any
  data.tg.ch ID as a source, check `has_records` is true and `/records?limit=1` returns a
  non-empty `results`. `sk-stat-113` (GWR) has a title, a long description, keywords, a
  licence and a publisher — and `has_records: false`, `records_count: 0`, zero fields, zero
  attachments; both `/records` and `/exports/json` return empty. It is a **pointer to a
  federal source**, not a copy of one. A 200 from `/catalog/datasets/{id}` proves only that
  the metadata record exists. Expect this again on other `sk-stat-*` IDs.
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

## GWR (`bronze.gwr_*`) — the building layer, and a new grain

`ingest/madd.py` + `ingest/discover_gwr.py`. The federal Gebäude- und Wohnungsregister:
11,217 buildings and 11,489 entrances in the pilot, from the **BFS MADD public download**
`https://public.madd.bfs.admin.ch/tg.zip` — no auth, ~35 MB, refreshed daily.

**Not from data.tg.ch.** `sk-stat-113` looks like the obvious route and is an empty stub —
see the data.tg.ch section above for the standing check that came out of it.

**Not from the Kanton TG WFS either,** though `geofy_access_proxy/gwr` is live and serves
`ms:gwr_gebaeude` with native Point geometry, `egrid` and `grundstuecksnummer`. Three
reasons, the first serious:

- **`gemeindename` is truncated to 10 characters, and the layer carries no BFS-Nr at all.**
  So `property_equals_any()` — the established selection pattern — silently returns a
  fraction of a Gemeinde: `Bottighofen` → **18** hits vs `Bottighofe*` → 886; `Kreuzlingen`
  → **159** vs `Kreuzlinge*` → 5,334; `Münsterlingen` → **32** vs `Münsterlin*` → 1,352.
  `Ermatingen` and `Tägerwilen` are exactly 10 characters and work fine, which makes the
  failure look like a data gap in the other three rather than a systematic bug. Same class
  as the `PILOT_BBOX` miss. If this layer is ever used, filter with `property_like_any()`
  on a prefix — there is no BFS column to fall back to.
- Attributes are German labels (`Gebäude ohne Wohnnutzung`), not the GWR numeric codes, so
  the published code table can't be applied.
- No dwelling level.

**The parcel join is an attribute join, not a spatial one.** The building record carries
`EGRID` in the same federal form as `bronze.landwertzonen.gs_egris_egrid`. Measured against
the built `silver.parcel`: **10,344 of 11,217 (92.2%)** join directly, so the spec's 90%
acceptance criterion is met with no point-in-polygon step. Of the 873 that don't, 383 carry
no EGRID at all and 490 sit on a parcel outside the pilot's Landwertzonen set. 6,641 of
9,879 pilot parcels (67.2%) carry at least one building.

**EGID is a new grain, one level BELOW the parcel.** 2,435 pilot parcels carry more than one
building, up to **29**. Joining `gwr_gebaeude` to the 9,879-row parcel spine multiplies it —
the same hazard as the Gefahrenkarte 2.97× fan-out. Aggregate first, or keep it as a
separate fact.

**`gwr_eingang` resolves address → parcel without a geocoder** (for the pilot). 10,286
distinct `(street, house number, PLZ)` keys, and **zero** of them resolve to conflicting
parcels; 9,803 (95.3%) resolve to a single EGRID present in `silver.parcel`. `DKODE`/`DKODN`
give the LV95 coordinate on 97.7% of rows, so a table lookup replaces both the geocoder and
the ÖREB `getegrid` round-trip inside these five Gemeinden. A geocode cache is still needed,
but only for the residual: new construction not yet in the register, non-official entrances,
the 1.1% with no house number, and anything outside the pilot. `EGAID` (100% populated) is
the federal address ID to key that cache on.

**`GSTAT` must be filtered before anything is shown as current.** The pilot holds 10,392
existing (`1004`), **700 demolished (`1007`)** and 125 projected/approved/under construction
(`1001`/`1002`/`1003`/`1008`). Bronze keeps all of them on purpose. A demolished building's
row looks entirely normal — every other column is populated exactly as it was the day it
came down — so surfacing one as a parcel's current state is a real correctness bug, not a
cosmetic one.

**It is a raw register, not statistics.** BFS states the data is "not corrected, imputed, or
statistically supplemented". Pilot fill rates: `GBAUJ` 80.7%, `GBAUP` 90.6%, `GAREA` 97.3%,
`GASTW` 67.5%, `GANZWHG` 62.7%, `GENH1` 70.3%, `GEBF` 6.6%, `GVOL` 3.5%. A null means
unrecorded — not zero, and not "no such feature". Model it the way `hazard_surveyed` already
distinguishes measured absence from unknown.

**Codes stay raw; `bronze.gwr_kodes` (405 rows) is the publisher's own lookup**, keyed
`(cecodid, cmerkm)` — unique on those two together, and `cmerkm` is the *attribute* the code
belongs to, not a category. **Join on both columns**: `857` is defined five times over, once
each for `GVOLSCE`, `GWAERSCEH1`, `GWAERSCEH2`, `GWAERSCEW1` and `GWAERSCEW2`, so joining on
`cecodid` alone fans out. Decoding happens in silver — the `gn_kantname` precedent, where the
source publishes its own classification and a hand-built crosswalk is the wrong move.

Other traps:
- The CSVs are **tab-delimited** with a utf-8 BOM, despite the `.csv` extension.
- Everything is read as `str`. `GEBNR`/`LPARZ` hold values like `1/721` and `1/.146`.
- **Ignore `buildings.geojson` / `entrances.geojson` / `data.sqlite` in the zip.** The
  geojson is Points at the same coordinates but a renamed, energy-focused *subset* — no
  `EGRID`, no `GBAUJ`, no `GAREA`, no `GANZWHG`. The CSVs are the complete record.
- `eingang` and `wohnung` carry **no Gemeinde column** — filter them on the pilot `EGID` set.
- `GGDENR` is text (as every MADD column is), so the pilot filter compares strings — the
  `bfs_nr_gemeinde` type trap in a new place.
- `discover_gwr.py` asserts a **range**, not an exact count: `GEXPDAT` is stamped daily and
  buildings come and go, so `== 11217` would fail on a routine rerun because the data moved.
  What is exact is that no Gemeinde may come back empty.

`bronze.gwr_wohnung` (22,249 pilot rows, PK `(EGID, EWID)` — per-dwelling area, rooms,
floor) is **not landed**; the fetch already reads the file, so adding it is one load script.

**Silver/gold now built — GWR is the new building grain.** `silver.building` (11,217, PK
`egid`) is the spine, and it settled the three gating questions as declared constraints:
- **GSTAT** — all states kept; `is_existing boolean` CHECKed against `gstat = '1004'`, so a
  demolished (`1007`) building can never be counted as current. `gold.building` (10,392)
  filters to existing via a CHECK, the `gold.parcel_hazard` synoptic-exclusion precedent.
- **null-means-unrecorded** — empty MADD strings land as NULL; numeric columns stay nullable
  and are never coalesced to 0 (a CHECK forbids a 0).
- **EGRID is a link, not a key** — nullable plain column, **not a FK** (383 have none, 490 sit
  on a parcel outside the pilot); the 92.2% (10,344) join to `silver.parcel` is asserted.
- Codes decoded in silver by joining `bronze.gwr_kodes` on **both** `(cecodid, cmerkm)` — the
  `gn_kantname` "source ships its own lookup" precedent, no hand-built crosswalk.

`gold.building` joins the building to its solar (`silver.building_solar`) and noise
(`silver.building_noise`) facts, and links to `gold.parcel` on `egrid` (many buildings per
parcel). `gold.parcel` gained pre-aggregated rollups (`n_buildings`, `best_solar_class`,
`has_solar_potential`, `max_noise_day`/`_night`) that leave its 9,879-row grain intact.

## Sonnendach (`bronze.sonnendach`) — roof solar potential, a third grain

`ingest/discover_sonnendach.py` + `ingest/bgdi.py`. BFE layer
`ch.bfe.solarenergie-eignung-daecher`: one MultiPolygon per **roof plane**, with a modelled
annual electricity/heat yield, orientation, tilt, area and a **1–5 suitability class**.
10,071,755 planes nationally; **34,358 in the pilot**. This is the second
building-level source (`docs/gebaeudedaten-bronze-specs-en.md` §2) and the first via the
federal BGDI bulk route.

**The spec's proposed access route does not work — three findings overturned it** (confirmed
live 2026-08-14/17):
- **`building_id` is NOT the EGID.** The spec assumed it was. The api3 `identify` response
  carries *both* a swisstopo `building_id` **and** a separate `gwr_egid`, different values and
  different cardinality (71 vs 46 distinct in one box). The bulk GeoPackage settles it: it
  carries **`GWR_EGID`** and no `building_id` column at all. Join on `gwr_egid` — it is the
  same federal id as `bronze.gwr_gebaeude.egid`. A join on `building_id` would silently
  produce garbage, not fail.
- **`MapServer/find` is dead here** — the layer is `"searchable": false` in `layersConfig`
  and returns HTTP 502/504.
- **`MapServer/identify` caps at 201 rows** regardless of area, and `offset` paging has
  **unstable ordering** (adjacent pages overlap by 17 and 34 rows), so a sweep **cannot be
  proven complete**. No WFS is reachable either (`wfs.geo.admin.ch` doesn't resolve here;
  `ows.geo.tg.ch/geofy_access_proxy/solarenergie` is a pass-through to the federal WMS with
  WFS disabled). **The STAC bulk GeoPackage is the only complete, reproducible route.**

**Access is bulk, via `ingest/bgdi.py`** (the project's 5th client — federal BGDI asset via
STAC, scoped so SonBase can reuse it). STAC collection → one item → `assets` dict → asset
`solarenergie-eignung-daecher_2056.gpkg.zip` (**1.5 GB zip → 4.58 GB member
`SOLKAT_DACH.gpkg`**). Both the zip and the extracted member are cached in `data/bronze/`,
same fetch/load split as MADD.
- **The member is DEFLATE64 (method 9).** The stdlib `zipfile` raises `NotImplementedError`
  and no `unzip`/`7z`/`bsdtar` is installed, so `bgdi.py` depends on **`zipfile_deflate64`**
  (a drop-in `ZipFile`). Real dependency, not convenience — added via `uv add`.
- **Don't use `/vsizip//vsicurl/` for a remote peek** — the member is deflated, so GDAL must
  inflate the whole stream to reach any page; the remote peek timed out. Extract locally once,
  then read normally — the GeoPackage carries an **RTree**, so a pilot-window `bbox` read is
  ~1 s over the 10-million-feature national layer.

**Selection is spatial, like Gefahrenkarte.** Roof planes carry no Gemeinde attribute, so the
five pilot boundaries come from `hoheitsgrenzen` `ms:Gemeinden_Layer`, their bbox drives the
windowed read, and rows are narrowed to those intersecting a pilot Gemeinde — **row selection
only, geometries never clipped.** Per-Gemeinde: Bottighofen 2,464 / Ermatingen 5,230 /
Kreuzlingen 17,033 / Münsterlingen 4,077 / Tägerwilen 5,565 — none empty (the assertion).

**A THIRD grain, one level below the building.** parcel (E-GRID) → building (EGID) → **roof
plane**. The unique key is **`DF_UID`** (verified unique on all 34,358); `(gwr_egid, df_nummer)`
is **not** unique. ~3 planes per building (a roof is split by pitch/orientation — south rated
apart from north). Joining straight to the 9,879-row parcel spine fans out **twice**: up to 29
buildings/parcel (GWR) × ~3 planes/building. Aggregate to EGID first (max `klasse`, sum
`flaeche`/`stromertrag`), or keep it a separate fact.

**Measured join.** 7,414 of 10,392 existing (`gstat='1004'`) pilot buildings (**71.3%**) carry
≥1 roof plane; through them **5,476 `silver.parcel` rows** are reachable. The ~29% of buildings
with no roof are **small/minor structures the survey excludes** — normal coverage, not a
defect. (The spec's cross-layer test parcel `CH107710829377` is exactly such a case: its one
building has no roof plane within 12 m, so it is not a valid Sonnendach demonstrator. Use a
roofed building, e.g. egid 663567 on `CH257817784197`: 6 planes, best class 4, 272 m², ~44,900
kWh/yr.)

**`gwr_egid` arrives as `double precision` with NULLs**, not integer. It is int32 in source,
but 6.3% of pilot planes have no register link and a nullable integer is rendered by
GDAL/pandas as float64 with NaN (same class as `lwz` landing double). **Silver casts it to the
text E-GID form** — `(gwr_egid)::bigint::text` — to join `bronze.gwr_gebaeude.egid`; reading
the float straight, `2337457.0` will not match the text `'2337457'`. A NULL is an **unlinked**
roof (surveyed, no register match), not "no roof" — keep it, the `hazard_surveyed`
measured-absence distinction.

**Other traps:**
- **Columns land lower-cased.** The SOLKAT GeoPackage stores them UPPER-CASE and GDAL
  preserves that, so `load_bronze_sonnendach.lower_columns()` applies the same mechanical
  fix `load_bronze_gwr` does. Nothing else touched.
- **69 of 34,358 geometries are invalid** (self-intersections), landed as-is per the bronze
  contract; silver `ST_MakeValid` before any area/overlay arithmetic, as `silver.hazard_zone`
  does for Gefahrenkarte.
- **`klasse` is a 1–5 ordinal**, worst→best, decoded by the file's own `EIGNUNG_DACH` lookup
  (fid = klasse): 1 `gering` (<800 kWh/m²/yr), 2 `mittel` (800–1000), 3 `gut` (1000–1200),
  4 `sehr gut` (1200–1400), 5 `top` (≥1400). `sb_objektart` is the swisstopo object type
  (fid = code: 1 Gebaeude Einzelhaus, 2 Hochhaus, …). Both lookups ship as extra GeoPackage
  layers and are **not landed** (24 tiny legend rows, awkward column names — the
  `bronze.gwr_wohnung` precedent). The decode above is the record.
- **Only the full `_2056.gpkg` asset is fetched.** `_generalized` (simplified geometry) and
  `_monthlydata` (5.42 GB, monthly yield series) are deliberately skipped.
  `ch.bfe.solarenergie-eignung-**fassaden**` (facades) is a sibling layer, out of scope
  (roofs only).
- Vintage: per-plane `datum_erstellung`/`datum_aenderung`; collection-level STAC `updated`
  (2025-01-18). Row count asserted as a **range** (baseline 34,358 ±10%), not an equality —
  the national layer is periodically re-flown.

**Silver/gold now built.** Promoted alongside GWR: `silver.roof_plane` (34,358, per-plane
detail, `ST_MakeValid`) and `silver.building_solar` (7,701, aggregated to EGID —
`best_class`/`roof_area_m2`/`solar_yield_kwh`); surfaced on `gold.building.solar_class` and
rolled up to `gold.parcel.best_solar_class` / `has_solar_potential`. The
`(gwr_egid)::bigint::text` cast is applied in `silver.roof_plane` and asserted to actually
match `silver.building.egid` (7,701 buildings). See the GWR promotion note below.

## SonBase / Lärm (`bronze.laerm_strasse` / `bronze.laerm_bahn`) — noise exposure

`ingest/discover_laerm.py` + `load_bronze_laerm.py`. The THIRD and last building-data source
(`docs/gebaeudedaten-bronze-specs-en.md` §3). **The name is a red herring:** the federal
legend confirms "SonBase" *is* **sonBASE**, BAFU's area-wide noise-exposure model. Noise is a
risk/livability signal analogous to the hazard layer. Access is the same federal **BGDI/STAC
route** as Sonnendach (`ingest/bgdi.py`, its intended second consumer), **not** the
`api3.geo.admin.ch` `MapServer/identify` route the spec named — `layersConfig` shows that is
the PNG *display* layer (`type: wmts`), not a data route.

**Road noise is a Cloud-Optimized GeoTIFF whose pixel value is dB directly.** Collections
`ch.bafu.laerm-strassenlaerm_tag` / `_nacht`; each STAC item carries a `*_2056.tif` COG
(**553 MB**) plus a `*.zip` that is `application/x.pdf+zip` (docs, not vector). The COG header,
parsed directly: **1 band, Float64, NODATA −9999, no colormap, LZW, 512² tiles, 10 m grid,
EPSG:2056** — so the value is the Beurteilungspegel Lr in dB(A) *directly*, **not** a class
index needing a lookup (unlike Sonnendach's `KLASSE`). Because it is a COG with range support,
a **windowed `/vsicurl/` read** of the pilot bbox pulls only the covering tiles (~16 MB) — the
raster analogue of Sonnendach's windowed GPKG read — written to `data/bronze/` as a small clip
and sampled at building points in the load step. **A 0.0 pixel is a computed "negligible"
reading and survives; −9999 is "outside the modelled area" → NULL.** Two different facts, the
`hazard_surveyed` measured-absence distinction — don't read a NULL as "quiet".

**Rail noise is richer than the spec knew — a vector GeoPackage, not a raster.**
`ch.bav.laermbelastung-eisenbahn_immissionen` ships an **uncompressed 60 MB `.gpkg`** (BAV, not
BAFU), read over `/vsicurl/` with a `bbox` window — no raster reader, no unzip. Layer
`immission_railway_pointofdetermination` is Point-per-facade with `Lr_day` / `Lr_night` in dB,
`floor`, `ES_Katalog_de`, `OperationStatus_Katalog_de`. Newer vintage (2023-04-18) than the
BAFU rail raster. The other layers (`_legal`, `noisebarrier` — 0 in pilot, `dispersion_calculation`)
are not landed.

**RAIL EGID TRAP:** the point layer *has* an `EGID` field but it is **0% populated in the
pilot** (every value NaN). So rail does **not** join to buildings by attribute — the building
link is **spatial** (facade point → nearest building/parcel) and belongs in silver. Landed
as-is per the bronze contract, emptiness recorded. Same class as the Bauzonen empty-`gml_id`.

**Two tables, two deliberate landing philosophies:**

| Table | Grain | Rows | How it lands |
|---|---|---|---|
| `bronze.laerm_strasse` | building (`egid`) | 11,217 | **DERIVED** — two road COGs sampled at each pilot building point (`lr_tag`, `lr_nacht`). A raster can't become a table without sampling; this is the spec's endorsed `laerm_punkte` deviation, flagged not hidden. |
| `bronze.laerm_bahn` | facade point (`xtf_id`) | 937 | **RAW** — BAV rail points as delivered, like Sonnendach roof planes. |

- **Selection is spatial** (like Sonnendach/Gefahrenkarte): pilot polygons from
  `hoheitsgrenzen ms:Gemeinden_Layer`, padded bbox drives the reads, rail narrowed to
  intersecting rows — geometry never clipped. Per-Gemeinde rail: Bottighofen 79 / Ermatingen
  130 / Kreuzlingen 500 / Münsterlingen 163 / Tägerwilen 65, none empty (the assertion).
- **`GSTAT` is not filtered** — all 11,217 buildings sampled, incl. 700 demolished; filtering
  is silver's job, per the GWR contract.
- **Measured join:** `lr_tag` lands on 11,029 buildings (188 outside the modelled area → NULL),
  dB 1.2–71.5; building maxima sit below the raster's 84.8 because buildings are set back from
  road centrelines. 6,599 `silver.parcel` rows are reachable through a road-noise-bearing
  building. Night ≤ day holds on every building; day ≥ night on every rail point (verified).
- **New dependency `rasterio`** (`uv add`) — pyogrio's GDAL is vector-only and can't read the
  COG. The "genuinely new pattern" the spec anticipated, analogous to `zipfile_deflate64` for
  Sonnendach. Rail needs nothing new.
- Row counts asserted as a **tolerance band**, not equality (the cadastre/raster are periodically
  recomputed); what is exact is that no pilot Gemeinde comes back empty.

**Silver/gold now built.** `silver.rail_noise` (937, per facade-point detail) and
`silver.building_noise` (11,217, one row per building — road `lr_tag`/`lr_nacht` by attribute,
rail `lr_day`/`lr_night` by the **nearest facade point within 50 m**, all 937 points link at
that threshold). The NULL-vs-0.0 modelled-area distinction is a `road_noise_modelled` boolean
tied to its payload by CHECK, and rail's `has_rail_noise` likewise. Surfaced on
`gold.building` (`noise_road_day/night`, `noise_rail_day/night`) and rolled up to
`gold.parcel.max_noise_day` / `max_noise_night` (`GREATEST` across road+rail, ignoring NULL).
The rail facade-point → building spatial link lives in `silver.building_noise` as planned.

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
- `ingest/madd.py` — `download()` (streamed, cached), `read_csv()` (tab-delimited,
  utf-8-sig, all-string). Bulk zip: no server-side filter, so the whole canton comes down
  and the pilot slice is cut locally.
- `ingest/bgdi.py` — `assets()` / `collection_updated()` (federal STAC), `download()`
  (streamed, cached, takes a URL), `extract_member()` (DEFLATE64 via `zipfile_deflate64`).
  Bulk national GeoPackage: no server-side filter, cut locally from a windowed `bbox` read.
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

## Bronze → silver → gold sequencing (explicit user decisions)

Original decision (2026-08-13): bronze first, gold not to be designed until several
sources had landed and could be checked against each other.

**All three layers are now built — for all eight sources, including the three
building-level ones.** Bronze is complete for the five spec layers plus GWR,
Sonnendach and SonBase noise; silver and **gold** are built and tested over all
of them — see the two sections below. Gold selects from `silver.*` and never
from `bronze.*` (a test enforces this by reading the DDL text, since Postgres
records no catalog dependency for an `INSERT ... SELECT`). `gold.parcel` is
keyed on `egrid` alone (single 2024 vintage), `gold.building` on `egid`, and
`gold.parcel_restriction` remains **deferred** pending the bulk WFS ingestion.

The building-level promotion (2026-08-18) was split silver-first then gold, for
the same reason hazard was: gold could not be designed until silver settled how
a building relates to a parcel (the `EGID` fan-out, `GSTAT`, null-means-
unrecorded — all now declared constraints). See the GWR / Sonnendach / SonBase
sections above for each source's silver/gold shape.

The remaining open work is the bulk WFS restrictions pull
(`docs/next-bronze-restrictions.md`), which is what unblocks
`gold.parcel_restriction`.

**Bronze has since been extended past the five spec layers, and the extension
now runs all the way to gold.** `docs/gebaeudedaten-bronze-specs-en.md` adds
three building-level sources — GWR (`bronze.gwr_gebaeude` / `_eingang` /
`_kodes`), Sonnendach (`bronze.sonnendach`) and SonBase noise
(`bronze.laerm_strasse` / `bronze.laerm_bahn`); see their sections above.
**All three are now modelled in silver and gold.** The three gating questions
were settled as declared constraints in silver: the `EGID` fan-out (a grain
below the parcel, contained by per-grain tables — `silver.building`,
`silver.roof_plane`/`building_solar`, `silver.rail_noise`/`building_noise`), the
`GSTAT` filter (`is_existing` CHECKed against `gstat`, `gold.building` keeps only
existing), and null-means-unrecorded (nulls preserved, a 0 forbidden by CHECK).
Gold adds `gold.building` (10,392, EGID grain) and building rollups on
`gold.parcel`. See the two "built" sections below.

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
| `bronze.gwr_gebaeude` | 11,217 | BFS MADD `tg.zip` | bulk zip, spatial (Point) |
| `bronze.gwr_eingang` | 11,489 | BFS MADD `tg.zip` | bulk zip, tabular |
| `bronze.gwr_kodes` | 405 | BFS MADD `tg.zip` | bulk zip, tabular |
| `bronze.sonnendach` | 34,358 | BFE BGDI `SOLKAT_DACH.gpkg` | bulk zip, spatial (MultiPolygon) |
| `bronze.laerm_strasse` | 11,217 | BAFU BGDI `strassenlaerm_{tag,nacht}` COG | windowed raster, **sampled at building points** |
| `bronze.laerm_bahn` | 937 | BAV BGDI `eisenbahn_immissionen.gpkg` | windowed vector, spatial (Point) |
| `bronze.oereb_extract` | 25 | ÖREB webservice | **per-parcel query** |
| `bronze.oereb_restriction` | 80 | (unnested from above) | — |

Bronze contract, as applied in `propsearch_data/bronze.py`:
- Source names and types preserved — no renaming, casting, unit fixes, or dropping
  redundant-looking columns. Wrong values stay wrong in bronze; silver corrects them.
- **One exception: column names are normalised to lower case.** GDAL does this implicitly
  for every GML/GPKG source, so all the WFS tables are already lower-case; CSV sources do
  it explicitly (`load_bronze_gwr.lower_columns()`) so both land the same way. Without it,
  the UPPER-CASE MADD headers would become quoted identifiers and every downstream query
  would have to spell `"EGID"`. It is mechanical, not semantic — apply it to the next
  upper-case source rather than rediscovering the problem.
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
- **The staging format decides whether "unrecorded" is `NULL` or `''`.** The GPKG round-trip
  converts empty strings to NULL (`bronze.gwr_gebaeude.egrid`: 383 NULL, 0 empty), while the
  JSON round-trip preserves them (`bronze.gwr_eingang.deinr`: 0 NULL, 124 empty). Both come
  from the same MADD zip and both mean the same thing. Silver must treat them alike —
  `NULLIF(col, '')` — and never read one table's emptiness convention into another's.
  Note `count(DISTINCT col)` skips NULL but counts `''`, so the two spellings give different
  answers to the same question.

Silver should assert types and geometry explicitly rather than trusting these.

## Silver is built — `sql/schema/silver/`, `make silver`

Physical tables from explicit DDL, run by `transform/silver.py` in filename
order, each file in its own transaction, full-replace like bronze. **Not** views:
`ST_MakeValid` inside a join predicate defeats the GIST index and *exceeded the
statement timeout* on this database — repairing once into an indexed table is
what makes the parcel joins viable at all.

**The constraints are the deliverable.** Each one makes a documented trap
unreachable rather than merely written down. Don't relax one to make an insert
pass; a failing CHECK means the source changed and that's the signal.

| Table | Rows | What it pins down |
|---|---|---|
| `silver.gemeinde` | 5 | `bfs_nr integer` everywhere (bronze keys it 4 different ways) |
| `silver.parcel` | 9,879 | PK `egrid`; `lwz` resolved to CHF; `CHECK price > 0` |
| `silver.zone` | 89 | PK `(bfs_nr, zone_code_norm)` — 79 codes, 89 Gemeinde-pairs |
| `silver.parcel_zone` | 8,303 | PK `egrid` — point-in-polygon, at most one zone |
| `silver.hazard_zone` | 6,422 | `ST_MakeValid` materialised + GIST; `CHECK ST_IsValid` |
| `silver.parcel_hazard` | 26,789 | PK `(egrid, source_layer)` — contains the 2.97× fan-out |
| `silver.parcel_hazard_synoptic` | 9,879 | `CHECK hazard_surveyed = (gefahrenstufe IS NOT NULL)` |
| `silver.bodenpreis` | 520 | 0/0 sentinel → NULL; `CHECK price > 0`; window materialised |
| `silver.gemeinde_*` (4) | 115/30/95/2,090 | typed casts, **full year ranges kept** |
| `silver.oereb_extract_sample` | 25 | 0.3% — `_sample` is load-bearing |
| `silver.parcel_restriction_sample` | 80 | — |
| `silver.building` | 11,217 | PK `egid`; `is_existing` CHECKed vs `gstat`; `egrid` a nullable link, not a FK |
| `silver.roof_plane` | 34,358 | PK `df_uid`; `ST_MakeValid` + GIST; `(gwr_egid)::bigint::text` cast |
| `silver.building_solar` | 7,701 | PK `egid` → `building` — roof planes aggregated to the building |
| `silver.rail_noise` | 937 | PK `xtf_id` — rail facade points (EGID unusable, link is spatial) |
| `silver.building_noise` | 11,217 | PK `egid`; road by attribute, rail by nearest point ≤50 m; NULL≠0 |

Things silver settled that contradict earlier notes here:

- **`gn_kantname` is an authoritative canton-wide zone class** (25 values, 0 nulls,
  populated even where `gn_kuerzel` is NULL). It collapses the 79 municipal codes —
  `StB`/`StrB`/`VfSi`/`VFiB` all → "Strassen und Wege innerhalb von Bauzonen". Use it
  as `zone_class` for cross-Gemeinde comparison; **don't hand-build a crosswalk.**
  `zone_label` (`gn_gmdname`) stays Gemeinde-specific: `G` is "Gewerbezone" in
  Ermatingen but "Arbeitszone Gewerbe" in Münsterlingen, one canton class, two labels.
- **Mechanical zone-code normalisation merges nothing within a Gemeinde** (verified 0
  cases). Each Gemeinde already spells its codes consistently; the variants are all
  cross-Gemeinde. `zone_code_norm` is defensive, not corrective.
- **`markt_ja_nein = 'n'` is NOT a data-absence flag.** All 40 sentinel rows are `'n'`,
  which makes the inference tempting — but **250 of the 290 `'n'` rows carry real
  prices**. The only "no data" filter is `minimum = 0 AND maximum = 0`. Filtering rows
  on `markt_ja_nein` discards 250 valid bands.
- **The ÖREB 25 are a POC sample, not the source's ceiling.** The *extract endpoint*
  has no bulk call, but the restriction *data* is bulk WFS for 7 of 9 themes. See
  `docs/next-bronze-restrictions.md`. `gold.parcel_restriction` is deferred.
- **Point-based matching costs something measurable.** No parcel polygons exist, so a
  parcel takes the zone its representative Point lands in. Against the ÖREB oracle:
  9/25 parcels carry >1 Nutzungsplanung restriction, 5/25 have base-zone coverage
  <99.5%. Fine for screening, wrong for area shares.
- **ÖREB overlays are additive, not contradictory.** A parcel has one base zone plus
  overlays (Gestaltungsplanpflicht, Umgebungsschutzzone, Gefahrenzone…). Comparing
  *every* `ch.Nutzungsplanung` row against the Bauzonen zone reads as disagreement;
  the correct check is that the base zone appears **among** them — 25/25.
- **The building layer is a new grain BELOW the parcel**, so nothing under it joins the
  9,879-row parcel spine 1:1. It is held in per-grain tables — building (`egid`), roof
  plane (`df_uid`), rail facade point (`xtf_id`) — with aggregates (`building_solar`,
  `building_noise`) at the building grain that gold consumes. The `(gwr_egid)::bigint::text`
  cast is asserted to actually match (7,701 buildings); read as a float, `2337457.0` would
  never match the text `'2337457'`. Rail links **spatially** (nearest building ≤50 m) because
  its `EGID` field is 0% populated — the one genuinely new join pattern in silver.

Tests are read-only assertions against whatever `make silver` last built (`tests/`,
90 of them). No fixture data: the pilot slice is the thing worth testing.

## Gold is built — `sql/schema/gold/`, `make gold`

Same runner pattern as silver (`transform/gold.py`, filename order, one
transaction per file, full-replace). **Selects from `silver.*` only.** Gold
corrects nothing — every source-fidelity fix already happened one layer down.
Its contribution is a **grain guarantee**.

| Table | Rows | Grain | What it pins down |
|---|---|---|---|
| `gold.parcel` | 9,879 | `egrid` | zoning + price + hazard + building rollups in one row; `in_bauzone` / `hazard_surveyed` / `has_solar_potential` keep "measured absence" distinct from NULL |
| `gold.parcel_hazard` | 17,784 | `(egrid, source_layer)` | per-process detail; **synoptic layer excluded by CHECK** |
| `gold.building` | 10,392 | `egid` | building attrs + solar + noise; **existing-only by CHECK**; links to `gold.parcel` on `egrid` |
| `gold.gemeinde_year` | 115 | `(bfs_nr, jahr)` | 2004–2026, ragged on purpose; age table aggregated to 2 shares |
| `gold.gemeinde_bodenpreis` | 520 | `(bfs_nr, jahr, zone_category_code)` | `CHECK (jahr > year(window_end))` makes "trailing window" structural |

The two facts join on `bfs_nr` — **always with a year predicate.** `bfs_nr`
alone yields 9,879 × 23 = 227,217 rows.

Things the build settled:

- **`ms:Gefaehrdung_synoptisch` is derivable from the two process layers**, so
  it is not in `gold.parcel_hazard`. Max-severity over Wasser + Rutschungen
  reproduces the published synoptic grade on **9,004 of 9,005** parcels; the one
  exception (`CH854589778397`) is a sub-metre point-in-polygon boundary
  artifact, inspected. The published value still lands on
  `gold.parcel.hazard_grade_overall`, carried verbatim rather than recomputed —
  so gold does not "fix" the source into agreement with itself. Fan-out is
  2×, not 2.97×; it is **reduced, not eliminated**.
- **`hazard_rank` needs a biconditional**, not `rank IS NULL OR grade <> 'Restgefahr'`.
  The one-way form leaks a graded-but-unranked row *and* an unsurveyed row with
  a stale rank (grade is NULL there, `<>` yields NULL, and a CHECK admits NULL).
- **Age structure is two shares, never a join.**
  `silver.gemeinde_bevoelkerung_alter` is 38 rows per Gemeinde-year and fans 5
  rows into 190. `pct_65_plus` / `pct_under_20` because both cuts fall exactly
  on a band boundary, so they are exact sums — a median age would need
  interpolation and an invented `90+` midpoint.
- **Spine growth is caught by the PK at build time, not by a test** (any fan-out
  duplicates an `egrid`). What no constraint catches is the spine *shrinking* —
  a `LEFT JOIN` silently becoming inner. That is what the row-count assertions
  cover, and the parcels at risk are the interesting ones (76 with no `lwz`,
  1,576 outside every Bauzone, 874 unsurveyed).
- **`gold.parcel` carries no `zone_category_code`,** and a test asserts the
  column never appears. Bodenpreise's 8 tax categories have no published
  crosswalk to the parcel's zone; the mapping *looks* obvious (EFH → `4 EFH`,
  EWG → `3 MFH`) and is a guess. The two tables join on `(bfs_nr, jahr)` only.
- **`pg_depend` cannot verify the silver-only contract.** Postgres records no
  dependency between a table and whatever an `INSERT ... SELECT` read to fill
  it, so a catalog-based check passes either way. The test reads the DDL text
  with comments stripped.
- **`gold.building` is a second grain (EGID), and it is filtered to existing.**
  `silver.building` keeps all GSTAT states; `gold.building` selects only
  `is_existing` and a CHECK forbids any other state leaking — the
  `gold.parcel_hazard` synoptic-exclusion precedent. It links to `gold.parcel`
  on `egrid` (nullable, not a FK: 13 existing buildings carry no in-pilot
  parcel), one parcel to many buildings.
- **The parcel building rollups aggregate BEFORE the join**, so the spine stays
  9,879. `n_buildings` / `best_solar_class` / `has_solar_potential` /
  `max_noise_day`/`_night` come from a subquery grouped on `egrid`; a per-parcel
  count off `gold.building` would otherwise fan out (up to 18 existing buildings
  per parcel). Rollups count existing buildings only, matching `gold.building`.
  Cross-checks landed on the independently-measured figures: 7,414 existing
  buildings carry a roof plane, reaching 5,476 parcels.

Gold tests are `tests/test_gold_*.py`, 58 of them, same read-only style —
148 tests total across silver and gold.

## The grounding rule

Do not invent column names, types, or service slugs — the discovery scripts exist
specifically to replace guesses with confirmed values. This is why bronze landed
before silver was designed, and silver before gold: each layer's DDL was written
against field names confirmed from the layer below, never against assumptions.

(This section used to say `sql/schema/` and `models.py` were empty placeholders
awaiting `DescribeFeatureType` output. That precondition has been met:
`sql/schema/silver/` and `sql/schema/gold/` are both populated.
`src/propsearch_data/models.py` stays empty — the project models the schema as
DDL, not as ORM classes, so there is nothing for it to hold.)

Confirmed so far:
- URL pattern `https://ows.geo.tg.ch/geofy_access_proxy/{slug}` is real. Live slugs:
  `datensammelstellen`, `oereb_ortsplanung_bauzonen`, `gewaesserkataster_gewaesser`,
  `landwertzonen`, `hoheitsgrenzen`, `oereb_gewaesserraum`
- `oereb_ortsplanung_bauzonen` serves far more than `ms:bau` — also `ms:les`, `ms:gp`,
  `ms:blp`/`ms:blpline`, `ms:no_*`/`ms:ko_*`, `ms:ueberlagernd`, `ms:schutz`,
  `ms:weitere` (each with a `_vx` pending-amendment twin). These are the bulk sources
  for most ÖREB restriction themes — see `docs/next-bronze-restrictions.md`.
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
| MADD `gwr_gebaeude` | Point, one per **building** | `EGID`; also carries `EGRID`, `GGDENR` | direct on E-GRID — but **one parcel holds many buildings** |
| MADD `gwr_eingang` | none (`DKODE`/`DKODN` cols) | `(EGID, EDID)`; `EGAID` | on `EGID` to the building, then E-GRID to the parcel |
| BGDI `sonnendach` | MultiPolygon, one per **roof plane** | `DF_UID` (grain); `GWR_EGID` (link) | on `GWR_EGID` to the building — but **one building has many roof planes** |
| BGDI `laerm_strasse` | Point, one per **building** (sampled) | `egid` | direct on `egid` to the building (sampled *at* the GWR point), then E-GRID to the parcel |
| BGDI `laerm_bahn` | Point, one per **facade point** | `xtf_id` (grain); no usable EGID | **spatial** — `EGID` field is empty in the pilot, so nearest-building in silver |

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
