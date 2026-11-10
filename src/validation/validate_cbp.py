"""Validation for County Business Patterns (CBP) data.

Works on a DataFrame straight from the Census API or from a saved CSV.
Collects every problem it finds and raises one CBPValidationError that
lists them all, so you can fix everything in one pass.

Missing and suppressed values become NA (never zero):
- ESTAB is never suppressed in CBP, so a missing ESTAB is an error.
- EMP and PAYANN can be withheld; a missing value there is a warning.

Validate a saved file from the project root:
    python -m src.validation.validate_cbp data/raw/cbp_2023_states.csv
"""

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# State FIPS code -> name for the states this project covers.
EXPECTED_STATES = {"20": "Kansas", "48": "Texas", "29": "Missouri", "08": "Colorado"}
MEASURES = ["ESTAB", "EMP", "PAYANN"]
# Measures that must always have a value. The rest may be suppressed.
REQUIRED_MEASURES = ["ESTAB"]
KEY_COLUMNS = ["state", "NAICS2017", "year"]
REQUIRED_COLUMNS = ["NAME", *KEY_COLUMNS]

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
    """Read a CBP CSV as text so codes like state "08" and NAICS "00" keep their leading zeros."""
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _parse_value(value) -> tuple[float | None, str | None]:
    """Return (number, None), (None, reason) for missing/suppressed, or raise ValueError."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
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
    name = df.at[idx, "NAME"] if "NAME" in df.columns else None
    return f"row {idx} ({name})" if name else f"row {idx}"


def _clean_measure(
    df: pd.DataFrame, col: str, required: bool, errors: list[str], warnings: list[str]
) -> pd.Series:
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
            msg = f"{col} in {where} is {reason}"
            (errors if required else warnings).append(msg)
            continue
        if number < 0:
            errors.append(f"{col} in {where} is negative: {value!r}")
        elif number != int(number):
            errors.append(f"{col} in {where} is not a whole number: {value!r}")
        else:
            cleaned.at[idx] = int(number)
    return cleaned


def validate_cbp(
    df: pd.DataFrame,
    expected_states: list[str] | None = None,
    measures: list[str] | None = None,
    required_measures: list[str] | None = None,
) -> ValidationReport:
    """Check CBP data and return a cleaned copy with integer measures.

    Raises CBPValidationError listing every problem found.
    """
    expected_states = list(EXPECTED_STATES) if expected_states is None else expected_states
    measures = MEASURES if measures is None else measures
    required_measures = REQUIRED_MEASURES if required_measures is None else required_measures

    # Other checks depend on these columns, so stop early if any are missing.
    missing_cols = [c for c in [*REQUIRED_COLUMNS, *measures] if c not in df.columns]
    if missing_cols:
        raise CBPValidationError(
            [f"Missing required columns: {missing_cols}. Found: {list(df.columns)}"]
        )
    if df.empty:
        raise CBPValidationError(["Data has no rows"])

    errors: list[str] = []
    warnings: list[str] = []
    data = df.copy()

    # States: must be 2-digit FIPS text and match the expected set exactly.
    states = data["state"].astype(str)
    bad_format = sorted({s for s in states if not (len(s) == 2 and s.isdigit())})
    if bad_format:
        errors.append(
            f"State codes must be 2-digit FIPS strings like '08', got {bad_format}. "
            "If reading a CSV, use load_cbp_csv() so leading zeros are kept."
        )
    found, expected = set(states), set(expected_states)
    if found - expected or expected - found:
        errors.append(
            f"State mismatch. Missing: {sorted(expected - found)}, "
            f"unexpected: {sorted(found - expected)}"
        )

    # Duplicates: one row per state, industry and year.
    dupes = data[data.duplicated(KEY_COLUMNS, keep=False)]
    if not dupes.empty:
        keys = sorted({tuple(str(v) for v in k) for k in dupes[KEY_COLUMNS].itertuples(index=False)})
        errors.append(f"Duplicate records for {KEY_COLUMNS}: {keys}")

    # Measures: whole, non-negative numbers; missing/suppressed become NA.
    for col in measures:
        data[col] = _clean_measure(data, col, col in required_measures, errors, warnings)

    # Census sometimes reports withheld employment as 0 alongside a real payroll.
    if {"EMP", "PAYANN"} <= set(measures):
        mask = ((data["EMP"] == 0) & (data["PAYANN"] > 0)).fillna(False)
        suspicious = data[mask].index
        for idx in suspicious:
            warnings.append(
                f"EMP in {_row_label(data, idx)} is 0 but PAYANN is positive; "
                "employment may be withheld"
            )

    if errors:
        raise CBPValidationError(errors)
    return ValidationReport(data=data, warnings=warnings)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python -m src.validation.validate_cbp <path/to/file.csv>")
        return 2
    try:
        report = validate_cbp(load_cbp_csv(argv[0]))
    except CBPValidationError as exc:
        print(exc)
        return 1
    for w in report.warnings:
        print(f"Warning: {w}")
    print(f"OK: {argv[0]} passed validation ({len(report.data)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
