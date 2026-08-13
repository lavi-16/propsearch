"""
Shared fixtures for the silver assertions.

These tests are READ-ONLY and run against whatever `make silver` last
built -- there is no fixture data and nothing is torn down. That is
deliberate: the thing worth testing is the real pilot slice, not a
synthetic miniature of it. Run `make silver` first.

Most of the invariants that CAN be expressed as a constraint already are
one, and fail at build time (see sql/schema/silver/00_schema.sql). What
lives here is the layer constraints cannot reach: row counts, coverage
ratios, distributions, and cross-source agreement.
"""

import pytest
from sqlalchemy import text

from propsearch_data.db import get_engine


@pytest.fixture(scope="session")
def engine():
    return get_engine()


@pytest.fixture(scope="session")
def conn(engine):
    with engine.connect() as connection:
        yield connection


@pytest.fixture(scope="session")
def scalar(conn):
    """Run a single-value query. Keeps the assertions to one line each."""

    def _scalar(sql: str):
        return conn.execute(text(sql)).scalar()

    return _scalar


@pytest.fixture(scope="session")
def rows(conn):
    def _rows(sql: str):
        return conn.execute(text(sql)).all()

    return _rows
