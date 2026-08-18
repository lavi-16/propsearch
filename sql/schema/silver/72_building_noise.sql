-- silver.rail_noise     -- one row per rail facade point (xtf_id), 937 rows (detail)
-- silver.building_noise -- one row per building (EGID), 11,217 rows      (aggregate)
--
-- Noise exposure (BAFU sonBASE road + BAV rail), a building-level risk signal
-- analogous to the hazard layer. Two sources, two very different join stories.
--
-- ROAD is already at building grain: bronze.laerm_strasse was derived by
-- sampling the two road COGs at each GWR building point, so it carries egid
-- directly. THE NULL/ZERO DISTINCTION IS A FACT: the raster NODATA (-9999)
-- landed as NULL = "outside the modelled area"; a genuine 0.0 pixel would mean
-- "computed negligible". They are different statements -- never read a NULL
-- lr_tag as "quiet". road_noise_modelled ties the two apart by CHECK. (188 of
-- 11,217 buildings fall outside the modelled area.)
--
-- RAIL DOES NOT JOIN BY ATTRIBUTE. bronze.laerm_bahn has an EGID field but it
-- is 0% populated in the pilot, so the building link is SPATIAL: each facade
-- point is assigned to its nearest building, then the per-building maximum is
-- taken. All 937 points fall within 50 m of a building (verified: 852 within
-- 20 m, 900 within 30 m, 937 within 50 m), so 50 m links every point exactly
-- once. The threshold is a documented choice, flagged like PILOT_BBOX.
--
-- Rail day/night are fully populated and day >= night on every point (verified);
-- road day >= night on every building. Both orderings are pinned by CHECK.

DROP TABLE IF EXISTS silver.rail_noise CASCADE;

CREATE TABLE silver.rail_noise (
    xtf_id           text     PRIMARY KEY,
    lr_day           numeric  NOT NULL,
    lr_night         numeric  NOT NULL,
    floor            text,
    es_katalog       text,          -- Empfindlichkeitsstufe (sensitivity class)
    operation_status text,
    geom             geometry(Point, 2056) NOT NULL,

    CONSTRAINT rail_noise_day_ge_night CHECK (lr_day >= lr_night)
);

INSERT INTO silver.rail_noise (
    xtf_id, lr_day, lr_night, floor, es_katalog, operation_status, geom
)
SELECT
    r.xtf_id,
    r.lr_day,
    r.lr_night,
    NULLIF(r.floor, ''),
    NULLIF(r.es_katalog_de, ''),
    NULLIF(r.operationstatus_katalog_de, ''),
    r.geometry
FROM bronze.laerm_bahn r;

CREATE INDEX rail_noise_geom_idx ON silver.rail_noise USING GIST (geom);

COMMENT ON TABLE silver.rail_noise IS
    'BAV rail noise facade points, one row per xtf_id. EGID is empty in the '
    'source -- these link to buildings spatially (see silver.building_noise), '
    'never by attribute.';


-- ---------------------------------------------------------------------------
-- One row per building: road (attribute) + rail (nearest-point maximum).
-- Spine is silver.building, so every building appears even where neither
-- source reaches it. Two NOT NULL booleans keep "measured" apart from
-- "unrecorded", each tied to its payload by CHECK.

DROP TABLE IF EXISTS silver.building_noise CASCADE;

CREATE TABLE silver.building_noise (
    egid                text     PRIMARY KEY REFERENCES silver.building (egid),

    road_lr_day         numeric,
    road_lr_night       numeric,
    road_noise_modelled boolean  NOT NULL,

    rail_lr_day         numeric,
    rail_lr_night       numeric,
    has_rail_noise      boolean  NOT NULL,

    -- Modelled iff a daytime road value exists (NODATA -> NULL -> not modelled).
    CONSTRAINT building_noise_road_modelled_iff_value
        CHECK (road_noise_modelled = (road_lr_day IS NOT NULL)),
    -- A rail exposure exists iff a facade point linked to this building.
    CONSTRAINT building_noise_rail_iff_value
        CHECK (has_rail_noise = (rail_lr_day IS NOT NULL)),
    CONSTRAINT building_noise_road_day_ge_night
        CHECK (road_lr_day IS NULL OR road_lr_night IS NULL OR road_lr_day >= road_lr_night),
    CONSTRAINT building_noise_rail_day_ge_night
        CHECK (rail_lr_day IS NULL OR rail_lr_night IS NULL OR rail_lr_day >= rail_lr_night)
);

INSERT INTO silver.building_noise (
    egid, road_lr_day, road_lr_night, road_noise_modelled,
    rail_lr_day, rail_lr_night, has_rail_noise
)
WITH rail_agg AS (
    -- Assign each facade point to its single nearest building within 50 m,
    -- then take the loudest reading per building.
    SELECT nb.egid,
           max(r.lr_day)   AS rail_lr_day,
           max(r.lr_night) AS rail_lr_night
    FROM silver.rail_noise r
    CROSS JOIN LATERAL (
        SELECT b.egid
        FROM silver.building b
        WHERE ST_DWithin(r.geom, b.geom, 50)
        ORDER BY r.geom <-> b.geom
        LIMIT 1
    ) nb
    GROUP BY nb.egid
)
SELECT
    b.egid,
    s.lr_tag,
    s.lr_nacht,
    s.lr_tag IS NOT NULL,
    ra.rail_lr_day,
    ra.rail_lr_night,
    ra.egid IS NOT NULL
FROM silver.building b
LEFT JOIN bronze.laerm_strasse s ON s.egid = b.egid
LEFT JOIN rail_agg            ra ON ra.egid = b.egid;

CREATE INDEX building_noise_rail_idx ON silver.building_noise (has_rail_noise);

COMMENT ON TABLE silver.building_noise IS
    'Noise exposure per building. Road from the sampled COG (attribute join, '
    'egid); rail from the nearest facade point within 50 m (spatial). dB(A) '
    'Beurteilungspegel Lr.';
COMMENT ON COLUMN silver.building_noise.road_noise_modelled IS
    'false means the building is outside the modelled road-noise area '
    '(raster NODATA). A genuinely quiet building would carry a value near 0, '
    'not NULL -- never read NULL as "quiet".';
COMMENT ON COLUMN silver.building_noise.has_rail_noise IS
    'true iff a rail facade point lies within 50 m. Most buildings have none.';
