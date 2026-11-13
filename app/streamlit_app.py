"""Market Intelligence Explorer: Streamlit app for Census CBP data.

Run from the project root:
    streamlit run app/streamlit_app.py

All calculations live in src/analytics/kpis.py; this file only lays out the page.
"""

import sys
from pathlib import Path

import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `src` importable

from src.analytics import kpis  # noqa: E402
from src.config import NAICS_SECTORS, STATES  # noqa: E402

st.set_page_config(page_title="Market Intelligence Explorer", layout="wide")

STATE_COLORS = {"Colorado": "#2a78d6", "Kansas": "#eb6834", "Missouri": "#1baf7a", "Texas": "#eda100"}
BAR_COLOR = "#2a78d6"
SOURCE = "Source: U.S. Census Bureau, County Business Patterns 2020–2023 (NAICS 2017)."
PAYROLL = "annual_payroll_thousands"
MEASURE_LABELS = {
    "establishments": "Establishments",
    "employees": "Employees (mid-March)",
    PAYROLL: "Annual payroll ($, nominal)",
}


@st.cache_data
def load():
    return kpis.load_data()



def measure_picker(key):
    return st.radio("Measure", list(MEASURE_LABELS), format_func=MEASURE_LABELS.get,
                    horizontal=True, key=key)


def year_pair(key, years, default_end):
    c1, c2 = st.columns(2)
    end = c2.selectbox("To", years, index=years.index(default_end), key=f"{key}_end")
    earlier = [y for y in years if y < end]
    if not earlier:
        st.info(f"{end} is the first year in the data, so there is no earlier year to compare with.")
        return None, end
    start = c1.selectbox("From", earlier, index=len(earlier) - 1, key=f"{key}_start")
    return start, end


def chart(fig, height=None):
    fig.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=40, b=10),
                      legend_title_text="", height=height)
    st.plotly_chart(fig, width="stretch")


# --- data ----------------------------------------------------------------------

try:
    data = load()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

years = sorted(int(y) for y in data.state["year"].unique())
state_by_name = {name: fips for fips, name in STATES.items()}
sector_by_label = {f"{name} ({code})": code for code, name in NAICS_SECTORS.items()}

# --- sidebar filters --------------------------------------------------------------

st.sidebar.title("Filters")
year = st.sidebar.selectbox("Year", years, index=len(years) - 1)
state_names = st.sidebar.multiselect("States", list(state_by_name), default=list(state_by_name))
states = [state_by_name[n] for n in state_names]

county_options = (
    data.county[data.county["state_fips"].isin(states)]
    .drop_duplicates("county_fips")
    .sort_values("county_name")
)
county_names = dict(zip(county_options["county_fips"], county_options["county_name"]))
counties = st.sidebar.multiselect(
    "Counties (optional)", list(county_names), format_func=county_names.get,
    help="Leave empty to see state totals. Picking counties switches to published county data.",
)
sector_labels = st.sidebar.multiselect(
    "Industries (optional)", list(sector_by_label), help="Leave empty for all 20 sectors."
)
industries = [sector_by_label[s] for s in sector_labels]

st.sidebar.caption(SOURCE)

if not states:
    st.title("Market Intelligence Explorer")
    st.warning("Select at least one state in the sidebar.")
    st.stop()

# Area rows (all years, all industries) and the view with the industry filter.
# Per docs/kpi_definitions.md: state totals come from the state file;
# counties only when counties are chosen. The two files are never mixed.
if counties:
    area = kpis.filter_rows(data.county, counties=counties)
    area_label = f"Published county data: {len(counties)} count{'y' if len(counties) == 1 else 'ies'}"
else:
    area = kpis.filter_rows(data.state, states=states)
    area_label = f"State totals: {', '.join(state_names)}"
view = kpis.filter_rows(area, naics=industries)
industry_label = f"{len(industries)} selected industr{'y' if len(industries) == 1 else 'ies'}" if industries else "all industries"

st.title("Market Intelligence Explorer")
st.caption(f"{area_label} · {industry_label} · {year}")

overview, industry_tab, county_tab, quality_tab = st.tabs(
    ["Overview", "Industry Trends", "County Comparison", "Data Quality"]
)

# --- Overview ------------------------------------------------------------------------

