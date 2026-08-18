"""
gold.parcel -- the grain guarantee, and the two facts a bare NULL would eat.

Note which half of the grain guarantee lives where. GROWTH is caught by the
PK on egrid, at build time: any fan-out necessarily duplicates an egrid, and
the INSERT aborts (verified by injecting one). What the PK cannot catch is
the spine SHRINKING -- a LEFT JOIN quietly becoming an inner one drops
parcels and violates nothing. That is what the row-count test below is for.
"""

import re

from propsearch_data.transform import gold


def test_gold_parcel_covers_its_whole_spine(scalar):
    """Every silver parcel reaches gold. The PK cannot check this direction.

    gold.parcel LEFT JOINs three silver tables onto silver.parcel. Turn any
    one of them into an inner join -- an easy edit, since two of them do in
    fact match every row today -- and parcels vanish silently: no constraint
    fires, and every coverage ratio computed from gold stays plausible
    because its denominator shrank too.

    The three parcels most at risk are exactly the interesting ones: the 76
    with no lwz, the 1,576 outside every Bauzone, and the 874 never
    surveyed for hazard.
    """
    assert scalar("SELECT count(*) FROM gold.parcel") == 9879
    assert scalar("SELECT count(*) FROM gold.parcel") == scalar(
        "SELECT count(*) FROM silver.parcel"
    )
    assert scalar(
        "SELECT count(*) FROM silver.parcel s "
        "WHERE NOT EXISTS (SELECT 1 FROM gold.parcel g WHERE g.egrid = s.egrid)"
    ) == 0
    # The parcels a stray inner join would take first.
    assert scalar("SELECT count(*) FROM gold.parcel WHERE lwz IS NULL") == 76
    assert scalar("SELECT count(*) FROM gold.parcel WHERE NOT in_bauzone") == 1576
    assert scalar("SELECT count(*) FROM gold.parcel WHERE NOT hazard_surveyed") == 874


def test_gold_reads_silver_only():
    """Gold's stated contract: never bronze.

    Read from the DDL text with comments stripped, not from pg_depend.
    Postgres records no dependency between a table and whatever an
    INSERT ... SELECT read to populate it, so the catalog cannot answer
    this at all -- a catalog-based version of this test passes whether or
    not gold touches bronze. Comments have to go because the headers
    discuss bronze at length.
    """
    offenders = [
        path.name
        for path in gold.sql_files()
        if "bronze." in re.sub(r"--[^\n]*", "", path.read_text())
    ]
    assert offenders == []


def test_geometry_survived_the_copy(rows):
    assert rows("SELECT DISTINCT GeometryType(geom), ST_SRID(geom) FROM gold.parcel") == [
        ("POINT", 2056)
    ]


def test_single_vintage(rows):
    """egrid alone is a valid PK only while this holds.

    A second vintage landing must fail here rather than silently
    duplicating parcels -- that is the moment to revisit (egrid, vintage).
    """
    assert rows("SELECT DISTINCT vintage FROM gold.parcel") == [(2024,)]


# --- the two booleans -----------------------------------------------------


def test_outside_a_bauzone_is_a_fact_not_a_gap(scalar):
    """1,576 parcels lie outside every Bauzone. That is measured, not missing.

    Without in_bauzone the whole zone_* block is NULL for them and reads
    identically to "we have no zoning data for this parcel".
    """
    assert scalar("SELECT count(*) FROM gold.parcel WHERE in_bauzone") == 8303
    assert scalar("SELECT count(*) FROM gold.parcel WHERE NOT in_bauzone") == 1576
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE NOT in_bauzone AND zone_class IS NOT NULL"
    ) == 0


def test_unsurveyed_is_not_the_same_as_clear(scalar):
    """The distinction that matters most on this table.

    'keine' means surveyed and clear -- a measured fact. hazard_surveyed
    = false means outside the surveyed perimeter -- unknown, not safe.
    Both are common (7,317 vs 874). Collapsing them asserts a safety that
    was never measured.
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel "
        "WHERE hazard_surveyed AND hazard_grade_overall = 'keine'"
    ) == 7317
    assert scalar(
        "SELECT count(*) FROM gold.parcel "
        "WHERE NOT hazard_surveyed AND hazard_grade_overall IS NULL"
    ) == 874
    assert scalar("SELECT count(*) FROM gold.parcel WHERE hazard_surveyed") == 9005


def test_zone_code_may_be_null_inside_a_bauzone(scalar):
    """Why in_bauzone is CHECKed against zone_class and not zone_code.

    16 Muensterlingen polygons carry a NULL gn_kuerzel but a populated
    gn_kantname. Keying the flag on zone_code would report those parcels
    as unzoned.
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE in_bauzone AND zone_code IS NULL"
    ) > 0
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE in_bauzone AND zone_class IS NULL"
    ) == 0


