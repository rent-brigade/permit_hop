"""Per-parcel evidence flags that aren't strong enough to be graph edges.

possible_self_transfer: doc_reason_code == 'R' combined with a nominal sale
amount is consistent with an individual moving title into their own LLC with
no arm's-length sale. This is surfaced as evidence attached to a node, NOT
used to construct an edge -- `first transfree name` (the would-be prior-owner
field) is dead in this table (0/11,169 populated in the sample), so we cannot
recover who the *previous* owner was and chain "old name -> new LLC" into an
edge. Doing that properly would need historical assessor rolls or County
Recorder grantor/grantee data joined via `document number`, neither of which
is in scope yet.
"""

import pandas as pd

from . import config


def add_self_transfer_flag(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    nominal = df["last_sale_amount_clean"].notna() & (
        df["last_sale_amount_clean"] <= config.NOMINAL_SALE_AMOUNT_THRESHOLD
    )
    is_r_code = df["doc reason code"] == "R"
    df["possible_self_transfer"] = (nominal & is_r_code).fillna(False)
    return df
