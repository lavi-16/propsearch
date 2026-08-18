"""
Roof solar -- the third grain (roof plane), the load-bearing gwr_egid cast,
geometry repair, and the aggregate that the building layer consumes.
"""


def test_roof_plane_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.roof_plane") == 34358
    assert scalar("SELECT count(DISTINCT df_uid) FROM silver.roof_plane") == 34358


def test_geometry_valid_after_makevalid(scalar):
    """69 self-intersections from bronze, all repaired here."""
    assert scalar(
        "SELECT count(*) FROM bronze.sonnendach WHERE NOT ST_IsValid(geometry)"
    ) == 69
    assert scalar(
        "SELECT count(*) FROM silver.roof_plane WHERE NOT ST_IsValid(geom)"
    ) == 0


def test_geometry_type_and_srid(rows):
    assert rows(
        "SELECT DISTINCT GeometryType(geom), ST_SRID(geom) FROM silver.roof_plane"
    ) == [("MULTIPOLYGON", 2056)]


def test_klasse_is_1_to_5(rows):
    assert rows(
        "SELECT DISTINCT klasse FROM silver.roof_plane ORDER BY 1"
    ) == [(1,), (2,), (3,), (4,), (5,)]


def test_unlinked_roofs_are_kept_as_null_not_dropped(scalar):
    """6.3% of planes have no register link. A NULL egid means unlinked
    (surveyed, no match) -- kept, not discarded, the measured-absence rule."""
    assert scalar(
        "SELECT count(*) FROM silver.roof_plane WHERE egid IS NULL"
    ) == 2150


def test_egid_cast_actually_matches_buildings(scalar):
    """The double->bigint->text cast is load-bearing: read as a float,
    2337457.0 would never match the text '2337457'. Prove it matches."""
    assert scalar(
        "SELECT count(DISTINCT r.egid) FROM silver.roof_plane r "
        "JOIN silver.building b ON b.egid = r.egid"
    ) == 7701


# --- the aggregate --------------------------------------------------------


def test_building_solar_row_count(scalar):
    """One row per building carrying >=1 plane, restricted to pilot buildings."""
    assert scalar("SELECT count(*) FROM silver.building_solar") == 7701
    assert scalar("SELECT count(DISTINCT egid) FROM silver.building_solar") == 7701


def test_building_solar_fanout_reduced_to_building_grain(scalar):
    """~3 planes per building collapse to one row. n_planes records the fan-out
    that was removed; every building_solar egid is a real building."""
    assert scalar("SELECT max(n_planes) FROM silver.building_solar") >= 5
    assert scalar(
        "SELECT count(*) FROM silver.building_solar s "
        "WHERE NOT EXISTS (SELECT 1 FROM silver.building b WHERE b.egid = s.egid)"
    ) == 0


def test_best_class_is_the_max_plane_class(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.building_solar s WHERE s.best_class <> "
        "(SELECT max(klasse) FROM silver.roof_plane r WHERE r.egid = s.egid)"
    ) == 0
