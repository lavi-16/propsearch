"""
gold.parcel_hazard -- the fan-out, and the synoptic layer's deliberate absence.

Silver contains the 2.97x cross-layer fan-out behind a PK. Gold narrows it
to 2x by dropping the synoptic layer, on the evidence recorded below. These
tests exist so that decision stays evidence-backed rather than inherited.
"""


def test_row_count_and_layers(rows, scalar):
    assert scalar("SELECT count(*) FROM gold.parcel_hazard") == 17784
    assert dict(
        rows("SELECT source_layer, count(*) FROM gold.parcel_hazard GROUP BY 1")
    ) == {
        "ms:Gefaehrdung_Rutschungen": 9005,
        "ms:Gefaehrdung_Wasser": 8779,
    }


def test_synoptic_layer_is_absent(scalar):
    """It lives on gold.parcel as hazard_grade_overall, and only there.

    Keeping it here too would double-count the same ground against its own
    components and put two 'synoptic' concepts in two tables under
    near-identical names.
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel_hazard "
        "WHERE source_layer = 'ms:Gefaehrdung_synoptisch'"
    ) == 0
    assert scalar("SELECT count(*) FROM silver.parcel_hazard") == 26789


def test_the_fanout_is_stated_not_hidden(scalar):
    """Joining gold.parcel to this table doubles the parcel count.

    Reduced from 2.97x, not eliminated. Asserting the exact join cardinality
    means anyone reading the suite learns the multiplier before they write
    a query that silently applies it.
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel p JOIN gold.parcel_hazard h USING (egrid)"
    ) == 17784
    assert scalar("SELECT count(DISTINCT egrid) FROM gold.parcel_hazard") == 9005


def test_one_row_per_parcel_per_layer(scalar):
    """Within a layer the polygons partition, so no parcel doubles up."""
    assert scalar(
        "SELECT count(*) FROM (SELECT egrid, source_layer FROM gold.parcel_hazard "
        "GROUP BY 1, 2 HAVING count(*) > 1) x"
    ) == 0


def test_a_missing_row_is_not_the_same_as_keine(scalar):
    """Per-process absence is its own fact, distinct from gold.parcel's flag.

    226 parcels sit inside the Rutschungen perimeter but outside the Wasser
    one. They are hazard_surveyed = true on gold.parcel and simply have no
    Wasser row here. Reading that as 'no flood risk' would be wrong.
    """
    only_rutschungen = scalar(
        "SELECT count(*) FROM gold.parcel p "
        "WHERE p.hazard_surveyed "
        "  AND EXISTS (SELECT 1 FROM gold.parcel_hazard h WHERE h.egrid = p.egrid "
        "              AND h.source_layer = 'ms:Gefaehrdung_Rutschungen') "
        "  AND NOT EXISTS (SELECT 1 FROM gold.parcel_hazard h WHERE h.egrid = p.egrid "
        "                  AND h.source_layer = 'ms:Gefaehrdung_Wasser')"
    )
    assert only_rutschungen == 226


def test_restgefahr_is_off_the_ordinal_scale(scalar):
    assert scalar(
        "SELECT count(*) FROM gold.parcel_hazard "
        "WHERE (hazard_rank IS NULL) <> (gefahrenstufe = 'Restgefahr')"
    ) == 0


def test_every_hazard_row_has_a_parcel(scalar):
    """The FK covers this, but a failure here localises it immediately."""
    assert scalar(
        "SELECT count(*) FROM gold.parcel_hazard h "
        "WHERE NOT EXISTS (SELECT 1 FROM gold.parcel p WHERE p.egrid = h.egrid)"
    ) == 0


# --- the evidence for dropping the synoptic layer -------------------------


def test_synoptic_is_derivable_from_the_two_process_layers(scalar):
    """The finding that justified excluding it. Exactly ONE exception.

    Ranking keine < Restgefahr < gering < mittel < erheblich and taking the
    max of the two process layers reproduces the published synoptic grade
    on 9,004 of 9,005 surveyed parcels.

    Note the rank used here places Restgefahr on the scale, which the SCHEMA
    deliberately does not -- it is a test convenience for ordering, not a
    claim that residual risk is comparable to a graded intensity.

    If this count ever moves, the layers have diverged and the exclusion
    needs re-deciding rather than inheriting.
    """
    rank = (
        "CASE gefahrenstufe WHEN 'keine' THEN 0 WHEN 'Restgefahr' THEN 1 "
        "WHEN 'gering' THEN 2 WHEN 'mittel' THEN 3 WHEN 'erheblich' THEN 4 END"
    )
    mismatches = scalar(
        f"""
        WITH w AS (SELECT egrid, gefahrenstufe g, {rank} r FROM gold.parcel_hazard
                   WHERE source_layer = 'ms:Gefaehrdung_Wasser'),
             ru AS (SELECT egrid, gefahrenstufe g, {rank} r FROM gold.parcel_hazard
                    WHERE source_layer = 'ms:Gefaehrdung_Rutschungen')
        SELECT count(*) FROM gold.parcel p
        LEFT JOIN w USING (egrid) LEFT JOIN ru USING (egrid)
        WHERE p.hazard_surveyed
          AND p.hazard_grade_overall IS DISTINCT FROM
              (CASE WHEN coalesce(w.r, -1) >= coalesce(ru.r, -1) THEN w.g ELSE ru.g END)
        """
    )
    assert mismatches == 1


def test_the_one_exception_is_a_boundary_artifact(rows):
    """CH854589778397 -- inspected, and kept as a live boundary case.

    The parcel point sits 0.26 m inside a synoptic `mittel` polygon and
    0.31 m outside a Wasser `mittel` one; the two layers' boundaries differ
    by well under a metre there. So it is a point-in-polygon artifact, not
    an independent assessment -- which is what makes the synoptic layer
    droppable.

    gold.parcel keeps the PUBLISHED value (`mittel`) rather than recomputing
    it from the components (`keine`). This test pins that direction: gold
    must not "fix" the source into agreement with itself.
    """
    assert rows(
        "SELECT hazard_surveyed, hazard_grade_overall "
        "FROM gold.parcel WHERE egrid = 'CH854589778397'"
    ) == [(True, "mittel")]

    assert rows(
        "SELECT source_layer, gefahrenstufe FROM gold.parcel_hazard "
        "WHERE egrid = 'CH854589778397' ORDER BY source_layer"
    ) == [
        ("ms:Gefaehrdung_Rutschungen", "keine"),
        ("ms:Gefaehrdung_Wasser", "keine"),
    ]
