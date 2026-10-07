"""Streamlit dashboard for lineup-level field diagnostics."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from field_model import (
    SlateConfig,
    contest_from_draftkings,
    contest_from_long,
    contest_from_wide,
)
from field_model.dashboard import (
    DashboardAnalysis,
    build_analysis,
    build_demo_analysis,
    comparison_cards,
    duplication_comparison,
    lineup_detail,
    ownership_table,
    pair_signal_table,
    salary_distribution,
)
from field_model.interview import (
    controlled_bundle,
    controlled_fields,
    controlled_summary,
    report_bundle,
    wide_entries,
)

st.set_page_config(
    page_title="DFS Field Lab",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    _inject_style()
    source = _sidebar_source()
    if source == "Start here: same ownership":
        _hero("Controlled synthetic example · exactly matching ownership")
        _render_controlled()
        return
    if source == "Synthetic demo":
        with st.spinner("Loading a legal synthetic field and ownership-only null…"):
            analysis = _cached_demo()
        source_note = "Synthetic demo · no private or proprietary data"
    else:
        analysis = _upload_analysis()
        source_note = "User-provided files · processed in this app session"
        if analysis is None:
            _render_upload_welcome()
            return

    _hero(source_note)
    st.download_button(
        "Download analysis report",
        report_bundle(
            analysis,
            source="Synthetic demo" if source == "Synthetic demo" else "User upload",
        ),
        file_name="field-analysis.zip",
        mime="application/zip",
    )
    st.caption(
        "Report includes aggregate player labels and metrics. Review uploaded results before sharing."
    )
    _render_summary(analysis)
    view = st.radio(
        "Analysis view",
        ["Overview", "Ownership", "Pair structure", "Lineup inspector", "Method"],
        horizontal=True,
        label_visibility="collapsed",
    )
    if view == "Overview":
        _render_overview(analysis)
    elif view == "Ownership":
        _render_ownership(analysis)
    elif view == "Pair structure":
        _render_dependence(analysis)
    elif view == "Lineup inspector":
        _render_inspector(analysis)
    else:
        _render_method(analysis)


def _sidebar_source() -> str:
    st.sidebar.markdown("### Field input")
    source = st.sidebar.radio(
        "Data source",
        ["Start here: same ownership", "Synthetic demo", "Upload CSVs"],
        help="Demo mode is deterministic and uses generated data only.",
    )
    st.sidebar.markdown("---")
    with st.sidebar.expander("Download sample CSVs"):
        demo = _cached_demo()
        st.download_button(
            "Player pool",
            demo.pool.to_csv(index=False),
            "sample-player-pool.csv",
            "text/csv",
        )
        st.download_button(
            "Contest entries (wide)",
            wide_entries(demo).to_csv(index=False),
            "sample-entries.csv",
            "text/csv",
        )
        st.caption(
            "Use Wide format and the default roster rules to reload these samples."
        )
    st.sidebar.caption(
        "This project measures lineup structure. It does not predict outcomes, "
        "recommend wagers, or estimate production expected value."
    )
    return source


@st.cache_data(show_spinner=False)
def _cached_demo() -> DashboardAnalysis:
    return build_demo_analysis()


def _metric_grid(metrics: list[tuple[str, str, str]]) -> None:
    for start in range(0, len(metrics), 2):
        for column, (label, value, help_text) in zip(
            st.columns(2), metrics[start : start + 2], strict=False
        ):
            column.metric(label, value, help=help_text)


def _render_controlled() -> None:
    st.subheader("Same ownership. Three times the concentration.")
    st.write(
        "Four players. Two slots per lineup. Twelve entries in each field. Every player appears in exactly half the entries."
    )
    st.dataframe(
        controlled_summary().round({"Lineup HHI": 3, "Effective lineups": 1}),
        hide_index=True,
        width="stretch",
    )
    clustered, spread = controlled_fields()
    constructions = pd.DataFrame(
        [
            {
                "Lineup": "".join(sorted(lineup)),
                "Entries": count,
                "Field": analysis.field.contest_id,
            }
            for analysis in (clustered, spread)
            for lineup, count in analysis.field.entries["lineup"].value_counts().items()
        ]
    )
    _grouped_chart(constructions, "Lineup", "Entries", "Field")
    st.info(
        "Ownership cannot distinguish these fields: A, B, C, and D are all at 50%. Exact-lineup HHI is 0.500 versus 0.167; effective lineup counts are 2 versus 6."
    )
    st.markdown(
        "**Why it matters:** selecting players together changes joint exposure. AB appears in 50% of the clustered field and only 16.7% of the spread field."
    )
    st.caption(
        "This exact construction proves information loss in marginals. It is a teaching example, not a fitted description of real entrants."
    )
    with st.expander("How to calculate HHI"):
        st.code(
            "Clustered: (6/12)² + (6/12)² = 0.500\nSpread:    6 × (2/12)² = 0.167\nEffective lineups = 1 / HHI"
        )
    st.download_button(
        "Download controlled case study",
        controlled_bundle(),
        "controlled-comparison.zip",
        "application/zip",
    )
    st.write(
        "Next: choose Synthetic demo in the sidebar to explore realistic roster constraints and an approximate ownership null."
    )


def _grouped_chart(
    data: pd.DataFrame,
    category: str,
    value: str,
    group: str,
    *,
    horizontal: bool = False,
) -> None:
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(f"{value}:Q" if horizontal else f"{category}:N"),
            y=alt.Y(f"{category}:N" if horizontal else f"{value}:Q"),
            color=alt.Color(
                f"{group}:N", scale=alt.Scale(range=["#48c6a8", "#8797ff"])
            ),
            tooltip=[category, value, group],
            **({"yOffset": f"{group}:N"} if horizontal else {"xOffset": f"{group}:N"}),
        )
    )
    st.altair_chart(chart, use_container_width=True)


def _upload_analysis() -> DashboardAnalysis | None:
    st.sidebar.markdown("### Upload configuration")
    pool_file = st.sidebar.file_uploader("Player pool CSV", type="csv")
    entries_file = st.sidebar.file_uploader("Contest entries CSV", type="csv")
    format_name = st.sidebar.selectbox(
        "Entry format", ["Wide", "Long", "DraftKings-style"]
    )
    include_null = st.sidebar.toggle("Build ownership-only null", value=True)

    with st.sidebar.expander("Roster rules", expanded=False):
        roster_size = st.number_input("Roster size", min_value=1, value=8, step=1)
        salary_cap = st.number_input("Salary cap", min_value=1, value=50_000, step=500)
        position_min_text = st.text_input("Position minimums", value="GK=1,D=2,M=2,F=2")
        flex_text = st.text_input("Flex positions", value="D,M,F")
        max_per_team = st.number_input("Maximum per team", min_value=1, value=4, step=1)

    with st.sidebar.expander("Column mapping", expanded=False):
        entry_id_column = st.text_input("Entry ID column", value="entry_id")
        account_column = st.text_input("Account column (optional)", value="")
        score_column = st.text_input("Score column (optional)", value="")
        if format_name == "Wide":
            player_columns_text = st.text_input(
                "Player columns (optional)",
                value="",
                help="Comma-separated. Leave blank to detect player1, player2, …",
            )
            player_id_column = "player_id"
            lineup_column = "Lineup"
            roster_slots_text = ""
        elif format_name == "Long":
            player_id_column = st.text_input("Player ID column", value="player_id")
            player_columns_text = ""
            lineup_column = "Lineup"
            roster_slots_text = ""
        else:
            lineup_column = st.text_input("Lineup column", value="Lineup")
            roster_slots_text = st.text_input(
                "Ordered roster slots", value="GK,D,D,M,M,F,F,UTIL"
            )
            player_columns_text = ""
            player_id_column = "player_id"

    if pool_file is None or entries_file is None:
        return None
    signature = sha256(
        pool_file.getvalue()
        + entries_file.getvalue()
        + repr(
            (
                format_name,
                include_null,
                roster_size,
                salary_cap,
                position_min_text,
                flex_text,
                max_per_team,
                entry_id_column,
                account_column,
                score_column,
                player_columns_text,
                player_id_column,
                lineup_column,
                roster_slots_text,
            )
        ).encode()
    ).hexdigest()
    if not st.sidebar.button("Analyze field", type="primary", width="stretch"):
        if signature == st.session_state.get("uploaded_signature"):
            return st.session_state.get("uploaded_analysis")
        return None

    try:
        pool = pd.read_csv(BytesIO(pool_file.getvalue()))
        entries = pd.read_csv(BytesIO(entries_file.getvalue()))
        config = SlateConfig(
            roster_size=int(roster_size),
            salary_cap=int(salary_cap),
            position_min=_parse_position_minimums(position_min_text),
            flex_positions=tuple(_split_csv(flex_text)),
            max_per_team=int(max_per_team),
        )
        metadata = {}
        if account_column.strip():
            metadata["account_id"] = account_column.strip()
        if score_column.strip():
            metadata["score"] = score_column.strip()
        if format_name == "Wide":
            player_columns = _split_csv(player_columns_text) or None
            field = contest_from_wide(
                entries,
                player_columns=player_columns,
                entry_id_column=entry_id_column,
                metadata_columns=metadata,
                contest_id=entries_file.name,
            )
        elif format_name == "Long":
            field = contest_from_long(
                entries,
                entry_id_column=entry_id_column,
                player_id_column=player_id_column,
                metadata_columns=metadata,
                contest_id=entries_file.name,
            )
        else:
            field = contest_from_draftkings(
                entries,
                pool,
                _split_csv(roster_slots_text),
                lineup_column=lineup_column,
                entry_id_column=entry_id_column,
                metadata_columns=metadata,
                contest_id=entries_file.name,
            )
        with st.spinner("Validating lineups and computing diagnostics…"):
            analysis = build_analysis(
                pool, field, config, include_null=include_null, null_walk_steps=12
            )
        st.session_state["uploaded_analysis"] = analysis
        st.session_state["uploaded_signature"] = signature
        return analysis
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        st.sidebar.error(f"Could not analyze these files: {error}")
        return None


def _hero(source_note: str) -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="eyebrow">LINEUP-LEVEL FIELD RESEARCH</div>
          <h1>DFS Field Lab</h1>
          <p>See the dependence that player ownership percentages leave out.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(source_note)


def _render_summary(analysis: DashboardAnalysis) -> None:
    summary = analysis.observed.summary
    metrics = [
        ("Entries", f"{int(summary['entries']):,}", "Complete lineups analyzed"),
        (
            "Unique lineups",
            f"{float(summary['unique_lineup_pct']):.1f}%",
            f"{int(summary['unique_lineups']):,} distinct constructions",
        ),
        (
            "Duplicated entries",
            f"{float(summary['duplicated_entry_pct']):.1f}%",
            "Entries sharing an exact lineup",
        ),
        (
            "Lineup HHI",
            f"{float(summary['lineup_hhi']):.4f}",
            "Higher means more lineup concentration",
        ),
        (
            "Effective lineups",
            f"{float(summary['effective_lineups']):.1f}",
            "Inverse-HHI equivalent lineup count",
        ),
    ]
    _metric_grid(metrics)


def _render_overview(analysis: DashboardAnalysis) -> None:
    st.subheader("Does ownership alone reproduce this field?")
    cards = comparison_cards(analysis)
    if cards:
        _metric_grid([(card["label"], card["value"], card["help"]) for card in cards])
        ratio = analysis.comparison.summary["lineup_hhi_ratio"]
        if np.isfinite(ratio) and ratio < 0.75:
            st.info(
                "The ownership null is less concentrated, but it also misses player ownership. "
                "This gap combines marginal mismatch and joint structure; it does not isolate dependence. "
                "Use the controlled example to see an exact ownership match."
            )
        else:
            st.info(
                "The null comparison does not show a large concentration gap. "
                "Inspect marginal error and pair structure before drawing conclusions."
            )
    else:
        st.warning("Null comparison was disabled for this analysis.")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Exact duplication")
        duplication = duplication_comparison(analysis).rename(
            columns={
                "observed_pct": "Observed field",
                "null_pct": "Ownership null",
                "exact_dup_count": "Copies of lineup",
            }
        )
        chart_data = duplication.melt(
            id_vars="Copies of lineup", var_name="Field", value_name="Entries (%)"
        )
        _grouped_chart(chart_data, "Copies of lineup", "Entries (%)", "Field")
        st.caption("Share of entries at each exact lineup-duplication count.")
    with right:
        st.markdown("#### Salary remaining")
        histogram = _salary_histogram(salary_distribution(analysis))
        st.line_chart(
            histogram.rename(
                columns={"observed": "Observed field", "null": "Ownership null"}
            ),
            color=["#48c6a8", "#8797ff"],
        )
        st.caption("Observed construction versus the legal ownership-only null.")

    if analysis.segment_summary is not None:
        st.markdown("#### Demo generator contrast")
        columns = [
            "segment",
            "entries",
            "unique_pct",
            "lineup_hhi",
            "effective_lineups",
            "mean_jaccard",
            "most_duplicated_lineup",
        ]
        st.dataframe(
            analysis.segment_summary[columns],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "These labels describe synthetic generator hypotheses, not inferred user types."
        )


def _render_ownership(analysis: DashboardAnalysis) -> None:
    st.subheader("Player ownership")
    table = ownership_table(analysis)
    chart_columns = ["ownership_pct"]
    if "null_ownership_pct" in table:
        chart_columns.append("null_ownership_pct")
    chart = table.head(20)[["player", *chart_columns]].rename(
        columns={
            "player": "Player",
            "ownership_pct": "Observed field",
            "null_ownership_pct": "Ownership null",
        }
    )
    _grouped_chart(
        chart.melt(id_vars="Player", var_name="Field", value_name="Ownership (%)"),
        "Player",
        "Ownership (%)",
        "Field",
        horizontal=True,
    )
    st.caption(
        "The null uses observed ownership as proposal weights, but its realized "
        "marginals are reported rather than assumed to match."
    )
    display = table.copy()
    numeric_columns = [
        column
        for column in ["ownership_pct", "null_ownership_pct", "ownership_gap_pp"]
        if column in display
    ]
    display[numeric_columns] = display[numeric_columns].round(2)
    st.dataframe(display.head(40), hide_index=True, width="stretch")


def _render_dependence(analysis: DashboardAnalysis) -> None:
    st.subheader("Player-pair dependence")
    st.markdown(
        "**Excess co-ownership** = observed pair frequency minus the frequency "
        "expected if the two player selections were independent."
    )
    pairs = pair_signal_table(analysis)
    formatted = pairs.rename(
        columns={
            "player_a_name": "Player A",
            "player_b_name": "Player B",
            "coownership_pct": "Observed %",
            "independent_pct": "Independent %",
            "excess_pp": "Excess pp",
            "coownership_lift": "Lift",
        }
    ).round(2)
    st.dataframe(formatted, hide_index=True, width="stretch")
    st.caption(
        "Large positive values identify repeated construction relationships. "
        "They do not establish why entrants selected the pair."
    )

    left, right = st.columns(2)
    with left:
        st.markdown("#### Maximum team stack")
        stacks = analysis.observed.team_stack_distribution.set_index("max_team_stack")[
            ["entry_pct"]
        ]
        st.bar_chart(stacks, color="#48c6a8")
    with right:
        st.markdown("#### Position shape")
        shapes = analysis.observed.position_shape_distribution.set_index(
            "position_shape"
        )[["entry_pct"]]
        st.bar_chart(shapes, color="#8797ff")


def _render_inspector(analysis: DashboardAnalysis) -> None:
    st.subheader("Inspect one complete lineup")
    entry_ids = analysis.observed.entries["entry_id"].astype(str).tolist()
    selected = st.selectbox("Entry ID", entry_ids)
    roster, diagnostics = lineup_detail(analysis, selected)
    values = [
        ("Salary used", f"${diagnostics['salary_used']:,}"),
        ("Salary remaining", f"${diagnostics['salary_remaining']:,}"),
        ("Exact duplicates", f"{diagnostics['exact_dup_count']:,}"),
        ("Largest team stack", str(diagnostics["max_team_stack"])),
        ("Consensus total", f"{diagnostics['consensus_total']:.1f}"),
    ]
    _metric_grid([(label, value, "Entry diagnostic") for label, value in values])
    st.dataframe(roster, hide_index=True, width="stretch")
    st.caption(
        "Consensus total is a synthetic/demo or uploaded projection sum—not a "
        "forecast of contest profit."
    )


def _render_method(analysis: DashboardAnalysis) -> None:
    st.subheader("What the dashboard proves—and what it does not")
    st.markdown(
        """
        **Directly measured**

        - Exact lineup frequencies and duplication
        - Player ownership and player-pair co-ownership
        - Team stacks, roster shapes, and salary usage
        - Differences from a legal ownership-weighted null field

        **Not established by this dashboard**

        - A user's skill level or intent
        - Causal reasons for lineup clustering
        - Future player outcomes or guaranteed returns
        - Production expected value without correlated outcome and payout simulation

        The null field is a transparent comparison, not a perfect
        maximum-entropy model. Its realized ownership error is displayed so a
        structural gap is not confused with a poorly matched baseline.
        """
    )
    with st.expander("Current analysis configuration"):
        st.json(
            {
                "contest_id": analysis.field.contest_id,
                "roster_size": analysis.config.roster_size,
                "salary_cap": analysis.config.salary_cap,
                "position_min": analysis.config.position_min,
                "flex_positions": analysis.config.flex_positions,
                "max_per_team": analysis.config.max_per_team,
                "ownership_only_null": analysis.baseline is not None,
            }
        )


def _render_upload_welcome() -> None:
    _hero("Upload mode · files stay in this app session")
    st.info(
        "Upload both CSV files in the sidebar, configure their columns, then analyze."
    )
    st.markdown(
        """
        ### Required player-pool columns

        `player_id, player, team, pos, salary, true_mean, consensus, fame, recency`

        ### Supported contest layouts

        - **Wide:** one row per entry with one player ID per roster column
        - **Long:** one row per entry-player pair
        - **DraftKings-style:** one lineup string per entry, resolved through the pool

        Invalid player IDs or illegal lineups are rejected before analysis.
        """
    )


def _salary_histogram(values: pd.DataFrame) -> pd.DataFrame:
    maximum = max(float(values["salary_remaining"].max()), 1.0)
    bins = np.linspace(0, maximum, 13)
    frames: list[pd.Series] = []
    for field_name, group in values.groupby("field"):
        counts, edges = np.histogram(group["salary_remaining"], bins=bins)
        centers = ((edges[:-1] + edges[1:]) / 2).round().astype(int)
        frames.append(pd.Series(counts, index=centers, name=field_name))
    return pd.concat(frames, axis=1).fillna(0)


def _parse_position_minimums(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in _split_csv(value):
        if "=" not in item:
            raise ValueError(f"position minimum must contain '=': {item!r}")
        position, minimum = item.split("=", 1)
        result[position.strip()] = int(minimum.strip())
    if not result:
        raise ValueError("at least one position minimum is required")
    return result


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _inject_style() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #0b1220; }
        [data-testid="stSidebar"] { background: #101a2d; }
        .hero {
            border: 1px solid rgba(135, 151, 255, .28);
            border-radius: 20px;
            padding: 2rem 2.2rem;
            margin-bottom: .5rem;
            background:
                radial-gradient(circle at 85% 20%, rgba(72,198,168,.16), transparent 32%),
                linear-gradient(135deg, rgba(135,151,255,.13), rgba(11,18,32,.2));
        }
        .hero h1 { font-size: 3rem; margin: .2rem 0 .35rem; letter-spacing: -.04em; }
        .hero p { color: #b8c4dc; font-size: 1.15rem; margin: 0; }
        .eyebrow { color: #48c6a8; font-size: .75rem; font-weight: 800; letter-spacing: .18em; }
        [data-testid="stMetric"] {
            background: rgba(18, 30, 51, .78);
            border: 1px solid rgba(148, 163, 184, .15);
            border-radius: 14px;
            padding: 1rem;
        }
        [data-testid="stMetricValue"] { color: #f6f8ff; }
        [data-testid="stMetricValue"] > div { white-space: normal; overflow: visible; }
        @media (max-width: 760px) {
            [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
            [data-testid="stColumn"] { min-width: 220px; flex: 1 1 220px; }
            .hero { padding: 1.2rem; }
            .hero h1 { font-size: 2.2rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
