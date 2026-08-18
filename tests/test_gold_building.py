"""
gold.building -- the new building grain: existing-only filter, the three
coverage booleans, and the link back to the parcel.
"""


def test_building_row_count(scalar):
    assert scalar("SELECT count(*) FROM gold.building") == 10392
    assert scalar("SELECT count(DISTINCT egid) FROM gold.building") == 10392


def test_only_existing_buildings(scalar):
    """The 700 demolished + 125 projected buildings that look current in
    silver must never appear here. The CHECK plus the WHERE enforce it;
    asserted against silver so a break localises."""
    assert scalar(
        "SELECT count(*) FROM gold.building b JOIN silver.building s USING (egid) "
        "WHERE NOT s.is_existing"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.building WHERE is_existing"
    ) == 10392


def test_geometry_type_and_srid(rows):
    assert rows(
        "SELECT DISTINCT GeometryType(geom), ST_SRID(geom) FROM gold.building"
    ) == [("POINT", 2056)]


def test_reads_silver_only():
    """Covered generically by test_gold_reads_silver_only, restated here so
    the building DDL is explicitly on the hook."""
    import re
    from propsearch_data.transform import gold

    building = next(p for p in gold.sql_files() if p.name == "50_building.sql")
    assert "bronze." not in re.sub(r"--[^\n]*", "", building.read_text())


# --- coverage booleans ----------------------------------------------------


def test_solar_coverage_and_biconditional(scalar):
    """7,414 of 10,392 existing buildings carry a roof plane -- the ~29%
    without one are minor structures the survey excludes, not a defect."""
    assert scalar(
        "SELECT count(*) FROM gold.building WHERE has_solar_potential"
    ) == 7414
    assert scalar(
        "SELECT count(*) FROM gold.building "
        "WHERE has_solar_potential <> (solar_class IS NOT NULL)"
    ) == 0


def test_road_noise_null_is_not_quiet(scalar):
    assert scalar(
        "SELECT count(*) FROM gold.building WHERE NOT road_noise_modelled"
    ) == 183
    assert scalar(
        "SELECT count(*) FROM gold.building "
        "WHERE road_noise_modelled <> (noise_road_day IS NOT NULL)"
    ) == 0


def test_rail_noise_biconditional(scalar):
    assert scalar("SELECT count(*) FROM gold.building WHERE has_rail_noise") == 339
    assert scalar(
        "SELECT count(*) FROM gold.building "
        "WHERE has_rail_noise <> (noise_rail_day IS NOT NULL)"
    ) == 0


# --- the parcel link ------------------------------------------------------


def test_building_links_to_parcel(scalar):
    """egrid is the link to gold.parcel, one parcel to many buildings.
    9,921 existing buildings sit on a pilot parcel; 13 carry no egrid."""
    assert scalar(
        "SELECT count(*) FROM gold.building b JOIN gold.parcel p ON p.egrid = b.egrid"
    ) == 9921
    assert scalar("SELECT count(*) FROM gold.building WHERE egrid IS NULL") == 13


def test_attributes_match_silver(scalar):
    """Gold corrects nothing; any drift is a transcription bug."""
    assert scalar(
        "SELECT count(*) FROM gold.building g JOIN silver.building s USING (egid) "
        "WHERE g.year_built IS DISTINCT FROM s.year_built "
        "   OR g.area_m2 IS DISTINCT FROM s.area_m2 "
        "   OR g.dwellings IS DISTINCT FROM s.dwellings "
        "   OR g.heating IS DISTINCT FROM s.heating"
    ) == 0


def test_the_roofed_demonstrator_building(rows):
    """CLAUDE.md's Sonnendach demonstrator: egid 663567, 6 planes, best
    class 4, on parcel CH257817784197."""
    assert rows(
        "SELECT egrid, solar_class, has_solar_potential "
        "FROM gold.building WHERE egid = '663567'"
    ) == [("CH257817784197", 4, True)]
