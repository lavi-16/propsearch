-- silver.parcel_hazard          -- one row per parcel x layer  (detail)
-- silver.parcel_hazard_synoptic -- one row per parcel, ALL parcels (summary)
--
-- Two tables because the two questions are different, and conflating them
-- is the single easiest way to get hazard wrong.

DROP TABLE IF EXISTS silver.parcel_hazard CASCADE;

-- THE PRIMARY KEY IS THE GUARD, NOT DECORATION.
--
-- Within a layer the hazard polygons partition, so a parcel gets exactly
-- one grading per layer -- measured 9,005 / 9,005 / 8,779 parcels for
-- synoptisch / rutschungen / wasser, max 1 row each. ACROSS layers the same
-- parcel gets up to 3 rows: 26,789 rows over 9,005 distinct parcels, 2.97x.
--
-- So anything that counts parcels off this table without filtering to one
-- source_layer will triple-count. The PK cannot stop a caller doing that,
-- but it does guarantee the fan-out is exactly the documented one and not
-- a build error -- if the partition assumption ever breaks, the INSERT
-- fails here instead of quietly inflating a downstream number.

CREATE TABLE silver.parcel_hazard (
    egrid              text     NOT NULL REFERENCES silver.parcel (egrid),
    source_layer       text     NOT NULL,
    gefahrenstufe      text     NOT NULL,
    matrixfeld         text     NOT NULL,
    prozess_massgebend text     NOT NULL,
    hazard_rank        smallint,
    PRIMARY KEY (egrid, source_layer)
);

INSERT INTO silver.parcel_hazard (
    egrid, source_layer, gefahrenstufe, matrixfeld, prozess_massgebend, hazard_rank
)
SELECT
    p.egrid, h.source_layer, h.gefahrenstufe, h.matrixfeld,
    h.prozess_massgebend, h.hazard_rank
FROM silver.parcel p
JOIN silver.hazard_zone h ON ST_Intersects(p.geom, h.geom);

CREATE INDEX parcel_hazard_layer_idx ON silver.parcel_hazard (source_layer);

COMMENT ON TABLE silver.parcel_hazard IS
    'Detail: one row per parcel per hazard layer. The three layers overlap '
    'by design (2.97 rows per matched parcel). FILTER TO ONE source_layer '
    'before aggregating, or use silver.parcel_hazard_synoptic.';


-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS silver.parcel_hazard_synoptic CASCADE;

-- ONE ROW PER PARCEL -- INCLUDING PARCELS THAT WERE NEVER SURVEYED.
--
-- This is the table that makes "keine" != "no match" structurally
-- impossible to collapse, which the gold design doc flagged as the part
-- most likely to be got wrong.
--
--   gefahrenstufe = 'keine'  -> the parcel WAS surveyed and is clear
--   no match at all          -> the parcel is OUTSIDE the surveyed
--                               perimeter: UNKNOWN, not safe
--
-- 9,005 of 9,879 parcels fall inside the synoptic layer; 874 do not.
-- Collapsing both to NULL, or both to "no hazard", asserts a safety that
-- was never measured. The CHECK below ties hazard_surveyed to the presence
-- of a grading, so no build can produce a row making that claim.
--
-- Synoptic only, and named so. The synoptic layer's 9,005 parcels are
-- exactly the set matched by ANY layer, so it is the right denominator --
-- no parcel is covered by a detail layer but missing from the synoptic view.

CREATE TABLE silver.parcel_hazard_synoptic (
    egrid              text     PRIMARY KEY REFERENCES silver.parcel (egrid),
    hazard_surveyed    boolean  NOT NULL,
    gefahrenstufe      text,
    matrixfeld         text,
    prozess_massgebend text,
    hazard_rank        smallint,

    -- A grading exists exactly when the parcel was surveyed.
    CONSTRAINT phs_surveyed_iff_graded
        CHECK (hazard_surveyed = (gefahrenstufe IS NOT NULL)),
    -- Restgefahr stays off the ordinal scale here too.
    CONSTRAINT phs_restgefahr_unranked
        CHECK (hazard_rank IS NULL OR gefahrenstufe <> 'Restgefahr')
);

INSERT INTO silver.parcel_hazard_synoptic (
    egrid, hazard_surveyed, gefahrenstufe, matrixfeld, prozess_massgebend, hazard_rank
)
SELECT
    p.egrid,
    h.egrid IS NOT NULL,
    h.gefahrenstufe,
    h.matrixfeld,
    h.prozess_massgebend,
    h.hazard_rank
FROM silver.parcel p
LEFT JOIN silver.parcel_hazard h
       ON h.egrid = p.egrid
      AND h.source_layer = 'ms:Gefaehrdung_synoptisch';

CREATE INDEX phs_surveyed_idx ON silver.parcel_hazard_synoptic (hazard_surveyed);

COMMENT ON TABLE silver.parcel_hazard_synoptic IS
    'Summary: exactly one row per parcel, synoptic layer only. Covers all '
    '9,879 parcels including the 874 outside the surveyed perimeter.';
COMMENT ON COLUMN silver.parcel_hazard_synoptic.hazard_surveyed IS
    'false means the parcel is outside the surveyed perimeter -- hazard is '
    'UNKNOWN, not absent. Never read false as "no hazard"; a surveyed-clear '
    'parcel is hazard_surveyed = true with gefahrenstufe = ''keine''.';
