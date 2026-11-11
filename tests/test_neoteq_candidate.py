"""
neoteq.candidate -- the persisted, hand-editable lead list. Structural
invariants only (not status values, which Lavi edits by hand): the candidate
predicate holds, addresses are fully resolved, and the FK to gold.building is
intact after a `make gold` rebuild.
"""

import pytest


def test_candidate_row_count(scalar):
    assert scalar("SELECT count(*) FROM neoteq.candidate WHERE is_candidate") == 2439


def test_candidates_satisfy_the_predicate(scalar):
    """Every is_candidate row is genuinely fossil + solar 4-5 + no attached PV.
    Guards against a stale row keeping is_candidate=true after it should have
    retired."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c "
        "WHERE c.is_candidate AND NOT EXISTS ("
        "  SELECT 1 FROM gold.building b "
        "  WHERE b.egid = c.egid "
        "    AND b.heating IN ('Gas','Heizöl') AND b.solar_class IN (4,5) "
        "    AND NOT EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = b.egid))"
    ) == 0


def test_candidates_have_no_pv(scalar):
    """has_existing_pv is false for every cold-conversion candidate by
    construction (the NOT EXISTS building_pv clause). A true here would mean a
    PV-bearing building leaked into the active list."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND has_existing_pv"
    ) == 0


def test_every_candidate_has_a_resolved_address(scalar):
    """100% address coverage via gwr_eingang -- the enrichment invariant. A
    NULL here would mean a candidate with no GWR entrance, which does not exist
    in the pilot."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate "
        "WHERE is_candidate AND (address IS NULL OR plz IS NULL OR ort IS NULL)"
    ) == 0


def test_fk_to_gold_building_is_present(scalar):
    """The FK is re-asserted on every build so a `make gold` CASCADE drop is
    self-healed. Its absence would mean egid is silently unconstrained."""
    assert scalar(
        "SELECT count(*) FROM pg_constraint "
        "WHERE conname = 'candidate_egid_fkey' "
        "AND conrelid = 'neoteq.candidate'::regclass"
    ) == 1


def test_no_candidate_egid_orphaned_from_gold(scalar):
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c "
        "WHERE NOT EXISTS (SELECT 1 FROM gold.building b WHERE b.egid = c.egid)"
    ) == 0


def test_hot_water_source_domain(scalar):
    """The decoded bucket only ever carries the four intended values (or NULL
    for unrecorded genw1). Guards against a source code drifting into a bucket
    the CHECK on silver.building would have caught."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        "AND hot_water_source IS NOT NULL "
        "AND hot_water_source NOT IN ('fossil','electric','solar-thermal','other')"
    ) == 0


def test_heat_generator_type_domain(scalar):
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        "AND heat_generator_type IS NOT NULL "
        "AND heat_generator_type NOT IN ('boiler_condensing','boiler_non_condensing',"
        "'boiler_generic','stove','heat_pump','other')"
    ) == 0


def test_roof_orientation_and_tilt_fully_populated(scalar):
    """Every candidate has solar_class 4-5 by the predicate, so every one has a
    best-class roof plane and therefore an orientation and tilt. A NULL here
    would mean the roll-up lost the plane the class is based on."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        "AND (roof_orientation_deg IS NULL OR roof_tilt_deg IS NULL)"
    ) == 0


def test_orientation_tilt_come_from_a_best_class_plane(scalar):
    """The item-2 invariant: orientation/tilt describe the plane that ACHIEVES
    solar_class (max klasse), not an average. Every candidate must have a roof
    plane whose klasse equals its solar_class carrying exactly the surfaced
    orientation and tilt."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c WHERE c.is_candidate "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM silver.roof_plane rp "
        "  WHERE rp.egid = c.egid AND rp.klasse = c.solar_class "
        "    AND rp.ausrichtung IS NOT DISTINCT FROM c.roof_orientation_deg "
        "    AND rp.neigung     IS NOT DISTINCT FROM c.roof_tilt_deg)"
    ) == 0


def test_dwelling_count_matches_gold_building(scalar):
    """dwelling_count is carried straight from gold.building.dwellings -- no
    transformation, so it must match exactly (NULLs included)."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c JOIN gold.building b USING (egid) "
        "WHERE c.is_candidate AND c.dwelling_count IS DISTINCT FROM b.dwellings"
    ) == 0


def test_building_segment_non_null_where_dwelling_resolvable(scalar):
    """Every candidate whose dwelling_count is known carries a non-null EFH/MFH
    segment. (The upsell maps NULL dwellings to 'unknown', so segment is in fact
    non-null on every row -- this pins the weaker, load-bearing guarantee.)"""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate "
        "WHERE is_candidate AND dwelling_count IS NOT NULL AND building_segment IS NULL"
    ) == 0


def test_building_segment_derives_from_dwelling_count(scalar):
    """The segment is a pure function of dwelling_count: 1 -> EFH, 2+ -> MFH,
    NULL -> unknown. Any row breaking the biconditional means the derivation
    drifted from the dwelling-count logic the EFH/MFH breakdown reports on."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND building_segment <> "
        "CASE WHEN dwelling_count = 1 THEN 'EFH' "
        "     WHEN dwelling_count >= 2 THEN 'MFH' ELSE 'unknown' END"
    ) == 0


