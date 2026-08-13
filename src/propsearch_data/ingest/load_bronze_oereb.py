"""
Load the ÖREB extracts into `bronze.oereb_extract` (+ a mechanical unnest
into `bronze.oereb_restriction`).

See propsearch_data.bronze for the bronze contract this follows.

TWO TABLES, and the second is derivable from the first:

  bronze.oereb_extract      one row per parcel. The COMPLETE extract
                            document is kept verbatim in a `jsonb`
                            column. Identity fields (egrid, identdn,
                            number, municipality, ...) are lifted into
                            real columns purely so the table is queryable
                            and joinable -- they are copies, not
                            replacements, and nothing is dropped.

  bronze.oereb_restriction  one row per (parcel, restriction), unnested
                            from RealEstate.RestrictionOnLandownership,
                            with each restriction's own JSON retained.

The unnest is STRUCTURAL, NOT SEMANTIC: it flattens a nested array into
rows and interprets nothing. It exists because a 175 KB nested document
per parcel is otherwise unqueryable, which would make the Restrictions
layer useless to check the gold design against. It is fully reproducible
from `bronze.oereb_extract` alone, so if you consider it a step too far
for bronze, drop the table -- no information is lost.

NOT done here: mapping themes to a restriction taxonomy, resolving
Lawstatus, deciding which themes matter for buildability, or joining to
parcels. Those are gold decisions.
"""

import json

import pandas as pd
from sqlalchemy.dialects.postgresql import JSONB

from propsearch_data import bronze
from propsearch_data.ingest.discover_oereb import OUTPUT_FILE, PILOT_BFS
from propsearch_data.ingest.oereb import BASE

EXTRACT_TABLE = "oereb_extract"
RESTRICTION_TABLE = "oereb_restriction"
SOURCE_LAYER = "GetExtractById"


def _first_text(node) -> str | None:
    """Pull the German label out of the spec's repeated multilingual Text[]."""
    if not isinstance(node, dict):
        return None
    texts = node.get("Text") or []
    if isinstance(texts, dict):
        texts = [texts]
    for t in texts:
        if t.get("Language") == "de":
            return t.get("Text")
    return texts[0].get("Text") if texts else None


def read_pull() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not OUTPUT_FILE.exists():
        raise FileNotFoundError(
            f"{OUTPUT_FILE} missing -- run discover_oereb.py first"
        )
    payload = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    print(f"  read {len(payload):>5} extracts from {OUTPUT_FILE.name}")

    extract_rows, restriction_rows = [], []
    for item in payload:
        doc = item["extract"]["GetExtractByIdResponse"]["extract"]
        estate = doc["RealEstate"]
        egrid = estate.get("EGRID")

        extract_rows.append(
            {
                "egrid": egrid,
                "identdn": estate.get("IdentDN"),
                "number": estate.get("Number"),
                "municipality_name": estate.get("MunicipalityName"),
                "municipality_code": estate.get("MunicipalityCode"),
                "gemcode": item["_gemcode"],
                "land_registry_area": estate.get("LandRegistryArea"),
                "realestate_type": _first_text(estate.get("Type")),
                "creation_date": doc.get("CreationDate"),
                "extract_identifier": doc.get("ExtractIdentifier"),
                "n_concerned_theme": len(doc.get("ConcernedTheme") or []),
                "n_not_concerned_theme": len(doc.get("NotConcernedTheme") or []),
                "n_theme_without_data": len(doc.get("ThemeWithoutData") or []),
                # Pass the dict itself, NOT json.dumps(...). SQLAlchemy's
                # JSONB type serialises it; handing it a pre-encoded string
                # stores a JSON *string* scalar instead of an object, and
                # every `->` lookup then silently returns NULL.
                "extract": doc,
            }
        )

        for idx, r in enumerate(estate.get("RestrictionOnLandownership") or []):
            restriction_rows.append(
                {
                    "egrid": egrid,
                    "gemcode": item["_gemcode"],
                    "restriction_index": idx,
                    "theme_code": (r.get("Theme") or {}).get("Code"),
                    "theme_text": _first_text(r.get("Theme")),
                    "type_code": r.get("TypeCode"),
                    "legend_text": _first_text({"Text": r.get("LegendText")})
                    if isinstance(r.get("LegendText"), list)
                    else r.get("LegendText"),
                    "lawstatus": _first_text(r.get("Lawstatus")),
                    "area_share": r.get("AreaShare"),
                    "part_in_percent": r.get("PartInPercent"),
                    "restriction": r,
                }
            )

    return pd.DataFrame(extract_rows), pd.DataFrame(restriction_rows)


if __name__ == "__main__":
    print("Reading ÖREB pull from data/bronze/ ...")
    extracts, restrictions = read_pull()

    src = f"{BASE}/extract/json/"
    extracts = bronze.tag_provenance(
        extracts, SOURCE_LAYER, src, OUTPUT_FILE.name
    )
    restrictions = bronze.tag_provenance(
        restrictions, SOURCE_LAYER, src, OUTPUT_FILE.name
    )

    name_of = {v: k for k, v in PILOT_BFS.items()}

    print(f"\nLoading {len(extracts)} rows into {bronze.SCHEMA}.{EXTRACT_TABLE} ...")
    bronze.load_table(
        extracts,
        EXTRACT_TABLE,
        index_columns=["egrid", "gemcode"],
        dtype={"extract": JSONB},
    )
    bronze.summarise_table(EXTRACT_TABLE, group_by="gemcode", label_map=name_of)

    print(
        f"\nLoading {len(restrictions)} rows into "
        f"{bronze.SCHEMA}.{RESTRICTION_TABLE} ..."
    )
    bronze.load_table(
        restrictions,
        RESTRICTION_TABLE,
        index_columns=["egrid", "theme_code"],
        dtype={"restriction": JSONB},
    )
    bronze.summarise_table(
        RESTRICTION_TABLE, group_by="theme_code"
    )
