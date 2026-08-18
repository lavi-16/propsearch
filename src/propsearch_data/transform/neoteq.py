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

WHAT SURVIVES A RE-RUN. The upsert updates only the derived columns
(gemeinde_name, heating, solar_class, has_pv, is_candidate, computed_at) and
leaves `status`, `address`, `plz`, `ort` untouched on an existing row. A
building that no longer qualifies (got PV, or the criteria changed) is NOT
deleted -- its is_candidate flips to false and its status/history is kept,
because "we contacted them, then they installed PV" is a fact worth keeping.

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

# The current candidate criteria, in one place. Fossil heating + top-2 roof
# solar class + no PV plant attached (silver.building_pv absence).
CANDIDATE_PREDICATE = """
    b.heating IN ('Gas', 'Heizöl')
    AND b.solar_class IN (4, 5)
    AND NOT EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = b.egid)
"""

DDL = """
CREATE SCHEMA IF NOT EXISTS neoteq;

CREATE TABLE IF NOT EXISTS neoteq.candidate (
    egid          text PRIMARY KEY REFERENCES gold.building (egid),
    gemeinde_name text,
    heating       text,
    solar_class   int,
    has_pv        boolean,
    is_candidate  boolean,      -- true under current criteria (see module doc)
    status        text NOT NULL DEFAULT 'not_contacted',
    address       text,         -- nullable, filled by enrich()
    plz           text,
    ort           text,
    computed_at   timestamptz NOT NULL DEFAULT now()
);
"""

# Re-assert the FK each run so a `make gold` CASCADE drop is self-healed.
ENSURE_FK = """
ALTER TABLE neoteq.candidate DROP CONSTRAINT IF EXISTS candidate_egid_fkey;
ALTER TABLE neoteq.candidate
    ADD CONSTRAINT candidate_egid_fkey
    FOREIGN KEY (egid) REFERENCES gold.building (egid);
"""

# Insert/refresh the current candidates. status/address/plz/ort are deliberately
# absent from the UPDATE set -- those are hand-edited and must survive a re-run.
UPSERT = f"""
INSERT INTO neoteq.candidate (
    egid, gemeinde_name, heating, solar_class, has_pv, is_candidate, computed_at
)
SELECT
    b.egid, b.gemeinde_name, b.heating, b.solar_class,
    EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = b.egid),  -- false for candidates
    true,
    now()
FROM gold.building b
WHERE {CANDIDATE_PREDICATE}
ON CONFLICT (egid) DO UPDATE SET
    gemeinde_name = excluded.gemeinde_name,
    heating       = excluded.heating,
    solar_class   = excluded.solar_class,
    has_pv        = excluded.has_pv,
    is_candidate  = true,
    computed_at   = excluded.computed_at;
"""

# Any row previously flagged a candidate but no longer qualifying: flip
# is_candidate to false, refresh has_pv, keep status/address. Never deleted.
RETIRE_DROPOUTS = f"""
UPDATE neoteq.candidate c
SET is_candidate = false,
    has_pv       = EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = c.egid),
    computed_at  = now()
WHERE c.is_candidate = true
  AND NOT EXISTS (
      SELECT 1 FROM gold.building b
      WHERE b.egid = c.egid AND {CANDIDATE_PREDICATE}
  );
"""

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
        conn.execute(text(UPSERT))
        retired = conn.execute(text(RETIRE_DROPOUTS)).rowcount
        conn.execute(text(ENRICH))

        total = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate")
        ).scalar()
        cands = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate WHERE is_candidate")
        ).scalar()
        with_addr = conn.execute(
            text("SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND address IS NOT NULL")
        ).scalar()

    print(f"neoteq.candidate: {total} rows | is_candidate={cands} | "
          f"retired this run={retired}")
    print(f"  address resolved: {with_addr}/{cands} "
          f"({100 * with_addr / cands:.1f}%) of current candidates")


if __name__ == "__main__":
    build()
