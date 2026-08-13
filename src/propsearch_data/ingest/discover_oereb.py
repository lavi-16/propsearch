"""
Pull ÖREB-Kataster extracts for a sample of test parcels per pilot
Gemeinde.

WHY A SAMPLE, NOT THE FULL PILOT AREA: the ÖREB webservice is a
per-parcel query -- one request per parcel, ~175 KB each, with no bulk
"all restrictions in this Gemeinde" call. Pulling all 7,296 Bauzonen
parcels in the pilot would be 7,296 requests and well over a gigabyte,
which is not a reasonable thing to do to a cantonal service for a POC.
PARCELS_PER_GEMEINDE keeps it to a handful; raise it deliberately.

Candidate parcels come from bronze.landwertzonen, which already holds
verified E-GRIDs -- so this needs no geocoding step and no guessing.
Selection is `ORDER BY gs_egris_egrid LIMIT n` per Gemeinde, which is
arbitrary but deterministic: re-running picks the same parcels, so the
sample is reproducible rather than shifting under you.

Restricted to the Bauzonen layer: `ms:Landwertzonen_Strasse` rows are
roads and similar, which are less interesting as due-diligence test cases.
"""

import json
from pathlib import Path

from sqlalchemy import text

from propsearch_data.db import get_engine
from propsearch_data.ingest import oereb

PILOT_BFS = {
    "Bottighofen": 4643,
    "Ermatingen": 4646,
    "Kreuzlingen": 4671,
    "Münsterlingen": 4691,
    "Tägerwilen": 4696,
}

PARCELS_PER_GEMEINDE = 5
SOURCE_LAYER = "ms:Landwertzonen_Bauz"

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "data" / "bronze"
OUTPUT_FILE = OUTPUT_DIR / "oereb_extracts_pilot.json"


def sample_egrids(n: int = PARCELS_PER_GEMEINDE) -> dict[int, list[str]]:
    """Deterministic per-Gemeinde parcel sample from bronze.landwertzonen."""
    sql = text(
        """
        SELECT gemcode, gs_egris_egrid
        FROM (
            SELECT gemcode, gs_egris_egrid,
                   row_number() OVER (PARTITION BY gemcode
                                      ORDER BY gs_egris_egrid) AS rn
            FROM bronze.landwertzonen
            WHERE _source_layer = :layer AND gemcode = ANY(:bfs)
        ) t
        WHERE rn <= :n
        ORDER BY gemcode, gs_egris_egrid
        """
    )
    out: dict[int, list[str]] = {}
    with get_engine().connect() as conn:
        rows = conn.execute(
            sql, {"layer": SOURCE_LAYER, "bfs": list(PILOT_BFS.values()), "n": n}
        ).all()
    for gemcode, egrid in rows:
        out.setdefault(gemcode, []).append(egrid)
    return out


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name_of = {v: k for k, v in PILOT_BFS.items()}

    print(f"ÖREB service topics available: {len(oereb.topics())}")
    sample = sample_egrids()
    total = sum(len(v) for v in sample.values())
    print(f"Sampling {PARCELS_PER_GEMEINDE} parcels x {len(sample)} Gemeinden "
          f"= {total} extracts\n")

    if len(sample) != len(PILOT_BFS):
        missing = set(PILOT_BFS.values()) - set(sample)
        raise RuntimeError(
            f"no candidate parcels for BFS {sorted(missing)} -- "
            "is bronze.landwertzonen loaded?"
        )

    documents, missed = [], []
    for gemcode, egrids in sample.items():
        print(f"{name_of[gemcode]} ({gemcode}):")
        docs, miss = oereb.extract_many(egrids)
        for doc in docs:
            documents.append({"_gemcode": gemcode, "extract": doc})
        missed.extend(miss)
        print()

    OUTPUT_FILE.write_text(
        json.dumps(documents, ensure_ascii=False), encoding="utf-8"
    )
    size_mb = OUTPUT_FILE.stat().st_size / 1e6
    print(f"[ok] {len(documents)}/{total} extracts -> {OUTPUT_FILE.name} "
          f"({size_mb:.1f} MB)")
    if missed:
        print(f"[warn] no extract for {len(missed)}: {', '.join(missed[:5])}")
