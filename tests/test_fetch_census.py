from unittest.mock import MagicMock, patch

import pytest

from src.ingestion.fetch_census import MEASURES, fetch_cbp, get_api_key
from src.validation.validate_cbp import validate_cbp

STATES = ["20", "48", "29", "08"]

SAMPLE = [
    ["NAME", "NAICS2017_LABEL", "ESTAB", "EMP", "PAYANN", "NAICS2017", "state"],
    ["Kansas", "Total for all sectors", "75000", "1200000", "60000000", "00", "20"],
    ["Texas", "Total for all sectors", "600000", "11000000", "700000000", "00", "48"],
    ["Missouri", "Total for all sectors", "150000", "2500000", "130000000", "00", "29"],
    ["Colorado", "Total for all sectors", "170000", "2400000", "150000000", "00", "08"],
]


def mock_response(json_data=None, json_error=False):
    resp = MagicMock()
    resp.url = "https://api.census.gov/data/missing_key.html"
    if json_error:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_data
    return resp


@patch("src.ingestion.fetch_census.requests.get")
def test_fetch_cbp_parses_and_requests_only_target_states(mock_get):
    mock_get.return_value = mock_response(SAMPLE)

    df = fetch_cbp(2023, STATES, "fake-key")

    params = mock_get.call_args.kwargs["params"]
    assert params["for"] == "state:20,48,29,08"
    assert params["key"] == "fake-key"
    assert len(df) == 4
    assert (df["year"] == 2023).all()

    data = validate_cbp(df, STATES, MEASURES).data
    for col in MEASURES:
        assert data[col].dtype.kind in "iu"


@patch("src.ingestion.fetch_census.requests.get")
def test_fetch_cbp_keeps_suppression_codes_for_validation(mock_get):
    rows = [r.copy() for r in SAMPLE]
    rows[1][3] = "D"  # Kansas EMP withheld
    mock_get.return_value = mock_response(rows)

    df = fetch_cbp(2023, STATES, "fake-key")  # must not crash on "D"

    assert df.loc[0, "EMP"] == "D"


@patch("src.ingestion.fetch_census.requests.get")
def test_fetch_cbp_non_json_gives_clear_error(mock_get):
    mock_get.return_value = mock_response(json_error=True)
    with pytest.raises(RuntimeError, match="API key"):
        fetch_cbp(2023, STATES, "bad-key")


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    monkeypatch.setattr("src.ingestion.fetch_census.load_dotenv", lambda: None)
    with pytest.raises(RuntimeError, match="CENSUS_API_KEY"):
        get_api_key()
