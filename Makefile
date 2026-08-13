.PHONY: setup discover \
        landwertzonen bauzonen gemeindestats oereb \
        bronze-landwertzonen bronze-bauzonen bronze-gemeindestats bronze-oereb \
        bronze

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

bronze-oereb:
	uv run python -m propsearch_data.ingest.load_bronze_oereb

# Full refresh. OEREB is last because its parcel sample is drawn from
# bronze.landwertzonen, so that table must already be loaded.
bronze: landwertzonen bauzonen gemeindestats \
        bronze-landwertzonen bronze-bauzonen bronze-gemeindestats \
        oereb bronze-oereb
