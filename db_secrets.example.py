"""Template for db_secrets.py (which is gitignored). Copy this file to
db_secrets.py and fill in the real connection string for the source Neon
database that holds parcels_raw.
"""

NEON_CONN_STR = (
    "postgresql://<user>:<password>@"
    "<host>/<dbname>"
    "?sslmode=require&channel_binding=require"
)
