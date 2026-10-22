"""Load the batch pipeline's outputs into the local serving Postgres.

This is the last step of the pipeline: it does NOT recompute anything --
normalize.py/build_graph.py/annotate.py already produced clusters.parquet,
edges.parquet, and weak_links.parquet (see build_graph.py's main()).
This script reads those, plus the normalized parcel-level data, and bulk-
writes them into the `hopgraph` database (paths.PGDATA), replacing
its contents inside one transaction so the API is never caught mid-refresh.

Requires the database to exist first (uv run python -m hopgraph.init_db),
then:
    uv run python -m hopgraph.load
"""

import io
from datetime import datetime, timezone
import pandas as pd
import psycopg2

from . import annotate, normalize
from .paths import DATA_DIR, DB_NAME, PGDATA


def build_situs_address(row: pd.Series) -> str:
    parts = [
        str(row.get("situs house no") or "").strip(),
        str(row.get("direction") or "").strip(),
        str(row.get("street name") or "").strip(),
        str(row.get("unit") or "").strip(),
        str(row.get("city state") or "").strip(),
    ]
    return " ".join(p for p in parts if p and p != "0")


def copy_df(cur, df: pd.DataFrame, table: str, columns: list[str]) -> None:
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(
        f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH CSV NULL '\\N'", buf
    )


def main() -> None:
    conn = psycopg2.connect(host=str(PGDATA), dbname=DB_NAME, user="postgres")
    cur = conn.cursor()

    started_at = datetime.now(timezone.utc)

    print("loading parquet outputs...")
    clusters = pd.read_parquet(DATA_DIR / "clusters.parquet")
    edges = pd.read_parquet(DATA_DIR / "edges.parquet")
    weak_links = pd.read_parquet(DATA_DIR / "weak_links.parquet")

    raw = pd.read_parquet(DATA_DIR / "parcels_raw.parquet")
    source_row_count = len(raw)
    df = normalize.normalize(raw)
    df = annotate.add_self_transfer_flag(df)
    df["situs_address"] = df.apply(build_situs_address, axis=1)

    # ain -> cluster_id, by exploding clusters.ains (inverse of clusters.parquet's
    # cluster -> [ains] shape). Parcels excluded from graph construction
    # (government/financial-services rows) simply have no entry here.
    ain_cluster = clusters[["cluster_id", "ains"]].explode("ains").rename(columns={"ains": "ain"})
    df = df.merge(ain_cluster, on="ain", how="left")

    # entities table: one row per distinct owner_name_norm actually present
    # in a cluster (i.e. survived the government/financial-services filter).
    cluster_members = clusters[["cluster_id", "owner_names"]].explode("owner_names").rename(
        columns={"owner_names": "owner_name_norm"}
    )
    entity_type_by_name = df.drop_duplicates("owner_name_norm").set_index("owner_name_norm")[
        "owner_entity_type"
    ]
    n_parcels_by_name = df.groupby("owner_name_norm")["ain"].count()
    entities = cluster_members.copy()
    entities["entity_type"] = entities["owner_name_norm"].map(entity_type_by_name)
    entities["n_parcels"] = entities["owner_name_norm"].map(n_parcels_by_name).fillna(0).astype(int)

    print(f"clusters={len(clusters)} parcels={len(df)} entities={len(entities)} "
          f"edges={len(edges)} weak_links={len(weak_links)}")

    print("writing to Postgres...")
    try:
        cur.execute(
            "INSERT INTO pipeline_runs (started_at, source_row_count, status) "
            "VALUES (%s, %s, 'running') RETURNING id",
            (started_at, source_row_count),
        )
        (run_id,) = cur.fetchone()

        # Clear existing data (single-database truncate-and-reload; see the
        # plan for the caveat that a true zero-downtime blue-green swap would
        # need parallel table sets instead -- not needed for a local/dev DB).
        cur.execute(
            "TRUNCATE parcels, entities, cluster_members, edges, weak_links, clusters "
            "RESTART IDENTITY CASCADE"
        )

        clusters_out = clusters.copy()
        clusters_out["pipeline_run_id"] = run_id
        copy_df(
            cur, clusters_out, "clusters",
            ["cluster_id", "tier", "n_distinct_owner_names", "n_parcels",
             "total_landlord_units", "possible_self_transfer_count", "pipeline_run_id"],
        )

        copy_df(cur, cluster_members, "cluster_members", ["cluster_id", "owner_name_norm"])
        copy_df(cur, entities, "entities", ["owner_name_norm", "entity_type", "cluster_id", "n_parcels"])

        parcels_out = df.copy()
        parcels_out["cluster_id"] = parcels_out["cluster_id"].astype("Int64")
        copy_df(
            cur, parcels_out, "parcels",
            ["ain", "situs_address", "owner_name_norm", "owner_entity_type",
             "cluster_id", "possible_self_transfer"],
        )

        edges_out = edges.rename(columns={"owner_name": "owner_name_norm"})
        copy_df(cur, edges_out, "edges", ["owner_name_norm", "key_type", "key_value", "is_person"])

        weak_out = weak_links.copy()
        weak_out["owner_names"] = weak_out["owner_names"].apply(
            lambda names: "{" + ",".join('"' + n.replace('"', '\\"') + '"' for n in names) + "}"
        )
        copy_df(cur, weak_out, "weak_links", ["key_type", "key_value", "degree", "owner_names"])

        cur.execute(
            "UPDATE pipeline_runs SET finished_at = %s, status = 'complete' WHERE id = %s",
            (datetime.now(timezone.utc), run_id),
        )
        conn.commit()
        print(f"done, pipeline_run_id={run_id}")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
