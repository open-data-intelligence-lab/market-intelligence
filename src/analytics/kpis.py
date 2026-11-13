"""KPI calculations for the Market Intelligence Explorer.

Plain pandas, no Streamlit, so every number can be tested. The rules follow
docs/kpi_definitions.md:
- missing values stay missing (never 0); results say how many were missing;
- growth compares only cells (area x sector) published in BOTH years;
- payroll is stored in $1,000s and converted to dollars here;
- ratios are ratios of sums, and a zero or missing denominator gives None.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.config import processed_path
from src.validation.validate_cbp import load_cbp_csv, validate_cbp

MEASURES = {
    "establishments": "Establishments",
    "employees": "Employees (mid-March)",
    "annual_payroll_thousands": "Annual payroll",
}
UNCLASSIFIED = "99"  # "Industries not classified": kept in totals, never ranked

# Minimum base-year establishments before a growth rate is shown or ranked.
MIN_BASE_GROWTH = 20  # any growth %
MIN_BASE_STATE_SECTOR = 500  # fastest-growing sectors, state level
MIN_BASE_COUNTY_SECTOR = 20  # fastest-growing sectors, single county
MIN_BASE_COUNTY = 100  # county growth rankings


# --- loading -----------------------------------------------------------------


@dataclass
class Dataset:
    state: pd.DataFrame
    county: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def load_data(state_path=None, county_path=None) -> Dataset:
    """Load both processed CSVs through the existing validator.

    Raises FileNotFoundError with the command to build the data if missing.
    """
    state_path = state_path or processed_path("state")
    county_path = county_path or processed_path("county")
    for path in (state_path, county_path):
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Build it with: python -m src.ingestion.fetch_census"
            )
    state = validate_cbp(load_cbp_csv(state_path))
    county = validate_cbp(load_cbp_csv(county_path))
    return Dataset(state.data, county.data, state.warnings + county.warnings)


def area_column(df: pd.DataFrame) -> str:
    return "county_fips" if "county_fips" in df.columns else "state_fips"


def filter_rows(df, years=None, states=None, counties=None, naics=None) -> pd.DataFrame:
    """Keep rows matching every given filter. None or an empty list means 'all'."""
    mask = pd.Series(True, index=df.index)
    for col, values in [
        ("year", years), ("state_fips", states), ("county_fips", counties), ("naics_code", naics)
    ]:
        if values:
            mask &= df[col].isin(values)
    return df[mask]


# --- basic arithmetic --------------------------------------------------------


def pct_change(new, old) -> float | None:
    """Percent change, or None if either value is missing or old is 0."""
    if new is None or old is None or pd.isna(new) or pd.isna(old) or old == 0:
        return None
    return (new - old) / old * 100


def cagr(start, end, years: int) -> float | None:
    """Compound annual growth rate in %, or None when it can't be computed."""
    if start is None or end is None or pd.isna(start) or pd.isna(end):
        return None
    if start <= 0 or end < 0 or years <= 0:
        return None
    return ((end / start) ** (1 / years) - 1) * 100


@dataclass
class Total:
    """A summed measure. value is None when nothing was available to sum."""

    value: float | None
    missing: int  # rows left out because the value was missing/suppressed

    @property
    def partial(self) -> bool:
        return self.missing > 0


def measure_total(df: pd.DataFrame, measure: str) -> Total:
    values = df[measure]
    missing = int(values.isna().sum())
    if values.notna().sum() == 0:
        return Total(None, missing)
    total = float(values.sum())  # skips NA
    if measure == "annual_payroll_thousands":
        total *= 1000  # $1,000s -> dollars
    return Total(total, missing)


def average_pay(df: pd.DataFrame) -> float | None:
    """Average annual pay per employee in dollars (ratio of sums).

    Uses only rows where payroll and employees are both present and
    employees > 0 (zero-employee rows are likely withheld employment).
    """
    ok = df["annual_payroll_thousands"].notna() & df["employees"].notna() & (df["employees"] > 0)
    employees = df.loc[ok, "employees"].sum()
    if employees == 0:
        return None
    return float(df.loc[ok, "annual_payroll_thousands"].sum()) * 1000 / float(employees)


# --- growth ------------------------------------------------------------------


@dataclass
class Growth:
    start_year: int
    end_year: int
    start: float | None
    end: float | None
    reason: str | None = None  # why growth is unavailable, if it is

    @property
    def change(self) -> float | None:
        return None if self.start is None or self.end is None else self.end - self.start

    @property
    def pct(self) -> float | None:
        return None if self.reason else pct_change(self.end, self.start)


def matched_totals(df: pd.DataFrame, start_year: int, end_year: int, measure: str) -> tuple:
    """Sum `measure` over area x sector cells present (and non-missing) in both years.

    Returns (start_total, end_total, n_matched_cells).
    """
    key = [area_column(df), "naics_code"]
    a = df[df["year"] == start_year].dropna(subset=[measure]).set_index(key)[measure]
    b = df[df["year"] == end_year].dropna(subset=[measure]).set_index(key)[measure]
    both = a.index.intersection(b.index)
    return float(a[both].sum()), float(b[both].sum()), len(both)