def test_building_segment_domain(scalar):
    """Only the three intended values ever appear -- the CHECK made concrete."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        "AND building_segment NOT IN ('EFH', 'MFH', 'unknown')"
    ) == 0


# Per-Gemeinde EFH/MFH counts as last reported (CLAUDE.md neoteq section):
# 1,309 EFH / 1,037 MFH / 93 unknown across the five pilot Gemeinden. The
# segment must reproduce that breakdown exactly, per Gemeinde.
SEGMENT_BREAKDOWN = {
    "Bottighofen": (112, 46),
    "Ermatingen": (144, 97),
    "Kreuzlingen": (649, 698),
    "Münsterlingen": (204, 91),
    "Tägerwilen": (200, 105),
}


@pytest.mark.parametrize("gemeinde,counts", SEGMENT_BREAKDOWN.items())
def test_segment_counts_match_last_report(scalar, gemeinde, counts):
    efh, mfh = counts
    # gemeinde is a hardcoded pilot name from the dict above, not user input.
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        f"AND building_segment = 'EFH' AND gemeinde_name = '{gemeinde}'"
    ) == efh
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate "
        f"AND building_segment = 'MFH' AND gemeinde_name = '{gemeinde}'"
    ) == mfh


def test_segment_totals_match_last_report(scalar):
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND building_segment = 'EFH'"
    ) == 1309
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND building_segment = 'MFH'"
    ) == 1037


# --- PV-upsell cohort: fossil + good roof + PV ALREADY attached -------------
# Kept a distinct, deliberately non-active sub-segment (is_candidate=false), so
# it persists and is queryable without inflating the active Phase-1 count.


def test_pv_upsell_cohort_size(scalar):
    assert scalar("SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell") == 317


def test_cohorts_are_mutually_exclusive(scalar):
    """No building is both a cold-conversion candidate and a PV-upsell lead --
    the two predicates are complementary on the PV clause."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND is_pv_upsell"
    ) == 0


def test_upsell_is_not_in_the_active_candidate_set(scalar):
    """The upsell cohort is is_candidate=false by design, so the headline active
    count stays 2,439 regardless of how many upsell rows exist."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell AND is_candidate"
    ) == 0


def test_upsell_rows_actually_have_pv(scalar):
    """Every upsell lead genuinely carries an attached PV plant -- has_existing_pv
    is the factual EXISTS against silver.building_pv, and it must be true for the
    whole cohort."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell AND NOT has_existing_pv"
    ) == 0


def test_upsell_rows_satisfy_the_predicate(scalar):
    """Every is_pv_upsell row is genuinely fossil + solar 4-5 + attached PV."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c WHERE c.is_pv_upsell AND NOT EXISTS ("
        "  SELECT 1 FROM gold.building b WHERE b.egid = c.egid "
        "    AND b.heating IN ('Gas','Heizöl') AND b.solar_class IN (4,5) "
        "    AND EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = b.egid))"
    ) == 0


def test_has_existing_pv_is_factual_for_all_rows(scalar):
    """has_existing_pv tracks silver.building_pv membership on EVERY row, not a
    per-cohort literal -- so a future retired row keeps an honest PV flag."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate c WHERE c.has_existing_pv IS DISTINCT FROM "
        "EXISTS (SELECT 1 FROM silver.building_pv pv WHERE pv.egid = c.egid)"
    ) == 0


def test_upsell_rows_have_a_resolved_address(scalar):
    """The upsell cohort is address-enriched too (all 317 have a GWR entrance),
    so it is queryable as a mailing list even though it is not yet worked."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate "
        "WHERE is_pv_upsell AND (address IS NULL OR plz IS NULL OR ort IS NULL)"
    ) == 0


def test_upsell_rows_carry_a_segment(scalar):
    """building_segment is derived for the upsell cohort on the same rule."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell AND building_segment IS NULL"
    ) == 0


UPSELL_SEGMENT_BREAKDOWN = {
    "Bottighofen": (21, 1),
    "Ermatingen": (24, 6),
    "Kreuzlingen": (108, 45),
    "Münsterlingen": (24, 12),
    "Tägerwilen": (55, 10),
}


@pytest.mark.parametrize("gemeinde,counts", UPSELL_SEGMENT_BREAKDOWN.items())
def test_upsell_segment_counts(scalar, gemeinde, counts):
    efh, mfh = counts
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell "
        f"AND building_segment = 'EFH' AND gemeinde_name = '{gemeinde}'"
    ) == efh
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_pv_upsell "
        f"AND building_segment = 'MFH' AND gemeinde_name = '{gemeinde}'"
    ) == mfh
