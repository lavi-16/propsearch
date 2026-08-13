-- silver.bodenpreis -- Gemeinde-level CHF/m2 bands, 2012-2024.
--
-- From bronze.bodenpreise (data.tg.ch dfs-sv-1, Steuerverwaltung TG).
-- Grain is (Gemeinde, year, zone category): a complete 5 x 13 x 8 grid.
--
-- THIS IS NOT THE PARCEL PRICE PATH. silver.parcel already carries
-- parcel-precise CHF/m2 resolved from Landwertzonen. This table is
-- Gemeinde-level context, historical trend, and a cross-check -- its
-- `bauzone` is one of 8 coarse tax-valuation categories which do NOT map
-- to the 79 municipal zone codes in silver.zone, and no crosswalk is
-- published. It joins on (bfs_nr, jahr), never to a zone polygon.
--
-- THREE TRAPS, ALL ENCODED HERE RATHER THAN LEFT TO THE READER:
--
-- 1. ZERO IS A NO-DATA SENTINEL, NOT A PRICE. 40 of 520 rows carry
--    minimum = maximum = 0. Zeros always come in pairs (verified: zero rows
--    where exactly one of the two is zero), so a single guard suffices.
--    They are nulled here, and the CHECK stops a zero ever reappearing.
--
-- 2. markt_ja_nein IS A CONFIDENCE FLAG, NOT A DATA-PRESENCE FLAG. It is
--    tempting to read 'n' as "no data" because all 40 sentinel rows are
--    'n'. That inference is BACKWARDS: 250 of the 290 'n' rows carry real
--    nonzero prices. 'n' means the cell had fewer than four transactions --
--    indicative rather than market-derived. Filtering on it would discard
--    250 valid price bands. Surface it, never filter on it.
--
-- 3. ROWS ARE SIX-YEAR TRAILING WINDOWS, NOT SPOT PRICES. The 2024 row is
--    computed over the Bemessungsperiode 2017-01-01 to 2023-12-31.
--    Consecutive years overlap heavily, so the series is smoothed by
--    construction and adjacent-year deltas are NOT market moves. The window
--    is materialised as period_start/period_end precisely so nobody diffs
--    two rows and calls it a trend.
--
-- NO MEDIAN EXISTS. The source documents a Zentralwert and defines
-- minimum/maximum as the quartiles around it, but publishes only the
-- bounds. (min+max)/2 does NOT recover the median -- the bounds are
-- quantiles. Deliberately no midpoint column here.

DROP TABLE IF EXISTS silver.bodenpreis CASCADE;

CREATE TABLE silver.bodenpreis (
    bfs_nr              integer  NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr                integer  NOT NULL,
    zone_category_code  smallint NOT NULL,
    zone_category_label text     NOT NULL,
    price_min_chf_m2    integer,
    price_max_chf_m2    integer,
    is_market_based     boolean  NOT NULL,
    period_start        date     NOT NULL,
    period_end          date     NOT NULL,
    PRIMARY KEY (bfs_nr, jahr, zone_category_code),

    CONSTRAINT bodenpreis_min_positive
        CHECK (price_min_chf_m2 IS NULL OR price_min_chf_m2 > 0),
    CONSTRAINT bodenpreis_max_positive
        CHECK (price_max_chf_m2 IS NULL OR price_max_chf_m2 > 0),
    -- The sentinel nulls both bounds, so they are present or absent together.
    CONSTRAINT bodenpreis_bounds_paired
        CHECK ((price_min_chf_m2 IS NULL) = (price_max_chf_m2 IS NULL)),
    CONSTRAINT bodenpreis_bounds_ordered
        CHECK (price_min_chf_m2 IS NULL OR price_min_chf_m2 <= price_max_chf_m2),
    CONSTRAINT bodenpreis_category_range
        CHECK (zone_category_code BETWEEN 1 AND 8),
    CONSTRAINT bodenpreis_period_ordered
        CHECK (period_start < period_end)
);

INSERT INTO silver.bodenpreis (
    bfs_nr, jahr, zone_category_code, zone_category_label,
    price_min_chf_m2, price_max_chf_m2, is_market_based,
    period_start, period_end
)
SELECT
    b.bfs_nr_gemeinde::integer,
    left(b.jahr, 4)::integer,
    split_part(b.bauzone, ' ', 1)::smallint,
    substr(b.bauzone, strpos(b.bauzone, ' ') + 1),
    -- The 0/0 no-data sentinel becomes NULL. Guarded on the pair, since
    -- zeros never occur singly.
    CASE WHEN b.minimum = 0 AND b.maximum = 0 THEN NULL ELSE b.minimum END,
    CASE WHEN b.minimum = 0 AND b.maximum = 0 THEN NULL ELSE b.maximum END,
    b.markt_ja_nein = 'j',
    make_date(left(b.jahr, 4)::integer - 7, 1, 1),
    make_date(left(b.jahr, 4)::integer - 1, 12, 31)
FROM bronze.bodenpreise b;

CREATE INDEX bodenpreis_jahr_idx ON silver.bodenpreis (jahr);

COMMENT ON TABLE silver.bodenpreis IS
    'Gemeinde-level CHF/m2 bands for unbuilt serviced building land. '
    'Gemeinde grain -- joins on (bfs_nr, jahr) only. Parcel pricing goes '
    'through silver.parcel, which needs no crosswalk.';
COMMENT ON COLUMN silver.bodenpreis.is_market_based IS
    'markt_ja_nein = j: the cell had at least 4 transactions. A CONFIDENCE '
    'flag, not a data-presence flag -- 250 of the 290 false rows carry real '
    'prices. Never filter rows on this.';
COMMENT ON COLUMN silver.bodenpreis.price_min_chf_m2 IS
    'Lower quartile bound, not a minimum observation. NULL where the source '
    'used the 0/0 no-data sentinel (40 rows, all 2012-2016).';
COMMENT ON COLUMN silver.bodenpreis.period_end IS
    'End of the six-year Bemessungsperiode this row summarises. Adjacent '
    'jahr values overlap by five years -- differencing them does not yield '
    'a market move.';
