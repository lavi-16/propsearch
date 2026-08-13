-- gold.gemeinde_bodenpreis -- CHF/m2 bands per Gemeinde x year x zone
-- category. 520 rows: a complete 5 x 13 x 8 grid, no gaps.
--
-- Kept as its own table rather than folded into gold.gemeinde_year, because
-- it has a genuinely finer grain (8 categories per Gemeinde-year). Folding
-- them into 8 pairs of columns would bake the tax taxonomy into the schema
-- and break the moment the Steuerverwaltung adds a category.
--
-- THIS IS NOT THE PARCEL PRICE PATH. gold.parcel already carries
-- parzellenscharfe CHF/m2 from Landwertzonen. Use this for Gemeinde-level
-- context, historical trend, and as an independent cross-check on a parcel
-- value -- never as the way to price a parcel.
--
-- ITS zone_category_code DOES NOT JOIN TO A PARCEL. These are 8 coarse
-- tax-valuation categories (1 Kern .. 8 Weiler). Parcels carry 73 municipal
-- zone codes / 25 canton classes, and NO crosswalk is published -- the
-- Schaetzer-Handbuch attached to the dataset was checked and is valuation
-- methodology that never mentions these categories. A mapping LOOKS obvious
-- (Landwertzonen EFH -> "4 EFH", EWG -> "3 MFH", Gewerbe -> "6 Gewerbe")
-- and is a guess. This table joins to gold.parcel on bfs_nr ONLY, with a
-- year predicate. gold.parcel deliberately carries no zone_category_code.
--
-- ROWS ARE SIX-YEAR TRAILING WINDOWS, NOT SPOT PRICES. The 2024 row covers
-- the Bemessungsperiode 2017-01-01 .. 2023-12-31. Consecutive years overlap
-- heavily, so the series is smoothed by construction and adjacent-year
-- deltas are NOT market moves; some series repeat verbatim across two
-- years. window_start/window_end are carried per row, and the CHECK below
-- makes the offset structural: the label year is always AFTER the measured
-- period ends. That is the fact that stops someone diffing 2023 against
-- 2024 and calling it a market move.
--
-- THERE IS NO MEDIAN, AND NONE IS INVENTED. The dataset describes a
-- Zentralwert at length and defines minimum/maximum as the quartiles around
-- it, but publishes only the bounds. (min+max)/2 does NOT recover the
-- median -- the bounds are quantiles.
--
-- TWO FLAGS THAT ARE EASY TO CONFLATE, and are not the same thing:
--
--   price_min/max NULL   the 0/0 no-data sentinel, nulled in silver.
--                        40 of 520 rows. THE ONLY "no data" signal.
--   is_market_based=false fewer than 4 transactions in the cell. 290 of
--                        520 rows -- but 250 of those carry REAL prices.
--                        A confidence flag, not an absence flag. Filtering
--                        rows on it discards 250 valid bands.

DROP TABLE IF EXISTS gold.gemeinde_bodenpreis CASCADE;

CREATE TABLE gold.gemeinde_bodenpreis (
    bfs_nr               integer  NOT NULL,
    jahr                 integer  NOT NULL,
    zone_category_code   smallint NOT NULL,
    zone_category_label  text     NOT NULL,
    price_min_chf_m2     integer,
    price_max_chf_m2     integer,
    is_market_based      boolean  NOT NULL,
    window_start         date     NOT NULL,
    window_end           date     NOT NULL,

    PRIMARY KEY (bfs_nr, jahr, zone_category_code),

    -- Bodenpreis years (2012-2024) sit inside the gemeinde_year grid
    -- (2004-2026). A future year outside it fails loudly, which is the
    -- signal wanted -- it means a Gemeinde series stopped covering a year
    -- the price data still reports.
    FOREIGN KEY (bfs_nr, jahr) REFERENCES gold.gemeinde_year (bfs_nr, jahr),

    CONSTRAINT bodenpreis_min_positive
        CHECK (price_min_chf_m2 IS NULL OR price_min_chf_m2 > 0),
    CONSTRAINT bodenpreis_max_positive
        CHECK (price_max_chf_m2 IS NULL OR price_max_chf_m2 > 0),
    CONSTRAINT bodenpreis_bounds_paired
        CHECK ((price_min_chf_m2 IS NULL) = (price_max_chf_m2 IS NULL)),
    CONSTRAINT bodenpreis_bounds_ordered
        CHECK (price_min_chf_m2 IS NULL OR price_min_chf_m2 <= price_max_chf_m2),
    CONSTRAINT bodenpreis_category_range
        CHECK (zone_category_code BETWEEN 1 AND 8),
    CONSTRAINT bodenpreis_window_ordered
        CHECK (window_start < window_end),
    -- The label year is always AFTER the period it measures. This is what
    -- makes "trailing window" structural rather than a note in a doc.
    CONSTRAINT bodenpreis_window_is_trailing
        CHECK (jahr > extract(year FROM window_end)::int)
);

INSERT INTO gold.gemeinde_bodenpreis (
    bfs_nr, jahr, zone_category_code, zone_category_label,
    price_min_chf_m2, price_max_chf_m2, is_market_based,
    window_start, window_end
)
SELECT
    b.bfs_nr,
    b.jahr,
    b.zone_category_code,
    b.zone_category_label,
    b.price_min_chf_m2,
    b.price_max_chf_m2,
    b.is_market_based,
    b.period_start,
    b.period_end
FROM silver.bodenpreis b;

CREATE INDEX gold_bodenpreis_jahr_idx     ON gold.gemeinde_bodenpreis (jahr);
CREATE INDEX gold_bodenpreis_category_idx ON gold.gemeinde_bodenpreis (zone_category_code);

COMMENT ON TABLE gold.gemeinde_bodenpreis IS
    'Gemeinde-level CHF/m2 bands for unbuilt, serviced building land. '
    'Context and cross-check for gold.parcel prices -- not a parcel pricing '
    'path. Joins on bfs_nr and jahr only, never on zone.';
COMMENT ON COLUMN gold.gemeinde_bodenpreis.zone_category_code IS
    '1-8 tax-valuation category. NOT the zone code on gold.parcel and NOT '
    'mappable to it -- no crosswalk is published. Do not join on this.';
COMMENT ON COLUMN gold.gemeinde_bodenpreis.price_min_chf_m2 IS
    'Lower QUARTILE around an unpublished Zentralwert, not a minimum '
    'observation. (min+max)/2 does not recover the median.';
COMMENT ON COLUMN gold.gemeinde_bodenpreis.is_market_based IS
    'Cell had 4+ transactions. false is a CONFIDENCE flag, not an absence '
    'flag: 250 of the 290 false rows carry real prices. The only no-data '
    'signal is a NULL price.';
COMMENT ON COLUMN gold.gemeinde_bodenpreis.window_end IS
    'End of the six-year Bemessungsperiode this row measures, always before '
    'jahr. Adjacent years overlap heavily -- their deltas are not market '
    'moves.';
