# Gold schema — design proposal

Status: **built.** `sql/schema/gold/`, `make gold`, 45 tests. Four tables:
`gold.parcel` (9,879), `gold.parcel_hazard` (17,784), `gold.gemeinde_year` (115),
`gold.gemeinde_bodenpreis` (520).

> **Update (2026-08-13): silver is built, and the three open decisions below
> are resolved.** See the "Open decisions — resolved" section at the end.
> Two things in this document are now superseded:
>
> - **`lwz` → CHF is resolved in silver, not gold.** Turning an inverse index
>   into a magnitude is a source-fidelity correction, which is silver's
>   contract. `silver.parcel` emits `price_efh_chf_m2` / `price_ewg_chf_m2` /
>   `price_gewerbe_chf_m2` with `lwz` kept alongside for traceability.
> - **`gold.parcel_restriction` is deferred**, not part of the next proposal.
>   Building it from the 80-row sample was ruled out — see below.
>
> Everything else here held up against the built data, including every
> measured figure.

> **Update (2026-08-13, build): three changes from the proposal below.**
> See "What the build changed" at the end for the evidence.
>
> - **`gold.parcel_hazard` carries two layers, not three.** The synoptic
>   layer was tested and found derivable from the two process layers, so it
>   is excluded by CHECK. Fan-out drops 2.97× → 2×.
> - **`hazard_grade_synoptic` → `hazard_grade_overall`**, so the column on
>   `gold.parcel` cannot be confused with the layer that is no longer in the
>   detail table.
> - **`gold.gemeinde_year` carries two age *shares*, not the age table.**
>   `silver.gemeinde_bevoelkerung_alter` is 38 rows per Gemeinde-year and
>   would have fanned 5 rows into 190.

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

## Open decisions — resolved

1. **Silver first, or gold straight off bronze?** → **Silver first, built.**
   All three cleanups live in `sql/schema/silver/` as declared constraints
   rather than prose, so each trap is now unreachable rather than merely
   documented: prices are `CHECK (… > 0)`, the hazard fan-out is prevented by
   `PRIMARY KEY (egrid, source_layer)`, and surveyed-vs-unknown is pinned by
   `CHECK (hazard_surveyed = (gefahrenstufe IS NOT NULL))`. Gold selects from
   `silver.*`.

2. **Parcel geometry.** → **Accepted as a v1 limitation, now quantified.**
   Still a Point per parcel, no polygon in any landed source. Measured
   against the ÖREB sample, which does know true parcel geometry:

   - **9 of 25** parcels carry more than one `ch.Nutzungsplanung` restriction
   - **5 of 25** have a base zone covering less than 99.5% of the parcel

   So roughly a fifth to a third of parcels straddle a zone boundary, and the
   point join picks one and reports it as *the* zone. Acceptable for
   screening; wrong for area shares or buildable envelope. The fix is the
   Amtliche Vermessung parcel layer, deliberately out of scope for v1.

3. **Vintage.** → **`egrid` alone, no composite key.** Every parcel-level
   source is `jahr` = 2024. `silver.parcel` carries `vintage` as a plain
   column and a test asserts it stays single-valued, so a second vintage
   landing will fail loudly rather than silently duplicating parcels — which
   is the moment to revisit `(egrid, vintage)`.

## What silver established that changes the gold proposal

