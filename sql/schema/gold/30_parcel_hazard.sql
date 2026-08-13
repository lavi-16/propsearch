-- gold.parcel_hazard -- per-process hazard detail. 17,784 rows.
--
-- One row per parcel per PROCESS layer: which process drives the grade, at
-- what matrix field. The combined answer is not here -- it is
-- gold.parcel.hazard_grade_overall.
--
-- THE SYNOPTIC LAYER IS DELIBERATELY EXCLUDED, and the CHECK below is what
-- makes that permanent. silver.parcel_hazard carries three layers and 26,789
-- rows; gold carries two and 17,784.
--
-- WHY. Before building this, the question "is Gefaehrdung_synoptisch an
-- independent assessment, or is it derivable from Wasser + Rutschungen?"
-- was tested at parcel grain across all 9,005 surveyed parcels. Ranking
-- keine < Restgefahr < gering < mittel < erheblich and taking the max of
-- the two process layers:
--
--   synoptic gefahrenstufe == max of components      9,004 / 9,005
--   synoptic prozess_massgebend == winning layer's   9,000 / 9,005
--   synoptic matrixfeld == winning layer's           9,000 / 9,005
--   synoptic parcels not covered by Rutschungen              0
--
-- The 5 process/matrixfeld differences are TIES -- both layers at equal
-- severity, the tie-break picking arbitrarily -- not disagreements.
--
-- The single grade exception, CH854589778397, was inspected: the parcel
-- point sits 0.26 m inside a synoptic `mittel` polygon and 0.31 m outside a
-- Wasser `mittel` polygon. The two layers' boundaries differ by well under
-- a metre there. It is a point-in-polygon edge artifact, not an independent
-- assessment.
--
-- So the synoptic layer is derivable, and keeping it here would put two
-- "synoptic" concepts in two gold tables under near-identical names while
-- double-counting the same ground against its own components. Nothing is
-- lost by dropping the ROW: the published synoptic grading -- including
-- that one parcel's disagreement, which is preserved verbatim rather than
-- recomputed -- lives on gold.parcel.
--
-- FAN-OUT IS REDUCED, NOT ELIMINATED. Joining gold.parcel to this table
-- still doubles: 2 rows per surveyed parcel, down from 2.97. The safe
-- default for a per-parcel question is gold.parcel alone. A test asserts
-- the join yields exactly 17,784 rows, so the fan-out is stated rather than
-- discovered.
--
-- COVERAGE DIFFERS BY LAYER, and absence here does not mean the same thing
-- as gold.parcel.hazard_surveyed = false:
--
--   ms:Gefaehrdung_Rutschungen  9,005 parcels
--   ms:Gefaehrdung_Wasser       8,779 parcels
--
-- 226 parcels are inside the Rutschungen perimeter but outside the Wasser
-- one. A missing row means that PROCESS was not assessed there.

DROP TABLE IF EXISTS gold.parcel_hazard CASCADE;

CREATE TABLE gold.parcel_hazard (
    egrid               text     NOT NULL REFERENCES gold.parcel (egrid),
    source_layer        text     NOT NULL,
    gefahrenstufe       text     NOT NULL,
    matrixfeld          text     NOT NULL,
    prozess_massgebend  text     NOT NULL,
    hazard_rank         smallint,

    PRIMARY KEY (egrid, source_layer),

    -- The constraint that keeps the synoptic layer out for good.
    CONSTRAINT parcel_hazard_process_layers_only
        CHECK (source_layer IN ('ms:Gefaehrdung_Wasser', 'ms:Gefaehrdung_Rutschungen')),

    CONSTRAINT parcel_hazard_grade_known
        CHECK (gefahrenstufe IN ('keine', 'gering', 'mittel', 'erheblich', 'Restgefahr')),

    -- gefahrenstufe is NOT NULL here, so the biconditional that gold.parcel
    -- needs in its three-state form collapses to this two-state one.
    CONSTRAINT parcel_hazard_rank_iff_ranked_grade
        CHECK ((hazard_rank IS NULL) = (gefahrenstufe = 'Restgefahr'))
);

INSERT INTO gold.parcel_hazard (
    egrid, source_layer, gefahrenstufe, matrixfeld, prozess_massgebend, hazard_rank
)
SELECT
    h.egrid,
    h.source_layer,
    h.gefahrenstufe,
    h.matrixfeld,
    h.prozess_massgebend,
    h.hazard_rank
FROM silver.parcel_hazard h
WHERE h.source_layer <> 'ms:Gefaehrdung_synoptisch';

CREATE INDEX gold_parcel_hazard_layer_idx   ON gold.parcel_hazard (source_layer);
CREATE INDEX gold_parcel_hazard_process_idx ON gold.parcel_hazard (prozess_massgebend);

COMMENT ON TABLE gold.parcel_hazard IS
    'Per-process hazard detail, 2 rows per surveyed parcel. Joining this to '
    'gold.parcel DOUBLES the parcel count -- for a per-parcel answer use '
    'gold.parcel.hazard_grade_overall instead.';
COMMENT ON COLUMN gold.parcel_hazard.source_layer IS
    'One of the two PROCESS layers. ms:Gefaehrdung_synoptisch is excluded by '
    'CHECK -- it is derivable from these two (9,004/9,005) and its published '
    'value lives on gold.parcel.hazard_grade_overall.';
COMMENT ON COLUMN gold.parcel_hazard.gefahrenstufe IS
    'keine here means this process was assessed and found clear. A MISSING '
    'row means the process was not assessed at that parcel -- 226 parcels '
    'sit inside the Rutschungen perimeter but outside the Wasser one.';
COMMENT ON COLUMN gold.parcel_hazard.matrixfeld IS
    'MF0-MF9 / MF99, the intensity x probability matrix field. MF99 pairs '
    'with gefahrenstufe = keine.';
