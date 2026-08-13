"""
gold.gemeinde_bodenpreis -- trailing windows, quantile bounds, and the two
flags that look interchangeable and are not.

The zone-category trap gets its guard in test_gold_parcel.py (the column
must never appear on the parcel). What is guarded here is everything that
would go wrong once someone reads these numbers as spot prices.
"""

from datetime import date


def test_the_grid_is_complete(scalar, rows):
    """5 Gemeinden x 13 years x 8 categories, no gaps."""
    assert scalar("SELECT count(*) FROM gold.gemeinde_bodenpreis") == 520
    assert scalar("SELECT min(jahr) FROM gold.gemeinde_bodenpreis") == 2012
    assert scalar("SELECT max(jahr) FROM gold.gemeinde_bodenpreis") == 2024
    assert rows(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis GROUP BY bfs_nr, jahr "
        "HAVING count(*) <> 8"
    ) == []


def test_categories_are_the_eight_tax_valuation_classes(rows):
    assert rows(
        "SELECT DISTINCT zone_category_code, zone_category_label "
        "FROM gold.gemeinde_bodenpreis ORDER BY 1"
    ) == [
        (1, "Kern"), (2, "Dorf"), (3, "MFH"), (4, "EFH"),
        (5, "W+G"), (6, "Gewerbe"), (7, "Industrie"), (8, "Weiler"),
    ]


def test_rows_are_trailing_windows_not_spot_prices(scalar, rows):
    """The label year always sits AFTER the period it measures.

    The 2024 row covers 2017-01-01..2023-12-31. Consecutive years overlap
    by five of six years, so the series is smoothed by construction and
    adjacent-year deltas are not market moves. The CHECK makes that
    structural; this asserts it holds for every row.
    """
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis "
        "WHERE jahr <= extract(year FROM window_end)::int"
    ) == 0
    assert rows(
        "SELECT window_start, window_end FROM gold.gemeinde_bodenpreis "
        "WHERE jahr = 2024 LIMIT 1"
    ) == [(date(2017, 1, 1), date(2023, 12, 31))]


def test_adjacent_years_overlap_so_deltas_are_not_market_moves(scalar):
    """Some series repeat verbatim across two years. That is the smoothing.

    Asserting that identical adjacent pairs EXIST stops anyone reading a
    flat stretch as a data error and "fixing" it.
    """
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis a "
        "JOIN gold.gemeinde_bodenpreis b "
        "  ON b.bfs_nr = a.bfs_nr AND b.zone_category_code = a.zone_category_code "
        " AND b.jahr = a.jahr + 1 "
        "WHERE a.price_min_chf_m2 = b.price_min_chf_m2 "
        "  AND a.price_max_chf_m2 = b.price_max_chf_m2"
    ) > 0


# --- the two flags --------------------------------------------------------


def test_the_only_no_data_signal_is_a_null_price(scalar):
    """The 0/0 sentinel, nulled in silver. 40 of 520 rows."""
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis WHERE price_min_chf_m2 IS NULL"
    ) == 40
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis "
        "WHERE price_min_chf_m2 = 0 OR price_max_chf_m2 = 0"
    ) == 0


def test_market_flag_is_confidence_not_absence(scalar):
    """The inference that looks safe and costs 250 rows.

    All 40 sentinel rows are is_market_based = false, which makes the flag
    look like a data-absence marker. It is not: 250 of the 290 false rows
    carry real prices. Filtering on it discards them.
    """
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis WHERE is_market_based"
    ) == 230
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis WHERE NOT is_market_based"
    ) == 290
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis "
        "WHERE NOT is_market_based AND price_min_chf_m2 IS NOT NULL"
    ) == 250
    # No priced-and-flagged row is ever a sentinel, which is why the
    # sentinel test above uses the price and not the flag.
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis "
        "WHERE is_market_based AND price_min_chf_m2 IS NULL"
    ) == 0


def test_no_median_column_was_invented(rows):
    """The dataset describes a Zentralwert at length and never publishes it.

    min/max are the quartiles AROUND that centre, so (min+max)/2 does not
    recover it. A midpoint column would look authoritative and be wrong.
    """
    assert rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'gemeinde_bodenpreis' "
        "AND (column_name LIKE '%median%' OR column_name LIKE '%mid%' "
        "     OR column_name LIKE '%zentral%' OR column_name LIKE '%_avg%')"
    ) == []


# --- the cross-check it exists for ----------------------------------------


def test_every_row_has_a_gemeinde_year(scalar):
    """The FK covers this; a failure here localises it."""
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_bodenpreis b "
        "WHERE NOT EXISTS (SELECT 1 FROM gold.gemeinde_year gy "
        "                  WHERE gy.bfs_nr = b.bfs_nr AND gy.jahr = b.jahr)"
    ) == 0


def test_parcel_prices_land_inside_the_band_for_the_documented_parcel(rows):
    """The five-layer cross-check, run on the happy-path parcel.

    Landwertzonen prices the parcel; dfs-sv-1 gives an independent
    Gemeinde-level band from a different method. CH107710829377's EFH price
    of 1,180 CHF/m2 sits inside Kreuzlingen's 2024 '4 EFH' band of
    817-1,514, and that band is market-based (4+ transactions). Two
    independent sources agreeing is the strongest evidence the pipeline
    produces something usable.

    Note this is a SANITY CHECK on the same Gemeinde and year, not a join
    on zone -- there is no crosswalk from a parcel's zone to a tax
    category, and the category is named literally here for that reason.
    """
    assert rows(
        "SELECT p.price_efh_chf_m2, b.price_min_chf_m2, b.price_max_chf_m2, "
        "       b.is_market_based, "
        "       p.price_efh_chf_m2 BETWEEN b.price_min_chf_m2 AND b.price_max_chf_m2 "
        "FROM gold.parcel p "
        "JOIN gold.gemeinde_bodenpreis b "
        "  ON b.bfs_nr = p.bfs_nr AND b.jahr = 2024 AND b.zone_category_code = 4 "
        "WHERE p.egrid = 'CH107710829377'"
    ) == [(1180, 817, 1514, True, True)]
