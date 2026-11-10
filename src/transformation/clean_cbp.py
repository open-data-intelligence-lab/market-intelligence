"""Turn raw CBP API responses into tidy, analysis-ready rows.

Measure values are left exactly as the API sent them (text, possibly a
suppression code). validate_cbp() converts them to numbers and decides how
to handle anything missing, so no value is silently turned into zero here.
"""

import pandas as pd

from src.config import MEASURES, STATES, TOTAL_CODE

ID_COLUMNS = {
    "state": ["year", "state_fips", "state_name"],
    "county": ["year", "state_fips", "state_name", "county_fips", "county_name"],
}
INDUSTRY_COLUMNS = ["naics_code", "industry_name", "naics_vintage"]


def output_columns(geography: str) -> list[str]:
    return [*ID_COLUMNS[geography], *INDUSTRY_COLUMNS, *MEASURES.values()]


def clean_cbp(
    rows: list[list], year: int, naics_var: str, geography: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split one raw API response into (sector rows, all-sector total rows).

    rows: the API's JSON (first row is the header).
    naics_var: the NAICS variable used for this year, e.g. "NAICS2017".
    geography: "state" or "county".
    """
    if geography not in ID_COLUMNS:
        raise ValueError(f"geography must be 'state' or 'county', got {geography!r}")

    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df.rename(
        columns={
            naics_var: "naics_code",
            f"{naics_var}_LABEL": "industry_name",
            "state": "state_fips",
            **MEASURES,
        }
    )
    df["year"] = year
    df["naics_vintage"] = naics_var
    df["state_name"] = df["state_fips"].map(STATES)
    if geography == "county":
        df["county_fips"] = df["state_fips"] + df["county"]  # 5-digit FIPS
        df["county_name"] = df["NAME"]

    df = df[output_columns(geography)]
    area = "county_fips" if geography == "county" else "state_fips"
    df = df.sort_values([area, "naics_code"]).reset_index(drop=True)

    is_total = df["naics_code"] == TOTAL_CODE
    return df[~is_total].reset_index(drop=True), df[is_total].reset_index(drop=True)
