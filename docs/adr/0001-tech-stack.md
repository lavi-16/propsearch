# ADR 0001: Tech stack for the PropSearch data platform (POC)

**Status:** Accepted
**Date:** 2026-08-12

## Decision

- Language: Python 3.12+, managed with `uv`
- Geodata access: `geopandas` + `owslib` for WFS/WMS
- Database: Postgres + PostGIS, hosted on Supabase (already connected);
  swappable to local Postgres via `DATABASE_URL` if needed
- Orchestration: none for v1 - scripts run manually. Revisit once ingestion
  needs scheduling.
- MCP server: not yet - revisit once the data model is proven (see spec
  non-goals).

## Why

- `geopandas`/`owslib` is the standard toolchain for spatial + tabular join
  work in Python and matches existing skillset.
- PostGIS is required, not optional, once doing point-in-polygon lookups
  (parcel vs. zoning/hazard polygons) - plain Postgres can't do this
  efficiently at any scale.
- Supabase removes the need to stand up local infra for a POC; moving to a
  different Postgres instance later is a one-line env var change.
- Deliberately no orchestration or MCP server for v1 - avoid building
  infrastructure the POC hasn't earned yet.
