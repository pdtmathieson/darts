import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import gspread
from datetime import datetime

st.set_page_config(
    page_title="Dart Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

SHEET_ID = "12_K6KTaU4IWyq_eiXp9fhCmqH2A66MPraqZ2Velyj94"
WORKSHEET_NAME = "data"
BOARD_RADIUS_MM = 170.0
DARTBOARD_ORDER = [20, 1, 18, 4, 13, 6, 10, 15, 2, 17, 3, 19, 7, 16, 8, 11, 14, 9, 12, 5]
RING_RADII_PCT = {
    "bull_inner": 6.35 / 170.0,
    "bull_outer": 15.9 / 170.0,
    "triple_inner": 99.0 / 170.0,
    "triple_outer": 107.0 / 170.0,
    "double_inner": 162.0 / 170.0,
    "double_outer": 170.0 / 170.0,
}

MODIFIER_SCORES = {"S": 1, "D": 2, "T": 3, "M": 0}
MODIFIER_LABELS = {
    "S": "Single",
    "D": "Double",
    "T": "Triple",
    "M": "Miss",
    "+": "Bullseye",
    "*": "Bull Socket",
}
COLORS = {
    "hit": "#2ecc71",
    "miss": "#e74c3c",
    "primary": "#01696f",
    "secondary": "#4f98a3",
    "target": "rgba(255,255,255,0.60)",
    "board": "rgba(255,255,255,0.22)",
    "board_bold": "rgba(255,255,255,0.35)",
}

EXPECTED_COLUMNS = [
    "Timestamp",
    "Target Segment",
    "Target Modifier",
    "Target X Offset",
    "Target Y Offset",
    "Target Radius Pct",
    "Target Angle",
    "Result Segment",
    "Result Modifier",
    "Result X Offset",
    "Result Y Offset",
    "Result Radius Pct",
    "Result Angle",
    "Name",
    "Mode",
    "Session",
]


def score_throw(result_segment, result_modifier):
    seg = str(result_segment).strip()
    mod = str(result_modifier).strip()
    if mod == "M":
        return 0
    if seg == "+":
        return 50
    if seg == "*":
        return 25
    try:
        return int(seg) * MODIFIER_SCORES.get(mod, 1)
    except (ValueError, TypeError):
        return 0


def is_hit(target_seg, result_seg, result_mod):
    if str(result_mod).strip() == "M":
        return False
    return str(target_seg).strip() == str(result_seg).strip()


def segment_sort_key(v):
    s = str(v).strip()
    if s.lstrip("-").isdigit():
        return (0, int(s))
    special_order = {"+": 21, "*": 22, "Bull": 23, "Bullseye": 24}
    return (1, special_order.get(s, 999), s)


def polar_to_cartesian(radius_pct, angle_deg):
    radius = pd.to_numeric(radius_pct, errors="coerce")
    angle = np.deg2rad(pd.to_numeric(angle_deg, errors="coerce"))
    x = radius * np.sin(angle)
    y = radius * np.cos(angle)
    return x, y


def prepare_sheet_dataframe(values):
    if not values or not values[0]:
        return pd.DataFrame()

    headers = [str(h).strip() for h in values[0]]
    row_len = len(headers)
    rows = []
    for row in values[1:]:
        padded = list(row[:row_len]) + [""] * max(0, row_len - len(row))
        rows.append(padded[:row_len])

    df = pd.DataFrame(rows, columns=headers)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_sheet():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
    except KeyError as e:
        return None, [f"Missing secret key: {e}. Add a [gcp_service_account] section to Streamlit secrets."]

    try:
        gc = gspread.service_account_from_dict(creds_dict)
    except Exception as e:
        return None, [
            f"Failed to build Google credentials: {e}. Check your private_key formatting — it needs real newlines, not escaped \\n characters."
        ]

    try:
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.worksheet(WORKSHEET_NAME)
        values = worksheet.get_all_values()
    except Exception as e:
        err = str(e)
        if "SpreadsheetNotFound" in err or "404" in err:
            return None, ["Spreadsheet not found. Check the Sheet ID and confirm it is shared with the service account email."]
        if "WorksheetNotFound" in err:
            return None, [f"Worksheet '{WORKSHEET_NAME}' not found in the spreadsheet."]
        if "PERMISSION_DENIED" in err or "403" in err:
            return None, ["Permission denied. Share the Google Sheet with the service account email as Viewer."]
        return None, [f"Failed to read Google Sheet: {e}"]

    df = prepare_sheet_dataframe(values)
    if df.empty:
        return df, []

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        return None, [f"Google Sheet is missing columns: {missing}. Found: {list(df.columns)}"]

    for col in ["Name", "Mode", "Target Segment", "Target Modifier", "Result Segment", "Result Modifier"]:
        df[col] = df[col].astype(str).str.strip()

    numeric_cols = [
        "Target X Offset",
        "Target Y Offset",
        "Target Radius Pct",
        "Target Angle",
        "Result X Offset",
        "Result Y Offset",
        "Result Radius Pct",
        "Result Angle",
        "Session",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], dayfirst=True, errors="coerce")
    df["Session"] = df["Session"].astype("Int64")

    df["Score"] = df.apply(lambda r: score_throw(r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Hit"] = df.apply(lambda r: is_hit(r["Target Segment"], r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Date"] = df["Timestamp"].dt.date
    df["Result Modifier Label"] = df["Result Modifier"].map(MODIFIER_LABELS).fillna(df["Result Modifier"])

    df["Target X Pct"], df["Target Y Pct"] = polar_to_cartesian(df["Target Radius Pct"], df["Target Angle"])
    df["Result X Pct"], df["Result Y Pct"] = polar_to_cartesian(df["Result Radius Pct"], df["Result Angle"])

    df["Target X mm"] = df["Target X Pct"] * BOARD_RADIUS_MM
    df["Target Y mm"] = df["Target Y Pct"] * BOARD_RADIUS_MM
    df["Result X mm"] = df["Result X Pct"] * BOARD_RADIUS_MM
    df["Result Y mm"] = df["Result Y Pct"] * BOARD_RADIUS_MM

    df["Distance from Target mm"] = (
        np.sqrt((df["Result X mm"] - df["Target X mm"]) ** 2 + (df["Result Y mm"] - df["Target Y mm"]) ** 2)
    ).round(1)

    return df, []


def render_sidebar(df):
    st.sidebar.markdown("## 🎯 Dart Tracker")
    st.sidebar.markdown("---")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Filters")

    players = sorted(df["Name"].dropna().astype(str).unique().tolist())
    selected_players = st.sidebar.multiselect("Player", players, default=players)

    modes = sorted(df["Mode"].dropna().astype(str).unique().tolist())
    selected_modes = st.sidebar.multiselect("Mode", modes, default=modes)

    sessions = sorted([int(s) for s in df["Session"].dropna().unique().tolist()])
    selected_sessions = st.sidebar.multiselect(
        "Session",
        sessions,
        default=sessions,
        format_func=lambda s: f"Session {s}",
    )

    valid_dates = sorted([d for d in df["Date"].dropna().unique().tolist() if pd.notna(d)])
    if valid_dates:
        if len(valid_dates) > 1:
            date_range = st.sidebar.date_input(
                "Date range",
                value=(valid_dates[0], valid_dates[-1]),
                min_value=valid_dates[0],
                max_value=valid_dates[-1],
            )
        else:
            date_range = (valid_dates[0], valid_dates[0])
    else:
        date_range = None

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Data last fetched: {datetime.now().strftime('%H:%M:%S')}")

    return selected_players, selected_modes, selected_sessions, date_range


def apply_filters(df, players, modes, sessions, date_range):
    f = df.copy()
    if players:
        f = f[f["Name"].isin(players)]
    if modes:
        f = f[f["Mode"].isin(modes)]
    if sessions:
        f = f[f["Session"].isin(sessions)]
    if date_range:
        try:
            start, end = date_range[0], date_range[-1]
            f = f[(f["Date"] >= start) & (f["Date"] <= end)]
        except Exception:
            pass
    return f


def render_kpis(df):
    total = len(df)
    hits = int(df["Hit"].sum())
    misses = int((df["Result Modifier"] == "M").sum())
    acc = (hits / total * 100) if total > 0 else 0
    avg_sc = df["Score"].mean() if total > 0 else 0
    doubles = int((df["Result Modifier"] == "D").sum())
    triples = int((df["Result Modifier"] == "T").sum())
    avg_dist = df["Distance from Target mm"].dropna().mean() if total > 0 else np.nan

    cols = st.columns(7)
    for col, (label, value) in zip(
        cols,
        [
            ("🎯 Throws", f"{total:,}"),
            ("✅ Hits", f"{hits:,}"),
            ("💥 Misses", f"{misses:,}"),
            ("📊 Accuracy", f"{acc:.1f}%"),
            ("⚡ Avg Score", f"{avg_sc:.2f}"),
            ("✌️ Doubles", f"{doubles:,}"),
            ("📏 Avg Error", f"{avg_dist:.1f} mm" if pd.notna(avg_dist) else "—"),
        ],
    ):
        col.metric(label, value)


def tab_overview(df):
    st.subheader("Accuracy by Segment")

    seg_stats = (
        df.groupby("Target Segment")
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
    )
    seg_stats["Accuracy"] = (seg_stats["Hits"] / seg_stats["Throws"] * 100).round(1)
    seg_stats = seg_stats.sort_values("Target Segment", key=lambda s: s.map(segment_sort_key))

    fig = px.bar(
        seg_stats,
        x="Target Segment",
        y="Accuracy",
        color="Accuracy",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        range_color=[0, 100],
        text="Accuracy",
    )
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(type="category"),
        height=400,
        margin=dict(t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Result Breakdown")
        mod_counts = df["Result Modifier Label"].value_counts().reset_index()
        mod_counts.columns = ["Modifier", "Count"]
        fig2 = px.pie(
            mod_counts,
            names="Modifier",
            values="Count",
            color_discrete_sequence=px.colors.qualitative.Set2,
            hole=0.4,
        )
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            height=320,
            margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        st.subheader("Score Distribution")
        fig3 = px.histogram(
            df[df["Score"] > 0],
            x="Score",
            nbins=20,
            color_discrete_sequence=[COLORS["primary"]],
        )
        fig3.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
            height=320,
            margin=dict(t=10, b=10),
            bargap=0.1,
        )
        st.plotly_chart(fig3, use_container_width=True)


def tab_accuracy(df):
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Accuracy Over Time (by Session)")
        sess_acc = (
            df.dropna(subset=["Session"])
            .groupby("Session")
            .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
            .reset_index()
            .sort_values("Session")
        )
        sess_acc["Accuracy"] = (sess_acc["Hits"] / sess_acc["Throws"] * 100).round(1)

        fig = px.line(
            sess_acc,
            x="Session",
            y="Accuracy",
            markers=True,
            color_discrete_sequence=[COLORS["primary"]],
        )
        if len(sess_acc) >= 3:
            sess_acc["Rolling"] = sess_acc["Accuracy"].rolling(3, min_periods=1).mean().round(1)
            fig.add_scatter(
                x=sess_acc["Session"],
                y=sess_acc["Rolling"],
                mode="lines",
                name="3-session avg",
                line=dict(dash="dash", color=COLORS["secondary"], width=2),
            )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"),
            height=350,
            margin=dict(t=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("10 Weakest Segments")
        seg_stats = (
            df.groupby("Target Segment")
            .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
            .reset_index()
        )
        seg_stats["Accuracy"] = (seg_stats["Hits"] / seg_stats["Throws"] * 100).round(1)
        worst = seg_stats.nsmallest(10, "Accuracy").sort_values("Accuracy")

        fig2 = px.bar(
            worst,
            x="Accuracy",
            y="Target Segment",
            orientation="h",
            color="Accuracy",
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 100],
            text="Accuracy",
            labels={"Target Segment": "Segment", "Accuracy": "Hit Rate (%)"},
        )
        fig2.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
        fig2.update_layout(
            coloraxis_showscale=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(type="category"),
            xaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
            height=350,
            margin=dict(t=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Accuracy Heatmap — Segment x Session")
    pivot = (
        df.dropna(subset=["Session"])
        .groupby(["Session", "Target Segment"])
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
    )
    pivot["Accuracy"] = (pivot["Hits"] / pivot["Throws"] * 100).round(1)
    try:
        heat = pivot.pivot(index="Target Segment", columns="Session", values="Accuracy")
        heat = heat.reindex(sorted(heat.index.tolist(), key=segment_sort_key))
        fig3 = px.imshow(
            heat,
            color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
            range_color=[0, 100],
            aspect="auto",
            labels=dict(color="Accuracy %"),
        )
        fig3.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=500,
            margin=dict(t=10),
        )
        st.plotly_chart(fig3, use_container_width=True)
    except Exception as e:
        st.info(f"Heatmap requires data across multiple sessions. ({e})")


def add_board_traces(fig):
    theta = np.linspace(0, 2 * np.pi, 721)
    ring_styles = [
        (RING_RADII_PCT["bull_inner"], COLORS["board_bold"], 2),
        (RING_RADII_PCT["bull_outer"], COLORS["board"], 1.5),
        (RING_RADII_PCT["triple_inner"], COLORS["board"], 1),
        (RING_RADII_PCT["triple_outer"], COLORS["board_bold"], 2),
        (RING_RADII_PCT["double_inner"], COLORS["board"], 1),
        (RING_RADII_PCT["double_outer"], COLORS["board_bold"], 2),
    ]
    for radius, color, width in ring_styles:
        fig.add_trace(
            go.Scatter(
                x=radius * np.sin(theta),
                y=radius * np.cos(theta),
                mode="lines",
                line=dict(color=color, width=width),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    for angle_deg in np.arange(9, 360, 18):
        angle = np.deg2rad(angle_deg)
        fig.add_trace(
            go.Scatter(
                x=[0, np.sin(angle)],
                y=[0, np.cos(angle)],
                mode="lines",
                line=dict(color="rgba(255,255,255,0.10)", width=1),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    number_x = []
    number_y = []
    number_text = []
    for i, seg in enumerate(DARTBOARD_ORDER):
        angle = np.deg2rad(i * 18)
        number_x.append(1.08 * np.sin(angle))
        number_y.append(1.08 * np.cos(angle))
        number_text.append(str(seg))

    fig.add_trace(
        go.Scatter(
            x=number_x,
            y=number_y,
            mode="text",
            text=number_text,
            textfont=dict(color="rgba(255,255,255,0.70)", size=12),
            showlegend=False,
            hoverinfo="skip",
        )
    )


def board_layout(fig, title=None):
    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=700,
        margin=dict(t=40 if title else 10, b=10),
        xaxis=dict(
            title="Horizontal position (board radii)",
            range=[-1.15, 1.15],
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
        ),
        yaxis=dict(
            title="Vertical position (board radii)",
            range=[-1.15, 1.15],
            gridcolor="rgba(255,255,255,0.04)",
            zeroline=False,
            scaleanchor="x",
            scaleratio=1,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )


def tab_positions(df):
    st.subheader("Throw Positions")
    st.caption(
        "This view uses the new radius/angle fields. 0° is straight up, 90° is right, and 1.0 is the outer board edge. Values above 1.0 are outside the board."
    )

    target_options = sorted(df["Target Segment"].dropna().unique().tolist(), key=segment_sort_key)
    controls = st.columns([1.1, 1.1, 1.1])
    with controls[0]:
        selected_seg = st.selectbox("Filter by Target Segment", ["All"] + [str(s) for s in target_options])
    with controls[1]:
        view_mode = st.radio("View", ["Individual throws", "Heatmap"], horizontal=True)
    with controls[2]:
        show_targets = st.checkbox("Show target markers", value=True)

    plot_df = df.dropna(subset=["Result X Pct", "Result Y Pct"]).copy()
    if selected_seg != "All":
        plot_df = plot_df[plot_df["Target Segment"].astype(str) == selected_seg]

    if plot_df.empty:
        st.warning("No plottable position data for the current filters.")
        return

    if view_mode == "Individual throws":
        fig = go.Figure()
        add_board_traces(fig)

        if show_targets:
            targets_df = plot_df.dropna(subset=["Target X Pct", "Target Y Pct"])
            if not targets_df.empty:
                fig.add_trace(
                    go.Scattergl(
                        x=targets_df["Target X Pct"],
                        y=targets_df["Target Y Pct"],
                        mode="markers",
                        name="Targets",
                        marker=dict(symbol="x", size=9, color=COLORS["target"], line=dict(width=1)),
                        customdata=np.stack(
                            [
                                targets_df["Target Segment"].astype(str),
                                targets_df["Target Modifier"].astype(str),
                                targets_df["Target Radius Pct"].round(3),
                                targets_df["Target Angle"].round(1),
                            ],
                            axis=-1,
                        ),
                        hovertemplate=(
                            "Target %{customdata[0]} (%{customdata[1]})<br>"
                            "Radius %{customdata[2]}<br>"
                            "Angle %{customdata[3]}°<extra></extra>"
                        ),
                    )
                )

        for label, subset, color in [
            ("Hit", plot_df[plot_df["Hit"]], COLORS["hit"]),
            ("Miss", plot_df[~plot_df["Hit"]], COLORS["miss"]),
        ]:
            if subset.empty:
                continue
            fig.add_trace(
                go.Scattergl(
                    x=subset["Result X Pct"],
                    y=subset["Result Y Pct"],
                    mode="markers",
                    name=label,
                    marker=dict(size=9, color=color, opacity=0.72, line=dict(width=0)),
                    customdata=np.stack(
                        [
                            subset["Name"].astype(str),
                            subset["Target Segment"].astype(str),
                            subset["Result Segment"].astype(str),
                            subset["Result Modifier"].astype(str),
                            subset["Result Radius Pct"].round(3),
                            subset["Result Angle"].round(1),
                            subset["Score"],
                            subset["Session"].astype(str),
                        ],
                        axis=-1,
                    ),
                    hovertemplate=(
                        "%{customdata[0]}<br>"
                        "Target: %{customdata[1]}<br>"
                        "Result: %{customdata[2]} (%{customdata[3]})<br>"
                        "Radius: %{customdata[4]}<br>"
                        "Angle: %{customdata[5]}°<br>"
                        "Score: %{customdata[6]}<br>"
                        "Session: %{customdata[7]}<extra></extra>"
                    ),
                )
            )

        board_layout(fig)
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Histogram2d(
                x=plot_df["Result X Pct"],
                y=plot_df["Result Y Pct"],
                nbinsx=48,
                nbinsy=48,
                colorscale="YlOrRd",
                colorbar=dict(title="Throws"),
                hovertemplate="X %{x:.2f}<br>Y %{y:.2f}<br>Count %{z}<extra></extra>",
            )
        )
        add_board_traces(fig)
        board_layout(fig)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("The heatmap bins result positions on the normalised board, so hot zones show where darts cluster most often.")

    st.subheader("Distance from Target Centre (mm)")
    dist_df = plot_df.dropna(subset=["Distance from Target mm"])
    avg_dist = dist_df["Distance from Target mm"].mean() if not dist_df.empty else np.nan

    fig2 = px.histogram(
        dist_df,
        x="Distance from Target mm",
        nbins=30,
        color_discrete_sequence=[COLORS["secondary"]],
        labels={"Distance from Target mm": "Distance from target (mm)"},
    )
    fig2.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        height=300,
        margin=dict(t=10),
        bargap=0.1,
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.caption(f"Average distance from target centre: **{avg_dist:.1f} mm**" if pd.notna(avg_dist) else "Average distance from target centre: —")


def tab_rtw(df):
    rtw_df = df[df["Mode"] == "RTW"]
    if rtw_df.empty:
        st.info("No RTW data found with current filters.")
        return

    st.subheader("Round the World — Performance")

    col1, col2, col3 = st.columns(3)
    col1.metric("RTW Accuracy", f"{rtw_df['Hit'].mean() * 100:.1f}%")
    col2.metric("Total RTW Throws", f"{len(rtw_df):,}")
    col3.metric("Sessions", f"{rtw_df['Session'].nunique()}")

    st.subheader("Accuracy by Number (1-20)")
    rtw_num = rtw_df[rtw_df["Target Segment"].apply(lambda x: str(x).isdigit())].copy()
    rtw_num["Target Segment"] = rtw_num["Target Segment"].astype(int)
    rtw_seg = (
        rtw_num.groupby("Target Segment")
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
        .sort_values("Target Segment")
    )
    rtw_seg["Accuracy"] = (rtw_seg["Hits"] / rtw_seg["Throws"] * 100).round(1)

    fig = px.bar(
        rtw_seg,
        x="Target Segment",
        y="Accuracy",
        color="Accuracy",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        range_color=[0, 100],
        text="Accuracy",
        labels={"Target Segment": "Number", "Accuracy": "Hit Rate (%)"},
    )
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(tickmode="linear", tick0=1, dtick=1),
        height=400,
        margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Accuracy Trend per Session")
        sess_rtw = (
            rtw_df.dropna(subset=["Session"])
            .groupby("Session")
            .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
            .reset_index()
            .sort_values("Session")
        )
        sess_rtw["Accuracy"] = (sess_rtw["Hits"] / sess_rtw["Throws"] * 100).round(1)

        fig2 = px.line(
            sess_rtw,
            x="Session",
            y="Accuracy",
            markers=True,
            color_discrete_sequence=[COLORS["primary"]],
        )
        if len(sess_rtw) >= 3:
            sess_rtw["Rolling"] = sess_rtw["Accuracy"].rolling(3, min_periods=1).mean().round(1)
            fig2.add_scatter(
                x=sess_rtw["Session"],
                y=sess_rtw["Rolling"],
                mode="lines",
                name="3-session avg",
                line=dict(dash="dash", color=COLORS["secondary"], width=2),
            )
        fig2.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"),
            height=320,
            margin=dict(t=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        st.subheader("Miss Breakdown by Number")
        misses_df = rtw_df[rtw_df["Result Modifier"] == "M"]
        if not misses_df.empty:
            miss_counts = misses_df["Target Segment"].value_counts().reset_index()
            miss_counts.columns = ["Segment", "Misses"]
            fig3 = px.bar(
                miss_counts.head(10),
                x="Segment",
                y="Misses",
                color_discrete_sequence=[COLORS["miss"]],
                labels={"Segment": "Target Segment", "Misses": "Total Misses"},
            )
            fig3.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(type="category"),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                height=320,
                margin=dict(t=10),
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.success("No misses recorded! 🎯")


def tab_players(df):
    st.subheader("Player Comparison")
    player_stats = (
        df.groupby("Name")
        .agg(
            Throws=("Hit", "count"),
            Hits=("Hit", "sum"),
            Misses=("Result Modifier", lambda x: (x == "M").sum()),
            Avg_Score=("Score", "mean"),
            Avg_Error_mm=("Distance from Target mm", "mean"),
            Doubles=("Result Modifier", lambda x: (x == "D").sum()),
            Triples=("Result Modifier", lambda x: (x == "T").sum()),
            Sessions=("Session", "nunique"),
        )
        .reset_index()
    )
    player_stats["Accuracy (%)"] = (player_stats["Hits"] / player_stats["Throws"] * 100).round(1)
    player_stats["Avg Score"] = player_stats["Avg_Score"].round(2)
    player_stats["Avg Error (mm)"] = player_stats["Avg_Error_mm"].round(1)

    st.dataframe(
        player_stats[
            [
                "Name",
                "Throws",
                "Hits",
                "Misses",
                "Accuracy (%)",
                "Avg Score",
                "Avg Error (mm)",
                "Doubles",
                "Triples",
                "Sessions",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    if len(df["Name"].dropna().unique()) >= 2:
        fig = px.bar(
            player_stats,
            x="Name",
            y="Accuracy (%)",
            color="Name",
            color_discrete_sequence=px.colors.qualitative.Set2,
            text="Accuracy (%)",
        )
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            showlegend=False,
            yaxis=dict(range=[0, 110], gridcolor="rgba(255,255,255,0.05)"),
            height=350,
            margin=dict(t=10),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Add more players to see a comparison chart.")


def tab_sessions(df):
    st.subheader("Session Summary")
    sess_stats = (
        df.groupby(["Session", "Name", "Date"])
        .agg(
            Throws=("Hit", "count"),
            Hits=("Hit", "sum"),
            Misses=("Result Modifier", lambda x: (x == "M").sum()),
            Avg_Score=("Score", "mean"),
            Avg_Error_mm=("Distance from Target mm", "mean"),
            Modes=("Mode", lambda x: ", ".join(sorted(pd.Series(x).dropna().astype(str).unique()))),
        )
        .reset_index()
    )
    sess_stats["Accuracy (%)"] = (sess_stats["Hits"] / sess_stats["Throws"] * 100).round(1)
    sess_stats["Avg Score"] = sess_stats["Avg_Score"].round(2)
    sess_stats["Avg Error (mm)"] = sess_stats["Avg_Error_mm"].round(1)
    sess_stats = sess_stats.sort_values("Session", ascending=False)

    st.dataframe(
        sess_stats[
            [
                "Session",
                "Name",
                "Date",
                "Throws",
                "Hits",
                "Misses",
                "Accuracy (%)",
                "Avg Score",
                "Avg Error (mm)",
                "Modes",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Throws per Session")
    fig = px.bar(
        sess_stats.sort_values("Session"),
        x="Session",
        y="Throws",
        color="Name",
        color_discrete_sequence=px.colors.qualitative.Set2,
        labels={"Session": "Session #", "Throws": "Total Throws"},
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(tickmode="linear"),
        height=350,
        margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def tab_raw(df):
    st.subheader(f"Raw Data — {len(df):,} rows")
    st.dataframe(df.drop(columns=["Date"], errors="ignore"), use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered CSV", csv, "dart_throws_filtered.csv", "text/csv")


def show_troubleshooting():
    lines = [
        "**Most common issues:**",
        "",
        "**1. Private key formatting** — In Streamlit secrets the key must use triple quotes with real newlines:",
        "```",
        'private_key = """-----BEGIN PRIVATE KEY-----',
        "MIIEo...",
        "-----END PRIVATE KEY-----",
        '"""',
        "```",
        "Do NOT use escaped \\\\n sequences.",
        "",
        "**2. Sheet not shared** — Share the Google Sheet with the service account email as Viewer.",
        "",
        "**3. APIs not enabled** — In Google Cloud Console enable both the Google Sheets API and Google Drive API.",
        "",
        "**4. Wrong sheet ID** — The app uses the spreadsheet key from the Sheet URL.",
        "",
        f"**5. Wrong worksheet name** — This app expects a tab named `{WORKSHEET_NAME}`.",
    ]
    st.markdown("\n".join(lines))


def main():
    with st.spinner("Fetching data from Google Sheets..."):
        df, errors = load_data_from_sheet()

    if errors:
        st.error("Could not load data")
        for err in errors:
            st.error(err)
        with st.expander("Troubleshooting checklist"):
            show_troubleshooting()
        st.stop()

    if df is None or df.empty:
        st.warning("The Google Sheet loaded but contains no data.")
        st.stop()

    players, modes, sessions, date_range = render_sidebar(df)
    filtered = apply_filters(df, players, modes, sessions, date_range)

    st.title("🎯 Dart Tracker")

    if filtered.empty:
        st.warning("No data matches the current filters. Try adjusting the sidebar.")
        st.stop()

    render_kpis(filtered)
    st.markdown("---")

    tabs = st.tabs(
        [
            "📊 Overview",
            "🎯 Accuracy",
            "📍 Positions",
            "🔄 RTW",
            "👥 Players",
            "📅 Sessions",
            "🗃️ Raw Data",
        ]
    )
    with tabs[0]:
        tab_overview(filtered)
    with tabs[1]:
        tab_accuracy(filtered)
    with tabs[2]:
        tab_positions(filtered)
    with tabs[3]:
        tab_rtw(filtered)
    with tabs[4]:
        tab_players(filtered)
    with tabs[5]:
        tab_sessions(filtered)
    with tabs[6]:
        tab_raw(filtered)


if __name__ == "__main__":
    main()
