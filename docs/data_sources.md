# Data Sources

## County Business Patterns

Provider: U.S. Census Bureau

Purpose:
Analyze business establishment trends
across selected U.S. states.

Initial states:
- Kansas
- Texas
- Missouri
- Colorado

Primary measures:
- Number of business establishments
- Employment
- Annual payroll

Data access:
Census Bureau API

Status:
Ingestion implemented for 2020–2023 at state and county level, by two-digit NAICS sector.

### What we download

| | |
|---|---|
| API | `https://api.census.gov/data/{year}/cbp` (free key: https://api.census.gov/data/key_signup.html) |
| Years | 2020, 2021, 2022, 2023 (2023 is the latest CBP year published; `2024/cbp` does not exist yet) |
| Geography | states `08` Colorado, `20` Kansas, `29` Missouri, `48` Texas; and every county in those states |
| Industries | the 20 two-digit NAICS sectors (list in `src/config.py`) |
| Measures | `ESTAB` establishments, `EMP` employees (mid-March pay period), `PAYANN` annual payroll in $1,000s |

### Files

| Stage | Path | Notes |
|---|---|---|
| Raw | `data/raw/cbp/cbp_{year}_{state,county}.json` | API response exactly as received, plus the NAICS variable used |
| Cleaned | `data/processed/cbp_state_industry_2020_2023.csv` | 320 rows: 4 years × 4 states × 20 sectors |
| Cleaned | `data/processed/cbp_county_industry_2020_2023.csv` | 31,986 rows (about 8,000 per year) |

Cleaned columns: `year, state_fips, state_name, [county_fips, county_name,] naics_code,
industry_name, naics_vintage, establishments, employees, annual_payroll_thousands`.
Read the CSVs with codes as text (`dtype={"state_fips": str, "county_fips": str, "naics_code": str}`
or `load_cbp_csv()`), or `08` becomes `8`.

### Industry classification

- Each CBP year has a single NAICS variable. The pipeline reads it from the year's
  `variables.json` instead of assuming it. All of 2020–2023 use **`NAICS2017`**, so the
  sector codes are identical across these years and need no remapping.
- Older CBP years use other vintages (e.g. `NAICS2012` before 2017). Future years may
  switch to `NAICS2022`. If a year uses a different vintage, `naics_vintage` will show it.
  Check sector definitions before comparing across vintages; at the two-digit level the
  2017 and 2022 sectors have the same codes.
- Several sectors span more than one two-digit code and come back as one combined row:
  `31-33` Manufacturing, `44-45` Retail trade, `48-49` Transportation and warehousing.
  No sector overlaps another, so each business is counted once.
- `00` "Total for all sectors" is downloaded only to cross-check the data and is
  **excluded** from the cleaned files. Keeping it would double-count every business.
- `99` "Industries not classified" is kept. It is small but part of the total.
- Public administration (NAICS 92), most agriculture production, private households,
  railroads and self-employed people are **not covered** by CBP at all. Sector `11`
  covers only agricultural support, forestry and fishing.

### Limitations

- **Employment is a mid-March snapshot.** 2020 `employees` mostly reflects the period
  before the COVID-19 lockdowns. 2020 `annual_payroll_thousands` covers the full year.
  Keep this in mind when comparing 2020 with 2021.
- **Noise infusion.** Since 2017 CBP adds small random noise to employment and payroll
  instead of suppressing cells. Small changes, especially in small counties, may not be real.
- **Withheld county cells.** CBP leaves out county × sector cells with no establishments or
  with withheld data. 10,894 of 42,880 possible county-year-sector cells are absent. In 2023,
  Kent County and Terrell County, Texas have only an all-sector total, with every sector
  withheld. Because of this, **county sums undercount state totals**: about 98–99.6% of
  establishments and 93–97% of employees and payroll. Use the state file for state totals.
- **Zero employment with payroll.** 12 county rows report 0 employees with positive
  payroll, a sign that employment was withheld. They are kept as 0 and flagged as warnings.
- **No explicit suppression flags in 2020–2023.** The API's `EMP_N`/`PAYANN_N` columns are
  always "0" for these years. The validator still handles suppression codes (`D`, `S`, `N`,
  `X`) and Census missing-value numbers (e.g. `-999999999`) by turning them into empty
  values, never 0. No such values occurred in the 2020–2023 data.
- **Nominal dollars.** Payroll is not adjusted for inflation.
- **Request limits.** Without an API key the Census API allows a small number of requests
  per day. A full run makes 12 requests (4 years × 2 geographies, plus 4 metadata lookups).

### Validation

`python -m src.validation.validate_cbp <csv>` checks a cleaned file. During ingestion,
`check_against_totals()` also compares sectors with the API's all-sector totals.

- Errors (the run stops): missing columns, unexpected years, states or NAICS codes, any
  `00` total rows, duplicate year-area-industry rows, a missing year-state-sector record,
  a county or state without a total row in some year, sectors adding up to more than the
  total, state sectors not matching the state total, and invalid or missing establishment counts.
- Warnings (the run continues): missing or suppressed employees or payroll, zero
  employees with positive payroll, and missing county cells.
