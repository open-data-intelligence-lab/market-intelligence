import pandas as pd
import pytest

from src.analytics import kpis
from src.config import processed_path


def make_county(rows):
    """rows: (year, county_fips, naics, estab, emp, payroll_thousands)."""
    df = pd.DataFrame(rows, columns=["year", "county_fips", "naics_code", "establishments",
                                     "employees", "annual_payroll_thousands"])
    df["state_fips"] = df["county_fips"].str[:2]
    df["state_name"] = df["state_fips"].map({"20": "Kansas", "29": "Missouri"})
    df["county_name"] = "County " + df["county_fips"]
    df["industry_name"] = "Sector " + df["naics_code"]
    df["naics_vintage"] = "NAICS2017"
    for col in ["establishments", "employees", "annual_payroll_thousands"]:
        df[col] = df[col].astype("Int64")  # nullable, like validated data
    return df


# --- arithmetic and zero denominators -------------------------------------------


@pytest.mark.parametrize(
    "new, old, expected",
    [(110, 100, 10.0), (90, 100, -10.0), (5, 0, None), (None, 100, None), (100, None, None),
     (pd.NA, 100, None)],
)
def test_pct_change(new, old, expected):
    assert kpis.pct_change(new, old) == (pytest.approx(expected) if expected is not None else None)


def test_cagr():
    assert kpis.cagr(100, 121, 2) == pytest.approx(10.0)
    assert kpis.cagr(0, 50, 3) is None
    assert kpis.cagr(100, 120, 0) is None


# --- totals: missing is not zero, payroll units -----------------------------------


def test_measure_total_skips_missing_and_reports_partial():
    df = make_county([(2023, "20001", "23", 10, None, 500), (2023, "20001", "42", 5, 30, 200)])

    employees = kpis.measure_total(df, "employees")

    assert employees.value == 30
    assert employees.missing == 1 and employees.partial


def test_measure_total_all_missing_is_none_not_zero():
    df = make_county([(2023, "20001", "23", 10, None, 500)])
    assert kpis.measure_total(df, "employees").value is None


def test_payroll_total_is_converted_to_dollars():
    df = make_county([(2023, "20001", "23", 10, 100, 805_008_752)])
    assert kpis.measure_total(df, "annual_payroll_thousands").value == 805_008_752_000


def test_average_pay_is_ratio_of_sums_and_skips_zero_employees():
    df = make_county([
        (2023, "20001", "23", 10, 100, 5_000),  # $50,000 each
        (2023, "20001", "42", 10, 300, 21_000),  # $70,000 each
        (2023, "20001", "55", 3, 0, 900),  # zero employees: excluded
        (2023, "20001", "61", 3, None, 900),  # missing employees: excluded
    ])
    # (5,000 + 21,000) * 1,000 / 400 = $65,000, not the average of 50k and 70k
    assert kpis.average_pay(df) == pytest.approx(65_000)


def test_average_pay_with_no_employees_is_none():
    df = make_county([(2023, "20001", "23", 3, 0, 900)])
    assert kpis.average_pay(df) is None


# --- growth on matched cells ------------------------------------------------------------


def test_growth_uses_only_cells_published_in_both_years():
    df = make_county([
        (2022, "20001", "23", 100, 1, 1), (2023, "20001", "23", 110, 1, 1),
        (2022, "20001", "42", 50, 1, 1),  # not published in 2023: dropped from both years
        (2023, "20001", "54", 40, 1, 1),  # new in 2023: dropped from both years
    ])

    g = kpis.growth(df, 2022, 2023)

    assert (g.start, g.end) == (100, 110)
    assert g.pct == pytest.approx(10.0)


def test_growth_skips_cells_missing_in_either_year():
    df = make_county([
        (2022, "20001", "23", 100, 10, 1), (2023, "20001", "23", 110, 20, 1),
        (2022, "20001", "42", 100, None, 1), (2023, "20001", "42", 100, 50, 1),
    ])
    g = kpis.growth(df, 2022, 2023, "employees")
    assert (g.start, g.end) == (10, 20)


def test_withheld_county_growth_is_unavailable_not_minus_100():
    df = make_county([(2022, "48263", "23", 3, 1, 1)])  # nothing published in 2023

    g = kpis.growth(df, 2022, 2023)

    assert g.pct is None
    assert "no published data for 2023" in g.reason


def test_growth_unavailable_for_first_year():
    df = make_county([(2020, "20001", "23", 100, 1, 1)])
    assert kpis.yoy_growth(df, 2020).reason == "no published data for 2019"


def test_growth_unavailable_when_industry_codes_differ():
    df = make_county([(2022, "20001", "23", 100, 1, 1), (2023, "20001", "23", 110, 1, 1)])
    df.loc[df["year"] == 2023, "naics_vintage"] = "NAICS2022"
    assert "industry codes differ" in kpis.growth(df, 2022, 2023).reason


def test_growth_not_shown_on_tiny_base():
    df = make_county([(2022, "20001", "23", 5, 1, 1), (2023, "20001", "23", 10, 1, 1)])
    g = kpis.growth(df, 2022, 2023)
    assert g.pct is None and "base below 20" in g.reason


def test_growth_of_empty_selection():
    assert kpis.growth(make_county([]), 2022, 2023).reason == "no data for this selection"


def test_payroll_growth_values_are_dollars():
    df = make_county([(2022, "20001", "23", 100, 1, 1_000), (2023, "20001", "23", 100, 1, 1_100)])
    g = kpis.growth(df, 2022, 2023, "annual_payroll_thousands")
    assert (g.start, g.end) == (1_000_000, 1_100_000)


