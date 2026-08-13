-- silver.parcel -- the parcel spine. One row per parcel, 9,879 rows.
--
-- From bronze.landwertzonen, where gs_egris_egrid is unique across all
-- three source layers with zero nulls, so E-GRID is a genuine primary key.
--
-- THE PRICE RESOLUTION IS THE POINT OF THIS TABLE.
--
-- `lwz` (1-7) is NOT a rank or a score. It is an INDEX selecting which of
-- the seven price bands applies to the parcel, and it runs INVERSE: 1 is
-- the priciest zone, 7 the cheapest. Averaging raw `lwz` is meaningless
-- and looks uncorrelated with price precisely because of the inversion.
-- Silver resolves it to CHF so nobody downstream has to know that.
--
-- (The gold design doc proposed resolving this at gold. Doing it here is
-- better: turning an inverse index into a magnitude is a source-fidelity
-- correction, which is silver's contract. `lwz` is kept alongside for
-- traceability, so nothing is lost.)
--
-- Verified on the landed data: there is no row where `lwz` is non-null and
-- the selected price column is null or zero. The zeros that DO exist in
-- efh/ewg_landwertzone5..7 are padding for Gemeinden that define fewer
-- than seven bands -- unreachable through a valid `lwz`. The CHECK
-- constraints below are therefore defensive rather than corrective, and
-- they are what stops a padding zero ever surfacing as a price.
--
-- The 76 rows with lwz IS NULL are all street/forest/remains parcels --
-- non-buildable. They are KEPT in the spine with NULL prices and flagged
-- via `kat`, rather than dropped: absence from the spine would be a worse
-- lie than a null price.

DROP TABLE IF EXISTS silver.parcel CASCADE;

CREATE TABLE silver.parcel (
    egrid                 text     PRIMARY KEY,
    bfs_nr                integer  NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    parcel_number         text     NOT NULL,
    kat                   text     NOT NULL,
    karte                 text,
    lwz                   smallint,
    price_efh_chf_m2      integer,
    price_ewg_chf_m2      integer,
    price_gewerbe_chf_m2  integer,
    vintage               integer  NOT NULL,
    source_layer          text     NOT NULL,
    geom                  geometry(Point, 2056) NOT NULL,

    CONSTRAINT parcel_lwz_range      CHECK (lwz IS NULL OR lwz BETWEEN 1 AND 7),
    CONSTRAINT parcel_efh_positive   CHECK (price_efh_chf_m2 IS NULL OR price_efh_chf_m2 > 0),
    CONSTRAINT parcel_ewg_positive   CHECK (price_ewg_chf_m2 IS NULL OR price_ewg_chf_m2 > 0),
    CONSTRAINT parcel_gew_positive   CHECK (price_gewerbe_chf_m2 IS NULL OR price_gewerbe_chf_m2 > 0),
    -- The residential prices exist exactly when the index that selects them does.
    CONSTRAINT parcel_price_needs_lwz
        CHECK ((lwz IS NULL) = (price_efh_chf_m2 IS NULL)
           AND (lwz IS NULL) = (price_ewg_chf_m2 IS NULL))
);

INSERT INTO silver.parcel (
    egrid, bfs_nr, parcel_number, kat, karte, lwz,
    price_efh_chf_m2, price_ewg_chf_m2, price_gewerbe_chf_m2,
    vintage, source_layer, geom
)
SELECT
    l.gs_egris_egrid,
    l.gemcode,
    l.gs_nummer,
    l.kat,
    l.karte,
    l.lwz::smallint,
    (ARRAY[l.efh_landwertzone1, l.efh_landwertzone2, l.efh_landwertzone3,
           l.efh_landwertzone4, l.efh_landwertzone5, l.efh_landwertzone6,
           l.efh_landwertzone7])[l.lwz::int],
    (ARRAY[l.ewg_landwertzone1, l.ewg_landwertzone2, l.ewg_landwertzone3,
           l.ewg_landwertzone4, l.ewg_landwertzone5, l.ewg_landwertzone6,
           l.ewg_landwertzone7])[l.lwz::int],
    NULLIF(l.gewerbe_industrie, 0),
    l.jahr,
    l._source_layer,
    l.geometry
FROM bronze.landwertzonen l;

CREATE INDEX parcel_bfs_nr_idx ON silver.parcel (bfs_nr);
CREATE INDEX parcel_geom_idx   ON silver.parcel USING GIST (geom);

COMMENT ON COLUMN silver.parcel.lwz IS
    'Source index 1-7 selecting the price band. INVERSE: 1 is the priciest '
    'zone. Kept for traceability only -- never average it, use the resolved '
    'price columns.';
COMMENT ON COLUMN silver.parcel.price_gewerbe_chf_m2 IS
    'Constant per Gemeinde in the source -- a Gemeinde-level attribute '
    'carried on the parcel row, not a parcel-level valuation.';
COMMENT ON COLUMN silver.parcel.vintage IS
    'Source jahr. Single vintage (2024) across every parcel-level source, '
    'which is why the PK is egrid alone and not (egrid, vintage).';
COMMENT ON COLUMN silver.parcel.kat IS
    'Source land category. street/forest/waterbody/railway/irreclaimable are '
    'non-buildable; these are where lwz and the prices are NULL.';
