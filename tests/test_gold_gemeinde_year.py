"""
gold.gemeinde_year -- ragged on purpose, and the 38x fan-out that isn't there.

Two failure modes this file guards. First, someone "tidying" the NULLs by
inner-joining the four series into their 2019-2024 intersection, which
discards 15 years of tax history. Second, the age table arriving as a join
rather than an aggregate, which would multiply every Gemeinde-year by 38.
"""

import pytest


def test_row_count_and_grain(scalar):
    assert scalar("SELECT count(*) FROM gold.gemeinde_year") == 115
    assert scalar(
        "SELECT count(*) FROM (SELECT bfs_nr, jahr FROM gold.gemeinde_year "
        "GROUP BY 1, 2 HAVING count(*) > 1) x"
    ) == 0
    assert scalar("SELECT count(DISTINCT bfs_nr) FROM gold.gemeinde_year") == 5


def test_the_age_table_did_not_fan_out(scalar):
    """silver.gemeinde_bevoelkerung_alter is 38 rows per Gemeinde-year.

    2 sexes x 19 five-year bands. Joining it in directly turns 5 rows per
    year into 190 -- the same grain mistake the bodenpreis/parcel split
    avoids. 115 rows here is the proof it was aggregated instead.
    """
    assert scalar("SELECT count(*) FROM silver.gemeinde_bevoelkerung_alter") == 2090
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_year WHERE jahr BETWEEN 2015 AND 2025"
    ) == 55


def test_the_full_year_range_survived(scalar):
    """No floor, no ceiling imposed by the narrowest source.

    Finanzkennzahlen covers only 2019-2024. Letting it bind would cut
    Steuerfuss from 23 years to 6.
    """
    assert scalar("SELECT min(jahr) FROM gold.gemeinde_year") == 2004
    assert scalar("SELECT max(jahr) FROM gold.gemeinde_year") == 2026


SERIES = {
    # column                        -> rows that must be populated
    "steuerfuss_konfessionslos": 115,
    "selbstfinanzierungsgrad_pct": 30,
    "einwohner": 95,
    "pct_65_plus": 55,
}


@pytest.mark.parametrize("column,expected", SERIES.items())
def test_per_series_coverage_is_ragged(scalar, column, expected):
    """Each source keeps its own coverage window. NULLs elsewhere are correct.

    If these four numbers ever become equal, someone inner-joined the
    series and the table now lies about how far back each one reaches.
    """
    assert scalar(f"SELECT count({column}) FROM gold.gemeinde_year") == expected


def test_no_year_was_dropped_by_sourcing_the_spine_from_one_series(scalar):
    """The spine is a UNION of every series' years, not the widest table.

    Steuerfuss happens to cover every other series' years today, so this
    passes trivially -- which is exactly why it needs asserting. A future
    series carrying a year outside 2004-2026 must appear here, not vanish.
    """
    for table in (
        "gemeinde_steuerfuss",
        "gemeinde_finanzkennzahlen",
        "gemeinde_bevoelkerung",
        "gemeinde_bevoelkerung_alter",
    ):
        orphans = scalar(
            f"SELECT count(*) FROM (SELECT DISTINCT bfs_nr, jahr FROM silver.{table}) s "
            "WHERE NOT EXISTS (SELECT 1 FROM gold.gemeinde_year gy "
            "                  WHERE gy.bfs_nr = s.bfs_nr AND gy.jahr = s.jahr)"
        )
        assert orphans == 0, f"{table} has years missing from gold.gemeinde_year"


# --- the age shares -------------------------------------------------------


def test_shares_reconcile_with_the_population_series(scalar):
    """einwohner and the shares come from two different datasets.

    sk-stat-56 gives the total, sk-stat-58 the age breakdown. They agree
    exactly on all 55 overlapping Gemeinde-years, which is what makes it
    safe to carry the total from one and the shares from the other on the
    same row.
    """
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_year gy "
        "JOIN (SELECT bfs_nr, jahr, sum(anzahl_personen) tot "
        "      FROM silver.gemeinde_bevoelkerung_alter GROUP BY 1, 2) a "
        "  USING (bfs_nr, jahr) "
        "WHERE gy.einwohner <> a.tot"
    ) == 0


def test_shares_are_exact_sums_not_interpolations(scalar):
    """Both cuts fall on a band boundary, so no interpolation is involved.

    65+ is codes 65..90; under-20 is codes 0,5,10,15. Recomputing from the
    silver detail must reproduce gold to the last decimal -- if it does
    not, someone estimated across a band.
    """
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_year gy "
        "JOIN (SELECT bfs_nr, jahr, "
        "        round(100.0 * sum(anzahl_personen) FILTER (WHERE alter5klassen_code >= 65) "
        "              / sum(anzahl_personen), 1) p65, "
        "        round(100.0 * sum(anzahl_personen) FILTER (WHERE alter5klassen_code < 20) "
        "              / sum(anzahl_personen), 1) pu20 "
        "      FROM silver.gemeinde_bevoelkerung_alter GROUP BY 1, 2) a "
        "  USING (bfs_nr, jahr) "
        "WHERE gy.pct_65_plus <> a.p65 OR gy.pct_under_20 <> a.pu20"
    ) == 0


def test_no_invented_age_statistic(rows):
    """No median or mean age. The source publishes bands, not a distribution.

    Either would need a within-band interpolation and an invented midpoint
    for the open-ended 90+ class -- precision the source does not contain.
    Same rule the Bodenpreise Zentralwert gets.
    """
    assert rows(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'gold' AND table_name = 'gemeinde_year' "
        "AND (column_name LIKE '%median%' OR column_name LIKE '%durchschnitt%' "
        "     OR column_name LIKE '%_avg%' OR column_name LIKE '%mittel%')"
    ) == []


def test_shares_are_disjoint_and_leave_a_working_age_residual(scalar):
    """pct_65_plus + pct_under_20 <= 100, so 20-64 is recoverable as 1 - both."""
    assert scalar(
        "SELECT count(*) FROM gold.gemeinde_year "
        "WHERE pct_65_plus IS NOT NULL AND pct_65_plus + pct_under_20 > 100"
    ) == 0


# --- the cross-fact join --------------------------------------------------


def test_joining_the_two_facts_on_bfs_nr_alone_multiplies(scalar):
    """Documents the trap rather than preventing it -- it cannot be prevented.

    9,879 parcels x up to 23 years. The join is only meaningful with a year
    predicate, and gold deliberately ships no convenience view that hides
    this.
    """
    unqualified = scalar(
        "SELECT count(*) FROM gold.parcel p JOIN gold.gemeinde_year gy USING (bfs_nr)"
    )
    qualified = scalar(
        "SELECT count(*) FROM gold.parcel p "
        "JOIN gold.gemeinde_year gy ON gy.bfs_nr = p.bfs_nr AND gy.jahr = 2024"
    )
    assert unqualified == 9879 * 23
    assert qualified == 9879
