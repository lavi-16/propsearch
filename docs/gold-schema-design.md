# Gold schema — design proposal

Status: **proposed, not built.** No tables created yet.

Written once all five spec layers had landed in bronze, which was the
stated precondition for designing gold against real data rather than
against assumptions. Every number below is measured from the landed pilot
slice, not estimated.

## The two grains

The single most consequential finding: **the sources do not share a
grain, and forcing them into one table destroys information either way.**

| | Grain | Time |
|---|---|---|
| Landwertzonen (price), Bauzonen (zoning), Gefahrenkarte (hazard) | per parcel | single vintage — `jahr` = 2024 only |
| Steuerfuss, Finanzkennzahlen, Bevölkerung, Bodenpreise | per Gemeinde | time series |

Putting Gemeinde time series on a parcel row means either duplicating
9,879 parcels × N years, or collapsing to a "latest" row and throwing away
the history the spec explicitly wants. So: **two fact tables, joined on
BFS-Nr when a caller wants both.**

Year coverage differs per source; the intersection of all five
Gemeinde-keyed sources is **2019–2024 (6 years)**, bounded by `sk-stat-4`:

```
gemeinde_steuerfuss          2004-2026   (23 years)
gemeinde_bevoelkerung        2007-2025   (19 years)
gemeinde_bevoelkerung_alter  2015-2025   (11 years)
bodenpreise                  2012-2024   (13 years)
gemeinde_finanzkennzahlen    2019-2024   ( 6 years)   <- binding
```

Gold should **not** inner-join these into a 6-year table. Keep the full
per-source range and let callers narrow; a 2019 floor imposed at gold
silently discards 15 years of tax history.

## Proposed tables

### `gold.parcel` — one row per parcel, 2024 snapshot

Spine is `bronze.landwertzonen`: 9,879 rows, `gs_egris_egrid` unique with
zero nulls, so E-GRID is a genuine primary key. Measured coverage:

| Attribute | Source | Coverage |
|---|---|---|
| land value CHF/m² | `landwertzonen` via `lwz` | 99.2% |
| hazard grade | `gefahrenkarte` point-in-polygon | 91.2% |
| building zone | `bauzonen` point-in-polygon | 84.0% |

Columns: `egrid` (PK), `gemeinde_bfs`, `gemeinde_name`, `parcel_number`,
`geometry` (Point, 2056), `source_layer`, plus —

**Price.** Resolve `lwz` to CHF at gold, since the raw form is a trap:
`lwz` is an *index* into `efh_landwertzone1..7` / `ewg_landwertzone1..7`,
running **inverse** (1 = priciest). Emit `price_efh_chf_m2`,
`price_ewg_chf_m2`, `price_gewerbe_industrie_chf_m2` and keep `lwz`
alongside for traceability. Averaging raw `lwz` is meaningless; gold
should make that mistake impossible to reach.

**Zoning.** `zone_code` (`gn_kuerzel`), `zone_label`, `sensitivity_level`
(`es_txt`). Note codes are unnormalised across Gemeinden — `W1.6` vs
`W 1.6`, `FH` vs `Fh`, `oeBA` vs `OeBA`. Normalising is a silver job;
gold should consume the normalised form, so this needs silver first or an
explicit "raw code" caveat.

**Hazard summary.** See the caveat below — this is the part most likely to
be got wrong.

### `gold.parcel_hazard` — one row per parcel × layer

Not folded into `gold.parcel`, for two measured reasons.

1. **Within a layer the polygons partition** (max = avg = 1.000 rows per
   parcel), but **across the three layers a parcel averages 2.97 rows.**
   A single hazard column would have to pick a layer or silently
   triplicate the parcel.
2. `_synoptisch` is the combined view; `_wasser` and `_rutschungen` are
   per-process detail over the same ground. They are not independent
   facts to be summed.

Columns: `egrid`, `source_layer`, `gefahrenstufe`, `matrixfeld`,
`prozess_massgebend`. `gold.parcel` then carries a **synoptic-only**
summary, explicitly named so (`hazard_grade_synoptic`).

**Two hazard traps to encode in the schema, not the docs:**

- **`keine` ≠ no match.** 9,005 of 9,879 parcels fall inside the synoptic
  layer. A parcel graded `keine` was surveyed and is clear; a parcel with
  no match is *outside the surveyed perimeter* — unknown. Collapsing both
  to NULL, or both to "no hazard", asserts safety that was never measured.
  Proposal: nullable `hazard_grade_synoptic` plus a non-null boolean
  `hazard_surveyed`.
- **`Restgefahr` is not on the ordinal scale.** Distribution is
  `keine` 7317, `gering` 1122, `mittel` 510, `erheblich` 29,
  `Restgefahr` 27. Residual risk behind a protection structure is a
  different kind of statement from a graded intensity, so it must not be
  sorted into `gering < mittel < erheblich`. Keep the source string; if an
  ordinal is needed, add a separate nullable `hazard_rank` that is NULL
  for `Restgefahr`.

### `gold.gemeinde_year` — one row per Gemeinde × year

Fiscal and demographic series plus the Bodenpreise bands. `bodenpreise` is
**Gemeinde-grain, not parcel-grain**, and belongs here rather than on a
parcel: its `bauzone` is one of 8 coarse tax categories that do not map to
the 79 municipal zone codes, and no crosswalk is published. Parcel pricing
goes through Landwertzonen instead, so nothing is lost.

Bodenpreise needs its own sub-grain (Gemeinde × year × zone category), so
either a separate `gold.gemeinde_bodenpreis` table or a nested/long form.
**Recommend a separate table** — folding 8 categories into columns bakes
the taxonomy into the schema.

Carry forward, do not silently clean:
- `minimum = maximum = 0` is a *no-data sentinel* (40/520 rows, all
  `markt_ja_nein = 'n'`). Silver should NULL these; gold must not emit 0
  as a price.
- `markt_ja_nein = 'n'` means fewer than 4 transactions — 290 of 520
  pilot cells. Surface it as a `is_market_based` boolean; a thin cell is
  indicative, not a market price.
- Rows are **six-year trailing windows**, not spot prices. Name the
  columns so nobody diffs adjacent years as a market move.

### `gold.parcel_restriction` — sparse, sample only

From `bronze.oereb_extract` / `oereb_restriction`. **Covers 25 of 9,879
parcels (0.3%).** ÖREB is a per-parcel service with no bulk call, so this
stays a sample until someone decides to spend ~7,300 requests.

Because of that it must **not** become a column on `gold.parcel` — an
absent restriction there would read as "no restriction" when it means "not
fetched". Keep it a separate table whose sparsity is self-evident, and
record `extract_fetched_at` per parcel.

## Open decisions

1. **Silver first, or gold straight off bronze?** Three cleanups are
   genuinely silver's: zone-code normalisation, the Bodenpreise zero
   sentinel, and `ST_MakeValid` on the 84 invalid hazard geometries
   (all `Ring Self-intersection`). Building gold directly off bronze means
   embedding those fixes in gold's DDL, where they are harder to test.
2. **Parcel geometry.** Landwertzonen is a Point per parcel; there is no
   parcel polygon in any landed source. Anything needing parcel area or
   true overlap needs the Amtliche Vermessung parcel layer, not yet
   ingested.
3. **Vintage.** Every parcel-level source is a single 2024 snapshot, so
   `gold.parcel` has no time dimension. If a second vintage ever lands,
   this becomes a slowly-changing dimension and the PK changes. Worth
   deciding now whether to pre-emptively key on `(egrid, vintage)`.
