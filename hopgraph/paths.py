"""Where the cached graph output lives. Resolved from the repo root, so it runs from any clone."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# clusters / edges / weak_links parquet and meta.json from build_graph. Gitignored.
DATA_DIR = REPO_ROOT / "data"
