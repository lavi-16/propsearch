-- gold.parcel -- the parcel record. One row per parcel, 9,879 rows.
--
-- This is the table the spec's success criterion is about: "one test parcel
-- in the pilot cluster returns a correct, complete record across all 5
-- layers", in one lookup rather than by re-deriving a five-way join.
--
-- Spine is silver.parcel, LEFT JOINed to silver.parcel_zone and
-- silver.parcel_hazard_synoptic. Both of those are keyed PK egrid, so
-- neither can fan out -- gold.parcel has exactly as many rows as
-- silver.parcel, and a test asserts it.
--
-- THE TWO BOOLEAN PAIRS ARE THE POINT OF THIS TABLE.
--
-- Denormalising three sources onto one row means three different reasons a
-- column can be NULL, and two of them are facts rather than gaps:
--
--   in_bauzone = false      the parcel is OUTSIDE every Bauzone. 1,576 of
--                           9,879. A measured fact, not missing data.
--   hazard_surveyed = false the parcel is outside the surveyed perimeter.
--                           874 of 9,879. UNKNOWN, not safe. This is the
--                           distinction that matters most: a parcel graded
--                           `keine` was surveyed and is clear; a parcel
--                           with no match was never assessed. Collapsing
--                           both to NULL asserts a safety that was never
--                           measured.
--
-- Without the booleans both arrive as a bare NULL and read identically to
-- "no zoning restriction" / "no hazard". The CHECKs tie each flag to its
-- payload so the two can never drift apart.
--
-- HAZARD_RANK IS A BICONDITIONAL, NOT A ONE-WAY GUARD. The obvious form,
--   CHECK (hazard_rank IS NULL OR hazard_grade_overall <> 'Restgefahr')
-- is asymmetric and leaks two states: a surveyed, graded row with a MISSING
-- rank passes, and an unsurveyed row carrying a stale rank passes too --
-- there hazard_grade_overall IS NULL, the <> comparison evaluates to NULL,
-- and a CHECK admits NULL. The biconditional pins the rank to exactly the
-- rows that have an ordinal position.
--
-- Restgefahr stays off the ordinal scale on purpose: residual risk behind a
-- protection structure is a different kind of statement from a graded
-- intensity, so it must never sort into gering < mittel < erheblich.
--
-- NAMING: hazard_grade_overall, not hazard_grade_synoptic. The synoptic
-- SOURCE LAYER is deliberately absent from gold.parcel_hazard (see 30_), so
-- a near-identical name across the two tables would invite exactly the
-- confusion that removal was meant to end.
--
-- WHAT IS NOT HERE. No zone_category_code. Bodenpreise uses 8 coarse
-- tax-valuation categories; parcels carry 73 municipal codes / 25 canton
-- classes, and NO crosswalk is published (the Schaetzer-Handbuch was
-- checked and has none). A mapping looks obvious -- EFH -> "4 EFH",
-- EWG -> "3 MFH" -- and is a guess. gold.gemeinde_bodenpreis joins on
-- (bfs_nr, jahr) only. A test asserts no such column ever appears here.
--
-- Also not here: area shares. Parcels are Points; no landed source has
-- parcel polygons. Measured against the OEREB oracle, 9 of 25 parcels carry
-- more than one Nutzungsplanung restriction and 5 of 25 have base-zone
-- coverage below 99.5%, so the point join picks one zone and reports it as
-- THE zone. Fine for screening, wrong for area arithmetic.

DROP TABLE IF EXISTS gold.parcel CASCADE;