# --- industries ---------------------------------------------------------------------------


def test_industry_shares_add_to_100():
    df = make_county([(2023, "20001", "23", 30, 1, 1), (2023, "20001", "42", 10, 1, 1),
                      (2023, "20003", "23", 60, 1, 1)])

    mix = kpis.industry_breakdown(df, 2023, "establishments")

    assert mix["value"].tolist() == [90, 10]
    assert mix["share_pct"].sum() == pytest.approx(100)
    assert mix.loc[0, "share_pct"] == pytest.approx(90)


def test_sector_growth_excludes_unclassified_and_small_sectors():
    df = make_county([
        (2022, "20001", "23", 1000, 1, 1), (2023, "20001", "23", 1100, 1, 1),  # +10%
        (2022, "20001", "42", 600, 1, 1), (2023, "20001", "42", 540, 1, 1),  # -10%
        (2022, "20001", "99", 600, 1, 1), (2023, "20001", "99", 900, 1, 1),  # unclassified
        (2022, "20001", "61", 100, 1, 1), (2023, "20001", "61", 150, 1, 1),  # below base
    ])

    out = kpis.sector_growth(df, 2022, 2023, min_base=500)

    assert "99" not in set(out["naics_code"])
    assert out[out["eligible"]]["naics_code"].tolist() == ["23", "42"]
    assert not out.set_index("naics_code").loc["61", "eligible"]


# --- counties -------------------------------------------------------------------------------


def test_county_ranking_orders_and_converts_payroll():
    df = make_county([(2023, "20001", "23", 10, 1, 2_000), (2023, "20003", "23", 10, 1, 5_000)])

    out = kpis.county_ranking(df, 2023, "annual_payroll_thousands")

    assert out["county_fips"].tolist() == ["20003", "20001"]
    assert out["rank"].tolist() == [1, 2]
    assert out.loc[0, "value"] == 5_000_000


def test_county_growth_matches_single_county_growth():
    df = make_county([
        (2022, "20001", "23", 200, 1, 1), (2023, "20001", "23", 220, 1, 1),
        (2022, "20001", "42", 50, 1, 1),  # unmatched cell
        (2022, "20003", "23", 50, 1, 1), (2023, "20003", "23", 40, 1, 1),  # below 100
        (2022, "29001", "23", 4, 1, 1),  # withheld in 2023
    ])

    out = kpis.county_growth(df, 2022, 2023).set_index("county_fips")

    assert out.loc["20001", "pct"] == pytest.approx(kpis.growth(df[df.county_fips == "20001"], 2022, 2023).pct)
    assert out.loc["20001", "eligible"]
    assert not out.loc["20003", "eligible"] and "below 100" in out.loc["20003", "note"]
    assert pd.isna(out.loc["29001", "pct"]) and "no published data" in out.loc["29001", "note"]


def test_county_growth_of_empty_selection():
    assert kpis.county_growth(make_county([]), 2022, 2023).empty


def test_filter_rows_empty_list_means_all():
    df = make_county([(2023, "20001", "23", 1, 1, 1), (2023, "29001", "23", 1, 1, 1)])
    assert len(kpis.filter_rows(df, states=[])) == 2
    assert len(kpis.filter_rows(df, states=["29"])) == 1


# --- formatting -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(1_218_152_149_000, "$1,218.2B"), (71_120_760_000, "$71.1B"), (5_500_000, "$5.5M"),
     (56_950.4, "$56,950"), (None, "n/a")],
)
def test_format_dollars(value, expected):
    assert kpis.format_dollars(value) == expected


def test_format_pct():
    assert kpis.format_pct(2.06) == "+2.1%"
    assert kpis.format_pct(-1.49) == "−1.5%"
    assert kpis.format_pct(None) == "n/a"


# --- reference values from docs/kpi_definitions.md (real data) -----------------------------------

needs_data = pytest.mark.skipif(
    not (processed_path("state").exists() and processed_path("county").exists()),
    reason="processed data not built (python -m src.ingestion.fetch_census)",
)


@pytest.fixture(scope="module")
def data():
    return kpis.load_data()


@needs_data
def test_reference_totals_2023(data):
    summary = kpis.kpi_summary(data.state, 2023)
    assert summary["establishments"].value == 1_080_978
    assert summary["employees"].value == 18_459_037
    assert summary["payroll"].value == 1_218_152_149_000


@needs_data
def test_reference_missouri_yoy(data):
    g = kpis.yoy_growth(kpis.filter_rows(data.state, states=["29"]), 2023)
    assert round(g.pct, 2) == -1.49


@needs_data
def test_reference_kansas_average_pay(data):
    kansas = kpis.filter_rows(data.state, states=["20"], years=[2023])
    assert round(kpis.average_pay(kansas)) == 56_950


@needs_data
def test_reference_fastest_growing_sector(data):
    top = kpis.sector_growth(data.state, 2022, 2023).query("eligible").iloc[0]
    assert top["industry_name"] == "Educational services"
    assert round(top["pct"], 2) == 3.96


@needs_data
def test_reference_kent_county_is_unavailable(data):
    g = kpis.growth(kpis.filter_rows(data.county, counties=["48263"]), 2022, 2023)
    assert g.pct is None


@needs_data
def test_reference_matched_county_growth_close_to_state(data):
    county = kpis.growth(data.county, 2022, 2023)
    state = kpis.growth(data.state, 2022, 2023)
    assert round(county.pct, 3) == 1.112
    assert round(state.pct, 3) == 1.113
