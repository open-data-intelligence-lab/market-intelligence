# market-intelligence

Market Intelligence Platform

An open-data analytics project exploring economic and business trends across U.S. regions.

Initial goals: Build reliable data pipelines, analyze public economic indicators, and publish interactive dashboards.

Status: Planning

## Setup

Requires Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env   # then add your CENSUS_API_KEY
```

## Fetch and validate data

County Business Patterns data for Colorado, Kansas, Missouri and Texas, 2020–2023,
by two-digit NAICS sector, at state and county level.

```bash
# Download from the Census API, save raw responses to data/raw/cbp/,
# then clean, validate and write the combined CSVs to data/processed/
python -m src.ingestion.fetch_census

# Rebuild the CSVs from the saved raw files (no API calls)
python -m src.ingestion.fetch_census --from-raw

# Re-validate a saved CSV (exits 1 and lists every problem if it fails)
python -m src.validation.validate_cbp data/processed/cbp_state_industry_2020_2023.csv
python -m src.validation.validate_cbp data/processed/cbp_county_industry_2020_2023.csv
```

| Output | Rows |
|---|---|
| `data/processed/cbp_state_industry_2020_2023.csv` | 320 (4 years × 4 states × 20 sectors) |
| `data/processed/cbp_county_industry_2020_2023.csv` | 31,986 |

Analysis: `notebooks/cbp_industry_analysis.ipynb` (industry mix, largest sectors,
year-over-year charts, county rankings).

Code layout:

- `src/config.py`: years, states, sectors, paths
- `src/ingestion/fetch_census.py`: API calls and raw files
- `src/transformation/clean_cbp.py`: raw API rows → tidy columns
- `src/validation/validate_cbp.py`: checks; converts measures to numbers

Missing values and Census suppression codes (`D`, `S`, `N`, `X`, and sentinels like
`-999999999`) become empty (NA). They are never replaced with 0. See
[docs/data_sources.md](docs/data_sources.md) for every validation check, the Census API
limitations, and notes on industry classification.

Read saved CSVs with `load_cbp_csv()`, or pass `dtype=str` for `state_fips`,
`county_fips` and `naics_code`, so codes like `08` keep their leading zero.

## Run the tests

From the project root:

```bash
python -m pytest            # all tests
python -m pytest -v tests/test_validate_cbp.py   # validation tests only
```

The tests use sample data and mocked API calls, so they need no API key or network access.
