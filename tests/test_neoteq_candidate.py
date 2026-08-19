"""
neoteq.candidate -- the persisted, hand-editable lead list. Structural
invariants only (not status values, which Lavi edits by hand): the candidate
predicate holds, addresses are fully resolved, and the FK to gold.building is
intact after a `make gold` rebuild.
"""


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
    """has_pv is false for every candidate by construction (PV buildings are
    excluded)."""
    assert scalar(
        "SELECT count(*) FROM neoteq.candidate WHERE is_candidate AND has_pv"
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
