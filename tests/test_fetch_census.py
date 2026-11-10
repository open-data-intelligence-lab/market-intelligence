import json
from unittest.mock import MagicMock, patch

import pytest

from src.config import NAICS_SECTORS
from src.ingestion import fetch_census
from src.ingestion.fetch_census import (
    build_dataset,
    fetch_cbp,
    find_naics_variable,
    get_api_key,
    load_raw,
    save_raw,
)

STATES = ["20", "48", "29", "08"]


def mock_response(json_data=None, json_error=False):
    resp = MagicMock()
    resp.url = "https://api.census.gov/data/missing_key.html"
    if json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


def api_rows(year_scale=1):
    """A fake state-level API response: all sectors plus a matching total."""
    names = {"08": "Colorado", "20": "Kansas", "29": "Missouri", "48": "Texas"}
    rows = [["NAME", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "NAICS2017", "state"]]
    for fips, name in names.items():
        for code, label in NAICS_SECTORS.items():
            rows.append([name, label, str(10 * year_scale), "100", "5000", code, fips])
        n = len(NAICS_SECTORS)
        rows.append([name, "Total for all sectors", str(10 * year_scale * n), str(100 * n), str(5000 * n), "00", fips])
    return rows


# --- NAICS variable lookup ----------------------------------------------------


@patch("src.ingestion.fetch_census.requests.get")
def test_find_naics_variable_reads_the_year_metadata(mock_get):
    mock_get.return_value = mock_response(
        {"variables": {"NAICS2017": {}, "NAICS2017_LABEL": {}, "ESTAB": {}}}
    )
    assert find_naics_variable(2021) == "NAICS2017"
    assert mock_get.call_args.args[0] == "https://api.census.gov/data/2021/cbp/variables.json"


@patch("src.ingestion.fetch_census.requests.get")
def test_find_naics_variable_fails_clearly_when_ambiguous(mock_get):
    mock_get.return_value = mock_response({"variables": {"NAICS2017": {}, "NAICS2022": {}}})
    with pytest.raises(RuntimeError, match=r"found \['NAICS2017', 'NAICS2022'\]"):
        find_naics_variable(2024)


# --- API requests -------------------------------------------------------------


@patch("src.ingestion.fetch_census.requests.get")
def test_state_request_asks_for_sectors_and_total_only(mock_get):
    mock_get.return_value = mock_response(api_rows())

    fetch_cbp(2023, "state", "NAICS2017", STATES, "fake-key")

    params = mock_get.call_args.kwargs["params"]
    assert ("for", "state:20,48,29,08") in params
    assert ("key", "fake-key") in params
    assert ("get", "NAME,NAICS2017_LABEL,ESTAB,EMP,PAYANN") in params
    codes = [v for k, v in params if k == "NAICS2017"]
    assert codes == ["00", *NAICS_SECTORS]


@patch("src.ingestion.fetch_census.requests.get")
def test_county_request_uses_in_clause(mock_get):
    mock_get.return_value = mock_response(api_rows())

    fetch_cbp(2020, "county", "NAICS2017", STATES, "fake-key")

    params = mock_get.call_args.kwargs["params"]
    assert ("for", "county:*") in params
    assert ("in", "state:20,48,29,08") in params
    assert mock_get.call_args.args[0] == "https://api.census.gov/data/2020/cbp"


@patch("src.ingestion.fetch_census.requests.get")
def test_non_json_response_gives_clear_error(mock_get):
    mock_get.return_value = mock_response(json_error=True)
    with pytest.raises(RuntimeError, match="API key"):
        fetch_cbp(2023, "state", "NAICS2017", STATES, "bad-key")


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    monkeypatch.setattr("src.ingestion.fetch_census.load_dotenv", lambda: None)
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        get_api_key()


# --- raw files ----------------------------------------------------------------


def test_raw_response_is_saved_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_census, "RAW_DIR", tmp_path)
    rows = api_rows()
    rows[1][2] = "D"  # suppression code stays as sent

    path = save_raw(rows, 2023, "state", "NAICS2017")

    assert path == tmp_path / "cbp_2023_state.json"
    saved = json.loads(path.read_text())
    assert saved["naics_variable"] == "NAICS2017"
    assert saved["rows"] == rows
    assert load_raw(2023, "state") == (rows, "NAICS2017")


def test_load_raw_missing_file_says_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_census, "RAW_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="without --from-raw"):
        load_raw(2020, "state")


# --- full build ---------------------------------------------------------------


def test_build_dataset_from_raw_combines_years_without_totals(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_census, "RAW_DIR", tmp_path)
    for i, year in enumerate([2020, 2021, 2022, 2023], start=1):
        save_raw(api_rows(year_scale=i), year, "state", "NAICS2017")

    data = build_dataset("state", from_raw=True, api_key=None)

    assert len(data) == 4 * 4 * len(NAICS_SECTORS)
    assert "00" not in set(data["naics_code"])
    assert sorted(data["year"].unique()) == [2020, 2021, 2022, 2023]


def test_build_dataset_stops_when_sectors_exceed_total(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_census, "RAW_DIR", tmp_path)
    for year in [2020, 2021, 2022, 2023]:
        rows = api_rows()
        rows[1][2] = "999999"  # Colorado sector far above its total
        save_raw(rows, year, "state", "NAICS2017")

    with pytest.raises(RuntimeError, match="double counting"):
        build_dataset("state", from_raw=True, api_key=None)
