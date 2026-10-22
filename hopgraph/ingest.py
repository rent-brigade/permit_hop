"""One-time (or manually-refreshed) bulk export from the live parcels_raw table.

This is the only module in the pipeline that touches the database. Everything
downstream (normalize.py, build_graph.py, annotate.py) reads the local parquet
cache this produces.

Usage:
    uv run python -m hopgraph.ingest --count-only   # cheap sanity check first
    uv run python -m hopgraph.ingest                # full bulk export

No geographic filter -- full county table, per project decision (see plan).
Column list is pruned to only what the ownership graph needs: no geometry,
no bd1-bd5 building characteristics, no legal-description lines -- those are
the majority of bytes per row in the full table and are irrelevant to entity
resolution.
"""

import argparse
import sys
import psycopg2

from .db_secrets import NEON_CONN_STR as CONN_STR
from .paths import DATA_DIR

# Actual column names in parcels_raw contain spaces, so each needs double-quoting
# in the SQL. Keep this list in sync with what normalize.py expects.
COLUMNS = [
    "ain",
    "tra",
    "situs house no",
    "fraction",
    "direction",
    "street name",
    "unit",
    "city state",
    "zip",
    "mail house no",
    "m fraction",
    "m direction",
    "m street name",
    "m unit",
    "m city state",
    "m zip",
    "first owner name",
    "first owner name overflow",
    "special name legend",
    "special name assessee",
    "second owner name",
    "recording date",
    "ownership code",
    "use code",
    "doc reason code",
    "last sale amount",
    "last sale date",
    "sale two amount",
    "sale two date",
    "sale three amount",
    "sale three date",
    "landlord reappraisal year",
    "landlord units",
    "document key",
    "document number",
]

CSV_PATH = DATA_DIR / "parcels_raw.csv"
PARQUET_PATH = DATA_DIR / "parcels_raw.parquet"


def quoted_columns() -> str:
    return ", ".join(f'"{c}"' for c in COLUMNS)


def count_only() -> int:
    with psycopg2.connect(CONN_STR) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM neondb.public.parcels_raw;")
            (n,) = cur.fetchone()
    return n


def bulk_export() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    copy_sql = (
        f"COPY (SELECT {quoted_columns()} FROM neondb.public.parcels_raw) "
        "TO STDOUT WITH CSV HEADER"
    )
    with psycopg2.connect(CONN_STR) as conn:
        with conn.cursor() as cur, open(CSV_PATH, "w", newline="") as f:
            cur.copy_expert(copy_sql, f)

    # Convert to parquet for fast repeated local loads. Read back with pandas
    # for the dtype/quoting handling rather than re-deriving a CSV->parquet
    # converter; this table is small enough post column-pruning that a single
    # pandas pass is fine even at county scale.
    import pandas as pd

    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False, low_memory=False)
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"Wrote {len(df)} rows to {PARQUET_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--count-only",
        action="store_true",
        help="Run the cheap SELECT COUNT(*) sanity check and exit, without pulling data.",
    )
    args = parser.parse_args()

    if args.count_only:
        n = count_only()
        print(f"parcels_raw row count: {n}")
        return

    bulk_export()


if __name__ == "__main__":
    sys.exit(main())
