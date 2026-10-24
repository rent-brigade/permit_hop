"""The only module that talks to the parcel database.

Reads the `api` schema as `researcher_ro` through parcel_query (connection string from
DB_CONNECTION_STRING in the environment or a .env file). The database has already cleaned
the owners: `owner_key` is the dedupe key, `owner_type` classifies them, and the mailing
address is keyed. This module only selects.
"""

import json
from pathlib import Path

import pandas as pd
from parcel_cleaning import CLEANING_VERSION
from parcel_query import connect as _connect
from parcel_query import run_sql

from . import config

# Owners per request. owner_summary aggregates each owner's parcels, so a single full scan
# can pass the role's 30 s statement timeout; keyset pages stay short. Unverified at full
# scale: time it and adjust.
PAGE_SIZE = 20_000
STATEMENT_TIMEOUT_S = 120

_OWNER_PAGE = """
SELECT owner_key, owner_key_bin, owner_full_name, owner_type,
       mail_building_address_key AS mail_key,
       CASE WHEN special_name_legend = %s THEN special_name_assessee END AS contact,
       active_parcel_count AS parcel_count, total_units
FROM api.owner_summary
WHERE owner_type <> 'public' AND active_parcel_count > 0
  AND (%s::bytea IS NULL OR owner_key_bin > %s::bytea)
ORDER BY owner_key_bin
LIMIT %s
"""


def connect():
    return _connect(statement_timeout_s=STATEMENT_TIMEOUT_S)


def fetch_owners(conn, *, page_size: int = PAGE_SIZE) -> pd.DataFrame:
    """Every private owner with an active parcel, in keyset pages ordered by owner_key_bin
    (the unique index). Columns: owner_key, owner_full_name, owner_type, mail_key, contact,
    parcel_count, total_units."""
    pages, after = [], None
    while True:
        page = run_sql(
            conn,
            _OWNER_PAGE,
            (config.CONTACT_LEGEND, after, after, page_size),
            limit=None,
        )
        if page.empty:
            break
        pages.append(page.drop(columns="owner_key_bin"))
        after = bytes(page["owner_key_bin"].iloc[-1])
        if len(page) < page_size:
            break
    if not pages:
        return pd.DataFrame(
            columns=["owner_key", "owner_full_name", "owner_type", "mail_key", "contact",
                     "parcel_count", "total_units"]
        )
    return pd.concat(pages, ignore_index=True)


def fetch_parcels(conn, owner_keys: list[str]) -> pd.DataFrame:
    """Parcels of the given owners, through the parcel_owner index (owner_key_bin)."""
    return run_sql(
        conn,
        """
        SELECT ain, owner_key, situs_address_full AS situs_address, latitude, longitude
        FROM api.parcel_wide
        WHERE is_active AND owner_key_bin = ANY(ARRAY(
            SELECT decode(k, 'hex') FROM unnest(%s::text[]) AS k))
        ORDER BY situs_address_full
        """,
        (owner_keys,),
        limit=None,
    )


def fetch_owner_details(conn, owner_keys: list[str]) -> pd.DataFrame:
    """Names and types for the given owners, through the unique owner_key index."""
    return run_sql(
        conn,
        """
        SELECT owner_key, owner_full_name, owner_type, parcel_count
        FROM api.owner_summary
        WHERE owner_key_bin = ANY(ARRAY(
            SELECT decode(k, 'hex') FROM unnest(%s::text[]) AS k))
        ORDER BY owner_full_name
        """,
        (owner_keys,),
        limit=None,
    )


def write_meta(conn, data_dir: Path) -> None:
    """Record which run and cleaning version the cached parquet files came from."""
    run = run_sql(conn, "SELECT run_id, dump_date, cleaning_version FROM api.current_run")
    meta = {
        "run_id": int(run["run_id"].iloc[0]),
        "dump_date": str(run["dump_date"].iloc[0]),
        "db_cleaning_version": run["cleaning_version"].iloc[0],
        "installed_cleaning_version": CLEANING_VERSION,
    }
    (data_dir / "meta.json").write_text(json.dumps(meta, indent=2))


def read_meta(data_dir: Path) -> dict:
    return json.loads((data_dir / "meta.json").read_text())
