-- silver.roof_plane   -- one row per roof plane (DF_UID), 34,358 rows  (detail)
-- silver.building_solar -- one row per building with >=1 plane (EGID)   (aggregate)
--
-- From bronze.sonnendach (BFE SOLKAT). A THIRD grain, one level below the
-- building: parcel (EGRID) -> building (EGID) -> roof plane (DF_UID). A roof is
-- split by pitch and orientation, so a building averages ~3 planes. Joining
-- planes straight to the parcel spine fans out TWICE (up to 29 buildings x ~3
-- planes) -- so the detail stays at its own grain and the aggregate is what the
-- building layer consumes.
--
-- THE gwr_egid CAST IS LOAD-BEARING. It arrives as double precision with NULLs
-- (int32 in source; 6.3% of planes carry no register link, rendered as
-- float64+NaN). Read straight, 2337457.0 will not match the text '2337457' in
-- silver.building.egid. Cast (gwr_egid)::bigint::text. A NULL egid is an
-- UNLINKED roof -- surveyed, no register match -- kept as a fact, the same
-- measured-absence distinction as hazard_surveyed; it is not "no roof".
--
-- GEOMETRY REPAIRED ONCE. 69 of 34,358 planes are invalid (self-intersections),
-- landed as-is per the bronze contract. ST_MakeValid materialised into an
-- indexed column, exactly as silver.hazard_zone does, so any future area or
-- overlay arithmetic runs over valid indexed geometry.

DROP TABLE IF EXISTS silver.roof_plane CASCADE;

CREATE TABLE silver.roof_plane (
    df_uid          bigint   PRIMARY KEY,
    egid            text,          -- (gwr_egid)::bigint::text; NULL = unlinked roof
    klasse          smallint NOT NULL,
    flaeche_m2      numeric  NOT NULL,
    stromertrag_kwh numeric,
    ausrichtung     numeric,       -- azimuth
    neigung         numeric,       -- tilt
    geom            geometry(MultiPolygon, 2056) NOT NULL,

    CONSTRAINT roof_plane_klasse_range CHECK (klasse BETWEEN 1 AND 5),
    CONSTRAINT roof_plane_valid_geom   CHECK (ST_IsValid(geom))
);

INSERT INTO silver.roof_plane (
    df_uid, egid, klasse, flaeche_m2, stromertrag_kwh, ausrichtung, neigung, geom
)
SELECT
    s.df_uid::bigint,
    (s.gwr_egid)::bigint::text,
    s.klasse::smallint,
    s.flaeche,
    s.stromertrag,
    s.ausrichtung,
    s.neigung,
    ST_Multi(ST_MakeValid(s.geometry))
FROM bronze.sonnendach s;

CREATE INDEX roof_plane_egid_idx ON silver.roof_plane (egid);
CREATE INDEX roof_plane_geom_idx ON silver.roof_plane USING GIST (geom);

COMMENT ON TABLE silver.roof_plane IS
    'Roof planes, one row per DF_UID. A grain below the building (~3 per '
    'building). Aggregate via silver.building_solar; never join straight to '
    'the parcel spine.';
COMMENT ON COLUMN silver.roof_plane.klasse IS
    'Suitability ordinal 1-5, WORST to best: 1 gering (<800 kWh/m2/yr), '
    '2 mittel, 3 gut, 4 sehr gut, 5 top (>=1400). Higher is better.';
COMMENT ON COLUMN silver.roof_plane.egid IS
    'Building link. NULL means the plane has no register match (unlinked, '
    'surveyed) -- not "no roof". Cast from the double-precision source.';


-- ---------------------------------------------------------------------------
-- Aggregate to the building grain. One row per building carrying >=1 plane,
-- restricted to buildings present in silver.building so egid is a real FK.
-- 7,701 buildings. A building with NO plane simply has no row here; whether
-- that means "surveyed, minor structure excluded" is decided where this joins
-- the building spine (gold.building.has_solar_potential).

DROP TABLE IF EXISTS silver.building_solar CASCADE;

CREATE TABLE silver.building_solar (
    egid            text     PRIMARY KEY REFERENCES silver.building (egid),
    best_class      smallint NOT NULL,
    roof_area_m2    numeric  NOT NULL,
    solar_yield_kwh numeric,
    n_planes        integer  NOT NULL,

    CONSTRAINT building_solar_best_class_range CHECK (best_class BETWEEN 1 AND 5),
    CONSTRAINT building_solar_n_planes_positive CHECK (n_planes > 0)
);

INSERT INTO silver.building_solar (egid, best_class, roof_area_m2, solar_yield_kwh, n_planes)
SELECT
    r.egid,
    max(r.klasse),
    sum(r.flaeche_m2),
    sum(r.stromertrag_kwh),
    count(*)
FROM silver.roof_plane r
JOIN silver.building b ON b.egid = r.egid
WHERE r.egid IS NOT NULL
GROUP BY r.egid;

COMMENT ON TABLE silver.building_solar IS
    'Roof solar potential aggregated to the building. best_class = max plane '
    'suitability, roof_area_m2/solar_yield_kwh summed over planes. Absence of '
    'a row means the building has no surveyed roof plane.';
