"""Filesystem locations shared by the pipeline, the local Postgres, and the
webapp. Everything is resolved relative to the repo root so the project runs
from any clone location; nothing here is user-specific.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Pipeline inputs/outputs: parcels_raw.parquet, clusters/edges/weak_links
# parquet, and the CSV dump of the serving tables (dump/). Gitignored.
DATA_DIR = REPO_ROOT / "data"
DUMP_DIR = DATA_DIR / "dump"

# Data directory of the embedded `pgserver` Postgres. Gitignored. Postgres also
# puts its unix socket here, which is why connections use host=PGDATA.
# Overridable because macOS caps unix-socket paths at ~104 chars, so a deeply
# nested checkout may need the cluster to live somewhere shorter.
PGDATA = Path(os.environ.get("HOPGRAPH_PGDATA", REPO_ROOT / "pgdata"))

DB_NAME = "hopgraph"

SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