- **`gn_kantname` is an authoritative canton-wide zone class** — 25 values,
  zero nulls, populated even where `gn_kuerzel` is NULL. It collapses the 79
  municipal codes (`StB`/`StrB`/`VfSi`/`VFiB` → "Strassen und Wege innerhalb
  von Bauzonen"). This is the crosswalk this document assumed did not exist.
  `gold.parcel` should carry `zone_class` from it, not a hand-built mapping.
- **`markt_ja_nein = 'n'` is not a data-absence flag.** 250 of the 290 `'n'`
  rows carry real prices. The only correct "no data" filter is
  `minimum = 0 AND maximum = 0`. Surfacing `is_market_based` as a confidence
  flag is right; filtering rows on it would discard 250 valid bands.
- **`gold.parcel_restriction` is deferred.** The 25-parcel ÖREB sample is a
  POC-scale sample of one API, *not* the source's coverage ceiling: the
  extract endpoint has no bulk call, but the restriction data is bulk-
  available as WFS for 7 of the 9 observed themes. Building a gold table from
  0.3% coverage was rejected; it waits for that ingestion. See
  `docs/next-bronze-restrictions.md`.

## What the build changed

### The synoptic layer is derivable, so it is not in the detail table

This document argued the three hazard layers must stay in a per-layer table
because "across the three layers a parcel averages 2.97 rows". True, but it
left the prior question unasked: **is `_synoptisch` an independent assessment,
or is it computable from `_wasser` + `_rutschungen`?** Tested at parcel grain
across all 9,005 surveyed parcels, ranking
`keine < Restgefahr < gering < mittel < erheblich` and taking the max:

| | |
|---|---|
| synoptic `gefahrenstufe` == max of the two process layers | **9,004 / 9,005** |
| synoptic `prozess_massgebend` == that of the winning layer | 9,000 / 9,005 |
| synoptic `matrixfeld` == that of the winning layer | 9,000 / 9,005 |
| synoptic parcels not covered by `_rutschungen` | 0 |

The 5 process/matrixfeld differences are **ties** — both layers at equal
severity, the tie-break picking arbitrarily — not disagreements.

The single grade exception, `CH854589778397`, was inspected: the parcel point
sits **0.26 m inside** a synoptic `mittel` polygon and **0.31 m outside** a
Wasser `mittel` polygon. The layers' boundaries differ by under a metre there.
A point-in-polygon edge artifact, not an independent assessment.

So `gold.parcel_hazard` carries the two **process** layers only (17,784 rows),
enforced by `CHECK (source_layer IN (...))`. Nothing is lost: the *published*
synoptic grading still lands on `gold.parcel.hazard_grade_overall` — including
that one parcel's `mittel`, carried verbatim rather than recomputed into
agreement with its components. What was removed is a duplicate row, and with
it the confusion of two "synoptic" concepts in two tables under near-identical
names.

### `hazard_rank` needed a biconditional, not a one-way guard

The proposal's `hazard_rank IS NULL OR grade <> 'Restgefahr'` is asymmetric and
leaks two states: a surveyed, graded row with a **missing** rank passes, and an
unsurveyed row carrying a **stale** rank passes too — there the grade is NULL,
`<>` evaluates to NULL, and a CHECK admits NULL. Built as:

```sql
CHECK ((hazard_rank IS NULL)
       = (hazard_grade_overall IS NULL OR hazard_grade_overall = 'Restgefahr'))
```

### The age table is aggregated, not joined

`silver.gemeinde_bevoelkerung_alter` is 2 sexes × 19 bands = **38 rows per
Gemeinde-year**; joining it into `gold.gemeinde_year` fans 5 rows into 190 per
year — the same grain mistake the bodenpreis/parcel split avoids. It collapses
to `pct_65_plus` and `pct_under_20`, chosen because both cuts fall **exactly on
a band boundary**, so both are exact sums. A median or mean age would need
within-band interpolation and an invented midpoint for the open-ended `90+`
band — the same reason no Bodenpreise median is emitted. Age sums reconcile
exactly with `gemeinde_bevoelkerung` on all 55 overlapping Gemeinde-years.

### What the tests can and cannot guarantee about grain

Worth recording, because it is easy to state backwards: **spine growth is caught
by the PK at build time**, not by a test — any fan-out duplicates an `egrid` and
the INSERT aborts (verified by injecting one). What no constraint catches is the
spine **shrinking**: a `LEFT JOIN` becoming an inner join drops parcels silently,
and every coverage ratio computed from gold stays plausible because its
denominator shrank too. That is what the row-count assertions are for, and the
parcels at risk are the interesting ones — the 76 with no `lwz`, the 1,576
outside every Bauzone, the 874 never surveyed.

### `gold.gemeinde_year`'s spine is a UNION

Steuerfuss spans 2004–2026 and today covers every year the other three series
carry, so sourcing the spine from it would give the same 115 rows. It is still
wrong: a future series with a year outside that range would vanish. The spine is
a `UNION` of all four series' `(bfs_nr, jahr)` pairs, with a test asserting no
source row is orphaned.
