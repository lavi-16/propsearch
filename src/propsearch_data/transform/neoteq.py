"""
neoteq strand -- persist the heat-pump/PV candidate list as a hand-editable
working table, and enrich it with addresses.

WHY ITS OWN SCHEMA, NOT gold. Per docs/context-neoteq-and-investment.md, gold
stays the shared, general-purpose due-diligence record; strand-specific state
(lead scoring, contact status) lives in its own namespace. neoteq.candidate is
that namespace: Lavi edits `status` by hand as outreach happens, so the table
must PERSIST INDEPENDENT OF RECOMPUTE -- it is never dropped and rebuilt the
way silver/gold are. This module is idempotent: run it to refresh the computed
columns without touching the hand-edited ones.

TWO COHORTS IN ONE TABLE. is_candidate is the cold-conversion list (fossil
heating + good roof + NO PV -- heat pump AND new PV, the active Phase-1 focus,
still 2,439). is_pv_upsell is the deliberately separate PV-upsell cohort (same
fossil + good roof but PV ALREADY attached -- heat pump only, a different
pitch). The upsell rows are is_candidate=false so they never inflate the active
count, but persist and are queryable. They are NOT contact-ready: pv_upsell is
a data segment, not yet a validated sales motion (see CLAUDE.md / the
docs/context file). The two cohorts are mutually exclusive by construction.

WHAT SURVIVES A RE-RUN. The upsert updates only the derived columns
(gemeinde_name, heating, solar_class, has_existing_pv, is_candidate,
is_pv_upsell, computed_at, ...) and leaves `status`, `address`, `plz`, `ort`
untouched on an existing row. A building that no longer qualifies for a cohort
is NOT deleted -- its flag flips to false and its status/history is kept,
because "we contacted them, then they installed PV" is a fact worth keeping;
that same building then joins the upsell cohort, carrying its history across.

THE FK IS SELF-HEALING. gold.building is DROP ... CASCADE'd on every `make
gold`, which silently drops any FK pointing at it -- including this one. So the
FK is re-asserted on every run rather than trusted to survive; without that,
`make gold` would quietly leave neoteq.candidate.egid unconstrained.

ADDRESS ENRICHMENT is an attribute join on egid to bronze.gwr_eingang (the
GWR entrance register), NOT a geocoder -- inside the pilot every candidate
resolves. Validated 2026-08-18: all 2,439 candidates carry >=1 entrance,
97.9% exactly one address; the 52 multi-entrance buildings are disambiguated
to the OFFICIAL address (doffadr='1') deterministically. Address parts are
essentially complete (0 missing street/PLZ, 1 missing house number).
"""

from sqlalchemy import text

from propsearch_data.db import get_engine

# TWO COHORTS, ONE SHARED GATE. Both start from fossil heating + top-2 roof
# solar class; they differ only on whether a PV plant is already attached
# (silver.building_pv). Fossil + no PV = the COLD-CONVERSION candidates (heat
# pump + new PV, the active Phase-1 list); fossil + has PV = the PV-UPSELL
# cohort (heat pump only, PV already there). The two are mutually exclusive by
# construction, so an egid is in at most one at a time.
_FOSSIL_SOLAR = "b.heating IN ('Gas', 'Heizöl') AND b.solar_class IN (4, 5)"
_HAS_PV = "EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = b.egid)"

# Cold-conversion candidates (is_candidate). Unchanged: this is still the 2,439.
CANDIDATE_PREDICATE = f"{_FOSSIL_SOLAR} AND NOT {_HAS_PV}"

# PV-upsell cohort (is_pv_upsell). CAVEAT -- the solar-4/5 roof gate is INHERITED
# from the cold-conversion query, not re-justified for this cohort. It was
# designed as "good roof -> viable heat pump + new PV"; these buildings already
# have PV, so the PV half of that rationale does not apply, and a heat pump
# itself needs no roof. Keeping the gate here scopes upsell to 317; dropping it
# would widen it to all fossil-heat + PV buildings regardless of roof class.
# That yes/no is deliberately left open (see docs/context-neoteq-and-investment
# and CLAUDE.md) -- pv_upsell is a data segment, not yet a validated sales
# motion, so this stays the conservative, gate-inherited definition until a
# conscious call is made.
UPSELL_PREDICATE = f"{_FOSSIL_SOLAR} AND {_HAS_PV}"

