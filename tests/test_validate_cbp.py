import pandas as pd
import pytest

from src.config import NAICS_SECTORS, STATES, YEARS
from src.validation.validate_cbp import (
    CBPValidationError,
    check_against_totals,
    load_cbp_csv,
    main,
    validate_cbp,
)

STATE_COLUMNS = [
    "year", "state_fips", "state_name", "naics_code", "industry_name", "naics_vintage",
    "establishments", "employees", "annual_payroll_thousands",
]


def make_state_df():
    """One row per year, state and sector, values as text like the API."""
    rows = []
    for year in YEARS:
        for fips, name in STATES.items():
            for i, (code, label) in enumerate(NAICS_SECTORS.items()):
                estab = 1000 + i
                rows.append([str(year), fips, name, code, label, "NAICS2017",
                             str(estab), str(estab * 10), str(estab * 500)])
    return pd.DataFrame(rows, columns=STATE_COLUMNS)


def make_county_df():
    """Two Kansas counties; county 001 lacks sector 21 (normal for CBP)."""
    rows = []
    for year in YEARS:
        for county, name in [("20001", "Allen County, Kansas"), ("20003", "Anderson County, Kansas")]:
            for code, label in NAICS_SECTORS.items():
                if county == "20001" and code == "21":
                    continue
                rows.append([str(year), "20", "Kansas", county, name, code, label,
                             "NAICS2017", "10", "100", "5000"])
    cols = STATE_COLUMNS[:3] + ["county_fips", "county_name"] + STATE_COLUMNS[3:]
    return pd.DataFrame(rows, columns=cols)


def row_of(df, year=2023, state="20", naics="23"):
    match = (df["year"] == str(year)) & (df["state_fips"] == state) & (df["naics_code"] == naics)
    return df.index[match][0]


def set_value(df, col, value, **where):
    df[col] = df[col].astype(object)  # allow mixed types, like raw API data
    df.loc[row_of(df, **where), col] = value
    return df


def errors_from(df, **kwargs):
    with pytest.raises(CBPValidationError) as exc_info:
        validate_cbp(df, **kwargs)
    return exc_info.value.errors


# --- valid data -------------------------------------------------------------


def test_valid_state_data_passes_and_converts_numbers():
    report = validate_cbp(make_state_df())

    assert report.warnings == []
    assert len(report.data) == len(YEARS) * len(STATES) * len(NAICS_SECTORS)
    for col in ["year", "establishments", "employees", "annual_payroll_thousands"]:
        assert str(report.data[col].dtype) == "Int64"


def test_input_dataframe_is_not_modified():
    df = make_state_df()
    validate_cbp(df)
    assert df["establishments"].iloc[0] == "1000"


def test_csv_round_trip_keeps_leading_zeros(tmp_path):
    path = tmp_path / "cbp.csv"
    make_state_df().to_csv(path, index=False)

    df = load_cbp_csv(path)

    assert "08" in set(df["state_fips"])
    assert validate_cbp(df).warnings == []


def test_cli_passes_on_valid_csv(tmp_path, capsys):
    path = tmp_path / "cbp.csv"
    make_state_df().to_csv(path, index=False)

    assert main([str(path)]) == 0
    assert "passed validation (320 rows)" in capsys.readouterr().out


def test_cli_reports_errors_and_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "cbp.csv"
    df = make_state_df()
    df[df["state_fips"] != "08"].to_csv(path, index=False)

    assert main([str(path)]) == 1
    assert "Missing: ['08']" in capsys.readouterr().out


# --- required columns -------------------------------------------------------


def test_missing_column_is_reported_by_name():
    errors = errors_from(make_state_df().drop(columns=["industry_name"]))
    assert "Missing required columns: ['industry_name']" in errors[0]


def test_empty_data_is_rejected():
    assert errors_from(make_state_df().iloc[0:0]) == ["Data has no rows"]


# --- years and states -------------------------------------------------------


def test_missing_year_is_reported():
    df = make_state_df()
    errors = errors_from(df[df["year"] != "2021"])
    assert any("Year mismatch. Missing: [2021]" in e for e in errors)


def test_missing_state_is_reported():
    df = make_state_df()
    errors = errors_from(df[df["state_fips"] != "08"])
    assert any("Missing: ['08'], unexpected: []" in e for e in errors)


def test_state_codes_without_leading_zero_get_a_helpful_hint(tmp_path):
    path = tmp_path / "cbp.csv"
    make_state_df().to_csv(path, index=False)
    df = pd.read_csv(path)  # default read turns "08" into 8

    errors = errors_from(df)

    assert any("2-digit FIPS" in e and "load_cbp_csv" in e for e in errors)


# --- industries -------------------------------------------------------------


def test_all_sector_total_rows_are_rejected():
    df = make_state_df()
    total = df.iloc[[0]].assign(naics_code="00", industry_name="Total for all sectors")
    errors = errors_from(pd.concat([df, total], ignore_index=True))
    assert any("NAICS '00'" in e and "double-counted" in e for e in errors)


def test_sub_industry_codes_are_rejected():
    df = set_value(make_state_df(), "naics_code", "236")  # construction sub-industry
    errors = errors_from(df)
    assert any("Unexpected NAICS codes ['236']" in e for e in errors)


# --- duplicates and missing records ------------------------------------------


def test_duplicate_year_state_industry_is_reported():
    df = make_state_df()
    df = pd.concat([df, df.iloc[[row_of(df)]]], ignore_index=True)
    errors = errors_from(df)
    assert any("Duplicate records" in e and "('2023', '20', '23')" in e for e in errors)


def test_missing_state_record_is_reported():
    df = make_state_df()
    errors = errors_from(df.drop(row_of(df, year=2022, state="29", naics="62")))
    assert "Missing 1 year-state-industry records: [('2022', '29', '62')]" in errors


