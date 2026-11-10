from src.transformation.clean_cbp import clean_cbp, output_columns

STATE_ROWS = [
    ["NAME", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "NAICS2017", "state"],
    ["Kansas", "Total for all sectors", "76139", "1248825", "71120760", "00", "20"],
    ["Kansas", "Construction", "7398", "70000", "4000000", "23", "20"],
    ["Colorado", "Manufacturing", "D", "", "100", "31-33", "08"],
]

COUNTY_ROWS = [
    ["NAME", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "NAICS2017", "state", "county"],
    ["Allen County, Kansas", "Construction", "30", "200", "9000", "23", "20", "001"],
    ["Allen County, Kansas", "Total for all sectors", "300", "4000", "150000", "00", "20", "001"],
]


def test_state_rows_are_split_into_sectors_and_totals():
    sectors, totals = clean_cbp(STATE_ROWS, 2023, "NAICS2017", "state")

    assert list(sectors.columns) == output_columns("state")
    assert sectors["naics_code"].tolist() == ["31-33", "23"]  # sorted by state FIPS
    assert totals["naics_code"].tolist() == ["00"]


def test_state_columns_are_filled():
    sectors, _ = clean_cbp(STATE_ROWS, 2023, "NAICS2017", "state")
    kansas = sectors[sectors["state_fips"] == "20"].iloc[0]

    assert kansas["year"] == 2023
    assert kansas["state_name"] == "Kansas"
    assert kansas["industry_name"] == "Construction"
    assert kansas["naics_vintage"] == "NAICS2017"
    assert kansas["establishments"] == "7398"


def test_values_are_left_as_sent_for_the_validator():
    sectors, _ = clean_cbp(STATE_ROWS, 2023, "NAICS2017", "state")
    colorado = sectors[sectors["state_fips"] == "08"].iloc[0]

    # Not converted and never turned into 0.
    assert colorado["establishments"] == "D"
    assert colorado["employees"] == ""


def test_county_rows_get_5_digit_fips_and_name():
    sectors, totals = clean_cbp(COUNTY_ROWS, 2021, "NAICS2017", "county")

    assert list(sectors.columns) == output_columns("county")
    row = sectors.iloc[0]
    assert row["county_fips"] == "20001"
    assert row["county_name"] == "Allen County, Kansas"
    assert row["state_name"] == "Kansas"
    assert len(totals) == 1


def test_other_naics_vintage_is_renamed_the_same_way():
    rows = [[c.replace("NAICS2017", "NAICS2022") for c in STATE_ROWS[0]], *STATE_ROWS[1:]]

    sectors, _ = clean_cbp(rows, 2024, "NAICS2022", "state")

    assert set(sectors["naics_vintage"]) == {"NAICS2022"}
    assert "naics_code" in sectors.columns and "industry_name" in sectors.columns