with overview:
    if view.empty:
        st.warning("No data for this selection. Try other filters.")
    else:
        summary = kpis.kpi_summary(view, year)
        yoy = summary["yoy_establishments"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Establishments", kpis.format_number(summary["establishments"].value),
                  help="Business locations with paid employees (not companies).")
        c2.metric("Employees (mid-March)", kpis.format_number(summary["employees"].value),
                  help="Paid employees in the pay period including March 12.")
        c3.metric("Annual payroll", kpis.format_dollars(summary["payroll"].value),
                  help="Total annual payroll in nominal dollars (not inflation-adjusted).")
        c4.metric(f"Establishment growth {year - 1}→{year}", kpis.format_pct(yoy.pct),
                  delta=None if yoy.change is None else f"{yoy.change:+,.0f} establishments",
                  help="Year-over-year change on cells published in both years.")

        notes = [f"Average annual pay per employee: **{kpis.format_dollars(summary['average_pay'])}**."]
        if view[view["year"] == year].empty:
            notes = [f"**No published data for {year}** in this selection (Census withheld it or "
                     "there were no establishments). Shown as n/a, not zero."]
        if yoy.reason:
            notes.append(f"Growth n/a: {yoy.reason}.")
        partial = [k for k in ("establishments", "employees", "payroll") if summary[k].partial]
        if partial:
            notes.append(f"Partial data: some values are suppressed for {', '.join(partial)}.")
        if counties:
            notes.append("County figures are sums of published cells and run slightly below official totals.")
        st.markdown(" ".join(notes))

        st.subheader("Trend over time")
        measure = measure_picker("overview_measure")
        indexed = st.toggle(f"Index to {years[0]} = 100", value=len(view["state_fips"].unique()) > 1 or bool(counties))
        trend = kpis.area_trend(view, measure)
        y_label = MEASURE_LABELS[measure]
        if indexed:
            base = trend[trend["year"] == years[0]].set_index("area")["value"]
            trend["value"] = trend["value"] / trend["area"].map(base) * 100
            y_label = f"Index ({years[0]} = 100)"
        fig = px.line(trend, x="year", y="value", color="area", markers=True,
                      color_discrete_map=STATE_COLORS, labels={"value": y_label, "year": ""})
        fig.update_xaxes(dtick=1)
        chart(fig, height=380)
        st.caption("2020 employment was counted in mid-March 2020, mostly before the COVID-19 "
                   "lockdowns; 2020 payroll covers the whole year. Payroll is nominal.")

# --- Industry Trends -------------------------------------------------------------------

with industry_tab:
    measure = measure_picker("industry_measure")

    st.subheader(f"Industry mix, {year}")
    mix = kpis.industry_breakdown(area, year, measure)
    if mix.empty or mix["value"].isna().all():
        st.info("No industry data for this selection and year.")
    else:
        mix = mix.sort_values("value")
        fig = px.bar(mix, x="value", y="industry_name", orientation="h",
                     hover_data={"share_pct": ":.1f", "naics_code": True},
                     labels={"value": MEASURE_LABELS[measure], "industry_name": "", "share_pct": "Share %"})
        fig.update_traces(marker_color=BAR_COLOR)
        chart(fig, height=600)
        st.caption("Shares are of all 20 sectors in the selected area, regardless of the industry filter.")

    st.subheader("Historical trend by industry")
    trend = kpis.industry_trend(view, measure)
    if trend.empty:
        st.info("No data for this selection.")
    else:
        if not industries:
            latest = trend[trend["year"] == trend["year"].max()]
            top = latest.nlargest(5, "value")["naics_code"]
            trend = trend[trend["naics_code"].isin(top)]
            st.caption("Showing the 5 largest sectors. Pick industries in the sidebar to compare others.")
        fig = px.line(trend, x="year", y="value", color="industry_name", markers=True,
                      labels={"value": MEASURE_LABELS[measure], "year": "", "industry_name": ""})
        fig.update_xaxes(dtick=1)
        chart(fig, height=420)

    st.subheader("Fastest-growing industries")
    start, end = year_pair("sector_growth", years, year)
    if start is not None:
        growth = kpis.sector_growth(area, start, end, measure)
        ranked = growth[growth["eligible"]]
        if ranked.empty:
            st.info("No industries large enough to rank for this selection.")
        else:
            fig = px.bar(ranked.sort_values("pct"), x="pct", y="industry_name", orientation="h",
                         hover_data={"start": ":,.0f", "end": ":,.0f", "change": ":+,.0f", "cagr": ":.2f"},
                         labels={"pct": f"% change {start}→{end}", "industry_name": "", "cagr": "CAGR %"})
            fig.update_traces(marker_color=BAR_COLOR)
            chart(fig, height=560)
        excluded = growth[~growth["eligible"]]
        st.caption(
            f"Excludes 'Industries not classified' (99) and {len(excluded)} sector(s) below the minimum size "
            "or without data in both years. Growth uses cells published in both years."
            + (" Payroll growth is nominal." if measure == PAYROLL else "")
        )

# --- County Comparison -------------------------------------------------------------------

