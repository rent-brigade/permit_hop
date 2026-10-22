"""Restore the hopgraph database from the CSV dump in graph/data/dump/.

Run this after: starting your own local Postgres (pgserver_env/start_pg.py),
creating the hopgraph database, and applying schema.sql. See the README
note left alongside the zip for the full sequence.
"""

from pathlib import Path

import psycopg2

from .dump_tables import PGDATA, TABLE_COLUMNS

DUMP_DIR = Path(__file__).parent / "data" / "dump"


def main() -> None:
    conn = psycopg2.connect(host=PGDATA, dbname="hopgraph", user="postgres")
    cur = conn.cursor()
    for table, cols in TABLE_COLUMNS.items():
        col_clause = f"({', '.join(cols)})" if cols else ""
        path = DUMP_DIR / f"{table}.csv"
        with open(path) as f:
            cur.copy_expert(f"COPY {table}{col_clause} FROM STDIN WITH CSV", f)
        print(f"loaded {table}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
