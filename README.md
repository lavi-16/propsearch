# PropSearch Data Platform

Bronze -> silver -> gold pipeline for Thurgau parcel due-diligence data:
zoning, public-law restrictions, hazard exposure, land value benchmarks,
and Gemeinde fiscal/demographic context. See `docs/spec.md` for the full
mini-spec and `docs/adr/` for architecture decisions.

## Status

POC (v0.1) - pilot scope: Kreuzlingen, Taegerwilen, Bottighofen,
Muensterlingen, Ermatingen (Bodensee-front cluster, Bezirk Kreuzlingen).

## Setup

1. Install [uv](https://docs.astral.sh/uv/)
2. `uv sync`
3. Copy `.env.example` to `.env` and fill in `DATABASE_URL`
   (Supabase recommended - see `docs/adr/0001-tech-stack.md`)

   Use the **connection pooler** URL, not the direct one: Supabase's
   direct host `db.<ref>.supabase.co` is IPv6-only and unreachable from
   WSL/CI. Take the "Connection pooling" string from the dashboard and use
   port **5432** (session mode), not 6543. See `.env.example` for details.

## Ground the schema (do this first)

`ows.geo.tg.ch` is reachable from a normal network and from Claude Code's
shell. (Claude's *web-fetch* tool honours the site's robots.txt and will
refuse - that's a crawler convention, not an access control. Scripted WFS
calls work fine.)

```bash
make discover   # GetCapabilities -> docs/wfs-capabilities/
make bronze     # pull both sources from WFS and load them into Postgres
```

Landed so far, **bronze only**, across the five pilot Gemeinden:

| Table | Rows | Source | Spec layer |
|---|---|---|---|
| `bronze.landwertzonen` | 9,879 | `landwertzonen` WFS | Land value |
| `bronze.bauzonen` | 1,609 | `oereb_ortsplanung_bauzonen` WFS | Zoning |
| `bronze.gemeinde_steuerfuss` | 115 | data.tg.ch `sk-stat-70` | Gemeinde context |
| `bronze.gemeinde_finanzkennzahlen` | 30 | data.tg.ch `sk-stat-4` | Gemeinde context |
| `bronze.gemeinde_bevoelkerung` | 95 | data.tg.ch `sk-stat-56` | Gemeinde context |
| `bronze.gemeinde_bevoelkerung_alter` | 2,090 | data.tg.ch `sk-stat-58` | Gemeinde context |
| `bronze.bodenpreise` | 520 | data.tg.ch `dfs-sv-1` | Land value (Gemeinde CHF/m²) |
| `bronze.gefahrenkarte` | 6,422 | 3 x `ng_gefahrenkarte_*` WFS | Hazard |
| `bronze.oereb_extract` | 25 | ÖREB webservice | Restrictions |
| `bronze.oereb_restriction` | 80 | (unnested from above) | Restrictions |

ÖREB is a **per-parcel** service (~175 KB/parcel, no bulk call), so it is
ingested as a deterministic sample of 5 test parcels per Gemeinde rather
than a full pull.

Two sources carry CHF/m², at different grains:

- **`bronze.landwertzonen` prices the parcel.** Alongside the zone code it
  carries `efh_landwertzone1..7`, `ewg_landwertzone1..7` and
  `gewerbe_industrie` - parcel-precise land values produced for the
  Steuerverwaltung by Wüest Partner. `lwz` (1-7) is the **index** picking
  which band applies, and it runs **inverse**: 1 is the priciest zone.
  So the EFH price is
  `(ARRAY[efh_landwertzone1,...,efh_landwertzone7])[lwz::int]`, not `lwz`
  itself. Don't average `lwz` - resolve it to CHF first.
- **`bronze.bodenpreise` gives Gemeinde-level bands and history.** Read the
  caveats in `discover_bodenpreise.py` first: rows are six-year trailing
  windows rather than spot prices, there is no median column (only
  quartile bounds), zero means "no data", and its 8 coarse zone categories
  do **not** map onto the 79 municipal zone codes in `bronze.bauzonen`.
  The Schätzer-Handbuch PDF attached to the dataset does not supply that
  crosswalk - but nothing needs it, since parcel pricing goes through
  Landwertzonen.

**Silver is built** (`make silver`, `make test`) - see "Silver" below. The
gold schema is designed but not built; `docs/gold-schema-design.md` holds
the proposal.

**Confirmed endpoints** (slug on `ows.geo.tg.ch/geofy_access_proxy/{slug}`):
`datensammelstellen`, `oereb_ortsplanung_bauzonen`,
`gewaesserkataster_gewaesser`, `landwertzonen`, `hoheitsgrenzen`,
`oereb_gewaesserraum`.
Unknown slugs return HTTP 401, so guessing candidates is cheap.

**Note:** these services serve **GML only** - `application/json` is
rejected. Parse with `geopandas.read_file()`, not `r.json()`.

**Gefahrenkarte** (flood/landslide) endpoints are confirmed and are WFS:
slugs `ng_gefahrenkarte_synoptisch`, `_wasser`, `_rutschungen`,
`_erhebungsgebiet`. Recorded in `ENDPOINTS`, not yet ingested.

Add newly confirmed URLs to the `ENDPOINTS` dict in
`discover_capabilities.py` - the gold-layer schema in `sql/schema/` gets
designed from real field names, not guessed ones. If you need to find a
service, the fastest routes are `map.geo.tg.ch` (turn on the layer, watch
the Network tab for the viewer's own request), the ThurGIS Shop catalog
at `shop.geo.tg.ch`, or `geodienste.ch`.

The ÖREB webservice is documented by the canton at
[geoinformation.tg.ch](https://geoinformation.tg.ch/grundstueck-gebaeudeinformationen/oereb-kataster/oereb-webservice.html/14502);
the federal spec it (partly) follows is at
[cadastre.ch](https://www.cadastre.ch/de/oereb-webservice).

## Silver

`make silver` rebuilds schema `silver` from bronze - pure database-to-database,
explicit DDL in `sql/schema/silver/`, run in filename order by
`transform/silver.py`. `make test` then runs 66 read-only assertions
against it.

| Table | Rows | |
|---|---|---|
| `silver.gemeinde` | 5 | `bfs_nr integer` everywhere |
| `silver.parcel` | 9,879 | PK `egrid`; `lwz` resolved to CHF/m² |
| `silver.zone` | 89 | PK `(bfs_nr, zone_code_norm)` |
| `silver.parcel_zone` | 8,303 | point-in-polygon, ≤1 zone per parcel |
| `silver.hazard_zone` | 6,422 | `ST_MakeValid` materialised + GIST |
| `silver.parcel_hazard` | 26,789 | PK `(egrid, source_layer)` |
| `silver.parcel_hazard_synoptic` | 9,879 | 9,005 surveyed / 874 unknown |
| `silver.bodenpreis` | 520 | 0/0 sentinel nulled, window materialised |
| `silver.gemeinde_*` (4) | 115/30/95/2,090 | typed, full year ranges kept |
| `silver.oereb_extract_sample` | 25 | 0.3% - a sample, not a layer |
| `silver.parcel_restriction_sample` | 80 | |

The constraints are the point: `CHECK price > 0` so a padding zero can't
become a price, `PRIMARY KEY (egrid, source_layer)` so the 2.97× hazard
fan-out can't reach a parcel count, and
`CHECK (hazard_surveyed = (gefahrenstufe IS NOT NULL))` so
"surveyed and clear" can never collapse into "never surveyed".

## Next steps

1. **Build the gold schema** from `docs/gold-schema-design.md`, selecting
   from `silver.*` rather than bronze. Two fact tables joined on BFS-Nr,
   plus `gold.parcel_hazard` and `gold.gemeinde_bodenpreis`. `gold.parcel`
   keys on `egrid` alone (single 2024 vintage).
   `gold.parcel_restriction` is **deferred** - see below.
2. **Bulk restriction layers** - `docs/next-bronze-restrictions.md`. The
   25-parcel ÖREB sample is a POC-scale sample of one API, not the
   source's ceiling: 7 of 9 themes are bulk-available as WFS, mostly on
   the already-ingested `oereb_ortsplanung_bauzonen` service.

Optional, same code path as Bauzonen: `ms:landwirt`
(Landwirtschaftszonen) rounds out the spec's "buildability" question,
since a parcel outside a Bauzone is currently just absent rather than
positively classified.

**Known v1 limitation:** no source carries parcel boundary polygons, so a
parcel takes the zone its representative Point falls in. Measured against
the ÖREB sample, 5 of 25 parcels have a base zone covering under 99.5% of
the parcel. Fine for screening, wrong for area shares - fixing it needs
the Amtliche Vermessung parcel layer.

## Project layout

```
docs/                    spec, ADRs, WFS capability dumps (gitignored XML)
sql/schema/               DDL - populated once the schema is grounded
src/propsearch_data/
  ingest/                 one module per data source
  transform/               bronze -> silver -> gold logic
  models.py                schema definitions (placeholder until grounded)
```