with county_tab:
    county_rows = kpis.filter_rows(data.county, states=states, counties=counties, naics=industries)
    if county_rows.empty:
        st.warning("No county data for this selection.")
    else:
        measure = measure_picker("county_measure")
        top_n = st.slider("Counties to show", 5, 30, 10)

        st.subheader(f"County ranking, {year}")
        ranking = kpis.county_ranking(county_rows, year, measure)
        if ranking.empty:
            st.info(f"No county data for {year}.")
        else:
            shown = ranking.head(top_n).iloc[::-1]
            fig = px.bar(shown, x="value", y="county_name", color="state_name", orientation="h",
                         color_discrete_map=STATE_COLORS,
                         labels={"value": MEASURE_LABELS[measure], "county_name": "", "state_name": ""})
            chart(fig, height=max(300, 28 * len(shown) + 80))
            st.caption("Sums of published county cells. Large counties dominate raw totals; "
                       "see growth below for a size-neutral view.")

        st.subheader("County growth")
        start, end = year_pair("county_growth", years, year)
        if start is not None:
            cg = kpis.county_growth(county_rows, start, end, measure)
            ranked = cg[cg["eligible"]]
            if ranked.empty:
                st.info("No counties large enough to rank (minimum 100 establishments in the base year).")
            else:
                c1, c2 = st.columns(2)
                for col, title, rows in [(c1, "Fastest growing", ranked.head(top_n)),
                                         (c2, "Slowest growing", ranked.tail(top_n).iloc[::-1])]:
                    col.markdown(f"**{title}**")
                    col.dataframe(
                        rows[["county_name", "start", "end", "pct"]].rename(columns={
                            "county_name": "County", "start": str(start), "end": str(end), "pct": "% change"}),
                        hide_index=True, width="stretch",
                        column_config={str(start): st.column_config.NumberColumn(format="%,.0f"),
                                       str(end): st.column_config.NumberColumn(format="%,.0f"),
                                       "% change": st.column_config.NumberColumn(format="%+.1f%%")},
                    )
            unavailable = cg[~cg["eligible"]]
            with st.expander(f"{len(unavailable)} counties not ranked"):
                st.dataframe(unavailable[["county_name", "state_name", "note"]], hide_index=True,
                             width="stretch")
            st.caption("Counties need at least 100 establishments in the base year. Growth uses only "
                       "county × industry cells published in both years.")

        if counties:
            st.subheader("Selected counties over time")
            trend = kpis.area_trend(county_rows, measure)
            fig = px.line(trend, x="year", y="value", color="area", markers=True,
                          labels={"value": MEASURE_LABELS[measure], "year": "", "area": ""})
            fig.update_xaxes(dtick=1)
            chart(fig, height=380)

# --- Data Quality ---------------------------------------------------------------------------

with quality_tab:
    st.subheader("Coverage")
    c1, c2 = st.columns(2)
    c1.markdown("**State file: rows by year and state**")
    c1.dataframe(kpis.rows_by_year_state(data.state), width="stretch")
    c2.markdown("**County file: rows by year and state**")
    c2.dataframe(kpis.rows_by_year_state(data.county), width="stretch")

    st.markdown("**County × industry cells published**")
    st.dataframe(kpis.county_cell_coverage(data.county), width="stretch")
    st.caption("Census leaves out county cells with no establishments or with withheld data. "
               "Missing cells are treated as unknown, never as zero.")

    st.markdown("**Counties with no published industry data in some years**")
    st.dataframe(kpis.counties_without_data(data.county), hide_index=True, width="stretch")

    st.markdown("**Share of state totals captured by county data (%)**")
    st.dataframe(kpis.county_share_of_state(data.state, data.county), width="stretch")

    st.subheader("Missing, suppressed and zero values")
    c1, c2 = st.columns(2)
    c1.markdown("**State file**")
    c1.dataframe(kpis.missing_values(data.state), width="stretch")
    c2.markdown("**County file**")
    c2.dataframe(kpis.missing_values(data.county), width="stretch")

    with st.expander(f"Validation warnings ({len(data.warnings)})"):
        for warning in data.warnings:
            st.text(warning)

    st.subheader("Methodology")
    st.markdown(
        """
- **Data**: Census County Business Patterns, 2020–2023, two-digit NAICS 2017 sectors. Covers
  establishments with paid employees; excludes self-employed people, most farms, government,
  railroads and private households.
- **No double counting**: sectors add up to the total. State totals come from the state file,
  never from summing counties.
- **Payroll** is stored in $1,000s and shown in dollars, nominal (not inflation-adjusted).
- **Employees** are counted in the mid-March pay period. 2020 is mostly pre-pandemic.
- **Growth** compares only area × industry cells published in both years. A growth rate is not
  shown when the base year has fewer than 20 establishments.
- **Missing or suppressed values** are never replaced with zero. Totals with missing parts are
  marked partial.
- **Noise**: Census adds small random noise to employment and payroll; small changes in small
  counties may not be meaningful.

Full definitions: `docs/kpi_definitions.md`. Data details: `docs/data_sources.md`.
"""
    )
    st.caption(SOURCE)
