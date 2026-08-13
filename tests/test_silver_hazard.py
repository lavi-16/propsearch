"""
Hazard -- the geometry repair, the cross-layer fan-out, and the
keine/unknown distinction.

Per the gold design doc this is "the part most likely to be got wrong",
so the assertions here are deliberately blunt about what must stay true.
"""


def test_hazard_zone_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.hazard_zone") == 6422


def test_all_geometries_valid_after_makevalid(scalar):
    """The 84 Ring Self-intersections from bronze must all be repaired."""
    assert scalar("SELECT count(*) FROM bronze.gefahrenkarte "
                  "WHERE NOT ST_IsValid(geometry)") == 84
    assert scalar("SELECT count(*) FROM silver.hazard_zone "
                  "WHERE NOT ST_IsValid(geom)") == 0


def test_makevalid_did_not_change_area(scalar):
    """Repair must be lossless, not a reshaping."""
    delta = scalar(
        "SELECT abs(sum(ST_Area(g.geometry)) - sum(ST_Area(h.geom))) "
        "FROM bronze.gefahrenkarte g JOIN silver.hazard_zone h ON h.obj_id = g.obj_id"
    )
    assert delta < 1.0, f"area changed by {delta} m2"


def test_geometry_type_not_promoted(rows):
    assert rows("SELECT DISTINCT GeometryType(geom) FROM silver.hazard_zone") == [
        ("MULTIPOLYGON",)
    ]


def test_restgefahr_is_off_the_ordinal_scale(scalar):
    """Residual risk must never sort against gering < mittel < erheblich."""
    assert scalar(
        "SELECT count(*) FROM silver.hazard_zone "
        "WHERE gefahrenstufe = 'Restgefahr' AND hazard_rank IS NOT NULL"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.hazard_zone "
        "WHERE gefahrenstufe <> 'Restgefahr' AND hazard_rank IS NULL"
    ) == 0


def test_matrixfeld_still_maps_1to1_onto_gefahrenstufe(scalar):
    """If the source ever breaks this, it is worth failing on."""
    assert scalar(
        "SELECT count(*) FROM (SELECT matrixfeld FROM silver.hazard_zone "
        "GROUP BY 1 HAVING count(DISTINCT gefahrenstufe) > 1) x"
    ) == 0


# --- the fan-out ----------------------------------------------------------


def test_one_row_per_parcel_per_layer(scalar):
    """Within a layer the polygons partition, so no parcel doubles up."""
    assert scalar(
        "SELECT count(*) FROM (SELECT egrid, source_layer FROM silver.parcel_hazard "
        "GROUP BY 1, 2 HAVING count(*) > 1) x"
    ) == 0


def test_cross_layer_fanout_is_real_and_contained(scalar):
    """26,789 rows over 9,005 parcels -- present in the detail table...

    ...and absent from anything keyed per parcel. This is the 2.97x that
    must never reach a downstream parcel count.
    """
    assert scalar("SELECT count(*) FROM silver.parcel_hazard") == 26789
    assert scalar("SELECT count(DISTINCT egrid) FROM silver.parcel_hazard") == 9005
    assert scalar("SELECT count(*) FROM silver.parcel_hazard_synoptic") == 9879


def test_per_layer_coverage(rows):
    assert dict(
        rows("SELECT source_layer, count(*) FROM silver.parcel_hazard GROUP BY 1")
    ) == {
        "ms:Gefaehrdung_synoptisch": 9005,
        "ms:Gefaehrdung_Rutschungen": 9005,
        "ms:Gefaehrdung_Wasser": 8779,
    }


# --- keine vs unknown -----------------------------------------------------


def test_synoptic_covers_every_parcel_exactly_once(scalar):
    assert scalar("SELECT count(*) FROM silver.parcel_hazard_synoptic") == 9879
    assert scalar(
        "SELECT count(DISTINCT egrid) FROM silver.parcel_hazard_synoptic"
    ) == 9879


def test_surveyed_and_unsurveyed_split(scalar):
    assert scalar(
        "SELECT count(*) FROM silver.parcel_hazard_synoptic WHERE hazard_surveyed"
    ) == 9005
    assert scalar(
        "SELECT count(*) FROM silver.parcel_hazard_synoptic WHERE NOT hazard_surveyed"
    ) == 874


def test_keine_is_not_the_same_as_unsurveyed(scalar):
    """The distinction the whole table exists to protect.

    'keine' means surveyed and clear -- a measured fact. No match means
    outside the surveyed perimeter -- unknown, not safe. Both are common
    here (7,317 vs 874), and collapsing them asserts a safety that was
    never measured.
    """
    surveyed_clear = scalar(
        "SELECT count(*) FROM silver.parcel_hazard_synoptic "
        "WHERE hazard_surveyed AND gefahrenstufe = 'keine'"
    )
    unsurveyed = scalar(
        "SELECT count(*) FROM silver.parcel_hazard_synoptic "
        "WHERE NOT hazard_surveyed AND gefahrenstufe IS NULL"
    )
    assert surveyed_clear == 7317
    assert unsurveyed == 874

    # No row may be ambiguous about which of the two it is.
    assert scalar(
        "SELECT count(*) FROM silver.parcel_hazard_synoptic "
        "WHERE hazard_surveyed <> (gefahrenstufe IS NOT NULL)"
    ) == 0


def test_no_parcel_is_graded_by_a_detail_layer_but_missing_from_synoptic(scalar):
    """Justifies using synoptic as the coverage denominator."""
    assert scalar(
        "SELECT count(DISTINCT h.egrid) FROM silver.parcel_hazard h "
        "JOIN silver.parcel_hazard_synoptic s ON s.egrid = h.egrid "
        "WHERE NOT s.hazard_surveyed"
    ) == 0
