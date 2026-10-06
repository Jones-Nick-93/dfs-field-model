"""Streamlit dashboard for lineup-level field diagnostics."""

from __future__ import annotations

from io import BytesIO

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

st.set_page_config(
    page_title="DFS Field Lab",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    _inject_style()
    source = _sidebar_source()
    if source == "Synthetic demo":
        with st.spinner("Loading a legal synthetic field and ownership-only null…"):
            analysis = build_demo_analysis()
        source_note = "Synthetic demo · no private or proprietary data"
    else:
        analysis = _upload_analysis()
        source_note = "User-provided files · processed in this app session"
        if analysis is None:
            _render_upload_welcome()
            return

    _hero(source_note)
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
        ["Synthetic demo", "Upload CSVs"],
        help="Demo mode is deterministic and uses generated data only.",
    )
    st.sidebar.markdown("---")
    st.sidebar.caption(
        "This project measures lineup structure. It does not predict outcomes, "
        "recommend wagers, or estimate production expected value."
    )
    return source


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
        salary_cap = st.number_input(
            "Salary cap", min_value=1, value=50_000, step=500
        )
        position_min_text = st.text_input(
            "Position minimums", value="GK=1,D=2,M=2,F=2"
        )
        flex_text = st.text_input("Flex positions", value="D,M,F")
        max_per_team = st.number_input(
            "Maximum per team", min_value=1, value=4, step=1
        )

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
    if not st.sidebar.button("Analyze field", type="primary", width="stretch"):
        return st.session_state.get("uploaded_analysis")

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
    columns = st.columns(5)
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
    for column, (label, value, help_text) in zip(columns, metrics, strict=True):
        column.metric(label, value, help=help_text)


def _render_overview(analysis: DashboardAnalysis) -> None:
    st.subheader("Does ownership alone reproduce this field?")
    cards = comparison_cards(analysis)
    if cards:
        columns = st.columns(len(cards))
        for column, card in zip(columns, cards, strict=True):
            column.metric(card["label"], card["value"], help=card["help"])
        ratio = analysis.comparison.summary["lineup_hhi_ratio"]
        if np.isfinite(ratio) and ratio < 0.75:
            st.info(
                "The legal ownership-only null is substantially less concentrated "
                "than the observed field. Marginal ownership is not reproducing the "
                "same exact-lineup structure in this sample."
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
        duplication = duplication_comparison(analysis).set_index("exact_dup_count")
        st.bar_chart(duplication, color=["#48c6a8", "#8797ff"])
        st.caption("Share of entries at each exact lineup-duplication count.")
    with right:
        st.markdown("#### Salary remaining")
        histogram = _salary_histogram(salary_distribution(analysis))
        st.area_chart(histogram, color=["#48c6a8", "#8797ff"])
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
    chart = table.head(20).set_index("player")[chart_columns]
    st.bar_chart(chart, horizontal=True, color=["#48c6a8", "#8797ff"])
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
    columns = st.columns(5)
    values = [
        ("Salary used", f"${diagnostics['salary_used']:,}"),
        ("Salary remaining", f"${diagnostics['salary_remaining']:,}"),
        ("Exact duplicates", f"{diagnostics['exact_dup_count']:,}"),
        ("Largest team stack", str(diagnostics["max_team_stack"])),
        ("Consensus total", f"{diagnostics['consensus_total']:.1f}"),
    ]
    for column, (label, value) in zip(columns, values, strict=True):
        column.metric(label, value)
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
    st.info("Upload both CSV files in the sidebar, configure their columns, then analyze.")
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
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
