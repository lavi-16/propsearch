-- gold.building -- the building record. One row per EXISTING building, 10,392 rows.
--
-- A new grain in gold: building (EGID), one level below gold.parcel. Callers
-- reach the parcel via `egrid`; anything per-parcel aggregates first (up to 29
-- buildings per parcel). The parcel-level rollups on gold.parcel exist so the
-- common "what's on this parcel?" question needs no join at all.
--
-- SELECTS FROM SILVER ONLY, like every gold table. Three silver facts, all
-- keyed PK egid so none can fan out: silver.building (the spine),
-- silver.building_solar, silver.building_noise.
--
-- EXISTING BUILDINGS ONLY, and the CHECK is what makes that permanent.
-- silver.building carries all 11,217 GSTAT states; the 700 demolished and 125
-- projected/approved rows look entirely current, so surfacing one here as a
-- building that stands today is a correctness bug. Filtered by is_existing on
-- the way in, pinned by CHECK on the way out -- the gold.parcel_hazard
-- synoptic-exclusion precedent.
--
-- Three coverage booleans keep "measured absence" apart from "unrecorded",
-- each tied to its payload by CHECK, exactly as gold.parcel does for zoning
-- and hazard. NULL attribute columns (year_built, volume, ...) are UNRECORDED
-- on a raw register, never zero -- carried through from silver unchanged.

DROP TABLE IF EXISTS gold.building CASCADE;

CREATE TABLE gold.building (
    egid               text     PRIMARY KEY,
    egrid              text,          -- link to gold.parcel; nullable, NOT a FK
    bfs_nr             integer  NOT NULL,
    gemeinde_name      text     NOT NULL,

    building_category  text,
    building_class     text,
    year_built         smallint,
    area_m2            integer,
    floors             smallint,
    dwellings          smallint,
    heating            text,

    -- Solar (aggregated from roof planes in silver).
    solar_class        smallint,
    roof_area_m2       numeric,
    solar_yield_kwh    numeric,
    has_solar_potential boolean NOT NULL,

    -- Noise (dB(A) Lr).
    noise_road_day     numeric,
    noise_road_night   numeric,
    road_noise_modelled boolean NOT NULL,
    noise_rail_day     numeric,
    noise_rail_night   numeric,
    has_rail_noise     boolean NOT NULL,

    geom               geometry(Point, 2056) NOT NULL,

    CONSTRAINT building_solar_iff_class
        CHECK (has_solar_potential = (solar_class IS NOT NULL)),
    CONSTRAINT building_road_modelled_iff_value
        CHECK (road_noise_modelled = (noise_road_day IS NOT NULL)),
    CONSTRAINT building_rail_iff_value
        CHECK (has_rail_noise = (noise_rail_day IS NOT NULL)),
    CONSTRAINT building_solar_class_range
        CHECK (solar_class IS NULL OR solar_class BETWEEN 1 AND 5)
);

INSERT INTO gold.building (
    egid, egrid, bfs_nr, gemeinde_name,
    building_category, building_class, year_built, area_m2, floors, dwellings, heating,
    solar_class, roof_area_m2, solar_yield_kwh, has_solar_potential,
    noise_road_day, noise_road_night, road_noise_modelled,
    noise_rail_day, noise_rail_night, has_rail_noise,
    geom
)
SELECT
    b.egid,
    b.egrid,
    b.bfs_nr,
    gm.gemeinde_name,

    b.building_category,
    b.building_class,
    b.year_built,
    b.area_m2,
    b.floors,
    b.dwellings,
    b.heating,

    s.best_class,
    s.roof_area_m2,
    s.solar_yield_kwh,
    s.egid IS NOT NULL,

    n.road_lr_day,
    n.road_lr_night,
    n.road_noise_modelled,
    n.rail_lr_day,
    n.rail_lr_night,
    n.has_rail_noise,

    b.geom
FROM silver.building b
JOIN      silver.gemeinde       gm ON gm.bfs_nr = b.bfs_nr
LEFT JOIN silver.building_solar s  ON s.egid = b.egid
LEFT JOIN silver.building_noise n  ON n.egid = b.egid
WHERE b.is_existing;

CREATE INDEX gold_building_egrid_idx  ON gold.building (egrid);
CREATE INDEX gold_building_bfs_nr_idx ON gold.building (bfs_nr);
CREATE INDEX gold_building_geom_idx   ON gold.building USING GIST (geom);

COMMENT ON TABLE gold.building IS
    'The building record: attributes, roof solar and noise in one row per '
    'existing EGID. Joins to gold.parcel on egrid (many buildings per parcel). '
    'Demolished/projected buildings are excluded by CHECK.';
COMMENT ON COLUMN gold.building.egrid IS
    'Links to gold.parcel. Nullable and NOT a FK: some buildings carry no '
    'EGRID or sit on a parcel outside the pilot.';
COMMENT ON COLUMN gold.building.has_solar_potential IS
    'false means the building has no surveyed roof plane -- typically a minor '
    'structure the survey excludes, not a defect.';
COMMENT ON COLUMN gold.building.road_noise_modelled IS
    'false means outside the modelled road-noise area. Never read the NULL '
    'noise value as "quiet".';
COMMENT ON COLUMN gold.building.heating IS
    'Decoded main heat generator. "Keine" is a real value; NULL is unrecorded.';
