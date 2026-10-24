"""Build owner networks: a bipartite graph of owners and the keys they share.

Input is one row per owner as the parcel database already cleaned it (see
source.fetch_owners): `owner_key` (the node), `owner_full_name`, `owner_type`,
`mail_key` (building mailing address) and `contact` (care-of name). Nothing is
cleaned here.

Owner nodes link through key nodes: a shared mailing building ("address") or a shared
care-of contact ("contact"). A key shared by more than HUB_DEGREE_THRESHOLD distinct
owners is a hub (a property manager, registered agent or institutional department):
it is recorded as a weak link and kept out of the graph, the main defense against
false hops. Connected components of what remains are candidate networks. They are
evidence for a researcher, not a finding of common ownership.
"""

import hashlib
import re

import networkx as nx
import pandas as pd

from . import config

OWNER_COLUMNS = ["owner_key", "owner_full_name", "owner_type", "mail_key", "contact"]


def clean_contact(value) -> str | None:
    """Strip a leading C/O and tidy spacing; empty becomes None. A light match on the
    care-of text, not a cleaning step: the database stores the field as the assessor gave it."""
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"^\s*C\s*/\s*O\b\.?", "", str(value).upper())
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def is_person_contact(contact: str) -> bool:
    return re.search(config.COMPANY_KEYWORDS, contact) is None


def exclude_financial(owners: pd.DataFrame) -> pd.DataFrame:
    """Drop mortgage servicers and securitization trustees (config.FINANCIAL_SERVICES_PATTERN).
    The database classifies public owners (owner_type = 'public') but not these."""
    mask = owners["owner_full_name"].fillna("").str.contains(
        config.FINANCIAL_SERVICES_PATTERN, regex=True
    )
    return owners[~mask]


def _key_groups(
    owners: pd.DataFrame, key_col: str
) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """Group owners by a non-null key, split into surviving (non-hub) and hub keys.

    A key held by one owner links nothing and is dropped. Degree is the number of
    distinct owners, not parcels.
    """
    sub = owners[[key_col, "owner_key"]].dropna(subset=[key_col])
    grouped = sub.groupby(key_col)["owner_key"].apply(set)

    surviving: dict[str, set[str]] = {}
    hub: dict[str, dict] = {}
    for key_value, members in grouped.items():
        if len(members) < 2:
            continue
        if len(members) > config.HUB_DEGREE_THRESHOLD:
            hub[key_value] = {"degree": len(members), "owner_keys": sorted(members)}
        else:
            surviving[key_value] = members
    return surviving, hub


def build_graph(owners: pd.DataFrame):
    """(graph, address_hubs, contact_hubs). Owner nodes are `owner_key` strings; key nodes
    are ("address", mail_key) and ("contact", name) tuples."""
    owners = owners.copy()
    owners["contact"] = owners["contact"].map(clean_contact)

    address_survive, address_hub = _key_groups(owners, "mail_key")
    contact_survive, contact_hub = _key_groups(owners, "contact")

    G = nx.Graph()
    G.add_nodes_from(owners["owner_key"].unique(), kind="owner")

    for key_value, members in address_survive.items():
        node = ("address", key_value)
        G.add_node(node, kind="address", key_value=key_value)
        for owner_key in members:
            G.add_edge(node, owner_key, key_type="address")

    for key_value, members in contact_survive.items():
        node = ("contact", key_value)
        is_person = is_person_contact(key_value)
        G.add_node(node, kind="contact", key_value=key_value, is_person=is_person)
        for owner_key in members:
            G.add_edge(node, owner_key, key_type="contact", is_person=is_person)

    return G, address_hub, contact_hub


def cluster_id_for(owner_keys: list[str]) -> str:
    """A stable id from the sorted member keys, so the same network keeps its id across runs."""
    digest = hashlib.sha1("|".join(sorted(owner_keys)).encode()).hexdigest()
    return digest[:12]


