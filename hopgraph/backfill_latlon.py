"""One-off backfill: add latitude/longitude to the local `parcels` table.

center_lat/center_lon were deliberately excluded from the original ingest.py
column list (kept the export small; irrelevant to graph construction). This
pulls just those two columns plus ain -- a small, targeted export, not a
full pipeline re-run -- and updates the already-loaded serving table.
"""

import io

import psycopg2

from .db_secrets import NEON_CONN_STR as SOURCE_CONN_STR
from .paths import DB_NAME, PGDATA


def main() -> None:
    print("exporting ain/center_lat/center_lon from source...")
    buf = io.StringIO()
    with psycopg2.connect(SOURCE_CONN_STR) as src_conn:
        with src_conn.cursor() as cur:
            cur.copy_expert(
                "COPY (SELECT ain, center_lat, center_lon FROM neondb.public.parcels_raw) "
                "TO STDOUT WITH CSV",
                buf,
            )
    buf.seek(0)
    print(f"exported {buf.getvalue().count(chr(10))} rows")

    print("updating local parcels table...")
    local_conn = psycopg2.connect(host=str(PGDATA), dbname=DB_NAME, user="postgres")
    cur = local_conn.cursor()
    cur.execute("ALTER TABLE parcels ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
    cur.execute("ALTER TABLE parcels ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
    cur.execute(
        "CREATE TEMP TABLE latlon_staging (ain TEXT, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION)"
    )
    buf.seek(0)
    cur.copy_expert("COPY latlon_staging FROM STDIN WITH CSV", buf)
    cur.execute(
        """
        UPDATE parcels SET latitude = s.latitude, longitude = s.longitude
        FROM latlon_staging s WHERE parcels.ain = s.ain
        """
    )
    print(f"updated {cur.rowcount} rows")
    local_conn.commit()
    cur.close()
    local_conn.close()


if __name__ == "__main__":
    main()
