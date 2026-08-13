-- silver.zone      -- the zone dimension, keyed per Gemeinde
-- silver.parcel_zone -- parcel -> zone, by point-in-polygon
--
-- ZONE CODES ARE MUNICIPAL, NOT CANTONAL. bronze.bauzonen carries 79
-- distinct gn_kuerzel across the pilot, unnormalised between Gemeinden
-- (W1.6 vs W 1.6, FH vs Fh, oeBA vs OeBA). The normalisation below is
-- mechanical and deterministic: strip spaces, upper-case.
--
-- Two things verified before settling on this, both worth knowing:
--
--   1. Within a single Gemeinde the normalisation merges NOTHING (0 cases).
--      Every Gemeinde already spells its own codes consistently; the
--      variants are all cross-Gemeinde. So the norm column is defensive --
--      it protects against a future Gemeinde that is not self-consistent --
--      and is not fixing anything in today's data.
--   2. (bfs_nr, zone_code_norm) is unambiguous: 89 pairs, each mapping to
--      exactly one gn_kantname and one gn_gmdname. So it is a real key.
--
-- Codes are NOT merged across Gemeinden. `G` means "Gewerbezone" in
-- Ermatingen and "Arbeitszone Gewerbe" in Muensterlingen -- collapsing on
-- the string would silently conflate them.
--
-- THE CROSS-GEMEINDE CLASS COMES FROM THE SOURCE, NOT FROM US.
-- gn_kantname is the canton's harmonised name for the zone type: 25 values,
-- zero nulls, populated even where gn_kuerzel is NULL. It resolves the four
-- different municipal codes for "street inside a building zone"
-- (StB / StrB / VfSi / VFiB) into one class. That is the crosswalk, and it
-- is published -- no hand-built mapping is needed or wanted here.

DROP TABLE IF EXISTS silver.zone CASCADE;

CREATE TABLE silver.zone (
    bfs_nr          integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    zone_code_norm  text    NOT NULL,
    zone_code_raw   text    NOT NULL,
    zone_class      text    NOT NULL,
    zone_label      text    NOT NULL,
    PRIMARY KEY (bfs_nr, zone_code_norm)
);

INSERT INTO silver.zone (bfs_nr, zone_code_norm, zone_code_raw, zone_class, zone_label)
SELECT DISTINCT
    split_part(t_id, '_', 1)::integer,
    upper(replace(gn_kuerzel, ' ', '')),
    gn_kuerzel,
    gn_kantname,
    gn_gmdname
FROM bronze.bauzonen
WHERE gn_kuerzel IS NOT NULL;

COMMENT ON TABLE silver.zone IS
    'Zone dimension. Deliberately excludes the 16 bauzonen rows with a NULL '
    'gn_kuerzel (all Muensterlingen 4691, Bahnareal and Strassenverkehrs'
    'flaeche): a NULL cannot sit in a primary key, and synthesising a code '
    'would be inventing data. Those parcels still get a zone_class via '
    'silver.parcel_zone, which for that reason carries no FK to this table.';
COMMENT ON COLUMN silver.zone.zone_class IS
    'gn_kantname -- the canton''s harmonised zone type. The only column here '
    'that is comparable ACROSS Gemeinden.';
COMMENT ON COLUMN silver.zone.zone_label IS
    'gn_gmdname -- the Gemeinde''s own name for the zone type. NOT a '
    'Gemeinde name.';


-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS silver.parcel_zone CASCADE;

-- Point-in-polygon. Verified: Bauzonen polygons do not overlap, so no
-- parcel falls in more than one -- egrid is a genuine PK here, and the PK
-- is what would catch it if that ever stopped being true.
--
-- COVERAGE IS NOT UNIVERSAL, AND ABSENCE IS A FACT. 8,303 of 9,879 parcels
-- fall inside a Bauzone. A parcel missing from this table is outside every
-- building zone -- that is information, not a gap.
--
-- V1 LIMITATION: bronze.landwertzonen is one representative POINT per
-- parcel; no landed source has parcel boundary polygons. A parcel that
-- straddles a zone boundary gets whichever zone its point lands in.
-- Measured against the OEREB sample (which does know true parcel geometry):
-- 9 of 25 parcels carry more than one Nutzungsplanung restriction and 5 of
-- 25 have base-zone coverage below 99.5%. Fine for screening; wrong for
-- area shares. Fixing it needs the Amtliche Vermessung parcel layer.

CREATE TABLE silver.parcel_zone (
    egrid                text    PRIMARY KEY REFERENCES silver.parcel (egrid),
    bauzone_t_id         text    NOT NULL,
    zone_code_raw        text,
    zone_code_norm       text,
    zone_class           text    NOT NULL,
    zone_label           text    NOT NULL,
    sensitivity_level    text    NOT NULL,
    datum_inkraftsetzung timestamp,
    verfahren_haengig    boolean NOT NULL,
    aufgestuft           boolean
);

INSERT INTO silver.parcel_zone (
    egrid, bauzone_t_id, zone_code_raw, zone_code_norm, zone_class,
    zone_label, sensitivity_level, datum_inkraftsetzung,
    verfahren_haengig, aufgestuft
)
SELECT
    p.egrid,
    b.t_id,
    b.gn_kuerzel,
    upper(replace(b.gn_kuerzel, ' ', '')),
    b.gn_kantname,
    b.gn_gmdname,
    b.es_txt,
    b.datum_inkraftsetzung,
    b.verfahren_haengig_txt = 'ja',
    CASE b.aufgestuft_txt WHEN 'ja' THEN true WHEN 'nein' THEN false END
FROM silver.parcel p
JOIN bronze.bauzonen b ON ST_Intersects(p.geom, b.geometry);

CREATE INDEX parcel_zone_class_idx ON silver.parcel_zone (zone_class);

COMMENT ON COLUMN silver.parcel_zone.sensitivity_level IS
    'es_txt, the Laermempfindlichkeitsstufe. ''keine'' is a real source '
    'value meaning no ES was assigned -- NOT missing data, and deliberately '
    'not nulled. Same principle as hazard ''keine''.';
COMMENT ON COLUMN silver.parcel_zone.aufgestuft IS
    'Tri-state in the source: ja / nein / absent. NULL means the source did '
    'not say, which is distinct from an explicit nein.';
COMMENT ON COLUMN silver.parcel_zone.zone_code_norm IS
    'NULL for the 16 Muensterlingen polygons with no gn_kuerzel. zone_class '
    'is populated on every row, so use that when the code is absent.';
