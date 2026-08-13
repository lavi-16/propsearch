.PHONY: setup discover

setup:
	uv sync

discover:
	uv run python src/propsearch_data/ingest/discover_capabilities.py
