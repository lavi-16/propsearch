.PHONY: setup discover \
        landwertzonen bauzonen gemeindestats bodenpreise gefahrenkarte gwr sonnendach laerm oereb \
        bronze-landwertzonen bronze-bauzonen bronze-gemeindestats \
        bronze-bodenpreise bronze-gefahrenkarte bronze-gwr bronze-sonnendach bronze-laerm bronze-oereb \
        bronze silver gold test

setup:
	uv sync

discover:
	uv run python src/propsearch_data/ingest/discover_capabilities.py

# --- pull from source -> data/bronze/ ---
landwertzonen:
	uv run python -m propsearch_data.ingest.discover_landwertzonen

bauzonen:
	uv run python -m propsearch_data.ingest.discover_bauzonen

gemeindestats:
	uv run python -m propsearch_data.ingest.discover_gemeindestats

bodenpreise:
	uv run python -m propsearch_data.ingest.discover_bodenpreise

gefahrenkarte:
	uv run python -m propsearch_data.ingest.discover_gefahrenkarte

# Federal GWR via the BFS MADD bulk download (~35 MB zip, cached in
# data/bronze/). Not a WFS and not data.tg.ch -- see ingest/madd.py.
gwr:
	uv run python -m propsearch_data.ingest.discover_gwr

# Roof solar potential (Sonnendach) via the federal BGDI bulk GeoPackage
# (~1.5 GB zip -> 4.58 GB member, cached in data/bronze/). Not the
# api3.geo.admin.ch REST route, which cannot produce a complete slice --
# see ingest/bgdi.py.
sonnendach:
	uv run python -m propsearch_data.ingest.discover_sonnendach

# SonBase / BAFU noise via the federal BGDI/STAC route. Road (day+night) is a
# Cloud-Optimized GeoTIFF read through a windowed /vsicurl/ clip; rail is the
# BAV vector cadastre. See ingest/discover_laerm.py.
laerm:
	uv run python -m propsearch_data.ingest.discover_laerm

# depends on bronze.landwertzonen for its parcel sample
oereb:
	uv run python -m propsearch_data.ingest.discover_oereb

# --- load data/bronze/ -> Postgres bronze.* ---
bronze-landwertzonen:
	uv run python -m propsearch_data.ingest.load_bronze_landwertzonen

bronze-bauzonen:
	uv run python -m propsearch_data.ingest.load_bronze_bauzonen

bronze-gemeindestats:
	uv run python -m propsearch_data.ingest.load_bronze_gemeindestats

bronze-bodenpreise:
	uv run python -m propsearch_data.ingest.load_bronze_bodenpreise

bronze-gefahrenkarte:
	uv run python -m propsearch_data.ingest.load_bronze_gefahrenkarte

bronze-gwr:
	uv run python -m propsearch_data.ingest.load_bronze_gwr

bronze-sonnendach:
	uv run python -m propsearch_data.ingest.load_bronze_sonnendach

# Road noise is sampled at building points, so bronze.gwr_gebaeude must be
# loaded first (see the bronze target ordering below).
bronze-laerm:
	uv run python -m propsearch_data.ingest.load_bronze_laerm

bronze-oereb:
	uv run python -m propsearch_data.ingest.load_bronze_oereb

# Full refresh. bronze-laerm follows bronze-gwr because road noise is sampled
# at bronze.gwr_gebaeude building points. OEREB is last because its parcel
# sample is drawn from bronze.landwertzonen, so that table must already be loaded.
bronze: landwertzonen bauzonen gemeindestats bodenpreise gefahrenkarte gwr sonnendach laerm \
        bronze-landwertzonen bronze-bauzonen bronze-gemeindestats \
        bronze-bodenpreise bronze-gefahrenkarte bronze-gwr bronze-sonnendach bronze-laerm \
        oereb bronze-oereb

# --- bronze -> silver ---
# Full rebuild: every table is dropped and recreated from bronze. Pure
# database-to-database, so no data/ pull is needed first.
silver:
	uv run python -m propsearch_data.transform.silver

# --- silver -> gold ---
# Full rebuild from silver. Never reads bronze, so `silver` must be current.
gold:
	uv run python -m propsearch_data.transform.gold

# Read-only assertions against the built silver and gold tables.
# Run after `silver` and `gold`.
test:
	uv run pytest -q
