"""
silver.parcel -- the spine, and the lwz -> CHF resolution.

The resolution is the part worth testing hardest: `lwz` is an INVERSE
index (1 = priciest), so a transform that looks right and is silently
reversed would produce plausible numbers everywhere.
"""


def test_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.parcel") == 9879


def test_egrid_is_unique(scalar):
    assert scalar("SELECT count(DISTINCT egrid) FROM silver.parcel") == 9879


def test_geometry_is_point_lv95(rows):
    assert rows(
        "SELECT DISTINCT GeometryType(geom), ST_SRID(geom) FROM silver.parcel"
    ) == [("POINT", 2056)]


def test_every_parcel_resolves_to_a_pilot_gemeinde(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.parcel p "
        "LEFT JOIN silver.gemeinde g USING (bfs_nr) WHERE g.bfs_nr IS NULL"
    ) == 0


def test_prices_null_exactly_where_lwz_is_null(scalar):
    """The 76 non-buildable parcels, and only those, have no price."""
    assert scalar("SELECT count(*) FROM silver.parcel WHERE lwz IS NULL") == 76
    assert scalar(
        "SELECT count(*) FROM silver.parcel "
        "WHERE (lwz IS NULL) <> (price_efh_chf_m2 IS NULL)"
    ) == 0


def test_no_price_is_ever_zero(scalar):
    """The padding zeros in *_landwertzone5..7 must never surface."""
    assert scalar(
        "SELECT count(*) FROM silver.parcel WHERE price_efh_chf_m2 = 0 "
        "OR price_ewg_chf_m2 = 0 OR price_gewerbe_chf_m2 = 0"
    ) == 0


def test_lwz_is_an_inverse_index(rows):
    """1 must be the PRICIEST band, not the cheapest.

    Guards the single most consequential way this transform could be
    wrong: reading `lwz` as a rank rather than an inverse index. Compared
    within a Gemeinde, since the bands are per-Gemeinde.
    """
    result = rows(
        "SELECT bfs_nr, avg(price_efh_chf_m2) FILTER (WHERE lwz = 1),"
        "               avg(price_efh_chf_m2) FILTER (WHERE lwz = 3) "
        "FROM silver.parcel WHERE price_efh_chf_m2 IS NOT NULL "
        "GROUP BY 1 HAVING count(*) FILTER (WHERE lwz = 1) > 0 "
        "AND count(*) FILTER (WHERE lwz = 3) > 0"
    )
    assert result, "no Gemeinde carries both lwz=1 and lwz=3"
    for bfs_nr, priciest, mid in result:
        assert priciest > mid, f"lwz=1 not priciest in {bfs_nr}: {priciest} <= {mid}"


def test_single_vintage(rows):
    """The PK is egrid alone; that only holds while there is one vintage."""
    assert rows("SELECT DISTINCT vintage FROM silver.parcel") == [(2024,)]


def test_non_buildable_categories_are_the_unpriced_ones(rows):
    unpriced = rows(
        "SELECT DISTINCT kat FROM silver.parcel WHERE lwz IS NULL ORDER BY 1"
    )
    assert {k for (k,) in unpriced} <= {"street", "forest", "remains"}
