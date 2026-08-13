"""
Database connection helper.

Two Supabase gotchas are handled here, both confirmed on this project
(2026-08-13), so callers don't have to rediscover them:

1. SQLAlchemy maps a bare `postgresql://` URL to the psycopg2 driver, but
   this project depends on psycopg 3. We rewrite the scheme to
   `postgresql+psycopg://`.

2. Supabase's *direct* host `db.<ref>.supabase.co` is IPv6-only. Anywhere
   without IPv6 egress (this WSL setup, most CI) cannot reach it at all --
   it fails as "Network is unreachable". The IPv4 route is the Supavisor
   pooler, `aws-0-<region>.pooler.supabase.com`, with the username
   `postgres.<project-ref>`.

   Note `<ref>.supabase.co` *without* the `db.` prefix is the Cloudflare-
   fronted REST endpoint, not Postgres -- pointing DATABASE_URL there
   times out on port 5432.

Use pooler port 5432 (session mode) rather than 6543 (transaction mode):
transaction mode does not support prepared statements, which SQLAlchemy
and psycopg use by default for bulk loads.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

# Anchored to the repo root rather than the cwd: bare load_dotenv() only
# searches upward from the working directory, so running a script from
# anywhere else silently finds no .env and fails as "DATABASE_URL is not set".
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _normalise(url: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def get_engine(echo: bool = False) -> Engine:
    """Engine built from DATABASE_URL in the environment or .env."""
    load_dotenv(ENV_PATH if ENV_PATH.exists() else None)
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (copy .env.example to .env)")
    return create_engine(_normalise(url), echo=echo, pool_pre_ping=True)
