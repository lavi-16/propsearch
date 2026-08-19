-- silver.building -- the building spine. One row per building (EGID), 11,217 rows.
--
-- From bronze.gwr_gebaeude (federal GWR via BFS MADD). This is a NEW GRAIN,
-- one level BELOW the parcel: up to 29 buildings share a single EGRID. Nothing
-- here joins to the 9,879-row parcel spine 1:1 -- callers reach the parcel via
-- `egrid`, and anything per-parcel must aggregate buildings first.
--
-- THREE TRAPS THIS TABLE PINS DOWN (all documented in CLAUDE.md, all made
-- unreachable here rather than merely written down):
--
-- 1. GSTAT. 700 of these buildings are DEMOLISHED (gstat='1007') and 125 are
--    projected/approved/under-construction; every other column on a demolished
--    row is populated exactly as it was the day it came down, so it looks
--    entirely current. ALL states are kept here on purpose -- "was there a
--    building on this parcel?" is a real question -- but `is_existing` is a
--    NOT NULL boolean tied to gstat by CHECK, so a demolished building can
--    never be silently counted as current. gold.building filters on it.
--
-- 2. NULL MEANS UNRECORDED. GWR is a raw register, "not corrected, imputed or
--    statistically supplemented" (BFS). Fill rates are low and honest:
--    year_built 80.7%, volume_m3 3.5%, floors 67.5%, dwellings 62.7%. A NULL is
--    unrecorded -- NOT zero, NOT "no such feature". The source empty string
--    becomes NULL via NULLIF, and the numeric columns stay nullable. Do not
--    coalesce them to 0.
--
-- 3. EGRID IS A LINK, NOT A KEY, AND NOT A FK. 383 buildings carry no EGRID and
--    490 sit on a parcel outside the pilot Landwertzonen set, so `egrid` cannot
--    REFERENCE silver.parcel. It is a nullable plain column; 10,344 of 11,217
--    (92.2%) resolve to a parcel in silver.parcel, and a test asserts that rate.
--
-- CODE DECODING follows the gn_kantname precedent: the source ships its own
-- lookup (bronze.gwr_kodes), so no hand-built crosswalk. The join is on BOTH
-- (cecodid, cmerkm) -- code 857 is defined five times over, once per attribute,
-- so joining on cecodid alone fans out. Verified 1:1 here.

DROP TABLE IF EXISTS silver.building CASCADE;

CREATE TABLE silver.building (
    egid               text     PRIMARY KEY,
    egrid              text,          -- link to silver.parcel; nullable, NOT a FK
    bfs_nr             integer  NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    parcel_number      text,          -- lparz, register parcel no. (informational)

    gstat              text     NOT NULL,
    building_status    text     NOT NULL,   -- decoded gstat label
    is_existing        boolean  NOT NULL,

    building_category  text,          -- decoded gkat
    building_class     text,          -- decoded gklas
    year_built         smallint,
    area_m2            integer,
    volume_m3          integer,
    floors             smallint,
    dwellings          smallint,
    heating            text,          -- decoded genh1
    hot_water_source   text,          -- genw1 bucketed (see CASE in the INSERT)
    heat_generator_type text,         -- gwaerzh1 bucketed (see CASE in the INSERT)

    geom               geometry(Point, 2056) NOT NULL,

    CONSTRAINT building_is_existing_iff_1004
        CHECK (is_existing = (gstat = '1004')),
    CONSTRAINT building_year_range
        CHECK (year_built IS NULL OR year_built BETWEEN 1200 AND 2035),
    CONSTRAINT building_area_positive
        CHECK (area_m2 IS NULL OR area_m2 > 0),
    CONSTRAINT building_volume_positive
        CHECK (volume_m3 IS NULL OR volume_m3 > 0),
    CONSTRAINT building_floors_positive
        CHECK (floors IS NULL OR floors > 0),
    CONSTRAINT building_dwellings_positive
        CHECK (dwellings IS NULL OR dwellings > 0),
    CONSTRAINT building_hot_water_source_domain
        CHECK (hot_water_source IS NULL OR hot_water_source
               IN ('fossil', 'electric', 'solar-thermal', 'other')),
    CONSTRAINT building_heat_generator_type_domain
        CHECK (heat_generator_type IS NULL OR heat_generator_type
               IN ('boiler_condensing', 'boiler_non_condensing',
                   'boiler_generic', 'stove', 'heat_pump', 'other'))
);

