-- silver.building_pv -- one row per building (EGID) that already has PV.
--
-- The aggregate that unblocks the neoteq exclusion: a building present here
-- already carries at least one registered PV plant, so it is NOT a "good roof,
-- no PV" candidate. The silver.building_solar shape (only matched buildings
-- get a row), not the silver.building_noise shape (every building) -- absence
-- from this table means "no attached PV", which is exactly what the candidate
-- query tests with NOT EXISTS.
--
-- THE LINK IS SPATIAL, lifted from silver.building_noise's rail join: each PV
-- plant is assigned to its single nearest EXISTING building within a radius,
-- then aggregated per building. silver.pv_plant carries no EGID (the Pronovo
-- registry has none), so there is no attribute join to fall back on.
--
-- RADIUS = 50 m, the rail-noise precedent. Grounded 2026-08-18, plant->nearest
-- existing-building distance is BIMODAL: ~75% within ~9 m (geocoded to the
-- building) but ~15% at PLZ/municipality-centroid distance (p90 668 m). 286 PV
-- plants sit >50 m from any building and CANNOT be attached -- so this table is
-- a FLOOR on "buildings with PV", not exhaustive; a candidate absent here may
-- still have centroid-geocoded PV we couldn't pin. The radius choice moves only
-- ~20 buildings (1,655 at 25 m .. 1,675 at 50 m), so 50 m stands for
-- consistency. It is a documented choice, flagged like the rail 50 m and
-- PILOT_BBOX. Matches to EXISTING buildings only (silver.building filtered by
-- is_existing), so a plant is never pinned to a demolished building.

DROP TABLE IF EXISTS silver.building_pv CASCADE;

CREATE TABLE silver.building_pv (
    egid                  text     PRIMARY KEY REFERENCES silver.building (egid),
    has_pv                boolean  NOT NULL,
    n_pv_plants           integer  NOT NULL,
    pv_total_power_kw     numeric,
    pv_earliest_operation date,

    -- Only matched buildings are inserted, so has_pv is always true; the column
    -- and CHECK make that explicit and self-documenting for a NOT EXISTS reader.
    CONSTRAINT building_pv_has_pv CHECK (has_pv),
    CONSTRAINT building_pv_count_positive CHECK (n_pv_plants > 0)
);

INSERT INTO silver.building_pv (
    egid, has_pv, n_pv_plants, pv_total_power_kw, pv_earliest_operation
)
WITH pv_matched AS (
    -- Assign each PV plant to its single nearest EXISTING building within 50 m.
    SELECT nb.egid,
           count(*)                      AS n_pv_plants,
           sum(p.total_power_kw)         AS pv_total_power_kw,
           min(p.beginning_of_operation) AS pv_earliest_operation
    FROM silver.pv_plant p
    CROSS JOIN LATERAL (
        SELECT b.egid
        FROM silver.building b
        WHERE b.is_existing
          AND ST_DWithin(p.geom, b.geom, 50)
        ORDER BY p.geom <-> b.geom
        LIMIT 1
    ) nb
    GROUP BY nb.egid
)
SELECT egid, true, n_pv_plants, pv_total_power_kw, pv_earliest_operation
FROM pv_matched;

COMMENT ON TABLE silver.building_pv IS
    'Existing buildings carrying >=1 registered PV plant, matched spatially '
    '(nearest building within 50 m). A FLOOR, not exhaustive: 286 pilot PV '
    'plants are geocoded to a PLZ centroid >50 m from any building and cannot '
    'be attached. Absence = no attached PV (the neoteq exclusion key).';
COMMENT ON COLUMN silver.building_pv.pv_earliest_operation IS
    'Earliest commissioning date among the building''s PV plants.';
