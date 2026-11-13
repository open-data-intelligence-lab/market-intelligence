# KPI Definitions: CBP Market Intelligence Dashboard (v1)

This document defines the KPIs for the first Streamlit dashboard. The dashboard must
calculate every KPI exactly as written here. If a calculation needs to change, update
this document first.

Data: Census County Business Patterns (CBP), 2020–2023, Colorado, Kansas, Missouri and
Texas, by two-digit NAICS sector. See [data_sources.md](data_sources.md) for how the
data is collected and validated.

---

## 1. Source data

| File | Grain (one row per) | Rows | Use for |
|---|---|---|---|
| `data/processed/cbp_state_industry_2020_2023.csv` | year × state × sector | 320 | State, multi-state and industry KPIs |
| `data/processed/cbp_county_industry_2020_2023.csv` | year × county × sector | 31,986 | County KPIs and county comparisons only |

Columns (from `src/transformation/clean_cbp.py`):

| Column | Type | Meaning |
|---|---|---|
| `year` | int | CBP reference year (2020–2023) |
| `state_fips` | text, 2 digits | State FIPS code: `08` CO, `20` KS, `29` MO, `48` TX |
| `state_name` | text | State name |
| `county_fips` | text, 5 digits | County FIPS (county file only) |
| `county_name` | text | e.g. "Allen County, Kansas" (county file only) |
| `naics_code` | text | Two-digit NAICS sector, e.g. `23`, `31-33` |
| `industry_name` | text | Census sector name |
| `naics_vintage` | text | NAICS edition used, `NAICS2017` for all rows |
| `establishments` | int | Number of establishments (physical business locations) |
| `employees` | int, nullable | Paid employees in the pay period including **March 12** |
| `annual_payroll_thousands` | int, nullable | Total annual payroll in **thousands of dollars**, nominal |

Load the files with codes as text, or `08` becomes `8`:

```python
from src.validation.validate_cbp import load_cbp_csv, validate_cbp
state = validate_cbp(load_cbp_csv("data/processed/cbp_state_industry_2020_2023.csv")).data
county = validate_cbp(load_cbp_csv("data/processed/cbp_county_industry_2020_2023.csv")).data
```

Running `validate_cbp` on load converts the measures to nullable integers, so missing
values stay missing (`<NA>`) and are never read as 0.

---

## 2. Rules that apply to every KPI

### 2.1 Avoiding double counting

1. **Sectors are additive.** Each establishment belongs to exactly one sector. The files
   contain no "Total for all sectors" (`00`) rows, and combined sectors such as `31-33`
   Manufacturing are single rows. Summing sectors gives the total. The pipeline checks
   that state sector sums equal the Census state totals exactly for every year.
2. **Never mix the two files in one sum.** The state file and the county file describe
   the same businesses at different levels. Adding them together counts everything twice.
3. **State and multi-state totals come from the state file, never from summing counties.**
   CBP withholds some small county cells, so county sums cover only about 98–99.6% of a
   state's establishments and 93–97% of its employees and payroll.
