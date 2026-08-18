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
