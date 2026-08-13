-- silver.hazard_zone -- the graded hazard polygons, geometry repaired.
--
-- 84 of the 6,422 bronze features are invalid (all "Ring Self-intersection").
-- They land as-is per the bronze contract; repairing them is silver's job.
--
-- WHY THIS IS A TABLE AND NOT A VIEW. ST_MakeValid inside a join predicate
-- defeats the GIST index: the parcel join written that way EXCEEDED THE
-- STATEMENT TIMEOUT against this database, while the same join over the raw
-- indexed geometry returns in seconds. Repairing once into an indexed table
-- is what makes every downstream join viable. This is the single strongest
-- argument for silver being materialised rather than a view stack.
--
-- ST_MakeValid is verified lossless here: all 84 become valid, all stay
-- MULTIPOLYGON (no promotion to a collection), and total area is unchanged
-- to within 0.1 m2.
--
-- THE THREE LAYERS OVERLAP EACH OTHER BY DESIGN. _synoptisch is the
-- combined view; _wasser and _rutschungen are per-process detail over the
-- same ground. They are not independent facts and must never be summed.
-- Within a layer the polygons partition cleanly.
--
-- RESTGEFAHR IS NOT ON THE ORDINAL SCALE. Residual risk behind a protection
-- structure is a different KIND of statement from a graded intensity, so it
-- gets hazard_rank NULL rather than a number that would sort it against
-- gering/mittel/erheblich. The CHECK makes that non-negotiable.

DROP TABLE IF EXISTS silver.hazard_zone CASCADE;

CREATE TABLE silver.hazard_zone (
    obj_id             text     PRIMARY KEY,
    source_layer       text     NOT NULL,
    gefahrenstufe      text     NOT NULL,
    matrixfeld         text     NOT NULL,
    prozess_massgebend text     NOT NULL,
    hazard_rank        smallint,
    geom               geometry(MultiPolygon, 2056) NOT NULL,

    CONSTRAINT hazard_zone_grade_known CHECK (
        gefahrenstufe IN ('keine', 'gering', 'mittel', 'erheblich', 'Restgefahr')),
    -- Restgefahr, and only Restgefahr, is off the ordinal scale.
    CONSTRAINT hazard_zone_restgefahr_unranked CHECK (
        (gefahrenstufe = 'Restgefahr') = (hazard_rank IS NULL)),
    CONSTRAINT hazard_zone_valid_geom CHECK (ST_IsValid(geom))
);

INSERT INTO silver.hazard_zone (
    obj_id, source_layer, gefahrenstufe, matrixfeld,
    prozess_massgebend, hazard_rank, geom
)
SELECT
    g.obj_id,
    g._source_layer,
    g.gefahrenstufe,
    g.matrixfeld,
    g.prozess_massgebend,
    CASE g.gefahrenstufe
        WHEN 'keine'     THEN 0
        WHEN 'gering'    THEN 1
        WHEN 'mittel'    THEN 2
        WHEN 'erheblich' THEN 3
        -- Restgefahr deliberately falls through to NULL.
    END,
    ST_Multi(ST_MakeValid(g.geometry))
FROM bronze.gefahrenkarte g;

CREATE INDEX hazard_zone_geom_idx   ON silver.hazard_zone USING GIST (geom);
CREATE INDEX hazard_zone_layer_idx  ON silver.hazard_zone (source_layer);

COMMENT ON TABLE silver.hazard_zone IS
    'bronze.gefahrenkarte with ST_MakeValid applied once and materialised. '
    'Three overlapping layers discriminated by source_layer -- ALWAYS filter '
    'to one before aggregating.';
COMMENT ON COLUMN silver.hazard_zone.hazard_rank IS
    'keine=0, gering=1, mittel=2, erheblich=3. NULL for Restgefahr, which is '
    'a different kind of statement and must not sort into the scale.';
COMMENT ON COLUMN silver.hazard_zone.matrixfeld IS
    'Intensity x probability matrix field. Maps 1:1 onto gefahrenstufe in '
    'the landed data (MF0=Restgefahr, MF1/2/4=gering, MF3/5/6=mittel, '
    'MF7/8/9=erheblich, MF99=keine); a test asserts it still does.';