def growth(df: pd.DataFrame, start_year: int, end_year: int, measure="establishments") -> Growth:
    """Growth between two years on matched cells, with a reason when unavailable."""
    if df.empty:
        return Growth(start_year, end_year, None, None, "no data for this selection")
    years = set(df["year"].unique())
    missing_years = [y for y in (start_year, end_year) if y not in years]
    if missing_years:
        return Growth(start_year, end_year, None, None,
                      f"no published data for {', '.join(map(str, missing_years))}")
    vintages = set(df.loc[df["year"].isin([start_year, end_year]), "naics_vintage"])
    if len(vintages) > 1:
        return Growth(start_year, end_year, None, None, f"industry codes differ ({sorted(vintages)})")

    start, end, n = matched_totals(df, start_year, end_year, measure)
    if n == 0:
        return Growth(start_year, end_year, None, None, "no data published in both years (withheld)")
    if measure == "annual_payroll_thousands":
        start, end = start * 1000, end * 1000
    if measure == "establishments" and start < MIN_BASE_GROWTH:
        return Growth(start_year, end_year, start, end, f"base below {MIN_BASE_GROWTH} establishments")
    return Growth(start_year, end_year, start, end)


def yoy_growth(df: pd.DataFrame, year: int, measure="establishments") -> Growth:
    return growth(df, year - 1, year, measure)


def _in_dollars(out: pd.DataFrame, measure: str, col: str = "value") -> pd.DataFrame:
    """Payroll is stored in $1,000s; every function here returns dollars."""
    if measure == "annual_payroll_thousands":
        out[col] = out[col] * 1000
    return out


# --- KPI cards -----------------------------------------------------------------


def kpi_summary(df: pd.DataFrame, year: int) -> dict:
    """Totals for one year plus YoY establishment growth. df is already filtered
    by area and industry but contains every year."""
    this_year = df[df["year"] == year]
    return {
        "establishments": measure_total(this_year, "establishments"),
        "employees": measure_total(this_year, "employees"),
        "payroll": measure_total(this_year, "annual_payroll_thousands"),
        "average_pay": average_pay(this_year),
        "yoy_establishments": yoy_growth(df, year, "establishments"),
    }


# --- industries ----------------------------------------------------------------


def industry_breakdown(df: pd.DataFrame, year: int, measure: str) -> pd.DataFrame:
    """One row per sector for one year: value and share of all sectors in df.

    Pass df filtered by area only, so shares are of the area's whole economy.
    """
    rows = df[df["year"] == year]
    out = (
        rows.groupby(["naics_code", "industry_name"], as_index=False)[measure]
        .sum(min_count=1)
        .rename(columns={measure: "value"})
    )
    out = _in_dollars(out, measure)
    total = out["value"].sum()
    out["share_pct"] = out["value"] / total * 100 if total else pd.NA
    return out.sort_values("value", ascending=False).reset_index(drop=True)


