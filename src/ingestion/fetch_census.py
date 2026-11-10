"""Fetch County Business Patterns (CBP) state totals from the Census API.

Run from the project root:
    python -m src.ingestion.fetch_census
"""

import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.validation.validate_cbp import validate_cbp

YEAR = 2023
STATES = {"20": "Kansas", "48": "Texas", "29": "Missouri", "08": "Colorado"}

# ESTAB = establishments, EMP = employees (mid-March),
# PAYANN = annual payroll in thousands of dollars.
MEASURES = ["ESTAB", "EMP", "PAYANN"]

KEY_SIGNUP_URL = "https://api.census.gov/data/key_signup.html"


def get_api_key() -> str:
    load_dotenv()
    key = os.getenv("CENSUS_API_KEY")
    if not key:
        raise RuntimeError(
            "CENSUS_API_KEY is not set. Get a free key at "
            f"{KEY_SIGNUP_URL} and add CENSUS_API_KEY=... to .env"
        )
    return key


def fetch_cbp(year: int, state_fips: list[str], api_key: str) -> pd.DataFrame:
    """Return all-industry CBP totals for the given states."""
    url = f"https://api.census.gov/data/{year}/cbp"
    params = {
        "get": ",".join(["NAME", "NAICS2017_LABEL", *MEASURES]),
        "for": f"state:{','.join(state_fips)}",
        "NAICS2017": "00",  # 00 = total for all sectors
        "key": api_key,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    # A missing or invalid key redirects to an HTML page instead of JSON.
    try:
        rows = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Census API did not return JSON (often a missing or invalid "
            f"API key). Final URL: {response.url}"
        ) from exc

    # Values stay as returned by the API (text, possibly suppression codes).
    # validate_cbp() converts them to numbers and handles missing values.
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["year"] = year
    return df


def main() -> None:
    raw = fetch_cbp(YEAR, list(STATES), get_api_key())
    report = validate_cbp(raw, expected_states=list(STATES), measures=MEASURES)
    for warning in report.warnings:
        print(f"Warning: {warning}")
    data = report.data

    output = Path(f"data/raw/cbp_{YEAR}_states.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output, index=False)

    print(data.to_string(index=False))
    print(f"\nSaved to {output}")


if __name__ == "__main__":
    main()
