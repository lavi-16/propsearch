"""
Zoning -- the normalisation, the canton-wide class, and what the
point-based join can and cannot say.
"""


def test_zone_dimension_row_count(scalar):
    """89 (bfs_nr, code) pairs, not 79 codes -- some codes recur."""
    assert scalar("SELECT count(*) FROM silver.zone") == 89


def test_zone_key_is_unambiguous(scalar):
    """Each (bfs_nr, zone_code_norm) maps to exactly one class and label."""
    assert scalar(
        "SELECT count(*) FROM (SELECT bfs_nr, zone_code_norm FROM silver.zone "
        "GROUP BY 1, 2 HAVING count(DISTINCT zone_class) > 1 "
        "OR count(DISTINCT zone_label) > 1) x"
    ) == 0


def test_normalisation_merges_nothing_within_a_gemeinde(scalar):
    """Documented as defensive, not corrective -- assert it stays that way.

    If this ever fails, a Gemeinde has become internally inconsistent in
    how it spells its own codes, which is worth knowing about.
    """
    assert scalar(
        "SELECT count(*) FROM (SELECT bfs_nr, zone_code_norm FROM silver.zone "
        "GROUP BY 1, 2 HAVING count(DISTINCT zone_code_raw) > 1) x"
    ) == 0


def test_gemeinde_labels_differ_where_the_canton_class_unifies(rows):
    """Why zone_class, and not zone_label, is the cross-Gemeinde column.

    `G` is 'Gewerbezone' in Ermatingen and 'Arbeitszone Gewerbe' in
    Muensterlingen -- two municipal names for what the canton classifies
    as one zone type. Comparing parcels across Gemeinden on the label
    would split a single class in two; comparing on zone_class would not.
    """
    result = rows(
        "SELECT bfs_nr, zone_class, zone_label FROM silver.zone "
        "WHERE zone_code_norm = 'G' ORDER BY bfs_nr"
    )
    assert len({cls for _, cls, _ in result}) == 1
    assert len({label for _, _, label in result}) == 2


def test_zone_class_collapses_the_street_codes(rows):
    """StB / StrB / VfSi / VFiB are one canton-wide class."""
    codes = rows(
        "SELECT DISTINCT zone_code_norm FROM silver.zone "
        "WHERE zone_class = 'Strassen und Wege innerhalb von Bauzonen' ORDER BY 1"
    )
    assert {c for (c,) in codes} == {"STB", "STRB", "VFSI", "VFIB"}


# --- the parcel join ------------------------------------------------------


def test_parcel_zone_coverage(scalar):
    """8,303 of 9,879. Absence means outside every Bauzone -- a fact."""
    assert scalar("SELECT count(*) FROM silver.parcel_zone") == 8303


def test_at_most_one_zone_per_parcel(scalar):
    assert scalar(
        "SELECT count(*) FROM (SELECT egrid FROM silver.parcel_zone "
        "GROUP BY 1 HAVING count(*) > 1) x"
    ) == 0


def test_zone_class_populated_even_where_the_code_is_null(scalar):
    """The 16 Muensterlingen polygons have no gn_kuerzel but do have a class."""
    assert scalar(
        "SELECT count(*) FROM silver.parcel_zone WHERE zone_class IS NULL"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.parcel_zone WHERE zone_code_norm IS NULL"
    ) > 0


def test_sensitivity_keine_is_preserved_not_nulled(scalar):
    """es_txt='keine' is an explicit 'none', same principle as hazard keine."""
    assert scalar(
        "SELECT count(*) FROM silver.parcel_zone WHERE sensitivity_level = 'keine'"
    ) > 0
    assert scalar(
        "SELECT count(*) FROM silver.parcel_zone WHERE sensitivity_level IS NULL"
    ) == 0


def test_zoning_agrees_with_the_oereb_oracle(rows):
    """Cross-source check against the independent OEREB sample: 25/25.

    Two things make a naive comparison read as total disagreement:

    1. OEREB appends the Kuerzel in parentheses to legend_text
       ("Wohnzone W 1.6 (W 1.6)"), so the suffix is stripped first.
    2. A parcel has SEVERAL ch.Nutzungsplanung restrictions -- one base
       zone plus overlays (Gestaltungsplanpflicht, Umgebungsschutzzone,
       Gefahrenzone, Hochwasserschutz). 9 of the 25 sampled parcels carry
       more than one. Overlays are ADDITIONAL, not contradictory, so the
       claim to test is that the base zone appears AMONG a parcel's
       restrictions -- not that every restriction equals it.
    """
    unmatched = rows(
        "SELECT z.egrid, z.zone_label FROM silver.parcel_zone z "
        "JOIN silver.oereb_extract_sample e USING (egrid) "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM silver.parcel_restriction_sample r "
        "  WHERE r.egrid = z.egrid AND r.theme_code = 'ch.Nutzungsplanung' "
        "    AND btrim(regexp_replace(r.legend_text, '\\s*\\([^)]*\\)\\s*$', '')) "
        "        = z.zone_label)"
    )
    assert not unmatched, f"base zone absent from OEREB for: {unmatched}"


def test_oereb_carries_overlays_the_bauzonen_layer_does_not(scalar):
    """The extra Nutzungsplanung rows are overlay restrictions.

    They are why the comparison above matches on existence rather than
    equality, and they are a real gap in silver.parcel_zone: hazard and
    Gestaltungsplan overlays reach OEREB as labels only. Graded hazard
    comes from silver.parcel_hazard instead.
    """
    assert scalar(
        "SELECT count(*) FROM silver.parcel_restriction_sample r "
        "JOIN silver.parcel_zone z USING (egrid) "
        "WHERE r.theme_code = 'ch.Nutzungsplanung' "
        "  AND btrim(regexp_replace(r.legend_text, '\\s*\\([^)]*\\)\\s*$', '')) "
        "      <> z.zone_label"
    ) > 0


def test_straddling_parcels_exist_and_are_a_known_limitation(scalar):
    """Documents the cost of having no parcel polygons.

    The point join gives one zone per parcel. OEREB, which knows true
    parcel geometry, shows that is an approximation for a real share of
    parcels.
    """
    straddling = scalar(
        "SELECT count(DISTINCT egrid) FROM silver.parcel_restriction_sample "
        "WHERE theme_code = 'ch.Nutzungsplanung' AND part_in_percent < 99.5"
    )
    assert straddling == 5
