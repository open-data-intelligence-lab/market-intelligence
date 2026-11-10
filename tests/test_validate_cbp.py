import pandas as pd
import pytest

from src.validation.validate_cbp import (
    CBPValidationError,
    load_cbp_csv,
    main,
    validate_cbp,
)

COLUMNS = ["NAME", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "NAICS2017", "state", "year"]
ROWS = [
    ["Colorado", "Total for all sectors", "182486", "2566040", "181369969", "00", "08", "2023"],
    ["Kansas", "Total for all sectors", "76139", "1248825", "71120760", "00", "20", "2023"],
    ["Missouri", "Total for all sectors", "151475", "2631543", "160652668", "00", "29", "2023"],
    ["Texas", "Total for all sectors", "670878", "12012629", "805008752", "00", "48", "2023"],
]


def make_df(rows=None):
    return pd.DataFrame([r.copy() for r in (rows or ROWS)], columns=COLUMNS)


def set_value(df, state, col, value):
    df[col] = df[col].astype(object)  # allow mixed types, like raw API data
    df.loc[df["state"] == state, col] = value
    return df


def errors_from(df, **kwargs):
    with pytest.raises(CBPValidationError) as exc_info:
        validate_cbp(df, **kwargs)
    return exc_info.value.errors


# --- valid data -------------------------------------------------------------


def test_valid_data_passes_and_converts_measures_to_integers():
    report = validate_cbp(make_df())

    assert report.warnings == []
    assert report.data["ESTAB"].tolist() == [182486, 76139, 151475, 670878]
    for col in ["ESTAB", "EMP", "PAYANN"]:
        assert str(report.data[col].dtype) == "Int64"


def test_valid_data_with_numeric_api_types_passes():
    df = make_df()
    for col in ["ESTAB", "EMP", "PAYANN"]:
        df[col] = df[col].astype(int)
    assert validate_cbp(df).warnings == []


def test_input_dataframe_is_not_modified():
    df = make_df()
    validate_cbp(df)
    assert df["ESTAB"].tolist() == ["182486", "76139", "151475", "670878"]


def test_csv_round_trip_keeps_leading_zeros(tmp_path):
    path = tmp_path / "cbp.csv"
    make_df().to_csv(path, index=False)

    df = load_cbp_csv(path)

    assert "08" in df["state"].tolist()
    assert validate_cbp(df).warnings == []


def test_cli_passes_on_valid_csv(tmp_path, capsys):
    path = tmp_path / "cbp.csv"
    make_df().to_csv(path, index=False)

    assert main([str(path)]) == 0
    assert "passed validation" in capsys.readouterr().out


# --- required columns -------------------------------------------------------


def test_missing_column_is_reported_by_name():
    errors = errors_from(make_df().drop(columns=["ESTAB"]))
    assert "Missing required columns: ['ESTAB']" in errors[0]


def test_empty_data_is_rejected():
    errors = errors_from(make_df().iloc[0:0])
    assert errors == ["Data has no rows"]


# --- expected states --------------------------------------------------------


def test_missing_state_is_reported():
    errors = errors_from(make_df(ROWS[1:]))  # drop Colorado
    assert "Missing: ['08'], unexpected: []" in errors[0]


def test_unexpected_state_is_reported():
    df = set_value(make_df(), "48", "state", "06")  # Texas -> California
    errors = errors_from(df)
    assert "Missing: ['48'], unexpected: ['06']" in errors[0]


def test_state_codes_without_leading_zero_get_a_helpful_hint(tmp_path):
    path = tmp_path / "cbp.csv"
    make_df().to_csv(path, index=False)
    df = pd.read_csv(path)  # default read turns "08" into 8

    errors = errors_from(df)

    assert any("2-digit FIPS" in e and "load_cbp_csv" in e for e in errors)


# --- duplicates -------------------------------------------------------------


def test_duplicate_records_are_reported():
    df = make_df(ROWS + [ROWS[1]])  # Kansas twice
    errors = errors_from(df)
    assert any("Duplicate records" in e and "('20', '00', '2023')" in e for e in errors)


# --- numeric establishment counts --------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("-5", "ESTAB in row 1 (Kansas) is negative: '-5'"),
        ("abc", "ESTAB in row 1 (Kansas) is not a number: 'abc'"),
        ("12.5", "ESTAB in row 1 (Kansas) is not a whole number: '12.5'"),
        ("nan", "ESTAB in row 1 (Kansas) is not a number: 'nan'"),
    ],
)
def test_bad_establishment_counts_are_rejected(value, expected):
    df = set_value(make_df(), "20", "ESTAB", value)
    assert expected in errors_from(df)


def test_negative_employment_is_rejected():
    df = set_value(make_df(), "20", "EMP", "-5")
    assert "EMP in row 1 (Kansas) is negative: '-5'" in errors_from(df)


def test_all_problems_are_reported_together():
    df = make_df(ROWS[1:])  # missing Colorado
    df = set_value(df, "20", "ESTAB", "abc")
    df = set_value(df, "48", "PAYANN", "-1")

    with pytest.raises(CBPValidationError) as exc_info:
        validate_cbp(df)

    assert len(exc_info.value.errors) == 3
    assert "3 problem(s)" in str(exc_info.value)


# --- missing values and suppression codes ------------------------------------


@pytest.mark.parametrize("value", [None, "", "D", "(D)", "S", "N", "X", "-999999999", -888888888])
def test_missing_or_suppressed_establishments_are_errors(value):
    df = set_value(make_df(), "29", "ESTAB", value)
    errors = errors_from(df)
    assert len(errors) == 1
    assert errors[0].startswith("ESTAB in row 2 (Missouri) is")


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
    df = set_value(make_df(), "29", "EMP", value)

    report = validate_cbp(df)

    missouri = report.data[report.data["state"] == "29"].iloc[0]
    assert pd.isna(missouri["EMP"])  # NA, never silently 0
    assert len(report.warnings) == 1
    assert f"EMP in row 2 (Missouri) is {reason}" in report.warnings[0]


def test_zero_employment_with_payroll_is_flagged_but_kept():
    df = set_value(make_df(), "20", "EMP", "0")

    report = validate_cbp(df)

    assert report.data.loc[1, "EMP"] == 0
    assert "may be withheld" in report.warnings[0]


def test_suppressed_measure_can_be_made_required():
    df = set_value(make_df(), "29", "EMP", "D")
    errors = errors_from(df, required_measures=["ESTAB", "EMP"])
    assert errors[0].startswith("EMP in row 2 (Missouri) is suppressed")


def test_suppressed_values_survive_csv_round_trip_as_missing(tmp_path):
    df = set_value(make_df(), "29", "EMP", "D")
    path = tmp_path / "cbp.csv"
    validate_cbp(df).data.to_csv(path, index=False)

    reloaded = validate_cbp(load_cbp_csv(path))

    assert pd.isna(reloaded.data.loc[2, "EMP"])
    assert "EMP in row 2 (Missouri) is missing" in reloaded.warnings[0]


def test_cli_reports_errors_and_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "cbp.csv"
    make_df(ROWS[1:]).to_csv(path, index=False)

    assert main([str(path)]) == 1
    assert "Missing: ['08']" in capsys.readouterr().out
