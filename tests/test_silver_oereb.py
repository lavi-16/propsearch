"""
The OEREB sample -- 25 of 9,879 parcels.

Tested mainly to keep it honest about being a sample, and to confirm it
still works as the cross-check oracle the zoning tests lean on.
"""


def test_sample_size(scalar):
    assert scalar("SELECT count(*) FROM silver.oereb_extract_sample") == 25
    assert scalar("SELECT count(*) FROM silver.parcel_restriction_sample") == 80


def test_sample_is_a_tiny_fraction_of_the_spine(scalar):
    """0.3% coverage. If this ever approaches 100%, drop the _sample name."""
    sampled = scalar("SELECT count(*) FROM silver.oereb_extract_sample")
    total = scalar("SELECT count(*) FROM silver.parcel")
    assert sampled / total < 0.01


def test_every_sampled_parcel_exists_in_the_spine(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample e "
        "LEFT JOIN silver.parcel p USING (egrid) WHERE p.egrid IS NULL"
    ) == 0


def test_parcel_number_agrees_with_the_spine(scalar):
    """OEREB Number vs Landwertzonen gs_nummer -- an independent check."""
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample e "
        "JOIN silver.parcel p USING (egrid) "
        "WHERE e.parcel_number <> p.parcel_number"
    ) == 0


def test_postal_code_is_not_a_bfs_number(scalar):
    """The source calls it municipality_code; it is a PLZ.

    Keying a Gemeinde join on it would silently produce nothing.
    """
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample e "
        "JOIN silver.gemeinde g ON g.bfs_nr = e.postal_code"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample e "
        "LEFT JOIN silver.gemeinde g ON g.bfs_nr = e.bfs_nr WHERE g.bfs_nr IS NULL"
    ) == 0


def test_empty_type_codes_became_null(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.parcel_restriction_sample WHERE type_code = ''"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.parcel_restriction_sample WHERE type_code IS NULL"
    ) > 0


def test_jsonb_landed_as_objects_not_strings(scalar):
    """A pre-encoded JSON string makes every -> lookup silently return NULL."""
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample "
        "WHERE jsonb_typeof(extract) <> 'object'"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.parcel_restriction_sample "
        "WHERE jsonb_typeof(restriction) <> 'object'"
    ) == 0


def test_hazard_is_absent_from_oereb_themes(scalar):
    """Why bronze.gefahrenkarte exists at all.

    ch.Gefahrenzone is not a TG OEREB theme; hazard reaches OEREB only as
    a Nutzungsplanung overlay label with no grading. Graded intensity has
    to come from the Gefahrenkarte WFS.
    """
    assert scalar(
        "SELECT count(*) FROM silver.parcel_restriction_sample "
        "WHERE theme_code = 'ch.Gefahrenzone'"
    ) == 0


def test_land_registry_area_is_the_only_parcel_area(scalar):
    """No parcel polygon is ingested, so this is it -- for 25 parcels."""
    assert scalar(
        "SELECT count(*) FROM silver.oereb_extract_sample "
        "WHERE land_registry_area_m2 > 0"
    ) == 25
