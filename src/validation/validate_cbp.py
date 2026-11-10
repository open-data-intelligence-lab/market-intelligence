"""Validation for cleaned County Business Patterns (CBP) data.

Works on the output of src.transformation.clean_cbp, at state or county level
(county level is detected from a `county_fips` column). Collects every problem
and raises one CBPValidationError listing them all.

Missing and suppressed values become NA, never zero:
- establishments is never suppressed in CBP, so a missing value is an error.
- employees and payroll can be withheld; a missing value there is a warning.

Validate a saved file from the project root:
    python -m src.validation.validate_cbp data/processed/cbp_state_industry_2020_2023.csv
"""

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.config import MEASURES, NAICS_SECTORS, STATES, TOTAL_CODE, YEARS

MEASURE_COLUMNS = list(MEASURES.values())
# Measures that must always have a value. The rest may be suppressed.
REQUIRED_MEASURES = ["establishments"]
TEXT_CODE_COLUMNS = ["state_fips", "county_fips", "naics_code"]
MAX_LISTED = 15  # cap long lists in messages

# Text codes Census uses in place of a number.
SUPPRESSION_CODES = {
    "D": "withheld to avoid disclosing data for individual companies",
    "S": "withheld because it does not meet publication standards",
    "N": "not available or not comparable",
    "X": "not applicable",
    "NA": "not available",
}
# Negative sentinel numbers the Census API uses for missing values.
SENTINEL_CODES = {
    -999999999: "not available",
    -888888888: "not applicable",
    -666666666: "estimate could not be computed",
    -555555555: "estimate is controlled",
    -333333333: "median falls in an open-ended category",
    -222222222: "not enough sample observations",
}


class CBPValidationError(ValueError):
    """Raised when CBP data fails validation. `errors` lists each problem."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"CBP data failed validation ({len(errors)} problem(s)):\n{bullet_list}")


@dataclass
class ValidationReport:
    """Cleaned data plus non-fatal warnings (e.g. suppressed values)."""

    data: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def load_cbp_csv(path: str | Path) -> pd.DataFrame:
    """Read a CBP CSV, keeping codes like state "08" as text with leading zeros."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _short_list(items: list) -> str:
    items = sorted(items)
    more = f" ... and {len(items) - MAX_LISTED} more" if len(items) > MAX_LISTED else ""
    return f"{items[:MAX_LISTED]}{more}"