CREATE TABLE gold.parcel (
    egrid                 text     PRIMARY KEY,
    bfs_nr                integer  NOT NULL,
    gemeinde_name         text     NOT NULL,
    parcel_number         text     NOT NULL,
    vintage               integer  NOT NULL,
    source_layer          text     NOT NULL,

    -- Land value, resolved from the inverse lwz index back in silver.
    lwz                   smallint,
    price_efh_chf_m2      integer,
    price_ewg_chf_m2      integer,
    price_gewerbe_chf_m2  integer,

    -- Zoning
    in_bauzone            boolean  NOT NULL,
    zone_code             text,
    zone_class            text,
    zone_label            text,
    sensitivity_level     text,
    verfahren_haengig     boolean,

    -- Hazard, synoptic summary only. Per-process detail: gold.parcel_hazard.
    hazard_surveyed       boolean  NOT NULL,
    hazard_grade_overall  text,
    hazard_rank           smallint,
    hazard_process        text,
    hazard_matrixfeld     text,

    -- Building rollups. Aggregated from silver.building (EXISTING buildings
    -- only) and its two facts, grouped to the parcel so the whole block is
    -- one row -- the per-building detail is gold.building. n_buildings = 0 is
    -- a fact (no building on the parcel), not missing data.
    n_buildings           integer  NOT NULL DEFAULT 0,
    best_solar_class      smallint,
    has_solar_potential   boolean  NOT NULL,
    max_noise_day         numeric,
    max_noise_night       numeric,

    geom                  geometry(Point, 2056) NOT NULL,

    CONSTRAINT parcel_efh_positive CHECK (price_efh_chf_m2 IS NULL OR price_efh_chf_m2 > 0),
    CONSTRAINT parcel_ewg_positive CHECK (price_ewg_chf_m2 IS NULL OR price_ewg_chf_m2 > 0),
    CONSTRAINT parcel_gew_positive CHECK (price_gewerbe_chf_m2 IS NULL OR price_gewerbe_chf_m2 > 0),

    -- zone_class, not zone_code: 16 Muensterlingen polygons have a NULL
    -- gn_kuerzel but a populated gn_kantname, so zone_code is legitimately
    -- NULL INSIDE a Bauzone. zone_class is the one column with zero nulls.
    CONSTRAINT parcel_zone_iff_in_bauzone
        CHECK (in_bauzone = (zone_class IS NOT NULL)),

    CONSTRAINT parcel_hazard_iff_surveyed
        CHECK (hazard_surveyed = (hazard_grade_overall IS NOT NULL)),

    -- Present iff surveyed AND on the ordinal scale. See the header.
    CONSTRAINT parcel_rank_iff_ranked_grade
        CHECK ((hazard_rank IS NULL)
               = (hazard_grade_overall IS NULL OR hazard_grade_overall = 'Restgefahr')),

    CONSTRAINT parcel_grade_known
        CHECK (hazard_grade_overall IS NULL
               OR hazard_grade_overall IN ('keine', 'gering', 'mittel', 'erheblich', 'Restgefahr')),

    -- Solar potential exists exactly when a class was aggregated.
    CONSTRAINT parcel_solar_iff_class
        CHECK (has_solar_potential = (best_solar_class IS NOT NULL)),
    CONSTRAINT parcel_solar_class_range
        CHECK (best_solar_class IS NULL OR best_solar_class BETWEEN 1 AND 5),
    -- A solar class can only come from a building.
    CONSTRAINT parcel_solar_needs_buildings
        CHECK (best_solar_class IS NULL OR n_buildings > 0)
);

INSERT INTO gold.parcel (
    egrid, bfs_nr, gemeinde_name, parcel_number, vintage, source_layer,
    lwz, price_efh_chf_m2, price_ewg_chf_m2, price_gewerbe_chf_m2,
    in_bauzone, zone_code, zone_class, zone_label, sensitivity_level,
    verfahren_haengig,
    hazard_surveyed, hazard_grade_overall, hazard_rank, hazard_process,
    hazard_matrixfeld,
    n_buildings, best_solar_class, has_solar_potential,
    max_noise_day, max_noise_night,
    geom
)
SELECT
    p.egrid,
    p.bfs_nr,
    g.gemeinde_name,
    p.parcel_number,
    p.vintage,
    p.source_layer,

    p.lwz,
    p.price_efh_chf_m2,
    p.price_ewg_chf_m2,
    p.price_gewerbe_chf_m2,

    z.egrid IS NOT NULL,
    z.zone_code_norm,
    z.zone_class,
    z.zone_label,
    z.sensitivity_level,
    z.verfahren_haengig,

    h.hazard_surveyed,
    h.gefahrenstufe,
    h.hazard_rank,
    h.prozess_massgebend,
    h.matrixfeld,

    coalesce(b.n_buildings, 0),
    b.best_solar_class,
    b.best_solar_class IS NOT NULL,
    b.max_noise_day,
    b.max_noise_night,

    p.geom