DDL = """
CREATE SCHEMA IF NOT EXISTS neoteq;

CREATE TABLE IF NOT EXISTS neoteq.candidate (
    egid          text PRIMARY KEY REFERENCES gold.building (egid),
    gemeinde_name text,
    heating       text,
    hot_water_source     text,
    heat_generator_type  text,
    solar_class   int,
    roof_orientation_deg numeric,
    roof_tilt_deg        numeric,
    dwelling_count       smallint,
    building_segment     text,  -- EFH (1 dwelling) / MFH (2+) / unknown (NULL)
    has_existing_pv boolean,    -- factual: a PV plant is attached (silver.building_pv)
    is_candidate  boolean,      -- cold-conversion cohort (see module doc)
    is_pv_upsell  boolean,      -- PV-upsell cohort; mutually exclusive with is_candidate
    status        text NOT NULL DEFAULT 'not_contacted',
    address       text,         -- nullable, filled by enrich()
    plz           text,
    ort           text,
    computed_at   timestamptz NOT NULL DEFAULT now()
);

-- neoteq.candidate PERSISTS across runs (never dropped), so new derived columns
-- must be added to the already-existing table, not merely declared in the
-- CREATE above. Idempotent: a freshly created table already carries them.
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS hot_water_source     text;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS heat_generator_type  text;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS roof_orientation_deg numeric;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS roof_tilt_deg        numeric;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS dwelling_count       smallint;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS building_segment     text;

-- has_pv was the original factual PV flag; rename it to has_existing_pv (the
-- name the strand uses) on a table that predates the rename. Guarded so a fresh
-- table (which already has the new name from CREATE) and a re-run are both
-- no-ops. A belt-and-suspenders ADD follows for the pathological "neither
-- column exists" case.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'neoteq' AND table_name = 'candidate'
                 AND column_name = 'has_pv')
   AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'neoteq' AND table_name = 'candidate'
                 AND column_name = 'has_existing_pv')
    THEN
        ALTER TABLE neoteq.candidate RENAME COLUMN has_pv TO has_existing_pv;
    END IF;
END $$;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS has_existing_pv boolean;
ALTER TABLE neoteq.candidate ADD COLUMN IF NOT EXISTS is_pv_upsell     boolean;

-- building_segment is the EFH/MFH outreach-track split: EFH = detached (1
-- dwelling), the active Phase-1 focus; MFH = multi-dwelling (2+), deliberately
-- deferred for STWEG/multi-stakeholder complexity; unknown = dwelling count
-- unrecorded in GWR. Pinned so a stray value can't creep in; NULL passes the
-- CHECK, but the upsell maps every dwelling_count (incl. NULL) to a bucket, so
-- no is_candidate row is ever left NULL. A guarded add keeps this idempotent on
-- the persisted table.
DO $$ BEGIN
    ALTER TABLE neoteq.candidate
        ADD CONSTRAINT candidate_building_segment_domain
        CHECK (building_segment IN ('EFH', 'MFH', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""

# Re-assert the FK each run so a `make gold` CASCADE drop is self-healed.
ENSURE_FK = """
ALTER TABLE neoteq.candidate DROP CONSTRAINT IF EXISTS candidate_egid_fkey;
ALTER TABLE neoteq.candidate
    ADD CONSTRAINT candidate_egid_fkey
    FOREIGN KEY (egid) REFERENCES gold.building (egid);
"""

# The EFH/MFH segment is a pure function of dwelling_count, shared by both
# cohorts so the derivation can never drift between them.
_SEGMENT_CASE = """
    CASE
        WHEN b.dwellings = 1  THEN 'EFH'
        WHEN b.dwellings >= 2 THEN 'MFH'
        ELSE 'unknown'                    -- NULL dwellings: unrecorded, not zero
    END"""


def _upsert(predicate: str, *, is_candidate: bool, is_upsell: bool) -> str:
    """Insert/refresh one cohort. status/address/plz/ort are deliberately absent
    from the UPDATE set -- they are hand-edited and must survive a re-run. Each
    cohort sets BOTH membership flags authoritatively (its own true, the other
    false), so a building that migrates cold->upsell (it installed PV) lands in
    exactly one cohort regardless of statement order. has_existing_pv carries the
    real EXISTS, not a per-cohort literal, so it stays factually correct."""
    return f"""
