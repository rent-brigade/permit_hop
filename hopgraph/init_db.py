"""Create the serving database and apply schema.sql. Safe to re-run: the
database is only created if missing, and schema.sql is all IF NOT EXISTS.

Starts the embedded Postgres first if it isn't already running, so on a fresh
clone this is the one setup step before restore_dump.py or load.py:
    uv run python -m hopgraph.init_db
"""

import psycopg2

from .paths import DB_NAME, PGDATA, SCHEMA_SQL
from .start_pg import start


def main() -> None:
    start()

    conn = psycopg2.connect(host=str(PGDATA), dbname="postgres", user="postgres")
    conn.autocommit = True  # CREATE DATABASE can't run inside a transaction
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    if cur.fetchone() is None:
        cur.execute(f"CREATE DATABASE {DB_NAME}")
        print(f"created database {DB_NAME}")
    conn.close()

    conn = psycopg2.connect(host=str(PGDATA), dbname=DB_NAME, user="postgres")
    with conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text())
    conn.close()
    print(f"applied {SCHEMA_SQL.name}")


if __name__ == "__main__":
    main()
