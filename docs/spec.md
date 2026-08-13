# PropSearch Data Platform — Mini-Spec (v0.1)

**Status:** POC — written so it can grow into a real PropSearch feature spec later
**Owner:** Lavi
**Last updated:** 2026-08-13

---

## Problem Statement

Screening a candidate parcel in Kanton Thurgau today means manually checking zoning (ThurGIS/ÖREB viewer), hazard exposure (Gefahrenkarte viewer), land value benchmarks (Bodenpreis tables or Landwertzonen), and Gemeinde fiscal/demographic context (statistik.tg.ch) — separately, per property, with no history retained. This doesn't scale past a handful of properties and throws away signal (e.g. price trend over time) every time you close the tab.

## Goal

Prove that Thurgau's open geodata + statistics can be pulled, joined, and stored into a single queryable "parcel record" that answers, in one lookup:
- What can legally be built here (zoning + restrictions)
- Is it hazard-exposed (flood/landslide, which return period)
- What's it worth relative to its zone (land value benchmark)
- What's the fiscal/demographic context of the Gemeinde it sits in

Secondary goal: validate that the bronze → silver → gold pipeline pattern works end-to-end for mixed spatial (WMS/WFS) + tabular (CSV/API) sources, at a scope small enough to build in days.

## Users (v1)

- Lavi (+ Burhan) for personal deal screening only
- **Not yet:** external users, PropSearch production consumers, public API

## V1 Scope

**Geography:** Bodensee-front cluster in Bezirk Kreuzlingen — Kreuzlingen, Tägerwilen, Bottighofen, Münsterlingen, Ermatingen.

**Deliverable:** a due-diligence lookup for a given parcel/address in the pilot area, returning:

| Layer | Source | Answers |
|---|---|---|
| Zoning | ÖREB-Kataster + Zonenplan (WFS) | Bauzone / Landwirtschaftszone / other, buildability |
| Restrictions | ÖREB-Kataster (WFS) | Grundwasserschutzzone, Fluglärm, other encumbrances |
| Hazard | Gefahrenkarte (WMS, GK_Intensitaetskarte HQ30/HQ100/HQ300) | Flood/landslide level + return period |
| Land value | Landwertzonen (WFS) + Bodenpreis-Basisdaten 2012–2024 (dfs-sv-1) | Benchmark price per zone, historic trend |
| Gemeinde context | sk-stat-70/74 (tax), sk-stat-56/58 (population), Gemeindefinanzen | Tax rate, population trend, net wealth/debt per capita |

## Non-Goals (v1)

- **No Homegate/listing scraping integration** — separate track, comes after the parcel-data layer works
- **No canton-wide coverage** — explicitly deferred to v2, once the pilot proves the join logic
- **No user-facing UI** — SQL query or notebook output is a fine v1 result
- **No scheduled/automated refresh** — manual pulls are fine to start; automate once the schema is stable
- **No MCP server** — revisit only once the data model is proven and you're doing this often enough to justify it
- **No licensing/redistribution review** — not needed for personal-use POC; becomes a blocking open question the moment this turns into a product feature (see below)

## Open Questions

Still open:

- **Address → parcel resolution** (engineering): **partly resolved.** *Coordinate* → parcel works: the ÖREB `getegrid` route accepts `EN=<easting>,<northing>` (LV95) and `GNSS=<lat>,<lon>` (WGS84, lat first) and returns an E-GRID. Use `GNSS` downstream of a geocoder. What remains genuinely open is *address* → coordinate, which still needs a geocoder — no landed source provides one.
- **Licensing** (legal, non-blocking for POC): OGD and geodienste.ch usage terms need review before any of this becomes a PropSearch product feature, not just personal use.

Resolved:

- ~~**Field-level schema**~~ — resolved. All five layers landed in bronze from confirmed `DescribeFeatureType` output; `sql/schema/silver/` and `sql/schema/gold/` are written against those names.
- ~~**Gemeinde-ID reconciliation**~~ — resolved. `gemcode` in the Landwertzonen layers *is* the BFS-Nr (Kreuzlingen = 4671 in both it and `hoheitsgrenzen.gemeinde_bfsnr`). Bronze keys it four different ways; `silver.gemeinde` pins it to `bfs_nr integer` everywhere, and `gold.parcel` / `gold.gemeinde_year` join on it.

## Success Criteria for the POC

- One test parcel in the pilot cluster returns a correct, complete record across all 5 layers above
- The join logic (Gemeinde-ID reconciliation, CRS alignment to LV95/EPSG:2056) is documented and repeatable for the next parcel without rework
- You can look at the output and trust it enough to actually use it for a real screening decision

## Next Steps

1. ~~Inspect WFS/WMS `GetCapabilities` for the pilot Gemeinden~~ — done
2. ~~Design the gold-layer schema (parcel record + Gemeinde context table)~~ — done and built: `gold.parcel` + `gold.gemeinde_year`, joined on `bfs_nr`
3. ~~Build bronze ingestion for the 5 pilot sources~~ — done, plus silver and gold
4. ~~Run the first end-to-end lookup on one real test parcel~~ — done: `CH107710829377` (Kreuzlingen 3228) returns all five layers from `gold.parcel`, with its 1,180 CHF/m² EFH price cross-checked against the independent Bodenpreise band (817–1,514, market-based)
5. **Next:** bulk WFS restrictions ingestion (`docs/next-bronze-restrictions.md`) — the one spec layer still served only by a 0.3% ÖREB sample, and what unblocks `gold.parcel_restriction`