def _parse_value(value) -> tuple[float | None, str | None]:
    """Return (number, None), (None, reason) for missing/suppressed, or raise ValueError."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None, "missing"
    text = str(value).strip()
    if text == "":
        return None, "missing"

    code = text.strip("()").upper()
    if code in SUPPRESSION_CODES:
        return None, f"suppressed ({text}: {SUPPRESSION_CODES[code]})"

    number = float(text)  # raises ValueError for anything non-numeric
    if not math.isfinite(number):
        raise ValueError(text)
    if number in SENTINEL_CODES:
        return None, f"Census missing-value code {int(number)} ({SENTINEL_CODES[number]})"
    return number, None


def _row_label(df: pd.DataFrame, idx) -> str:
    """e.g. "row 5 (2023 Kansas, NAICS 23)" so a message points at one record."""
    place = df.at[idx, "county_name"] if "county_name" in df.columns else df.at[idx, "state_name"]
    return f"row {idx} ({df.at[idx, 'year']} {place}, NAICS {df.at[idx, 'naics_code']})"


def _to_number(df: pd.DataFrame, col: str, required: bool, errors: list, warnings: list) -> pd.Series:
    """Convert one measure column to nullable integers, recording problems."""
    cleaned = pd.Series(pd.NA, index=df.index, dtype="Int64")
    for idx, value in df[col].items():
        where = _row_label(df, idx)
        try:
            number, reason = _parse_value(value)
        except ValueError:
            errors.append(f"{col} in {where} is not a number: {value!r}")
            continue

        if reason:
            (errors if required else warnings).append(f"{col} in {where} is {reason}")
        elif number < 0:
            errors.append(f"{col} in {where} is negative: {value!r}")
        elif number != int(number):
            errors.append(f"{col} in {where} is not a whole number: {value!r}")
        else:
            cleaned.at[idx] = int(number)
    return cleaned


def validate_cbp(
    df: pd.DataFrame,
    expected_years: list[int] | None = None,
    expected_states: list[str] | None = None,
    expected_naics: list[str] | None = None,
) -> ValidationReport:
    """Check cleaned CBP data and return a copy with numeric year and measures.

    Raises CBPValidationError listing every problem found.
    """
    expected_years = YEARS if expected_years is None else expected_years
    expected_states = list(STATES) if expected_states is None else expected_states
    expected_naics = list(NAICS_SECTORS) if expected_naics is None else expected_naics
    is_county = "county_fips" in df.columns
    area = "county_fips" if is_county else "state_fips"
    key = ["year", area, "naics_code"]

    required = ["year", "state_fips", "state_name", "naics_code", "industry_name", *MEASURE_COLUMNS]
    if is_county:
        required += ["county_fips", "county_name"]
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise CBPValidationError(
            [f"Missing required columns: {missing_cols}. Found: {list(df.columns)}"]
        )
    if df.empty:
        raise CBPValidationError(["Data has no rows"])

    errors: list[str] = []
    warnings: list[str] = []
    data = df.copy()
    for col in TEXT_CODE_COLUMNS:
        if col in data.columns:
            data[col] = data[col].astype(str)

    # Years.
    years = pd.to_numeric(data["year"], errors="coerce")
    if years.isna().any():
        errors.append(f"year has non-numeric values: {_short_list(set(data.loc[years.isna(), 'year'].astype(str)))}")
    data["year"] = years.astype("Int64")
    found_years = set(years.dropna().astype(int))
    if found_years != set(expected_years):
        errors.append(
            f"Year mismatch. Missing: {sorted(set(expected_years) - found_years)}, "
            f"unexpected: {sorted(found_years - set(expected_years))}"
        )

    # States: 2-digit FIPS text matching the expected set exactly.
    states = data["state_fips"]
    bad_format = sorted({s for s in states if not (len(s) == 2 and s.isdigit())})
    if bad_format:
        errors.append(
            f"State codes must be 2-digit FIPS strings like '08', got {bad_format}. "
            "If reading a CSV, use load_cbp_csv() so leading zeros are kept."
        )
    found, expected = set(states), set(expected_states)
    if found != expected:
        errors.append(
            f"State mismatch. Missing: {sorted(expected - found)}, "
            f"unexpected: {sorted(found - expected)}"
        )

    if is_county:
        bad = data[(data["county_fips"].str.len() != 5) | (data["county_fips"].str[:2] != states)]
        if not bad.empty:
            errors.append(
                "county_fips must be 5 digits starting with the state code; bad values: "
                f"{_short_list(set(bad['county_fips']))}"
            )

    # Industries: two-digit sectors only. A total row would double-count.
    naics = data["naics_code"]
    if (naics == TOTAL_CODE).any():
        errors.append(
            f"Found NAICS '{TOTAL_CODE}' (total for all sectors) rows. "
            "Totals must be excluded or sector sums will be double-counted."
        )
    unexpected = set(naics) - set(expected_naics) - {TOTAL_CODE}
    if unexpected:
        errors.append(
            f"Unexpected NAICS codes {_short_list(unexpected)}; only two-digit sectors are allowed."
        )

    # Duplicates: one row per year, area and industry.
    dupes = data[data.duplicated(key, keep=False)]
    if not dupes.empty:
        keys = {tuple(str(v) for v in k) for k in dupes[key].itertuples(index=False)}
        errors.append(f"Duplicate records for {key}: {_short_list(keys)}")

    # Unexpected missing records.
    if is_county:
        # CBP leaves out county-industry cells with no establishments or with
        # withheld data, so gaps are normal. For very small counties CBP can
        # withhold every sector in a year; check_against_totals() confirms
        # those counties still have a total row.
        counties_by_year = data.groupby("year")["county_fips"].apply(set)
        all_counties = set(data["county_fips"])
        for year, counties in counties_by_year.items():
            if counties != all_counties:
                warnings.append(
                    f"Year {year} has no sector rows for counties present in other years: "
                    f"{_short_list(all_counties - counties)} (all sectors withheld?)"
                )
        n_cells = len(found_years) * len(all_counties) * len(expected_naics)
        n_absent = n_cells - len(data.drop_duplicates(key))
        if n_absent > 0:
            warnings.append(
                f"{n_absent} of {n_cells} county-year-industry cells are not in the data. "
                "CBP omits cells with no establishments or with withheld data."
            )
    else:
        present = set(data[key].astype(str).itertuples(index=False, name=None))
        missing = [
            (str(y), s, n)
            for y in expected_years
            for s in expected_states
            for n in expected_naics
            if (str(y), s, n) not in present
        ]
        if missing:
            errors.append(f"Missing {len(missing)} year-state-industry records: {_short_list(missing)}")

    # Measures: whole, non-negative numbers; missing/suppressed become NA.
    for col in MEASURE_COLUMNS:
        data[col] = _to_number(data, col, col in REQUIRED_MEASURES, errors, warnings)

    # Census sometimes reports withheld employment as 0 alongside a real payroll.
    zero_emp = ((data["employees"] == 0) & (data["annual_payroll_thousands"] > 0)).fillna(False)
    for idx in data[zero_emp].index:
        warnings.append(
            f"employees in {_row_label(data, idx)} is 0 but payroll is positive; "
            "employment may be withheld"
        )

    if errors:
        raise CBPValidationError(errors)
    return ValidationReport(data=data, warnings=warnings)


def check_against_totals(sectors: pd.DataFrame, totals: pd.DataFrame) -> list[str]:
    """Compare sector rows with the API's all-sector total rows.

    sectors: validated sector rows. totals: the NAICS "00" rows from clean_cbp().
    Returns error messages (empty if fine):
    - every area must have a total row in every year (no missing records);
    - every area with sector rows must have a total row;
    - sectors summing to MORE than the total means double counting. Summing
      to less is expected only at county level, where CBP withholds sectors.
    """
    area = "county_fips" if "county_fips" in sectors.columns else "state_fips"
    key = ["year", area]
    errors = []

    total_areas = totals.assign(year=totals["year"].astype(int)).groupby("year")[area].apply(set)
    all_areas = set(totals[area])
    for year, areas in total_areas.items():
        if areas != all_areas:
            errors.append(f"Year {year} has no total row for {_short_list(all_areas - areas)}")
    no_total = set(sectors[area]) - all_areas
    if no_total:
        errors.append(f"Sector rows without any total row: {_short_list(no_total)}")

    sums = (
        sectors.assign(year=sectors["year"].astype(int))
        .groupby(key)[MEASURE_COLUMNS]
        .sum(min_count=1)
    )
    tot = (
        totals.assign(year=totals["year"].astype(int))
        .set_index(key)[MEASURE_COLUMNS]
        .apply(pd.to_numeric, errors="coerce")  # suppressed totals become NA and are skipped
    )

    for col in MEASURE_COLUMNS:
        diff = (sums[col].astype("Float64") - tot[col].reindex(sums.index)).dropna()
        over = diff[diff > 0]
        if not over.empty:
            errors.append(f"{col}: sectors add up to more than the total (double counting?) for {_short_list(over.index.tolist())}")
        if area == "state_fips":
            under = diff[diff < 0]
            if not under.empty:
                errors.append(f"{col}: sectors add up to less than the state total for {_short_list(under.index.tolist())}")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m src.validation.validate_cbp <path/to/file.csv>")
        return 2
    try:
        report = validate_cbp(load_cbp_csv(argv[0]))
    except CBPValidationError as exc:
        print(exc)
        return 1
    for w in report.warnings[:MAX_LISTED]:
        print(f"Warning: {w}")
    if len(report.warnings) > MAX_LISTED:
        print(f"... and {len(report.warnings) - MAX_LISTED} more warnings")
    print(f"OK: {argv[0]} passed validation ({len(report.data)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
