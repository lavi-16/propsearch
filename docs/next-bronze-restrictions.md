# Next bronze task: bulk restriction layers

Status: **written up, not built.** Scoped while building silver.

## Why

`bronze.oereb_extract` covers 25 of 9,879 parcels (0.3%), and that number was
easy to misread as the source's ceiling. It is not. Two separate things were
conflated:

- The **ÖREB extract endpoint** genuinely has no bulk call — one request per
  parcel, ~175 KB each. Full pilot coverage would be ~7,300 requests and
  >1 GB. That constraint is real.
- The **restriction data itself** is not similarly limited. It is served as
  bulk WFS for 7 of the 9 themes observed in the sample — 76 of the 80
  restriction rows — and all but one of those layers sit on
  `oereb_ortsplanung_bauzonen`, a service already ingested for `ms:bau`.

So the path to pilot-wide restrictions is a bronze WFS pull, not more ÖREB
requests. Until it lands, `gold.parcel_restriction` is deferred and
`silver.parcel_restriction_sample` stays explicitly named as a sample.

## Layers

Confirmed present in `GetCapabilities` (2026-08-13). All on
`https://ows.geo.tg.ch/geofy_access_proxy/oereb_ortsplanung_bauzonen` unless
noted.

| ÖREB theme | Bulk layer(s) | Sample rows |
|---|---|---|
| `ch.Laermempfindlichkeitsstufen` | `ms:les` | 25 |
| `ch.TG.Gestaltungsplaene` | `ms:gp` | 3 |
| `ch.TG.Baulinienplaene` | `ms:blp`, `ms:blpline` | 6 |
| `ch.TG.NaturKulturobjekte` | `ms:no_flaechen`, `ms:no_linien`, `ms:no_punkte`, `ms:ko_*` | 2 |
| `ch.Nutzungsplanung` (overlays) | `ms:ueberlagernd`, `ms:schutz`, `ms:weitere` | 14 beyond the base zone |
| `ch.TG.VorpublikationNutzungsplanung` | the `_vx` layers | 2 |
| `ch.Gewaesserraum` | `oereb_gewaesserraum` → `ms:raum` | 1 |

`oereb_gewaesserraum` is a **newly confirmed live slug** — added to
`ENDPOINTS` in `ingest/discover_capabilities.py`.

## Still unresolved

`ch.BelasteteStandorte` and `ch.BaulinienNationalstrassen` (1 row each in the
sample) have **no confirmed bulk source**. Guessed slugs all returned HTTP
401. Both are federal themes, likely served off-canton (geodienste.ch,
ASTRA). Record as open — 401 on a guessed slug is not evidence of absence.

## Approach

Reuses the existing code path, so this is thin config rather than new
plumbing:

- `ingest/wfs.py` `fetch()` / `property_like_any()` / `count()`
- selection by `t_id` prefix, as `discover_bauzonen.py` already does —
  **but check per layer** that `t_id` is present and prefixed the same way.
  It is not safe to assume it carries across layers; `ms:bau` has an empty
  `gml_id`, and the sibling layers have not been checked.
- `discover_<source>.py` → `data/bronze/`, then `load_bronze_<source>.py` →
  Postgres, per the established split.
- Exclude `_vx` layers unless proposed amendments are specifically wanted —
  they are pending changes, not current state.

The overlay layers are where hazard and Gestaltungsplan restrictions live as
*labels*. They do not replace `silver.parcel_hazard`, which carries the
graded intensity ÖREB has never had.

## Caveat that will carry over

These are polygons, and parcels are still Points (no Amtliche Vermessung),
so a restriction attaches to a parcel by point-in-polygon and inherits the
straddle limitation documented in `gold-schema-design.md`: no `area_share`,
no `part_in_percent`. The ÖREB sample is the only source of those, which is
one reason it is worth keeping.