INSERT INTO neoteq.candidate (
    egid, gemeinde_name, heating, hot_water_source, heat_generator_type,
    solar_class, roof_orientation_deg, roof_tilt_deg, dwelling_count,
    building_segment, has_existing_pv, is_candidate, is_pv_upsell, computed_at
)
SELECT
    b.egid, b.gemeinde_name, b.heating, b.hot_water_source, b.heat_generator_type,
    b.solar_class, b.roof_orientation_deg, b.roof_tilt_deg, b.dwellings,
    {_SEGMENT_CASE},
    {_HAS_PV},
    {str(is_candidate).lower()},
    {str(is_upsell).lower()},
    now()
FROM gold.building b
WHERE {predicate}
ON CONFLICT (egid) DO UPDATE SET
    gemeinde_name        = excluded.gemeinde_name,
    heating              = excluded.heating,
    hot_water_source     = excluded.hot_water_source,
    heat_generator_type  = excluded.heat_generator_type,
    solar_class          = excluded.solar_class,
    roof_orientation_deg = excluded.roof_orientation_deg,
    roof_tilt_deg        = excluded.roof_tilt_deg,
    dwelling_count       = excluded.dwelling_count,
    building_segment     = excluded.building_segment,
    has_existing_pv      = excluded.has_existing_pv,
    is_candidate         = excluded.is_candidate,
    is_pv_upsell         = excluded.is_pv_upsell,
    computed_at          = excluded.computed_at;
"""


def _retire(predicate: str, flag_col: str) -> str:
    """Any row still flagged in a cohort but no longer qualifying for it: flip
    that cohort's flag to false, refresh has_existing_pv, keep status/address.
    Never deleted -- outreach history is kept. Covers rows that leave BOTH
    cohorts (e.g. heating is no longer fossil), which neither upsert would touch."""
    return f"""
UPDATE neoteq.candidate c
SET {flag_col}       = false,
    has_existing_pv  = EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = c.egid),
    computed_at      = now()
WHERE c.{flag_col} = true
  AND NOT EXISTS (
      SELECT 1 FROM gold.building b
      WHERE b.egid = c.egid AND {predicate}
  );
"""


UPSERT_CANDIDATE = _upsert(CANDIDATE_PREDICATE, is_candidate=True, is_upsell=False)
UPSERT_UPSELL = _upsert(UPSELL_PREDICATE, is_candidate=False, is_upsell=True)
RETIRE_CANDIDATE = _retire(CANDIDATE_PREDICATE, "is_candidate")
RETIRE_UPSELL = _retire(UPSELL_PREDICATE, "is_pv_upsell")

# One canonical address per building: the official entrance (doffadr='1') first,
# then official street, then lowest edid -- deterministic for multi-entrance
# buildings. Fills every row that has an entrance (all candidates do).
ENRICH = """
UPDATE neoteq.candidate c
SET address = a.address,
    plz     = a.plz,
    ort     = a.ort
FROM (
    SELECT DISTINCT ON (egid)
        egid,
        NULLIF(trim(strname || ' ' || COALESCE(deinr, '')), '') AS address,
        NULLIF(dplz4, '')    AS plz,
        NULLIF(dplzname, '') AS ort
    FROM bronze.gwr_eingang
    ORDER BY egid, (doffadr = '1') DESC, (stroffiziel = '1') DESC, edid
) a
WHERE a.egid = c.egid;
"""


def build() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(DDL))
        for stmt in ENSURE_FK.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        conn.execute(text(UPSERT_CANDIDATE))
        conn.execute(text(UPSERT_UPSELL))
        retired = conn.execute(text(RETIRE_CANDIDATE)).rowcount
        retired_upsell = conn.execute(text(RETIRE_UPSELL)).rowcount
        conn.execute(text(ENRICH))

        total = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate")
        ).scalar()
        cands = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate WHERE is_candidate")
        ).scalar()
        upsell = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell")
        ).scalar()
        with_addr = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND address IS NOT NULL")
        ).scalar()

    print(f"neoteq.candidate: {total} rows | is_candidate={cands} | "
          f"is_pv_upsell={upsell} | retired={retired}/+{retired_upsell} this run")
    print(f"  address resolved: {with_addr}/{cands} "
          f"({100 * with_addr / cands:.1f}%) of current candidates")


if __name__ == "__main__":
    build()
