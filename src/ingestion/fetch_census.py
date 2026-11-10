"""Fetch County Business Patterns (CBP) data by two-digit NAICS sector.

For each year in src.config.YEARS and each geography (state, county):
  1. Ask the Census API which NAICS variable the year uses (e.g. NAICS2017).
  2. Download the sectors plus the all-sector total for the four states.
  3. Save the untouched API response to data/raw/cbp/.
  4. Clean, validate, and write one combined CSV per geography to data/processed/.

Run from the project root:
    python -m src.ingestion.fetch_census             # download, then build CSVs
    python -m src.ingestion.fetch_census --from-raw  # rebuild CSVs from saved raw files
"""

import argparse
import json
import os
import re
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.config import (
    MEASURES,
    NAICS_SECTORS,
    RAW_DIR,
    STATES,
    TOTAL_CODE,
    YEARS,
    processed_path,
)
from src.transformation.clean_cbp import clean_cbp
from src.validation.validate_cbp import check_against_totals, validate_cbp

GEOGRAPHIES = ["state", "county"]
BASE_URL = "https://api.census.gov/data/{year}/cbp"
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


def _get_json(url: str, params=None, timeout: int = 60):
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    # A missing or invalid key redirects to an HTML page instead of JSON.
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Census API did not return JSON (often a missing or invalid "
            f"API key). Final URL: {response.url}"
        ) from exc


def find_naics_variable(year: int) -> str:
    """Return the NAICS variable the CBP API uses for `year`, e.g. "NAICS2017".

    CBP switches NAICS vintages over time (NAICS2012, NAICS2017, ...), so this
    reads the year's variable list instead of assuming.
    """
    variables = _get_json(BASE_URL.format(year=year) + "/variables.json")["variables"]
    matches = sorted(v for v in variables if re.fullmatch(r"NAICS\d{4}", v))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one NAICS variable for CBP {year}, found {matches}")
    return matches[0]


def fetch_cbp(
    year: int, geography: str, naics_var: str, state_fips: list[str], api_key: str
) -> list[list]:
    """Return the raw API rows (header first) for the sectors plus the total."""
    params = [
        ("get", ",".join(["NAME", f"{naics_var}_LABEL", *MEASURES])),
        ("key", api_key),
    ]
    if geography == "state":
        params.append(("for", f"state:{','.join(state_fips)}"))
    else:
        params += [("for", "county:*"), ("in", f"state:{','.join(state_fips)}")]
    # Repeating the predicate requests several codes at once.
    params += [(naics_var, code) for code in [TOTAL_CODE, *NAICS_SECTORS]]
    return _get_json(BASE_URL.format(year=year), params=params, timeout=120)


def raw_path(year: int, geography: str) -> Path:
    return RAW_DIR / f"cbp_{year}_{geography}.json"


def save_raw(rows: list[list], year: int, geography: str, naics_var: str) -> Path:
    """Save the API response untouched, with the NAICS variable used."""
    path = raw_path(year, geography)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"year": year, "naics_variable": naics_var, "rows": rows}))
    return path


def load_raw(year: int, geography: str) -> tuple[list[list], str]:
    path = raw_path(year, geography)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run without --from-raw to download it.")
    saved = json.loads(path.read_text())
    return saved["rows"], saved["naics_variable"]


def build_dataset(geography: str, from_raw: bool, api_key: str | None) -> pd.DataFrame:
    """Fetch (or load) every year, then clean, validate and cross-check."""
    sectors, totals = [], []
    for year in YEARS:
        if from_raw:
            rows, naics_var = load_raw(year, geography)
        else:
            naics_var = find_naics_variable(year)
            rows = fetch_cbp(year, geography, naics_var, list(STATES), api_key)
            print(f"Saved {save_raw(rows, year, geography, naics_var)} ({naics_var})")
        year_sectors, year_totals = clean_cbp(rows, year, naics_var, geography)
        sectors.append(year_sectors)
        totals.append(year_totals)

    report = validate_cbp(pd.concat(sectors, ignore_index=True))
    total_errors = check_against_totals(report.data, pd.concat(totals, ignore_index=True))
    if total_errors:
        raise RuntimeError("Sector totals check failed:\n" + "\n".join(total_errors))

    for warning in report.warnings[:10]:
        print(f"Warning: {warning}")
    if len(report.warnings) > 10:
        print(f"... and {len(report.warnings) - 10} more warnings")
    return report.data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-raw", action="store_true", help="use saved raw files, no API calls")
    args = parser.parse_args()
    api_key = None if args.from_raw else get_api_key()

    for geography in GEOGRAPHIES:
        print(f"\n== {geography} level ==")
        data = build_dataset(geography, args.from_raw, api_key)
        output = processed_path(geography)
        output.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(output, index=False)

        counts = data.pivot_table(
            index="year", columns="state_name", values="naics_code", aggfunc="count"
        )
        counts["Total"] = counts.sum(axis=1)
        print(f"Rows by year and state:\n{counts.to_string()}")
        print(f"Saved {len(data)} rows to {output}")


if __name__ == "__main__":
    main()
