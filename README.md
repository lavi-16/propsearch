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

## Ground the schema (do this first)

The Claude sandbox can't reach `ows.geo.tg.ch` / `data.tg.ch` directly -
both block bot/proxy traffic via robots.txt, and neither is on the sandbox's
network allowlist. Run this from your own machine instead:

```bash
uv run python src/propsearch_data/ingest/discover_capabilities.py
```

This dumps `GetCapabilities` info for known WFS endpoints to
`docs/wfs-capabilities/`. One endpoint (OEREB datensammelstellen) is
pre-filled. You'll still need to track down:

- **Bauzonen / Zonenplan** WFS endpoint
- **Gefahrenkarte** WMS endpoint (flood/landslide, HQ30/HQ100/HQ300)
- **Landwertzonen** WFS endpoint

Find these via:
- `map.geo.tg.ch` -> click a layer -> look for service/object info in the
  layer details panel
- `shop.geo.tg.ch` (ThurGIS Shop) -> data catalog, often lists the service
  URL alongside the download option
- `geodienste.ch` -> several cantons publish Nutzungsplanung and
  Gefahrenkarte there under a harmonized schema; worth checking whether
  TG's zoning/hazard layers live there too instead of on `ows.geo.tg.ch`

Add confirmed URLs to the `ENDPOINTS` dict in
`discover_capabilities.py`, re-run, and paste the output back - the
gold-layer schema in `sql/schema/` gets designed from those real field
names, not guessed ones.

## Project layout

```
docs/                    spec, ADRs, WFS capability dumps (gitignored XML)
sql/schema/               DDL - populated once the schema is grounded
src/propsearch_data/
  ingest/                 one module per data source
  transform/               bronze -> silver -> gold logic
  models.py                schema definitions (placeholder until grounded)
```