def test_county_gaps_are_warnings_not_errors():
    report = validate_cbp(make_county_df(), expected_states=["20"])
    assert any("4 of 160 county-year-industry cells are not in the data" in w for w in report.warnings)


def test_county_missing_from_one_year_is_a_warning():
    df = make_county_df()
    df = df[~((df["county_fips"] == "20003") & (df["year"] == "2023"))]

    report = validate_cbp(df, expected_states=["20"])

    assert any("Year 2023 has no sector rows for counties" in w and "20003" in w for w in report.warnings)


def test_duplicate_county_record_is_reported():
    df = make_county_df()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    errors = errors_from(df, expected_states=["20"])
    assert any("Duplicate records for ['year', 'county_fips', 'naics_code']" in e for e in errors)


def test_county_fips_must_match_state():
    df = make_county_df()
    df.loc[0, "county_fips"] = "29001"
    errors = errors_from(df, expected_states=["20"])
    assert any("county_fips must be 5 digits starting with the state code" in e for e in errors)


# --- numeric values ---------------------------------------------------------


@pytest.mark.parametrize(
    "value, problem",
    [
        ("-5", "is negative: '-5'"),
        ("abc", "is not a number: 'abc'"),
        ("12.5", "is not a whole number: '12.5'"),
        ("nan", "is not a number: 'nan'"),
    ],
)
def test_bad_establishment_counts_are_rejected(value, problem):
    df = set_value(make_state_df(), "establishments", value)
    assert f"establishments in row {row_of(df)} (2023 Kansas, NAICS 23) {problem}" in errors_from(df)


def test_all_problems_are_reported_together():
    df = make_state_df()
    df = set_value(df, "establishments", "abc")
    df = set_value(df, "annual_payroll_thousands", "-1", state="48")
    df = df[df["state_fips"] != "08"]

    with pytest.raises(CBPValidationError) as exc_info:
        validate_cbp(df)

    # Missing state + its 80 missing records + bad ESTAB + negative payroll.
    assert len(exc_info.value.errors) == 4
    assert "4 problem(s)" in str(exc_info.value)
    assert any(e.startswith("Missing 80 year-state-industry records") for e in exc_info.value.errors)


# --- missing values and suppression codes ------------------------------------


@pytest.mark.parametrize("value", [None, "", "D", "(D)", "S", "N", "X", "-999999999", -888888888])
def test_missing_or_suppressed_establishments_are_errors(value):
    df = set_value(make_state_df(), "establishments", value)
    errors = errors_from(df)
    assert len(errors) == 1
    assert errors[0].startswith(f"establishments in row {row_of(df)} (2023 Kansas, NAICS 23) is")


@pytest.mark.parametrize(
    "value, reason",
    [
        (None, "missing"),
        ("", "missing"),
        ("D", "suppressed (D: withheld to avoid disclosing"),
        ("(S)", "suppressed ((S): withheld because it does not meet"),
        ("-999999999", "Census missing-value code -999999999"),
    ],
)
def test_suppressed_employment_becomes_na_not_zero(value, reason):
    df = set_value(make_state_df(), "employees", value)

    report = validate_cbp(df)

    assert pd.isna(report.data.loc[row_of(df), "employees"])  # NA, never silently 0
    assert len(report.warnings) == 1
    assert f"employees in row {row_of(df)} (2023 Kansas, NAICS 23) is {reason}" in report.warnings[0]


def test_zero_employment_with_payroll_is_flagged_but_kept():
    df = set_value(make_state_df(), "employees", "0")

    report = validate_cbp(df)

    assert report.data.loc[row_of(df), "employees"] == 0
    assert "may be withheld" in report.warnings[0]


def test_suppressed_values_survive_csv_round_trip_as_missing(tmp_path):
    df = set_value(make_state_df(), "employees", "D")
    path = tmp_path / "cbp.csv"
    validate_cbp(df).data.to_csv(path, index=False)

    reloaded = validate_cbp(load_cbp_csv(path))

    assert pd.isna(reloaded.data.loc[row_of(df), "employees"])
    assert "is missing" in reloaded.warnings[0]


# --- cross-check against all-sector totals ------------------------------------


def make_totals(sectors, area="state_fips", scale=1.0):
    measures = ["establishments", "employees", "annual_payroll_thousands"]
    sums = sectors.groupby(["year", area])[measures].sum().reset_index()
    for col in measures:
        sums[col] = (sums[col] * scale).round().astype(int).astype(str)
    return sums.assign(naics_code="00")


def test_sectors_matching_totals_pass():
    sectors = validate_cbp(make_state_df()).data
    assert check_against_totals(sectors, make_totals(sectors)) == []


def test_sectors_exceeding_totals_flag_double_counting():
    sectors = validate_cbp(make_state_df()).data
    errors = check_against_totals(sectors, make_totals(sectors, scale=0.9))
    assert any("more than the total (double counting?)" in e for e in errors)


def test_state_sectors_below_total_are_an_error():
    sectors = validate_cbp(make_state_df()).data
    errors = check_against_totals(sectors, make_totals(sectors, scale=1.1))
    assert any("less than the state total" in e for e in errors)


def test_county_sectors_below_total_are_fine():
    sectors = validate_cbp(make_county_df(), expected_states=["20"]).data
    assert check_against_totals(sectors, make_totals(sectors, "county_fips", scale=1.1)) == []


def test_area_missing_total_row_in_a_year_is_reported():
    sectors = validate_cbp(make_state_df()).data
    totals = make_totals(sectors)
    totals = totals[~((totals["year"] == 2021) & (totals["state_fips"] == "29"))]
    errors = check_against_totals(sectors, totals)
    assert any("Year 2021 has no total row for ['29']" in e for e in errors)
