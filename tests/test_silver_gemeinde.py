"""
The Gemeinde dimension and the four statistics series.

The one thing worth guarding here is that nobody quietly inner-joins the
four series into their shared year range.
"""

import pytest

SERIES = {
    "gemeinde_steuerfuss": (115, 2004, 2026),
    "gemeinde_finanzkennzahlen": (30, 2019, 2024),
    "gemeinde_bevoelkerung": (95, 2007, 2025),
    "gemeinde_bevoelkerung_alter": (2090, 2015, 2025),
}


def test_pilot_gemeinden(rows):
    assert rows(
        "SELECT bfs_nr, gemeinde_name FROM silver.gemeinde ORDER BY 1"
    ) == [
        (4643, "Bottighofen"),
        (4646, "Ermatingen"),
        (4671, "Kreuzlingen"),
        (4691, "Münsterlingen"),
        (4696, "Tägerwilen"),
    ]


def test_bezirk_name_normalised(rows):
    """'Bezirk Kreuzlingen' in one source, 'Kreuzlingen' in another."""
    assert rows("SELECT DISTINCT bezirk_name FROM silver.gemeinde") == [("Kreuzlingen",)]


@pytest.mark.parametrize("table,expected", SERIES.items())
def test_series_row_counts(scalar, table, expected):
    n_rows, _, _ = expected
    assert scalar(f"SELECT count(*) FROM silver.{table}") == n_rows


@pytest.mark.parametrize("table,expected", SERIES.items())
def test_full_year_range_survives(rows, table, expected):
    """No inner join to the 2019-2024 intersection.

    Imposing sk-stat-4's floor on the others would silently discard 15
    years of tax history -- exactly the signal the spec wants kept.
    """
    _, first, last = expected
    assert rows(f"SELECT min(jahr), max(jahr) FROM silver.{table}") == [(first, last)]


@pytest.mark.parametrize("table", SERIES)
def test_bfs_nr_is_integer_everywhere(conn, table):
    """Bronze keys Gemeinde four different ways; silver keys it one way."""
    dtype = conn.exec_driver_sql(
        "SELECT data_type FROM information_schema.columns "
        f"WHERE table_schema = 'silver' AND table_name = '{table}' "
        "AND column_name = 'bfs_nr'"
    ).scalar()
    assert dtype == "integer"


def test_latest_year_differs_across_series(scalar):
    """Guards against a shared 'current year' constant creeping in."""
    steuerfuss = scalar("SELECT max(jahr) FROM silver.gemeinde_steuerfuss")
    finanzen = scalar("SELECT max(jahr) FROM silver.gemeinde_finanzkennzahlen")
    assert steuerfuss > finanzen
