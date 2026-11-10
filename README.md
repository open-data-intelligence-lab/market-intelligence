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

```bash
# Download CBP totals for KS, TX, MO, CO, validate them, save to data/raw/
python -m src.ingestion.fetch_census

# Re-validate a saved CSV (exits 1 and lists every problem if it fails)
python -m src.validation.validate_cbp data/raw/cbp_2023_states.csv
```

Validation (`src/validation/validate_cbp.py`) checks:

- Required columns are present (`NAME`, `state`, `NAICS2017`, `year`, `ESTAB`, `EMP`, `PAYANN`).
- States are exactly the expected 2-digit FIPS codes (`08`, `20`, `29`, `48`).
- No duplicate records for the same state, industry, and year.
- Measures are whole, non-negative numbers.

Missing values and Census suppression codes (`D`, `S`, `N`, `X`, and
sentinels like `-999999999`) become empty (NA). They are never replaced with 0.
A missing `ESTAB` is an error. A missing `EMP` or `PAYANN` is a warning, because
Census can withhold these to protect individual businesses.

Read saved CSVs with `load_cbp_csv()`, not plain `pd.read_csv()`, so codes like `08` keep their leading zero.

## Run the tests

From the project root:

```bash
python -m pytest            # all tests
python -m pytest -v tests/test_validate_cbp.py   # validation tests only
```

The tests use sample data and mocked API calls, so they need no API key or network access.