INSERT INTO silver.building (
    egid, egrid, bfs_nr, parcel_number,
    gstat, building_status, is_existing,
    building_category, building_class, year_built, area_m2, volume_m3,
    floors, dwellings, heating, hot_water_source, heat_generator_type, geom
)
SELECT
    g.egid,
    NULLIF(g.egrid, ''),
    g.ggdenr::integer,
    NULLIF(g.lparz, ''),

    g.gstat,
    kstat.codtxtld,
    g.gstat = '1004',

    kkat.codtxtld,
    kklas.codtxtld,
    NULLIF(g.gbauj, '')::numeric::smallint,
    NULLIF(g.garea, '')::numeric::integer,
    NULLIF(g.gvol,  '')::numeric::integer,
    NULLIF(g.gastw, '')::numeric::smallint,
    NULLIF(g.ganzwhg, '')::numeric::smallint,
    kenh.codtxtld,

    -- genw1 (hot-water energy SOURCE) bucketed to the four the strand targets.
    -- Codes are the GWR energy-source space (7500-7599). We group rather than
    -- carry the raw label because the question is "is the hot water still on the
    -- fossil boiler?": 7520 Gas / 7530 Heizoel = fossil; 7560 Elektrizitaet =
    -- electric; 7570 Sonne (thermisch) = solar-thermal; the rest (wood, district
    -- heat, heat-pump sources, Keine, ...) = other. NULL = unrecorded.
    CASE
        WHEN g.genw1 IN ('7520', '7530') THEN 'fossil'
        WHEN g.genw1 =  '7560'           THEN 'electric'
        WHEN g.genw1 =  '7570'           THEN 'solar-thermal'
        WHEN NULLIF(g.genw1, '') IS NULL THEN NULL
        ELSE 'other'
    END,

    -- gwaerzh1 (heat generator TYPE) bucketed, flagging condensing vs generic.
    -- 7434/7435 condensing boiler; 7432/7433 non-condensing; 7430/7431 generic;
    -- 7436 Ofen (stove); 7410/7411 heat pump; rest = other. NULL = unrecorded.
    CASE
        WHEN g.gwaerzh1 IN ('7434', '7435') THEN 'boiler_condensing'
        WHEN g.gwaerzh1 IN ('7432', '7433') THEN 'boiler_non_condensing'
        WHEN g.gwaerzh1 IN ('7430', '7431') THEN 'boiler_generic'
        WHEN g.gwaerzh1 =  '7436'           THEN 'stove'
        WHEN g.gwaerzh1 IN ('7410', '7411') THEN 'heat_pump'
        WHEN NULLIF(g.gwaerzh1, '') IS NULL THEN NULL
        ELSE 'other'
    END,

    g.geometry
FROM bronze.gwr_gebaeude g
LEFT JOIN bronze.gwr_kodes kstat ON kstat.cecodid = g.gstat AND kstat.cmerkm = 'GSTAT'
LEFT JOIN bronze.gwr_kodes kkat  ON kkat.cecodid  = g.gkat  AND kkat.cmerkm  = 'GKAT'
LEFT JOIN bronze.gwr_kodes kklas ON kklas.cecodid = g.gklas AND kklas.cmerkm = 'GKLAS'
LEFT JOIN bronze.gwr_kodes kenh  ON kenh.cecodid  = g.genh1 AND kenh.cmerkm  = 'GENH1';

CREATE INDEX building_egrid_idx  ON silver.building (egrid);
CREATE INDEX building_bfs_nr_idx ON silver.building (bfs_nr);
CREATE INDEX building_geom_idx   ON silver.building USING GIST (geom);
CREATE INDEX building_existing_idx ON silver.building (is_existing);

COMMENT ON TABLE silver.building IS
    'Building spine, one row per EGID. A grain BELOW the parcel (up to 29 '
    'buildings per EGRID) -- aggregate before any per-parcel count. Keeps all '
    'GSTAT states; filter on is_existing for current state.';
COMMENT ON COLUMN silver.building.egrid IS
    'Federal parcel id, links to silver.parcel. Nullable and NOT a FK: 383 '
    'buildings have none and 490 sit on a parcel outside the pilot set. '
    '10,344 of 11,217 (92.2%) resolve to silver.parcel.';
COMMENT ON COLUMN silver.building.is_existing IS
    'gstat = 1004. false includes 700 demolished (1007) and 125 '
    'projected/approved/under-construction buildings that otherwise look '
    'entirely current. gold.building keeps only is_existing rows.';
COMMENT ON COLUMN silver.building.volume_m3 IS
    'Raw register value, 3.5% filled. NULL means unrecorded, never zero.';
COMMENT ON COLUMN silver.building.heating IS
    'Decoded genh1 (heat generator, main heating). "Keine" is a real value '
    '(no heating), distinct from NULL (unrecorded).';
COMMENT ON COLUMN silver.building.hot_water_source IS
    'genw1 (hot-water energy source) bucketed: fossil (Gas/Heizoel), electric, '
    'solar-thermal, other. NULL is unrecorded, never "no hot water".';
COMMENT ON COLUMN silver.building.heat_generator_type IS
    'gwaerzh1 (heat generator type) bucketed, condensing kept distinct from '
    'generic boiler. NULL is unrecorded.';
