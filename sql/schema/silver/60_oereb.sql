-- silver.oereb_extract_sample     -- 25 parcels
-- silver.parcel_restriction_sample -- 80 restrictions over those 25
--
-- THE _sample SUFFIX IS LOAD-BEARING. These are 25 of 9,879 parcels (0.3%),
-- and the naming exists so nothing downstream mistakes them for the
-- restrictions layer.
--
-- WHAT THE 25 ACTUALLY REPRESENT -- two separate things were conflated in
-- earlier notes, and the distinction decides what gets built on this:
--
--   * The OEREB EXTRACT ENDPOINT genuinely has no bulk call. One request
--     per parcel, ~175 KB each. That is a real source constraint.
--   * The restriction DATA is not similarly limited. It is bulk-available
--     as WFS for 7 of the 9 themes seen here (76 of these 80 rows) --
--     ms:les, ms:gp, ms:blp/blpline, ms:no_*/ko_*, ms:ueberlagernd on the
--     already-ingested oereb_ortsplanung_bauzonen service, plus ms:raum on
--     oereb_gewaesserraum. Only ch.BelasteteStandorte and
--     ch.BaulinienNationalstrassen (1 row each) have no confirmed bulk
--     source; both are federal and likely served off-canton.
--
-- So this is a POC-scale sample of one API, NOT the source's coverage
-- ceiling. gold.parcel_restriction is therefore NOT built from it -- it
-- waits for the bulk WFS ingestion.
--
-- WHY PROMOTE IT TO SILVER AT ALL, THEN? Two uses that survive the sparsity:
-- it is the only independent oracle for the zoning cross-check (OEREB
-- agreed with the Bauzonen WFS on the base zone 25/25), and the only source
-- of true parcel area in the project, since no parcel polygon is ingested.
-- The tests use it as a cross-check on silver.parcel_zone.

DROP TABLE IF EXISTS silver.oereb_extract_sample CASCADE;

CREATE TABLE silver.oereb_extract_sample (
    egrid                 text    PRIMARY KEY REFERENCES silver.parcel (egrid),
    bfs_nr                integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    identdn               text    NOT NULL,
    parcel_number         text    NOT NULL,
    municipality_name     text    NOT NULL,
    postal_code           integer NOT NULL,
    land_registry_area_m2 integer,
    realestate_type       text,
    extract_identifier    text,
    n_concerned_theme     integer,
    n_not_concerned_theme integer,
    n_theme_without_data  integer,
    extract_fetched_at    timestamptz NOT NULL,
    extract               jsonb   NOT NULL,

    CONSTRAINT oereb_extract_is_object CHECK (jsonb_typeof(extract) = 'object')
);

INSERT INTO silver.oereb_extract_sample (
    egrid, bfs_nr, identdn, parcel_number, municipality_name, postal_code,
    land_registry_area_m2, realestate_type, extract_identifier,
    n_concerned_theme, n_not_concerned_theme, n_theme_without_data,
    extract_fetched_at, extract
)
SELECT
    e.egrid,
    e.gemcode::integer,
    e.identdn,
    e.number,
    e.municipality_name,
    -- NOT a BFS number despite the source column name, see comment below.
    e.municipality_code::integer,
    e.land_registry_area,
    e.realestate_type,
    e.extract_identifier,
    e.n_concerned_theme,
    e.n_not_concerned_theme,
    e.n_theme_without_data,
    e.creation_date::timestamptz,
    e.extract
FROM bronze.oereb_extract e;

COMMENT ON TABLE silver.oereb_extract_sample IS
    'Deterministic 5-per-Gemeinde sample, 25 of 9,879 parcels. A validation '
    'oracle, not a data layer -- gold.parcel_restriction is not built from '
    'this. Full coverage needs the bulk WFS restriction layers.';
COMMENT ON COLUMN silver.oereb_extract_sample.postal_code IS
    'Source column is named municipality_code but carries a PLZ (8280, 8272, '
    '8274, 8596/8597 -- Muensterlingen spans two), NOT a Swiss BFS-Nr. '
    'Renamed here so it cannot be joined as one; bfs_nr comes from gemcode.';
COMMENT ON COLUMN silver.oereb_extract_sample.land_registry_area_m2 IS
    'True parcel area from the land register. The only parcel area in the '
    'project -- no parcel polygon is ingested (Amtliche Vermessung is out '
    'of scope for v1), so this exists for 25 parcels only.';
COMMENT ON COLUMN silver.oereb_extract_sample.identdn IS
    'TG9999 marks Taegermoos parcels -- Swiss territory administered from '
    'Konstanz, carried under gemcode 4696 alongside Taegerwilen proper.';


-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS silver.parcel_restriction_sample CASCADE;

CREATE TABLE silver.parcel_restriction_sample (
    egrid             text    NOT NULL REFERENCES silver.oereb_extract_sample (egrid),
    restriction_index integer NOT NULL,
    theme_code        text    NOT NULL,
    theme_text        text    NOT NULL,
    type_code         text,
    legend_text       text    NOT NULL,
    lawstatus         text    NOT NULL,
    area_share_m2     double precision,
    part_in_percent   double precision,
    restriction       jsonb   NOT NULL,
    PRIMARY KEY (egrid, restriction_index),

    CONSTRAINT restriction_is_object CHECK (jsonb_typeof(restriction) = 'object'),
    CONSTRAINT restriction_percent_range
        CHECK (part_in_percent IS NULL OR part_in_percent BETWEEN 0 AND 100)
);

INSERT INTO silver.parcel_restriction_sample (
    egrid, restriction_index, theme_code, theme_text, type_code,
    legend_text, lawstatus, area_share_m2, part_in_percent, restriction
)
SELECT
    r.egrid,
    r.restriction_index,
    r.theme_code,
    r.theme_text,
    -- Empty string is the source's "no code", used on 5 of the 9 themes.
    NULLIF(r.type_code, ''),
    r.legend_text,
    r.lawstatus,
    r.area_share,
    r.part_in_percent,
    r.restriction
FROM bronze.oereb_restriction r;

CREATE INDEX parcel_restriction_theme_idx ON silver.parcel_restriction_sample (theme_code);

COMMENT ON COLUMN silver.parcel_restriction_sample.type_code IS
    'NULL where the source published an empty string. Not a stable enum: '
    'the same code maps to different legend_text values across themes, so '
    'join on legend_text when you need the label.';
COMMENT ON COLUMN silver.parcel_restriction_sample.legend_text IS
    'For ch.Nutzungsplanung this appends the Kuerzel in parentheses '
    '("Wohnzone W 1.6 (W 1.6)"). Strip that suffix before comparing to '
    'silver.parcel_zone.zone_label, or equality scores 0.';
COMMENT ON COLUMN silver.parcel_restriction_sample.part_in_percent IS
    'Share of the parcel the restriction covers. Below 100 means the parcel '
    'straddles a boundary -- which the point-based silver.parcel_zone join '
    'cannot represent. 5 of these 25 parcels are below 99.5%.';
