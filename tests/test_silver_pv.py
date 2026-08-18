"""
PV registry -- the coded-subcategory filter (only Photovoltaik lands), the
spatial building link (no EGID in the source, nearest existing building
within 50 m), and the "floor not census" caveat (centroid-geocoded plants
that no building can claim).
"""


# --- pv_plant: the detail grain, PV only ----------------------------------


def test_pv_plant_is_photovoltaik_only(scalar):
    """silver.pv_plant keeps only SubCategory=subcat_2. The 1 non-PV plant in
    the pilot window (subcat_4 Biomass) must not leak in."""
    assert scalar("SELECT count(*) FROM silver.pv_plant") == 1675
    assert scalar("SELECT count(DISTINCT xtf_id) FROM silver.pv_plant") == 1675
    assert scalar(
        "SELECT count(*) FROM bronze.stromproduktion WHERE subcategory = 'subcat_2'"
    ) == 1675


def test_pv_plant_power_positive(scalar):
    assert scalar("SELECT count(*) FROM silver.pv_plant WHERE total_power_kw <= 0") == 0


# --- building_pv: aggregated to the building, existing only ----------------


def test_building_pv_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.building_pv") == 1644


def test_building_pv_only_existing_buildings(scalar):
    """The match is to EXISTING buildings only, so a plant is never pinned to a
    demolished one. Every row FKs to an is_existing building."""
    assert scalar(
        "SELECT count(*) FROM silver.building_pv pv "
        "JOIN silver.building b ON b.egid = pv.egid "
        "WHERE NOT b.is_existing"
    ) == 0


def test_building_pv_has_pv_and_count_positive(scalar):
    """Absence from this table means 'no attached PV' (the neoteq exclusion
    key), so every present row is a genuine PV building."""
    assert scalar("SELECT count(*) FROM silver.building_pv WHERE NOT has_pv") == 0
    assert scalar("SELECT count(*) FROM silver.building_pv WHERE n_pv_plants < 1") == 0


def test_building_pv_matches_honour_the_50m_radius(scalar):
    """No matched building sits further than 50 m from its nearest PV plant --
    the documented radius, not an accident of the join."""
    assert scalar(
        "SELECT count(*) FROM silver.building_pv pv "
        "JOIN silver.building b ON b.egid = pv.egid "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM silver.pv_plant p "
        "  WHERE ST_DWithin(p.geom, b.geom, 50))"
    ) == 0


def test_building_pv_is_a_floor_not_a_census(scalar):
    """The bimodal-geocoding caveat, pinned: some PV plants are geocoded to a
    PLZ centroid with no building within 50 m, so they attach to nothing. This
    is why the exclusion is a floor -- a change to 0 would mean the source
    started geocoding to the building and the caveat could be dropped."""
    unattached = scalar(
        "SELECT count(*) FROM silver.pv_plant p "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM silver.building b "
        "  WHERE b.is_existing AND ST_DWithin(p.geom, b.geom, 50))"
    )
    assert unattached > 0
