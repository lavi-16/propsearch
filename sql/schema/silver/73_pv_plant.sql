-- silver.pv_plant -- one row per registered PV plant (xtf_id) in the pilot.
--
-- From bronze.stromproduktion (BFE/Pronovo electricity-production registry).
-- The detail grain, the silver.rail_noise analogue: raw plant points that
-- silver.building_pv aggregates to the building. This exists to answer one
-- neoteq question -- "does this building already have PV?" -- so it excludes
-- everything but PV.
--
-- PV IS A CODED SUBCATEGORY. The source ships coded categories decoded by its
-- own catalogue layers (not landed -- the EIGNUNG_DACH / gwr_wohnung
-- precedent). Confirmed live: SubCategory 'subcat_2' = Photovoltaik. The pilot
-- window holds 1,675 subcat_2 plants plus 1 subcat_4 (Biomass); this table
-- keeps only subcat_2, so a downstream reader never has to know the code.
-- plant_category stays the raw mount code (plantcat_8 Angebaut/attached,
-- plantcat_9 Integriert, plantcat_10 Freistehend/ground-mount; NULL on ~6%),
-- the way silver.roof_plane keeps KLASSE as an ordinal.
--
-- NO EGID. The plant carries no building id, so the building link is SPATIAL
-- and lives in silver.building_pv (nearest existing building), exactly as rail
-- noise links. Geometry is a clean Point (0 invalid in the pilot).

DROP TABLE IF EXISTS silver.pv_plant CASCADE;

CREATE TABLE silver.pv_plant (
    xtf_id                integer  PRIMARY KEY,
    total_power_kw        numeric  NOT NULL,   -- registered capacity, kW
    initial_power_kw      numeric,
    beginning_of_operation date,               -- commissioning date
    plant_category        text,                -- raw mount code (plantcat_*)
    municipality          text,
    postcode              integer,
    geom                  geometry(Point, 2056) NOT NULL,

    CONSTRAINT pv_plant_power_positive CHECK (total_power_kw > 0)
);

INSERT INTO silver.pv_plant (
    xtf_id, total_power_kw, initial_power_kw, beginning_of_operation,
    plant_category, municipality, postcode, geom
)
SELECT
    p.xtf_id,
    p.totalpower,
    p.initialpower,
    NULLIF(p.beginningofoperation, '')::date,
    NULLIF(p.plantcategory, ''),
    NULLIF(p.municipality, ''),
    p.postcode,
    p.geometry
FROM bronze.stromproduktion p
WHERE p.subcategory = 'subcat_2';   -- Photovoltaik only

CREATE INDEX pv_plant_geom_idx ON silver.pv_plant USING GIST (geom);

COMMENT ON TABLE silver.pv_plant IS
    'Registered PV plants (BFE/Pronovo), one row per xtf_id, filtered to '
    'SubCategory=subcat_2 (Photovoltaik). No EGID -- links to buildings '
    'spatially via silver.building_pv, never by attribute.';
COMMENT ON COLUMN silver.pv_plant.plant_category IS
    'Raw mount code: plantcat_8 Angebaut (attached), plantcat_9 Integriert, '
    'plantcat_10 Freistehend (ground-mount). NULL where the register omits it.';
COMMENT ON COLUMN silver.pv_plant.total_power_kw IS
    'Registered plant capacity in kW. Pilot range ~1.8 .. 1123 kW.';