def test_restgefahr_carries_no_rank(scalar):
    """Both directions of the biconditional, not just the obvious one.

    A one-way guard would let a graded-but-unranked row through, and would
    let an unsurveyed row keep a stale rank (the <> comparison against a
    NULL grade evaluates to NULL, and a CHECK admits NULL).
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel "
        "WHERE hazard_grade_overall = 'Restgefahr' AND hazard_rank IS NOT NULL"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE hazard_grade_overall "
        "NOT IN ('Restgefahr') AND hazard_rank IS NULL"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM gold.parcel "
        "WHERE NOT hazard_surveyed AND hazard_rank IS NOT NULL"
    ) == 0


# --- building rollups -----------------------------------------------------


def test_building_rollups_do_not_change_the_grain(scalar):
    """The rollups aggregate buildings to one row per parcel before joining,
    so the spine stays 9,879. n_buildings = 0 is a fact, not a NULL."""
    assert scalar("SELECT count(*) FROM gold.parcel") == 9879
    assert scalar("SELECT count(*) FROM gold.parcel WHERE n_buildings > 0") == 6578
    assert scalar("SELECT count(*) FROM gold.parcel WHERE n_buildings = 0") == 3301
    # The rollup counts exactly the existing buildings that sit on a pilot parcel.
    assert scalar("SELECT sum(n_buildings) FROM gold.parcel") == 9921


def test_parcel_solar_rollup(scalar):
    """5,476 parcels are reachable through a building with a roof plane.
    has_solar_potential is tied to best_solar_class by CHECK."""
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE has_solar_potential"
    ) == 5476
    assert scalar(
        "SELECT count(*) FROM gold.parcel "
        "WHERE has_solar_potential <> (best_solar_class IS NOT NULL)"
    ) == 0
    # A solar class can only ride on a parcel that actually has a building.
    assert scalar(
        "SELECT count(*) FROM gold.parcel WHERE best_solar_class IS NOT NULL "
        "AND n_buildings = 0"
    ) == 0


def test_parcel_solar_class_is_the_building_maximum(scalar):
    """The parcel's best class is the max over its existing buildings."""
    assert scalar(
        "SELECT count(*) FROM gold.parcel p WHERE p.best_solar_class IS DISTINCT FROM "
        "(SELECT max(b.solar_class) FROM gold.building b WHERE b.egrid = p.egrid)"
    ) == 0


# --- what must not be here ------------------------------------------------


def test_no_bodenpreis_category_leaked_onto_the_parcel(rows):
    """Guards the most tempting wrong join in the project.

    Bodenpreise's 8 tax-valuation categories have no published crosswalk to
    the 73 municipal zone codes -- the Schaetzer-Handbuch was checked and
    has none. A mapping looks obvious (EFH -> '4 EFH', EWG -> '3 MFH') and
    is a guess. If it ever appears as a column here, it will get joined on.
    """
    assert rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'parcel' "
        "AND (column_name LIKE '%categor%' OR column_name LIKE '%kategorie%')"
    ) == []


def test_no_area_share_columns(rows):
    """Parcels are Points; there is no polygon to take a share of.

    9 of 25 OEREB-sampled parcels straddle more than one restriction and
    5 of 25 have base-zone coverage below 99.5%. An area_share column here
    would be arithmetic on a fiction.
    """
    assert rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'parcel' "
        "AND (column_name LIKE '%area%' OR column_name LIKE '%percent%' "
        "     OR column_name LIKE '%share%')"
    ) == []


# --- agreement with silver ------------------------------------------------


def test_prices_match_silver_exactly(scalar):
    """Gold corrects nothing. Any drift here is a transcription bug."""
    assert scalar(
        "SELECT count(*) FROM gold.parcel g JOIN silver.parcel s USING (egrid) "
        "WHERE g.price_efh_chf_m2 IS DISTINCT FROM s.price_efh_chf_m2 "
        "   OR g.price_ewg_chf_m2 IS DISTINCT FROM s.price_ewg_chf_m2 "
        "   OR g.price_gewerbe_chf_m2 IS DISTINCT FROM s.price_gewerbe_chf_m2 "
        "   OR g.lwz IS DISTINCT FROM s.lwz"
    ) == 0


def test_hazard_summary_matches_the_synoptic_table(scalar):
    """gold.parcel carries the PUBLISHED synoptic grade, not a recomputation."""
    assert scalar(
        "SELECT count(*) FROM gold.parcel g "
        "JOIN silver.parcel_hazard_synoptic s USING (egrid) "
        "WHERE g.hazard_grade_overall IS DISTINCT FROM s.gefahrenstufe "
        "   OR g.hazard_surveyed <> s.hazard_surveyed "
        "   OR g.hazard_rank IS DISTINCT FROM s.hazard_rank"
    ) == 0


def test_every_parcel_gemeinde_exists_in_the_other_fact(scalar):
    """The two facts join on bfs_nr, and nothing declares that as an FK.

    gold has no gemeinde dimension -- gemeinde_name is denormalised onto
    both facts instead -- so this agreement is a test rather than a
    constraint. It is the one thing that would break the bfs_nr join.
    """
    assert scalar(
        "SELECT count(*) FROM gold.parcel p "
        "WHERE NOT EXISTS (SELECT 1 FROM gold.gemeinde_year gy WHERE gy.bfs_nr = p.bfs_nr)"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM gold.parcel p JOIN gold.gemeinde_year gy USING (bfs_nr) "
        "WHERE gy.gemeinde_name <> p.gemeinde_name"
    ) == 0


def test_the_documented_happy_path_parcel_is_still_complete(rows):
    """The spec's success criterion, pinned to one parcel.

    "One test parcel returns a correct, complete record across all 5
    layers." CH107710829377 is that parcel: zoned, priced, surveyed, in a
    Gemeinde with a full fiscal series. If any layer regresses, this is
    where it shows as a concrete missing value rather than a shifted count.
    """
    assert rows(
        "SELECT bfs_nr, gemeinde_name, parcel_number, lwz, price_efh_chf_m2, "
        "       zone_code, zone_class, sensitivity_level, "
        "       in_bauzone, hazard_surveyed, hazard_grade_overall "
        "FROM gold.parcel WHERE egrid = 'CH107710829377'"
    ) == [
        (
            4671, "Kreuzlingen", "3228", 3, 1180,
            "W80", "Wohnzone 2 mittlere Dichte", "II",
            True, True, "keine",
        )
    ]