def _cluster_tier(G: nx.Graph, component: set) -> str:
    """tier1: an address key and a person-contact key. tier2: any other linking key.
    single: no linking key. oversized_needs_review: more than MAX_PLAUSIBLE_CLUSTER_SIZE
    owners, unless it holds a key in VERIFIED_LARGE_CLUSTER_EXCEPTIONS (see config for why
    size alone cannot separate a real portfolio from shared-vendor chaining)."""
    owner_nodes = [n for n in component if isinstance(n, str)]
    key_nodes = [n for n in component if isinstance(n, tuple)]

    is_verified = any(n in config.VERIFIED_LARGE_CLUSTER_EXCEPTIONS for n in key_nodes)
    if not is_verified and len(owner_nodes) > config.MAX_PLAUSIBLE_CLUSTER_SIZE:
        return "oversized_needs_review"

    if not key_nodes:
        return "single"
    has_address = any(n[0] == "address" for n in key_nodes)
    has_person_contact = any(
        n[0] == "contact" and G.nodes[n].get("is_person") for n in key_nodes
    )
    if has_address and has_person_contact:
        return "tier1"
    return "tier2"


def extract_clusters(G: nx.Graph, owners: pd.DataFrame) -> pd.DataFrame:
    """One row per connected component. Parcel and unit totals come from the owner rows
    (owners needs `parcel_count` and `total_units`; missing columns count as zero)."""
    by_owner = owners.drop_duplicates("owner_key").set_index("owner_key")
    parcels = by_owner.get("parcel_count", pd.Series(0, index=by_owner.index)).fillna(0)
    units = by_owner.get("total_units", pd.Series(0, index=by_owner.index)).fillna(0)

    rows = []
    for component in nx.connected_components(G):
        owner_keys = sorted(n for n in component if isinstance(n, str))
        if not owner_keys:
            continue
        n_keys = sum(1 for n in component if isinstance(n, tuple))
        rows.append(
            {
                "cluster_id": cluster_id_for(owner_keys),
                "tier": _cluster_tier(G, component),
                "n_owners": len(owner_keys),
                "owner_keys": owner_keys,
                "n_parcels": int(parcels.reindex(owner_keys).sum()),
                "total_units": float(units.reindex(owner_keys).sum()),
                # Review-priority signal for oversized clusters: a low ratio (few reused
                # keys for the size) fits a real single operator better than vendor chaining.
                "keys_per_owner": (n_keys / len(owner_keys)) if len(owner_keys) > 1 else None,
            }
        )
    return pd.DataFrame(rows)


def build_weak_links(address_hub: dict, contact_hub: dict) -> pd.DataFrame:
    rows = [
        {"key_type": key_type, "key_value": key_value, **info}
        for key_type, hubs in (("address", address_hub), ("contact", contact_hub))
        for key_value, info in hubs.items()
    ]
    return pd.DataFrame(rows, columns=["key_type", "key_value", "degree", "owner_keys"])


def build_edges(G: nx.Graph) -> pd.DataFrame:
    """One row per (owner, key) edge: the evidence that ties an owner into its cluster."""
    rows = []
    for u, v, data in G.edges(data=True):
        owner, key_node = (u, v) if isinstance(u, str) else (v, u)
        rows.append(
            {
                "owner_key": owner,
                "key_type": data["key_type"],
                "key_value": key_node[1],
                "is_person": data.get("is_person"),
            }
        )
    return pd.DataFrame(rows, columns=["owner_key", "key_type", "key_value", "is_person"])


def run(owners: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The whole graph step on an owners frame: filter, build, extract."""
    owners = exclude_financial(owners)
    G, address_hub, contact_hub = build_graph(owners)
    return {
        "clusters": extract_clusters(G, owners),
        "edges": build_edges(G),
        "weak_links": build_weak_links(address_hub, contact_hub),
    }


def main() -> None:
    from . import source
    from .paths import DATA_DIR

    conn = source.connect()
    owners = source.fetch_owners(conn)
    print(f"{len(owners)} private owners read")
    out = run(owners)

    DATA_DIR.mkdir(exist_ok=True)
    for name, frame in out.items():
        frame.to_parquet(DATA_DIR / f"{name}.parquet", index=False)
    source.write_meta(conn, DATA_DIR)

    clusters = out["clusters"]
    print(f"{len(clusters)} clusters, {int((clusters['n_owners'] > 1).sum())} linked (2+ owners)")
    print(clusters["tier"].value_counts().to_string())
    print(f"{len(out['weak_links'])} hub keys recorded as weak links")


if __name__ == "__main__":
    main()