def industry_trend(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Sum of `measure` per year and sector (long format, for line charts)."""
    out = (
        df.groupby(["year", "naics_code", "industry_name"], as_index=False)[measure]
        .sum(min_count=1)
        .rename(columns={measure: "value"})
    )
    return _in_dollars(out, measure)


def sector_growth(
    df: pd.DataFrame, start_year: int, end_year: int, measure="establishments", min_base=None
) -> pd.DataFrame:
    """Growth per sector on matched cells, sorted fastest first.

    Excludes "Industries not classified" (99). `eligible` is False for sectors
    whose base-year establishments are below min_base.
    """
    if min_base is None:
        single_county = "county_fips" in df.columns and df["county_fips"].nunique() == 1
        min_base = MIN_BASE_COUNTY_SECTOR if single_county else MIN_BASE_STATE_SECTOR
    rows = []
    for (code, name), sector in df[df["naics_code"] != UNCLASSIFIED].groupby(["naics_code", "industry_name"]):
        g = growth(sector, start_year, end_year, measure)
        base_estab, _, _ = matched_totals(sector, start_year, end_year, "establishments")
        rows.append({
            "naics_code": code,
            "industry_name": name,
            "start": g.start,
            "end": g.end,
            "change": g.change,
            "pct": g.pct,
            "cagr": cagr(g.start, g.end, end_year - start_year) if not g.reason else None,
            "eligible": g.pct is not None and base_estab >= min_base,
        })
    out = pd.DataFrame(rows, columns=["naics_code", "industry_name", "start", "end", "change", "pct", "cagr", "eligible"])
    return out.sort_values("pct", ascending=False, na_position="last").reset_index(drop=True)


# --- counties ------------------------------------------------------------------


def county_ranking(county: pd.DataFrame, year: int, measure: str) -> pd.DataFrame:
    """Counties ranked by `measure` in one year (sum of published sector cells)."""
    rows = county[county["year"] == year]
    out = (
        rows.groupby(["county_fips", "county_name", "state_name"], as_index=False)[measure]
        .sum(min_count=1)
        .rename(columns={measure: "value"})
        .sort_values("value", ascending=False)
        .reset_index(drop=True)
    )
    out = _in_dollars(out, measure)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def county_growth(
    county: pd.DataFrame, start_year: int, end_year: int, measure="establishments", min_base=MIN_BASE_COUNTY
) -> pd.DataFrame:
    """Growth per county on matched cells, sorted fastest first.

    `eligible` is False below min_base establishments; `note` explains any n/a.
    Same rules as growth(), done for all counties at once for speed.
    """
    columns = ["county_fips", "county_name", "state_name", "start", "end", "change", "pct", "eligible", "note"]
    if county.empty:
        return pd.DataFrame(columns=columns)
    key = ["county_fips", "naics_code"]
    a = county[county["year"] == start_year].dropna(subset=[measure]).set_index(key)
    b = county[county["year"] == end_year].dropna(subset=[measure]).set_index(key)
    both = a.index.intersection(b.index)
    a, b = a.loc[both], b.loc[both]

    out = county.drop_duplicates("county_fips").set_index("county_fips")[["county_name", "state_name"]]
    out["start"] = a.groupby(level="county_fips")[measure].sum().astype(float)
    out["end"] = b.groupby(level="county_fips")[measure].sum().astype(float)
    base_estab = a.groupby(level="county_fips")["establishments"].sum().reindex(out.index)
    out = _in_dollars(_in_dollars(out, measure, "start"), measure, "end")
    out["change"] = out["end"] - out["start"]

    has_data = out["start"].notna()
    big_enough = base_estab >= min_base
    can_grow = has_data & (base_estab >= MIN_BASE_GROWTH) & (out["start"] > 0)
    out["pct"] = (out["change"] / out["start"] * 100).where(can_grow)
    out["eligible"] = (can_grow & big_enough).astype(bool)
    out["note"] = ""
    out.loc[has_data & ~big_enough.fillna(False), "note"] = f"base below {min_base} establishments"
    out.loc[~has_data, "note"] = f"no published data in both {start_year} and {end_year}"

    out = out.reset_index()[columns]
    return out.sort_values("pct", ascending=False, na_position="last").reset_index(drop=True)


def area_trend(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Sum of `measure` per year and area (state or county), for line charts."""
    name = "county_name" if "county_fips" in df.columns else "state_name"
    out = df.groupby(["year", name], as_index=False)[measure].sum(min_count=1)
    return _in_dollars(out.rename(columns={name: "area", measure: "value"}), measure)


# --- data quality ----------------------------------------------------------------


def rows_by_year_state(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index="year", columns="state_name", values="naics_code", aggfunc="count", fill_value=0)


def missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Per measure: missing (suppressed) count and zero-value count."""
    return pd.DataFrame({
        "missing or suppressed": df[list(MEASURES)].isna().sum(),
        "zero values": (df[list(MEASURES)] == 0).sum(),
    })


def county_cell_coverage(county: pd.DataFrame, n_sectors: int = 20) -> pd.DataFrame:
    """Per year: county x sector cells published vs possible."""
    counties = county["county_fips"].nunique()
    out = county.groupby("year").size().rename("published cells").to_frame()
    out["possible cells"] = counties * n_sectors
    out["not published"] = out["possible cells"] - out["published cells"]
    return out


def counties_without_data(county: pd.DataFrame) -> pd.DataFrame:
    """Counties with sector rows in some years but none in others."""
    present = county.groupby("county_fips")["year"].apply(set)
    years = set(county["year"].unique())
    names = county.drop_duplicates("county_fips").set_index("county_fips")["county_name"]
    rows = [
        {"county_fips": f, "county_name": names[f], "years without data": ", ".join(map(str, sorted(years - ys)))}
        for f, ys in present.items() if ys != years
    ]
    return pd.DataFrame(rows, columns=["county_fips", "county_name", "years without data"])


def county_share_of_state(state: pd.DataFrame, county: pd.DataFrame) -> pd.DataFrame:
    """% of each state total captured by summing published county cells."""
    cols = list(MEASURES)
    s = state.groupby(["year", "state_name"])[cols].sum()
    c = county.groupby(["year", "state_name"])[cols].sum()
    return (c / s * 100).astype(float).round(1)


# --- formatting --------------------------------------------------------------------


def format_number(value) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:,.0f}"


def format_dollars(value) -> str:
    """e.g. $1,218.2B, $71.1M, $56,950."""
    if value is None or pd.isna(value):
        return "n/a"
    for size, unit in [(1e9, "B"), (1e6, "M")]:
        if abs(value) >= size:
            return f"${value / size:,.1f}{unit}"
    return f"${value:,.0f}"


def format_pct(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.1f}%".replace("-", "−")
