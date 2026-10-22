"""Clean and derive linkage keys from the raw ingested parcel data.

Logic here is ported from the ad-hoc analysis scripts (inspect_examples.py
through inspect_examples4.py) that were validated against real data during
exploration -- see permits/ASSESSOR_FIELD_NOTES.md for the findings that
motivated each derived column.
"""

import re

import pandas as pd

from . import config

NAME_COL = "first owner name"


def _blank_to_none(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().replace({"": None, "nan": None})


def classify_entity_type(owner_name: pd.Series) -> pd.Series:
    """LLC / LP / trust / corp / individual, via suffix regex on owner name."""
    name = owner_name.astype(str)
    result = pd.Series("individual", index=owner_name.index, dtype=object)
    # Order matters only in that later matches can override earlier ones if a
    # name somehow matches multiple patterns; in practice these are disjoint.
    for label, pattern in config.ENTITY_SUFFIX_PATTERNS.items():
        mask = name.str.contains(pattern, case=False, na=False, regex=True)
        result = result.where(~mask, label)
    return result


def classify_is_government(owner_name: pd.Series, entity_type: pd.Series) -> pd.Series:
    """Government/public entities, out of scope for landlord-portfolio
    tracing. Restricted to names without a business-entity suffix, so a
    private LLC that happens to contain a word like "CITY" isn't
    misclassified -- see config.GOVERNMENT_NAME_PATTERN for why this filter
    exists (it's the direct fix for an observed transitive-chaining bug)."""
    matches_gov_pattern = owner_name.astype(str).str.contains(
        config.GOVERNMENT_NAME_PATTERN, case=False, na=False, regex=True
    )
    return matches_gov_pattern & (entity_type == "individual")


def classify_is_financial_services(owner_name: pd.Series) -> pd.Series:
    """Mortgage servicers / securitization trustees / REO investors -- pass-
    through financial administration, not beneficial ownership. Unlike
    classify_is_government, NOT restricted to entity_type == "individual":
    these entities usually already carry an LLC/Inc/Assn suffix, so that
    guard would defeat the purpose. See config.FINANCIAL_SERVICES_PATTERN."""
    return owner_name.astype(str).str.contains(
        config.FINANCIAL_SERVICES_PATTERN, case=False, na=False, regex=True
    )


def normalize_owner_name(owner_name: pd.Series) -> pd.Series:
    return (
        owner_name.astype(str)
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def build_mail_addr_key(df: pd.DataFrame) -> pd.Series:
    house_no = _blank_to_none(df["mail house no"]).fillna("")
    # Treat literal "0" as no house number (legitimate absence, per field notes).
    house_no = house_no.where(house_no != "0", "")
    street = df["m street name"].astype(str).str.strip().str.upper()
    unit = df["m unit"].astype(str).str.strip().str.upper()
    zip_ = df["m zip"].astype(str).str.strip()

    key = house_no + "|" + street + "|" + unit + "|" + zip_
    # No street name at all means no real mailing address on file -- these
    # should not participate in address-based clustering (they're not a real
    # shared address, just shared *absence* of one). Null them out.
    key = key.where(street != "", None)
    return key


def clean_co_name(special_name_assessee: pd.Series) -> pd.Series:
    cleaned = (
        special_name_assessee.astype(str)
        .str.strip()
        .str.replace(r"^C/O\s*", "", regex=True, case=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    return cleaned.replace({"": None})


def classify_co_is_person(co_name_clean: pd.Series) -> pd.Series:
    is_company = co_name_clean.astype(str).str.contains(
        config.COMPANY_KEYWORDS, case=False, na=False, regex=True
    )
    # NaN co_name_clean -> NaN is_person (not applicable), handled by caller
    # filtering on notna() first where relevant.
    return ~is_company


def scrub_sale_amount(amount: pd.Series) -> pd.Series:
    """Null out only the exact sentinel value; leave small real amounts alone.

    See ASSESSOR_FIELD_NOTES.md correction: $0/$9/etc. are real nominal-
    consideration values and must be preserved for the self-transfer flag.
    """
    numeric = pd.to_numeric(amount, errors="coerce")
    return numeric.where(numeric != config.SALE_AMOUNT_SENTINEL, other=pd.NA)


def scrub_landlord_units(units: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Returns (units_for_aggregation, is_outlier_flag).

    0 is ambiguous (not-tracked vs. genuinely zero) -> null for aggregation.
    The 999 outlier is flagged separately and excluded from sums.
    """
    numeric = pd.to_numeric(units, errors="coerce")
    is_outlier = numeric >= config.LANDLORD_UNITS_OUTLIER
    for_agg = numeric.where((numeric != 0) & ~is_outlier, other=pd.NA)
    return for_agg, is_outlier


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    # A small number of AINs (46 distinct, 94 rows in the full county table)
    # are exact duplicate rows in the source table -- not a real multi-entity
    # case, just repeated data. Dedupe before anything downstream assumes
    # ain is a unique key (e.g. reindex-by-ain lookups in build_graph.py).
    df = df.drop_duplicates(subset="ain").copy()

    df["owner_entity_type"] = classify_entity_type(df[NAME_COL])
    df["owner_name_norm"] = normalize_owner_name(df[NAME_COL])
    df["is_government"] = classify_is_government(df[NAME_COL], df["owner_entity_type"])
    df["is_financial_services"] = classify_is_financial_services(df[NAME_COL])

    df["mail_addr_key"] = build_mail_addr_key(df)

    df["co_name_clean"] = clean_co_name(df["special name assessee"])
    df["co_is_person"] = classify_co_is_person(df["co_name_clean"].fillna("")).astype(
        "boolean"
    )
    df.loc[df["co_name_clean"].isna(), "co_is_person"] = pd.NA

    df["last_sale_amount_clean"] = scrub_sale_amount(df["last sale amount"])
    df["landlord_units_clean"], df["landlord_units_outlier"] = scrub_landlord_units(
        df["landlord units"]
    )

    df["landlord_reappraisal_year_clean"] = pd.to_numeric(
        df["landlord reappraisal year"], errors="coerce"
    ).replace({0: pd.NA})

    for col in ("doc reason code", "ownership code", "use code"):
        df[col] = _blank_to_none(df[col])

    return df