4. **Never sum across years.** All three measures describe a single year
   (establishments and employees are counts at a point in time, payroll is one year's total).
   "Total establishments 2020–2023" is not a meaningful number. Show one year, or a change
   between years.
5. **Establishments are not firms.** A company with 40 store locations counts as 40
   establishments. Label the KPI "establishments" or "business locations", never
   "businesses" or "companies".

### 2.2 Payroll units

- `annual_payroll_thousands` is in **$1,000s**. Multiply by 1,000 before showing dollars.
  Example: Texas 2023 = 805,008,752 → **$805.0 billion**.
- Values are **nominal** (not adjusted for inflation). Payroll grew 8–10% per year in
  2021–2023, and part of that is inflation. Label payroll growth "nominal".
- Payroll covers the **whole calendar year**; employees are a **mid-March** count.

### 2.3 Consistent year-over-year comparisons

A change between two years is valid only when both years use the same geography, the
same industry definitions and the same set of records.

1. **Same industry definitions.** Compare years only when `naics_vintage` is identical.
   All 2020–2023 rows use `NAICS2017`. If a future year uses `NAICS2022`, the dashboard
   must show the comparison as unavailable until the codes are mapped.
2. **Same geography.** State boundaries and the 537 county codes in this data are
   unchanged across 2020–2023. Compare a county only with itself.
3. **Same records ("matched cells") at county level.** Each year about 120–160 county ×
   sector cells appear or disappear because CBP omits withheld or empty cells. For
   county-level growth, use only county × sector cells present in **both** years. A cell
   missing in one year means "unknown", not "zero".
   - Example: Kent County and Terrell County, Texas had 3–4 establishments in 2020–2022
     but no published sectors in 2023. Treating 2023 as 0 would show −100%, which is wrong.
4. **State level needs no matching.** The state file is complete: every state has all
   20 sectors in every year (validated).
5. **The 2020 baseline is unusual.** 2020 `employees` was counted in mid-March 2020,
   mostly before the COVID-19 lockdowns, while 2020 payroll covers the whole year.
   Employment then fell 3.5% in 2021 and recovered. Annotate any chart or KPI that
   starts at 2020.

### 2.4 Missing, suppressed and noisy data

| Situation | Where it occurs | How to handle |
|---|---|---|
| Value is `<NA>` (suppressed or missing) | Not present in 2020–2023 data, but supported by the validator | Leave it out of sums and averages. Show the KPI with a "partial data" note, or as "n/a" if any part of a required comparison is missing. **Never fill with 0.** |
| `employees` = 0 with payroll > 0 | 12 county rows (flagged as validation warnings) | Probably withheld employment. Include the 0 in employment sums (it's what Census published), but exclude these rows from any per-employee ratio. |
| County × sector cell absent | ~10,900 of 42,880 possible county-year-sector cells | Not zero. Leave it out of county sums and use matched cells for growth (2.3). |
| County present with no sector rows | Kent and Terrell, TX in 2023 | Show "data withheld" for that county and year, not 0. |
| Small values | Smallest published cell has 3 establishments | CBP adds random noise to employees and payroll. Don't rank by growth rate below the minimum bases in each KPI. |

Rule of thumb: **missing is not zero, and a sum with missing parts must say it is partial.**

---

## 3. KPI definitions

Summary:

| # | KPI | Default view | Source file |
|---|---|---|---|
| 3.1 | Total business establishments | Latest year, selected states | State |
| 3.2 | Year-over-year establishment growth | Latest year vs prior year | State (county: matched cells) |
| 3.3 | Total employment | Latest year | State |
| 3.4 | Annual payroll | Latest year, in $ | State |
| 3.5 | Establishments by industry | Latest year, by sector | State (or county for one county) |
| 3.6 | County and state comparisons | Latest year, ranked | State or county, never mixed |
| 3.7 | Fastest-growing industries | Latest year vs prior year | State |

Filters assumed on every KPI: **year**, **state(s)**, and where relevant **sector(s)** and
**county**. "Selected" below means the rows remaining after filters.

---

### 3.1 Total business establishments

**Business meaning.** How many business locations with paid employees exist in the
selected area. A measure of market size and business density.

**Calculation.**
`Total establishments = SUM(establishments)` over the selected sectors, for **one** year.

```python
state.loc[(state.year == Y) & state.state_fips.isin(S), "establishments"].sum()
```

**Required fields.** `year`, `state_fips` (or `county_fips`), `naics_code`, `establishments`.

**Aggregation rules.**
- Sum across sectors and across states. Never sum across years (2.1.4).
- For one or more states, use the state file. For a single county, use the county file.
- For a group of counties (e.g. a metro area), sum the county file and label the result
  "sum of published county data". It will be slightly below the true figure.

**Limitations.**
- Counts only establishments with paid employees. Self-employed people and most farms,
  government, railroads and private households are not covered.
- Counts locations, not companies (2.1.5).

**Missing / suppressed data.** Establishments are never suppressed in CBP; the validator
rejects a missing value. At county level, absent sector cells are left out and the total
is labeled as published county data.

**Reference value.** 2023, all four states: **1,080,978** (CO 182,486 · KS 76,139 ·
MO 151,475 · TX 670,878).

---

### 3.2 Year-over-year establishment growth

**Business meaning.** Is the number of business locations growing or shrinking? An
indicator of market momentum and new business formation net of closures.

**Calculation.**
```
YoY growth % = (Establishments[Y] − Establishments[Y−1]) / Establishments[Y−1] × 100
Absolute change = Establishments[Y] − Establishments[Y−1]
```
For multi-year periods, also show the compound annual growth rate:
`CAGR % = ((Establishments[end] / Establishments[start]) ^ (1 / (end − start)) − 1) × 100`.

**Required fields.** `year`, geography codes, `naics_code`, `establishments`, `naics_vintage`.

**Aggregation rules.**
- Sum each year **first** (using 3.1), then compute the change. Never average
  per-sector or per-state growth rates; that gives small sectors the same weight as large ones.
- State level: use the state file directly; it is complete.
- County level: sum only the **matched cells** (county × sector present in both years), then
  compute the change. Over all four states for 2022→2023, matched county cells give
  +1.112%, matching the state file's +1.113%. Unmatched sums give +1.107%.
- Year 2020 has no prior year in this data. Show "n/a" for 2020 YoY.

**Limitations.**
- Net change only: openings minus closures. It can't show churn.
- Small bases produce large, noisy percentages. Show the absolute change next to the
  percentage, and don't show a growth % when the base year has fewer than 20 establishments.
- `naics_vintage` must match in both years (2.3.1).

**Missing / suppressed data.** If either year's value is missing for a matched cell, drop
that cell from both years. If a county has no published sectors in either year, show
"n/a — data withheld", not −100% or +∞.

**Reference values.** All four states: 2021 +2.59%, 2022 +2.27%, 2023 +1.11%.
2023 by state: CO +0.29%, KS +0.19%, MO −1.49%, TX +2.06%.

---

### 3.3 Total employment

**Business meaning.** How many people are on business payrolls in the area. A measure of
labor market size.

**Calculation.** `Total employment = SUM(employees)` over the selected sectors, for one year.

**Required fields.** `year`, geography codes, `naics_code`, `employees`.

**Aggregation rules.** Same as 3.1: sum across sectors and areas, never across years; use
the state file for state totals.

**Limitations.**
- **Mid-March snapshot**, not an annual average. Seasonal sectors (construction,
  accommodation and food, agriculture) are understated or overstated depending on the season.
- **2020 is pre-pandemic** for employment (2.3.5).
- Counts jobs (people on payroll), not residents. A person with two jobs at different
  employers is counted twice. Employees are counted where they work, not where they live.
- Noise infusion: small county values are approximate.

**Missing / suppressed data.** Leave `<NA>` values out of the sum and show "partial". Keep
the 12 county rows with `employees = 0` in the sum (they are what Census published) but
flag them; see 3.4 for ratios.

**Reference value.** 2023, all four states: **18,459,037** employees.

---

### 3.4 Annual payroll

**Business meaning.** Total wages paid by businesses in the area during the year. A
measure of local spending power and the economic weight of an industry.

**Calculation.**
```
Annual payroll ($) = SUM(annual_payroll_thousands) × 1,000
```
Display in $ millions or $ billions with the unit in the label, e.g. "$805.0B".

Supporting metric, **average annual pay per employee**:
```
Average pay ($) = SUM(annual_payroll_thousands) × 1,000 / SUM(employees)
```
Calculate it over rows where **both** payroll and employees are present and employees > 0.

**Required fields.** `year`, geography codes, `naics_code`, `annual_payroll_thousands`,
and `employees` for average pay.

**Aggregation rules.**
- Sum across sectors and areas for one year. Never sum across years.
- Compute average pay as **ratio of sums** (total payroll ÷ total employees), never as an
  average of per-sector or per-county averages.
- Payroll growth uses the same method as 3.2 and is labeled **nominal**.

**Limitations.**
- **Units: the raw column is in thousands of dollars.** Forgetting the ×1,000 is the most
  likely bug; the dashboard tests should check one reference value.
- Nominal dollars; not adjusted for inflation or cost of living between states.
- Average pay divides a full-year payroll by a mid-March headcount. It's an approximation,
  distorted for seasonal sectors and when headcount changed during the year (notably 2020).
- Includes all pay to employees (wages, bonuses, paid leave); excludes owners' income.

**Missing / suppressed data.** Leave `<NA>` out of the sum and show "partial". Exclude rows
with `employees = 0` or `<NA>` from both the numerator and denominator of average pay.

**Reference values.** 2023 payroll: all four states **$1,218.2 billion**; Texas $805.0B.
2023 average pay: CO $70,681 · KS $56,950 · MO $61,049 · TX $67,014.

---

### 3.5 Establishments by industry

**Business meaning.** Which industries make up the local economy. Shows market
composition and where business activity is concentrated.

**Calculation.** For one year, group by sector and sum `establishments`. Also show each
sector's **share**:
```
Share % = Establishments[sector] / SUM(Establishments over all 20 sectors) × 100
```

**Required fields.** `year`, geography codes, `naics_code`, `industry_name`, `establishments`.

**Aggregation rules.**
- Group by `naics_code`, not by `industry_name`, and display `industry_name` (or a short label).
- Calculate shares against the sum of all 20 sectors in the **same** area and year, even
  when the chart shows only the top N sectors. Group the rest as "Other sectors".
- Keep `99` "Industries not classified" in totals and shares, but it may be grouped into
  "Other" in charts (0.13% of establishments in 2023).
- The same breakdown works for `employees` and payroll; the chart must say which measure it shows.

**Limitations.**
- At county level, sector shares use only published cells, so they are shares of
  published activity. Small sectors in small counties are often missing.
- Sector `11` covers only agricultural support, forestry and fishing, not crop and animal
  farms (0.18% of establishments). Don't present it as the size of local agriculture.
- Sector `55` Management of companies is mostly corporate headquarters; its counts depend on
  where companies locate their head offices.

**Missing / suppressed data.** Show absent county sectors as "not published", not as 0%.
A sector with `<NA>` is left out of both the numerator and the denominator, and the chart
notes it.

---

### 3.6 County and state comparisons

**Business meaning.** How areas compare in size, industry mix and growth. Used to
benchmark markets and spot opportunities.

**Calculation.** Calculate the chosen KPI (3.1–3.5) separately for each area, then rank or
chart them side by side. Use **size-neutral** measures when comparing areas of very
different sizes:

| Comparison | Measure |
|---|---|
| Size | Total establishments, employment, payroll (3.1, 3.3, 3.4) |
| Growth | YoY % or CAGR (3.2) |
| Industry mix | Sector share % (3.5) |
| Pay level | Average annual pay (3.4) |
| Change over time | Index to a base year = 100 (e.g. 2020 = 100) |

**Required fields.** As for the chosen KPI, plus `state_name` / `county_name` for labels.

**Aggregation rules.**
- Compare **like with like**: state vs state from the state file, county vs county from the
  county file. Never rank a county against a state.
- A county's share of its state: county value (county file) ÷ state value (state file).
  Label it "approximate", since county data is incomplete.
- Use one year for all areas in a comparison. Growth comparisons use the same start and
  end years and matched cells for every county.
- Raw totals favor large areas (Texas has about 9× Kansas's establishments, and Harris
  County alone has more than 111,000). Default rankings to growth % or shares; show
  totals alongside them.

**Limitations.**
- No population data yet, so "per capita" measures are not available. Comparisons of size
  reflect population as much as economic strength.
- Average pay is not adjusted for cost of living.
- Many counties are very small (median county × sector cell: 19 establishments).
  Growth ranks need minimum sizes (below).

**Minimum size for county growth rankings.** Include a county only if it had at least
**100 establishments** in the base year (summed over matched cells). This removes noise
from tiny counties and is the threshold the analysis notebook uses.

**Missing / suppressed data.** Show areas with withheld data as "n/a" and sort them last,
not as 0. Say on the chart how many areas were excluded and why.

---

### 3.7 Fastest-growing industries

**Business meaning.** Which industries are expanding fastest in the selected area. Points
to emerging opportunities and shifting demand.

**Calculation.** For each sector, compute growth with 3.2's method on the chosen measure
(establishments by default; employment and payroll as options):
```
Sector growth % = (Value[sector, Y] − Value[sector, Y−1]) / Value[sector, Y−1] × 100
```
For 2020–2023, use CAGR. Rank sectors by growth % in descending order. Show the absolute
change next to each percentage.

**Required fields.** `year`, geography codes, `naics_code`, `industry_name`, the chosen
measure, `naics_vintage`.

**Aggregation rules.**
- Sum each sector across the selected states **first**, then compute growth. Don't average
  state growth rates.
- **Exclude `99` "Industries not classified" from the ranking.** It is a small residual
  category whose size depends on how Census classifies new businesses, not on economic
  activity. In 2022→2023 it would rank first (+9.3%) while having fallen 33% since 2020.
- Minimum base: rank a sector only if it had at least **500 establishments** (state-level
  ranking) or **20 establishments** (single-county ranking, matched cells) in the base year.
- Use the same years for every sector. Employment-based rankings starting in 2020 must
  carry the pre-pandemic note (2.3.5).

**Limitations.**
- Percent growth favors small sectors; absolute growth favors large ones. Show both, and
  let the user switch the sort.
- One-year growth is volatile. Present 1-year and 2020–2023 CAGR side by side where space allows.
- Two-digit sectors are broad. "Retail" combines very different businesses, so a flat
  sector can hide fast-growing sub-industries. Sub-industry detail is not in this dataset.

**Missing / suppressed data.** A sector with a missing value in either year is left out of
the ranking with a note. At county level, use only matched cells.

**Reference values (all four states, establishments, 2022→2023, excluding `99`).**
Top three: Educational services +3.96%, Arts, entertainment and recreation +3.76%,
Accommodation and food services +2.59%. Bottom: Agriculture, forestry, fishing and
hunting −4.81%.

---

## 4. Display conventions

- Always show the **year** with each KPI, and "employees (mid-March)" in employment labels.
- Payroll: "$805.0B" or "$71.1M", unit in the label. Growth: one decimal place, with sign
  ("+2.1%", "−1.5%").
- A KPI that excludes data says so in a footnote: "Partial: 2 counties withheld",
  "Excludes Industries not classified".
- Source line on every page: "Source: U.S. Census Bureau, County Business Patterns
  2020–2023 (NAICS 2017)."

## 5. Dashboard testing checklist

The dashboard's KPI functions must reproduce these values from the processed files:

| Check | Expected |
|---|---|
| 2023 establishments, 4 states | 1,080,978 |
| 2023 employees, 4 states | 18,459,037 |
| 2023 payroll, 4 states | $1,218,152,149,000 |
| 2023 establishment YoY, Missouri | −1.49% |
| 2023 average annual pay, Kansas | $56,950 |
| Top non-`99` sector by establishment growth 2022→2023, 4 states | Educational services, +3.96% |
| Kent County, TX establishment growth 2022→2023 | n/a (data withheld), not −100% |

## 6. Open decisions

These need a team decision before or during the dashboard build:

1. **Inflation adjustment.** Should payroll be shown in constant dollars (e.g. using CPI)?
   This requires a new data source.
2. **Per-capita measures.** Adding Census population estimates would allow fair
   comparisons between areas of very different sizes.
3. **Minimum-size thresholds.** The 20 / 100 / 500 establishment cut-offs above are
   starting points; confirm them once the dashboard is in use.
4. **2020 as the default baseline.** Consider defaulting multi-year charts to 2021 to
   avoid the pre-pandemic employment snapshot.
