"""
silver.gemeinde_energiefoerderung -- the cantonal energy-subsidy programme.

Gemeinde-level context (adoption/market signal), NOT per-building. The
invariants worth guarding: the full year range survives (like the other
Gemeinde series), the pilot grain is complete, and it stays UNLINKED from the
neoteq strand -- it is context, never a per-building fact.
"""


def test_grain_is_complete_pilot_grid(scalar):
    """5 Gemeinden x 17 years (2008-2024) = 85 rows, one per (bfs_nr, jahr)."""
    assert scalar("SELECT count(*) FROM silver.gemeinde_energiefoerderung") == 85
    assert scalar(
        "SELECT count(DISTINCT bfs_nr) FROM silver.gemeinde_energiefoerderung"
    ) == 5


def test_full_year_range_survives(scalar):
    assert scalar("SELECT min(jahr) FROM silver.gemeinde_energiefoerderung") == 2008
    assert scalar("SELECT max(jahr) FROM silver.gemeinde_energiefoerderung") == 2024


def test_bfs_nr_is_integer(scalar):
    """Cast from the text bronze key, like every other data.tg.ch series."""
    assert scalar(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema='silver' AND table_name='gemeinde_energiefoerderung' "
        "AND column_name='bfs_nr'"
    ) == "integer"


def test_waermepumpe_counts_present(scalar):
    """The heat-pump subsidy count -- the strand-relevant measure -- is a clean
    non-negative integer on every pilot row."""
    assert scalar(
        "SELECT count(*) FROM silver.gemeinde_energiefoerderung "
        "WHERE waermepumpe IS NULL OR waermepumpe < 0"
    ) == 0


def test_not_linked_to_neoteq_candidate(scalar):
    """It is Gemeinde-level context and must never become a per-building key on
    the candidate table. neoteq.candidate carries no column referencing it."""
    assert scalar(
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_schema='neoteq' AND table_name='candidate' "
        "AND column_name LIKE '%%energie%%'"
    ) == 0
