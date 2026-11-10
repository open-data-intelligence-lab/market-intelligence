"""Shared settings for the County Business Patterns (CBP) pipeline."""

from pathlib import Path

YEARS = [2020, 2021, 2022, 2023]

# State FIPS code -> name.
STATES = {"08": "Colorado", "20": "Kansas", "29": "Missouri", "48": "Texas"}

# API measure -> column name in the cleaned data.
MEASURES = {
    "ESTAB": "establishments",
    "EMP": "employees",  # mid-March pay period
    "PAYANN": "annual_payroll_thousands",  # $1,000s
}

# NAICS code for "Total for all sectors". Fetched only to cross-check that
# sectors add up; never kept in the cleaned data.
TOTAL_CODE = "00"

# Two-digit NAICS sectors. Some sectors span several 2-digit codes and the
# API returns them as one combined row (e.g. "31-33" Manufacturing), so each
# business is counted in exactly one of these.
NAICS_SECTORS = {
    "11": "Agriculture, forestry, fishing and hunting",
    "21": "Mining, quarrying, and oil and gas extraction",
    "22": "Utilities",
    "23": "Construction",
    "31-33": "Manufacturing",
    "42": "Wholesale trade",
    "44-45": "Retail trade",
    "48-49": "Transportation and warehousing",
    "51": "Information",
    "52": "Finance and insurance",
    "53": "Real estate and rental and leasing",
    "54": "Professional, scientific, and technical services",
    "55": "Management of companies and enterprises",
    "56": "Administrative and support and waste management and remediation services",
    "61": "Educational services",
    "62": "Health care and social assistance",
    "71": "Arts, entertainment, and recreation",
    "72": "Accommodation and food services",
    "81": "Other services (except public administration)",
    "99": "Industries not classified",
}

RAW_DIR = Path("data/raw/cbp")
PROCESSED_DIR = Path("data/processed")


def processed_path(geography: str) -> Path:
    """e.g. data/processed/cbp_state_industry_2020_2023.csv"""
    return PROCESSED_DIR / f"cbp_{geography}_industry_{YEARS[0]}_{YEARS[-1]}.csv"
