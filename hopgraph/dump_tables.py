"""Export the live hopgraph tables to local CSV files, as a pg_dump
substitute -- the bundled pg_dump binary is blocked by this session's
sandbox (external binaries can't open the unix socket; psycopg2 can,
since it runs in-process). Captures current state, including the lat/lon
backfill that happened after the original parquet exports.

Restore with restore_dump.py.
"""

import psycopg2

from .paths import DB_NAME, DUMP_DIR, PGDATA

# Explicit column lists for tables with a GENERATED ALWAYS ... STORED column
# (name_tsv, addr_tsv) -- those can't be COPY FROM'd back in on restore, so
# they're excluded here too, on both sides, to keep dump/restore symmetric.
# Ordered so restore_dump.py can load them straight through respecting FKs
# (pipeline_runs -> clusters -> {cluster_members, entities, parcels} -> edges/weak_links).
TABLE_COLUMNS = {
    "pipeline_runs": None,
    "clusters": None,
    "cluster_members": None,
    "entities": ["owner_name_norm", "entity_type", "cluster_id", "n_parcels"],
    "parcels": [
        "ain", "situs_address", "owner_name_norm", "owner_entity_type",
        "cluster_id", "possible_self_transfer", "latitude", "longitude",
    ],
    "edges": None,
    "weak_links": None,
}


def main() -> None:
    DUMP_DIR.mkdir(parents=True, exist_ok=True)
    conn = psycopg2.connect(host=str(PGDATA), dbname=DB_NAME, user="postgres")
    cur = conn.cursor()
    for table, cols in TABLE_COLUMNS.items():
        col_clause = f"({', '.join(cols)})" if cols else ""
        path = DUMP_DIR / f"{table}.csv"
        with open(path, "w") as f:
            cur.copy_expert(f"COPY {table}{col_clause} TO STDOUT WITH CSV", f)
        print(f"{table}: {path.stat().st_size / 1e6:.2f} MB")
    conn.close()


if __name__ == "__main__":
    main()
