"""
Noise -- the NULL/0 modelled-area distinction on road, the spatial rail
link (EGID empty in the source), and the day >= night orderings.
"""


def test_rail_noise_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.rail_noise") == 937
    assert scalar("SELECT count(DISTINCT xtf_id) FROM silver.rail_noise") == 937


def test_rail_egid_is_unusable_so_link_is_spatial(scalar):
    """The trap: bronze.laerm_bahn has an EGID field, 0% populated. Recorded
    here so a future populated EGID (which would allow an attribute join) is
    a visible change rather than a silent one."""
    assert scalar(
        "SELECT count(*) FROM bronze.laerm_bahn WHERE egid IS NOT NULL"
    ) == 0


def test_rail_day_ge_night(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.rail_noise WHERE lr_day < lr_night"
    ) == 0


# --- building_noise: one row per building ---------------------------------


def test_building_noise_covers_every_building(scalar):
    assert scalar("SELECT count(*) FROM silver.building_noise") == 11217
    assert scalar(
        "SELECT count(*) FROM silver.building_noise n "
        "WHERE NOT EXISTS (SELECT 1 FROM silver.building b WHERE b.egid = n.egid)"
    ) == 0


def test_road_null_is_outside_modelled_area_not_quiet(scalar):
    """188 buildings sit outside the modelled road-noise area -> NULL. That is
    'unknown', not 'quiet'; road_noise_modelled keeps the two apart and the
    CHECK forbids them drifting."""
    assert scalar(
        "SELECT count(*) FROM silver.building_noise WHERE road_noise_modelled"
    ) == 11029
    assert scalar(
        "SELECT count(*) FROM silver.building_noise WHERE NOT road_noise_modelled"
    ) == 188
    assert scalar(
        "SELECT count(*) FROM silver.building_noise "
        "WHERE road_noise_modelled <> (road_lr_day IS NOT NULL)"
    ) == 0


def test_rail_link_is_present_on_few_buildings(scalar):
    """All 937 facade points fall within 50 m of a building, but rail exposure
    reaches only a minority of buildings. has_rail_noise is tied to its value."""
    assert scalar(
        "SELECT count(*) FROM silver.building_noise WHERE has_rail_noise"
    ) > 0
    assert scalar(
        "SELECT count(*) FROM silver.building_noise WHERE has_rail_noise"
    ) < 11217
    assert scalar(
        "SELECT count(*) FROM silver.building_noise "
        "WHERE has_rail_noise <> (rail_lr_day IS NOT NULL)"
    ) == 0


def test_day_ge_night_on_both_sources(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.building_noise "
        "WHERE road_lr_day IS NOT NULL AND road_lr_night IS NOT NULL "
        "AND road_lr_day < road_lr_night"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.building_noise "
        "WHERE rail_lr_day IS NOT NULL AND rail_lr_night IS NOT NULL "
        "AND rail_lr_day < rail_lr_night"
    ) == 0
