"""
Bodenpreise -- the zero sentinel, and the flag that looks like a
data-presence flag but is not one.
"""


def test_grid_is_complete(scalar):
    """5 Gemeinden x 13 years x 8 categories, no gaps."""
    assert scalar("SELECT count(*) FROM silver.bodenpreis") == 520
    assert scalar("SELECT count(DISTINCT jahr) FROM silver.bodenpreis") == 13
    assert scalar(
        "SELECT count(DISTINCT zone_category_code) FROM silver.bodenpreis"
    ) == 8


def test_zero_sentinel_became_null(scalar):
    """40 rows carried minimum = maximum = 0, which is 'no data', not free land."""
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis WHERE price_min_chf_m2 IS NULL"
    ) == 40
    assert scalar(
        "SELECT count(*) FROM bronze.bodenpreise WHERE minimum = 0 AND maximum = 0"
    ) == 40


def test_no_price_is_ever_zero(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis "
        "WHERE price_min_chf_m2 = 0 OR price_max_chf_m2 = 0"
    ) == 0


def test_bounds_are_present_or_absent_together(scalar):
    """Zeros never occurred singly in the source, so nulls must not either."""
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis "
        "WHERE (price_min_chf_m2 IS NULL) <> (price_max_chf_m2 IS NULL)"
    ) == 0


def test_thin_sample_is_not_missing_data(scalar):
    """The finding that changed the design.

    All 40 sentinel rows are is_market_based = false, which makes it
    tempting to treat the flag as 'no data'. That inference is backwards:
    250 of the 290 false rows carry real prices. Filtering on the flag
    would discard them.
    """
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis "
        "WHERE NOT is_market_based AND price_min_chf_m2 IS NOT NULL"
    ) == 250
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis WHERE NOT is_market_based"
    ) == 290
    # ...and no market-based cell was ever a sentinel.
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis "
        "WHERE is_market_based AND price_min_chf_m2 IS NULL"
    ) == 0


def test_trailing_window_is_materialised(scalar):
    """Six-year window ending the year before the label year.

    Adjacent rows overlap by five years, so this exists to stop anyone
    differencing them and calling it a market move.
    """
    assert scalar(
        "SELECT count(*) FROM silver.bodenpreis "
        "WHERE extract(year FROM period_end) <> jahr - 1 "
        "   OR extract(year FROM period_start) <> jahr - 7"
    ) == 0


def test_zone_category_split_is_clean(rows):
    assert rows(
        "SELECT DISTINCT zone_category_code, zone_category_label "
        "FROM silver.bodenpreis ORDER BY 1"
    ) == [
        (1, "Kern"), (2, "Dorf"), (3, "MFH"), (4, "EFH"),
        (5, "W+G"), (6, "Gewerbe"), (7, "Industrie"), (8, "Weiler"),
    ]


def test_no_median_column_was_invented(conn):
    """(min+max)/2 does not recover the median; the bounds are quantiles."""
    cols = {
        c for (c,) in conn.exec_driver_sql(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'silver' AND table_name = 'bodenpreis'"
        )
    }
    assert not {c for c in cols if "median" in c or "mid" in c or "zentral" in c}
