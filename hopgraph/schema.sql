-- Serving schema for the ownership hop-graph app. Applied by init_db.py;
-- populated by load.py (or restore_dump.py) from
-- the batch pipeline's outputs (clusters.parquet / edges.parquet /
-- weak_links.parquet / normalized parcels_raw.parquet). The Flask API only
-- ever reads from these tables -- see the plan for why graph construction
-- itself stays a batch job, not a live computation.
--
-- Search uses built-in full-text search (tsvector + GIN), not pg_trgm:
-- this local setup runs on the `pgserver` embedded Postgres distribution
-- (hopgraph/start_pg.py), which only bundles plpgsql and pgvector -- no
-- contrib extensions. tsvector needs no extension and handles word-prefix
-- autocomplete fine; the tradeoff is it won't match an arbitrary mid-word
-- substring the way pg_trgm ILIKE would. A production deployment on a full
-- Postgres install could add pg_trgm for that if it turns out to matter.
-- 'simple' config is used deliberately (not 'english') to avoid stemming
-- mangling addresses and proper names.

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    source_row_count INTEGER,
    status TEXT NOT NULL DEFAULT 'running'  -- running | complete | failed
);

CREATE TABLE IF NOT EXISTS clusters (
    cluster_id INTEGER PRIMARY KEY,
    tier TEXT NOT NULL,
    n_distinct_owner_names INTEGER NOT NULL,
    n_parcels INTEGER NOT NULL,
    total_landlord_units DOUBLE PRECISION,
    possible_self_transfer_count INTEGER NOT NULL,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES clusters(cluster_id),
    owner_name_norm TEXT NOT NULL,
    PRIMARY KEY (cluster_id, owner_name_norm)
);
CREATE INDEX IF NOT EXISTS idx_cluster_members_owner ON cluster_members (owner_name_norm);

CREATE TABLE IF NOT EXISTS entities (
    owner_name_norm TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    cluster_id INTEGER REFERENCES clusters(cluster_id),
    n_parcels INTEGER NOT NULL,
    name_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', owner_name_norm)) STORED
);
CREATE INDEX IF NOT EXISTS idx_entities_name_tsv ON entities USING GIN (name_tsv);

CREATE TABLE IF NOT EXISTS parcels (
    ain TEXT PRIMARY KEY,
    situs_address TEXT NOT NULL,
    owner_name_norm TEXT NOT NULL,
    owner_entity_type TEXT NOT NULL,
    cluster_id INTEGER REFERENCES clusters(cluster_id),
    possible_self_transfer BOOLEAN NOT NULL DEFAULT FALSE,
    -- Filled in after load.py by backfill_latlon.py (not in the parquet outputs).
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    addr_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', situs_address)) STORED
);
CREATE INDEX IF NOT EXISTS idx_parcels_addr_tsv ON parcels USING GIN (addr_tsv);
CREATE INDEX IF NOT EXISTS idx_parcels_owner ON parcels (owner_name_norm);
CREATE INDEX IF NOT EXISTS idx_parcels_cluster ON parcels (cluster_id);

CREATE TABLE IF NOT EXISTS edges (
    id SERIAL PRIMARY KEY,
    owner_name_norm TEXT NOT NULL,
    key_type TEXT NOT NULL,     -- 'address' | 'contact'
    key_value TEXT NOT NULL,
    is_person BOOLEAN
);
CREATE INDEX IF NOT EXISTS idx_edges_owner ON edges (owner_name_norm);
CREATE INDEX IF NOT EXISTS idx_edges_key ON edges (key_type, key_value);

CREATE TABLE IF NOT EXISTS weak_links (
    id SERIAL PRIMARY KEY,
    key_type TEXT NOT NULL,
    key_value TEXT NOT NULL,
    degree INTEGER NOT NULL,
    owner_names TEXT[] NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_weak_links_key ON weak_links (key_type, key_value);