FROM silver.parcel p
JOIN      silver.gemeinde                g ON g.bfs_nr = p.bfs_nr
LEFT JOIN silver.parcel_zone             z ON z.egrid  = p.egrid
-- silver.parcel_hazard_synoptic already covers every parcel (9,879 rows),
-- so this LEFT JOIN never actually misses. It is a LEFT JOIN so that a
-- future gap fails the NOT NULL on hazard_surveyed instead of silently
-- dropping a parcel from the spine.
LEFT JOIN silver.parcel_hazard_synoptic  h ON h.egrid  = p.egrid
-- Building rollups, pre-aggregated to one row per parcel so this LEFT JOIN
-- cannot fan out the 9,879-row spine. EXISTING buildings only, matching
-- gold.building. GREATEST ignores NULL, so a building with only road (or
-- only rail) noise still contributes.
LEFT JOIN (
    SELECT
        bl.egrid,
        count(*)                                             AS n_buildings,
        max(sol.best_class)                                  AS best_solar_class,
        max(GREATEST(noi.road_lr_day,   noi.rail_lr_day))    AS max_noise_day,
        max(GREATEST(noi.road_lr_night, noi.rail_lr_night))  AS max_noise_night
    FROM silver.building bl
    LEFT JOIN silver.building_solar sol ON sol.egid = bl.egid
    LEFT JOIN silver.building_noise noi ON noi.egid = bl.egid
    WHERE bl.is_existing AND bl.egrid IS NOT NULL
    GROUP BY bl.egrid
) b ON b.egrid = p.egrid;

CREATE INDEX gold_parcel_bfs_nr_idx     ON gold.parcel (bfs_nr);
CREATE INDEX gold_parcel_zone_class_idx ON gold.parcel (zone_class);
CREATE INDEX gold_parcel_geom_idx       ON gold.parcel USING GIST (geom);

COMMENT ON TABLE gold.parcel IS
    'The parcel record: zoning, land value and hazard in one row per E-GRID. '
    'Joins to gold.gemeinde_year on bfs_nr -- always with a year predicate.';
COMMENT ON COLUMN gold.parcel.in_bauzone IS
    'false means the parcel lies outside every Bauzone -- a measured fact, '
    'not missing data. All zone_* columns are NULL in that case.';
COMMENT ON COLUMN gold.parcel.hazard_surveyed IS
    'false means the parcel is outside the surveyed perimeter: UNKNOWN, not '
    'safe. A surveyed-and-clear parcel has hazard_surveyed = true and '
    'hazard_grade_overall = ''keine''. These are different facts.';
COMMENT ON COLUMN gold.parcel.hazard_grade_overall IS
    'Published synoptic grading from silver.parcel_hazard_synoptic. NOT '
    'recomputed from the process layers -- on one parcel (CH854589778397) '
    'the published value disagrees with both, and the published value wins.';
COMMENT ON COLUMN gold.parcel.hazard_rank IS
    'Ordinal 0-3 (keine..erheblich). NULL for Restgefahr, which is residual '
    'risk behind a protection structure and not a point on that scale.';
COMMENT ON COLUMN gold.parcel.zone_class IS
    'Canton-wide zone class (gn_kantname), 25 values, zero nulls. The only '
    'column comparable ACROSS Gemeinden -- zone_code and zone_label are '
    'Gemeinde-specific.';
COMMENT ON COLUMN gold.parcel.zone_label IS
    'The Gemeinde''s own name for the zone type. Not comparable across '
    'Gemeinden: G is "Gewerbezone" in Ermatingen, "Arbeitszone Gewerbe" in '
    'Muensterlingen -- one canton class, two labels.';
COMMENT ON COLUMN gold.parcel.lwz IS
    'Source index 1-7, INVERSE (1 = priciest). Kept for traceability only. '
    'Never average it -- use the resolved price columns.';
COMMENT ON COLUMN gold.parcel.price_gewerbe_chf_m2 IS
    'Constant per Gemeinde in the source -- a Gemeinde-level attribute '
    'riding on a parcel row. avg() across parcels weights it by parcel '
    'count, not by area or value.';
COMMENT ON COLUMN gold.parcel.vintage IS
    'Single-valued (2024), which is the only reason egrid alone is a valid '
    'PK. A test asserts it stays so; a second vintage is the moment to '
    'revisit (egrid, vintage).';
COMMENT ON COLUMN gold.parcel.verfahren_haengig IS
    'A zoning amendment is pending, so the zone may not mean what it says. '
    '41 parcels. NULL where the parcel is outside every Bauzone.';
