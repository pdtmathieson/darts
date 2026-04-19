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
    "target": "rgba(255,255,255,0.65)",
    "target_line": "rgba(255,255,255,0.35)",
    "board": "rgba(255,255,255,0.22)",
    "board_bold": "rgba(255,255,255,0.35)",
    "adjacent": "#f39c12",
    "neutral": "#95a5a6",
    "left": "#3498db",
    "right": "#9b59b6",
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
    "Points Target",
    "Points Remaining",
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
    return pd.DataFrame(rows, columns=headers)


def _numeric_segment(value):
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    return None


def get_adjacent_segments(segment):
    seg = _numeric_segment(segment)
    if seg is None or seg not in DARTBOARD_ORDER:
        return []
    idx = DARTBOARD_ORDER.index(seg)
    return [
        DARTBOARD_ORDER[(idx - 1) % len(DARTBOARD_ORDER)],
        DARTBOARD_ORDER[(idx + 1) % len(DARTBOARD_ORDER)],
    ]


def get_nearby_segments(segment, distance=2):
    seg = _numeric_segment(segment)
    if seg is None or seg not in DARTBOARD_ORDER:
        return []
    idx = DARTBOARD_ORDER.index(seg)
    nearby = []
    for d in range(1, distance + 1):
        nearby.append(DARTBOARD_ORDER[(idx - d) % len(DARTBOARD_ORDER)])
        nearby.append(DARTBOARD_ORDER[(idx + d) % len(DARTBOARD_ORDER)])
    seen = []
    for n in nearby:
        if n not in seen:
            seen.append(n)
    return seen


def classify_adjacent_miss(target_segment, result_segment, result_modifier):
    if str(result_modifier).strip() == "M":
        return "Board Miss"
    target_num = _numeric_segment(target_segment)
    result_num = _numeric_segment(result_segment)
    if target_num is None or result_num is None:
        return "Non-numeric / bull"
    if target_num == result_num:
        return "Hit"
    adjacent = get_adjacent_segments(target_num)
    nearby = get_nearby_segments(target_num, distance=2)
    if result_num in adjacent:
        if adjacent[0] == result_num:
            return "Adjacent Left"
        if adjacent[1] == result_num:
            return "Adjacent Right"
        return "Adjacent"
    if result_num in nearby:
        return "Nearby (2 away)"
    return "Other Number"


def is_double_score(result_segment, result_modifier):
    seg = str(result_segment).strip()
    mod = str(result_modifier).strip()
    return mod == "D" or seg == "+"


def is_checkout_attempt(points_remaining):
    try:
        remaining = float(points_remaining)
    except (TypeError, ValueError):
        return False
    return remaining <= 170 and remaining > 1


def is_successful_checkout(points_remaining, result_segment, result_modifier):
    try:
        remaining = float(points_remaining)
    except (TypeError, ValueError):
        return False
    score = score_throw(result_segment, result_modifier)
    if remaining - score != 0:
        return False
    return is_double_score(result_segment, result_modifier)


def add_throw_and_visit_columns(df):
    group_cols = ["Name", "Session"]
    ordered = df.sort_values(group_cols + ["Timestamp", "Row Order"], na_position="last").copy()
    ordered["Player Throw Number"] = ordered.groupby(group_cols, dropna=False).cumcount() + 1
    ordered["Throw In Visit"] = ((ordered["Player Throw Number"] - 1) % 3) + 1
    ordered["Visit Number"] = ((ordered["Player Throw Number"] - 1) // 3) + 1
    return ordered


@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_sheet():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
    except KeyError as e:
        return None, [f"Missing secret key: {e}. Add a [gcp_service_account] section to Streamlit secrets."]

    try:
        gc = gspread.service_account_from_dict(creds_dict)
    except Exception as e:
        return None, [f"Failed to build Google credentials: {e}. Check your private_key formatting — it needs real newlines, not escaped \\n characters."]

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
        "Target X Offset", "Target Y Offset", "Target Radius Pct", "Target Angle",
        "Result X Offset", "Result Y Offset", "Result Radius Pct", "Result Angle",
        "Session", "Points Target", "Points Remaining",
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
    df["Distance from Target mm"] = np.sqrt((df["Result X mm"] - df["Target X mm"]) ** 2 + (df["Result Y mm"] - df["Target Y mm"]) ** 2).round(1)

    df = df.reset_index().rename(columns={"index": "Row Order"})
    df = add_throw_and_visit_columns(df)
    df["Adjacent Miss Type"] = df.apply(lambda r: classify_adjacent_miss(r["Target Segment"], r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Is Adjacent Miss"] = df["Adjacent Miss Type"].isin(["Adjacent Left", "Adjacent Right"])
    df["Is Nearby Miss"] = df["Adjacent Miss Type"].isin(["Adjacent Left", "Adjacent Right", "Nearby (2 away)"])
    df["Checkout Attempt"] = df["Points Remaining"].apply(is_checkout_attempt)
    df["Checkout Success"] = df.apply(lambda r: is_successful_checkout(r["Points Remaining"], r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Competition Bust"] = (
        df["Mode"].astype(str).str.strip().str.lower().eq("competition")
        & df["Points Remaining"].notna()
        & (
            ((df["Points Remaining"] - df["Score"]) < 0)
            | ((df["Points Remaining"] - df["Score"]) == 1)
            | (((df["Points Remaining"] - df["Score"]) == 0) & (~df.apply(lambda r: is_double_score(r["Result Segment"], r["Result Modifier"]), axis=1)))
        )
    )
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
    selected_sessions = st.sidebar.multiselect("Session", sessions, default=sessions, format_func=lambda s: f"Session {s}")
    valid_dates = sorted([d for d in df["Date"].dropna().unique().tolist() if pd.notna(d)])
    if valid_dates:
        if len(valid_dates) > 1:
            date_range = st.sidebar.date_input("Date range", value=(valid_dates[0], valid_dates[-1]), min_value=valid_dates[0], max_value=valid_dates[-1])
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
    avg_dist = df["Distance from Target mm"].dropna().mean() if total > 0 else np.nan
    adjacent_rate = (df["Is Adjacent Miss"].mean() * 100) if total > 0 else 0
    cols = st.columns(8)
    for col, (label, value) in zip(cols, [
        ("🎯 Throws", f"{total:,}"), ("✅ Hits", f"{hits:,}"), ("💥 Misses", f"{misses:,}"),
        ("📊 Accuracy", f"{acc:.1f}%"), ("⚡ Avg Score", f"{avg_sc:.2f}"), ("✌️ Doubles", f"{doubles:,}"),
        ("📏 Avg Error", f"{avg_dist:.1f} mm" if pd.notna(avg_dist) else "—"), ("↔️ Adjacent Misses", f"{adjacent_rate:.1f}%")
    ]):
        col.metric(label, value)


def get_mode_scoped_df(df, relevant_mode, include_all_modes=False):
    if include_all_modes:
        return df.copy(), "All filtered modes"
    mode_key = str(relevant_mode).strip().lower()
    scoped = df[df["Mode"].astype(str).str.strip().str.lower() == mode_key].copy()
    return scoped, f"{relevant_mode} only"


def format_mode_scope_caption(df, scope_label):
    if df.empty:
        return f"Scope: {scope_label}."
    mode_counts = df["Mode"].astype(str).str.strip().replace("", "Unknown").value_counts()
    mode_text = ", ".join([f"{mode} ({count:,})" for mode, count in mode_counts.items()])
    return f"Scope: {scope_label}. Modes included: {mode_text}."


def build_adjacent_summary(df):
    numeric_targets = df[df["Target Segment"].apply(lambda x: _numeric_segment(x) is not None)].copy()
    if numeric_targets.empty:
        return pd.DataFrame(), pd.DataFrame()
    rows = []
    detail_rows = []
    for seg in sorted({_numeric_segment(v) for v in numeric_targets["Target Segment"] if _numeric_segment(v) is not None}):
        seg_df = numeric_targets[numeric_targets["Target Segment"].astype(str) == str(seg)].copy()
        adjacent = get_adjacent_segments(seg)
        nearby = get_nearby_segments(seg, distance=2)
        left_seg = adjacent[0] if len(adjacent) >= 1 else None
        right_seg = adjacent[1] if len(adjacent) >= 2 else None
        throws = len(seg_df)
        exact_hits = int((seg_df["Result Segment"].astype(str) == str(seg)).sum())
        left_hits = int((seg_df["Result Segment"].astype(str) == str(left_seg)).sum()) if left_seg is not None else 0
        right_hits = int((seg_df["Result Segment"].astype(str) == str(right_seg)).sum()) if right_seg is not None else 0
        nearby_hits = int(seg_df["Result Segment"].astype(str).isin([str(x) for x in nearby]).sum())
        board_misses = int((seg_df["Result Modifier"] == "M").sum())
        rows.append({
            "Target Segment": seg, "Throws": throws, "Exact Hit %": round(exact_hits / throws * 100, 1) if throws else 0,
            "Adjacent %": round((left_hits + right_hits) / throws * 100, 1) if throws else 0,
            "Left Adjacent": left_seg, "Left %": round(left_hits / throws * 100, 1) if throws else 0,
            "Right Adjacent": right_seg, "Right %": round(right_hits / throws * 100, 1) if throws else 0,
            "Nearby (2 away) %": round(nearby_hits / throws * 100, 1) if throws else 0,
            "Board Miss %": round(board_misses / throws * 100, 1) if throws else 0,
        })
        result_counts = seg_df["Result Segment"].astype(str).value_counts().reset_index()
        result_counts.columns = ["Result Segment", "Count"]
        result_counts["Target Segment"] = seg
        result_counts["Rate %"] = (result_counts["Count"] / throws * 100).round(1)
        result_counts["Bucket"] = result_counts["Result Segment"].apply(
            lambda x: "Exact" if str(x) == str(seg) else "Adjacent" if str(x) in [str(y) for y in adjacent] else "Nearby (2 away)" if str(x) in [str(y) for y in nearby] else "Other"
        )
        detail_rows.append(result_counts)
    return pd.DataFrame(rows), pd.concat(detail_rows, ignore_index=True) if detail_rows else pd.DataFrame()


def render_adjacent_section(df, heading="Adjacent Miss Analysis", section_key="adjacent"):
    st.subheader(heading)
    summary, detail = build_adjacent_summary(df)
    if summary.empty:
        st.info("No numeric target-segment data is available for adjacent miss analysis.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Avg Adjacent Miss Rate", f"{summary['Adjacent %'].mean():.1f}%")
    c2.metric("Best Controlled Number", str(summary.sort_values(["Adjacent %", "Throws"]).iloc[0]["Target Segment"]))
    c3.metric("Worst Adjacent Leak", str(summary.sort_values(["Adjacent %", "Throws"], ascending=[False, False]).iloc[0]["Target Segment"]))
    c4.metric("Avg Board Miss Rate", f"{summary['Board Miss %'].mean():.1f}%")
    col1, col2 = st.columns(2)
    with col1:
        plot_df = summary.sort_values("Target Segment")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=plot_df["Target Segment"].astype(str), y=plot_df["Left %"], name="Left adjacent", marker_color=COLORS["left"]))
        fig.add_trace(go.Bar(x=plot_df["Target Segment"].astype(str), y=plot_df["Right %"], name="Right adjacent", marker_color=COLORS["right"]))
        fig.add_trace(go.Bar(x=plot_df["Target Segment"].astype(str), y=plot_df["Nearby (2 away) %"], name="Nearby (2 away)", marker_color=COLORS["adjacent"]))
        fig.update_layout(barmode="group", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(title="Rate %", gridcolor="rgba(255,255,255,0.05)"), xaxis=dict(title="Target segment", type="category"), height=380, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True, key=f"{section_key}_adjacent_rates")
    with col2:
        top_leaks = detail[detail["Bucket"].isin(["Adjacent", "Nearby (2 away)"])].copy()
        if top_leaks.empty:
            st.info("No adjacent or nearby misses found.")
        else:
            top_leaks = top_leaks.sort_values(["Rate %", "Count"], ascending=[False, False]).head(15)
            top_leaks["Label"] = top_leaks["Target Segment"].astype(str) + " → " + top_leaks["Result Segment"].astype(str)
            fig2 = px.bar(top_leaks.sort_values("Rate %"), x="Rate %", y="Label", orientation="h", color="Bucket", color_discrete_map={"Adjacent": COLORS["adjacent"], "Nearby (2 away)": COLORS["neutral"]}, text="Rate %")
            fig2.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=380, margin=dict(t=10))
            st.plotly_chart(fig2, use_container_width=True, key=f"{section_key}_adjacent_pairs")
    st.dataframe(summary.sort_values("Target Segment"), use_container_width=True, hide_index=True)


def tab_overview(df):
    st.subheader("Accuracy by Segment")
    seg_stats = df.groupby("Target Segment").agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index()
    if seg_stats.empty:
        st.info("No overview data available for the current filters.")
        return
    seg_stats["Accuracy"] = (seg_stats["Hits"] / seg_stats["Throws"] * 100).round(1)
    seg_stats = seg_stats.sort_values("Target Segment", key=lambda s: s.map(segment_sort_key))
    fig = px.bar(seg_stats, x="Target Segment", y="Accuracy", color="Accuracy", color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], range_color=[0, 100], text="Accuracy")
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"), xaxis=dict(type="category"), height=400, margin=dict(t=20, b=40))
    st.plotly_chart(fig, use_container_width=True, key="overview_accuracy_segment")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Result Breakdown")
        mod_counts = df["Result Modifier Label"].value_counts().reset_index()
        mod_counts.columns = ["Modifier", "Count"]
        if not mod_counts.empty:
            fig2 = px.pie(mod_counts, names="Modifier", values="Count", color_discrete_sequence=px.colors.qualitative.Set2, hole=0.4)
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=320, margin=dict(t=10, b=10))
            st.plotly_chart(fig2, use_container_width=True, key="overview_result_breakdown")
        else:
            st.info("No modifier data available.")
    with col2:
        st.subheader("Score Distribution")
        score_df = df[df["Score"] > 0].copy()
        if score_df.empty:
            st.info("No scoring data available.")
        else:
            fig3 = px.histogram(score_df, x="Score", nbins=20, color_discrete_sequence=[COLORS["primary"]])
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=320, margin=dict(t=10, b=10), bargap=0.1)
            st.plotly_chart(fig3, use_container_width=True, key="overview_score_distribution")
    render_adjacent_section(df, "Adjacent Miss Analysis", section_key="overview")


def tab_accuracy(df):
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Accuracy Over Time (by Session)")
        sess_acc = df.dropna(subset=["Session"]).groupby("Session").agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index().sort_values("Session")
        if sess_acc.empty:
            st.info("No session accuracy data available.")
        else:
            sess_acc["Accuracy"] = (sess_acc["Hits"] / sess_acc["Throws"] * 100).round(1)
            fig = px.line(sess_acc, x="Session", y="Accuracy", markers=True, color_discrete_sequence=[COLORS["primary"]])
            if len(sess_acc) >= 3:
                sess_acc["Rolling"] = sess_acc["Accuracy"].rolling(3, min_periods=1).mean().round(1)
                fig.add_scatter(x=sess_acc["Session"], y=sess_acc["Rolling"], mode="lines", name="3-session avg", line=dict(dash="dash", color=COLORS["secondary"], width=2))
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"), height=350, margin=dict(t=10))
            st.plotly_chart(fig, use_container_width=True, key="accuracy_over_time")
    with col2:
        st.subheader("10 Weakest Segments")
        seg_stats = df.groupby("Target Segment").agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index()
        if seg_stats.empty:
            st.info("No segment accuracy data available.")
        else:
            seg_stats["Accuracy"] = (seg_stats["Hits"] / seg_stats["Throws"] * 100).round(1)
            worst = seg_stats.nsmallest(10, "Accuracy").sort_values("Accuracy")
            fig2 = px.bar(worst, x="Accuracy", y="Target Segment", orientation="h", color="Accuracy", color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], range_color=[0, 100], text="Accuracy", labels={"Target Segment": "Segment", "Accuracy": "Hit Rate (%)"})
            fig2.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
            fig2.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(type="category"), xaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"), height=350, margin=dict(t=10))
            st.plotly_chart(fig2, use_container_width=True, key="accuracy_weakest_segments")
    st.subheader("Accuracy Heatmap — Segment x Session")
    pivot = df.dropna(subset=["Session"]).groupby(["Session", "Target Segment"]).agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index()
    if pivot.empty:
        st.info("Heatmap requires data across sessions.")
        return
    pivot["Accuracy"] = (pivot["Hits"] / pivot["Throws"] * 100).round(1)
    try:
        heat = pivot.pivot(index="Target Segment", columns="Session", values="Accuracy")
        heat = heat.reindex(sorted(heat.index.tolist(), key=segment_sort_key))
        fig3 = px.imshow(heat, color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], range_color=[0, 100], aspect="auto", labels=dict(color="Accuracy %"))
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=500, margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True, key="accuracy_heatmap")
    except Exception as e:
        st.info(f"Heatmap requires data across multiple sessions. ({e})")


def build_points_segment_stats(points_df):
    stats = points_df.groupby("Target Segment").agg(
        Throws=("Score", "count"), Total_Points=("Score", "sum"), Avg_Points=("Score", "mean"), Hits=("Hit", "sum"),
        Misses=("Result Modifier", lambda x: (x == "M").sum()), Doubles=("Result Modifier", lambda x: (x == "D").sum()),
        Triples=("Result Modifier", lambda x: (x == "T").sum()), Adjacent_Misses=("Is Adjacent Miss", "sum"),
        Avg_Error_mm=("Distance from Target mm", "mean"), Std_Error_mm=("Distance from Target mm", "std"), Unique_Sessions=("Session", "nunique")
    ).reset_index()
    if stats.empty:
        return stats
    stats["Accuracy %"] = (stats["Hits"] / stats["Throws"] * 100).round(1)
    stats["Miss %"] = (stats["Misses"] / stats["Throws"] * 100).round(1)
    stats["Double %"] = (stats["Doubles"] / stats["Throws"] * 100).round(1)
    stats["Triple %"] = (stats["Triples"] / stats["Throws"] * 100).round(1)
    stats["Adjacent Miss %"] = (stats["Adjacent_Misses"] / stats["Throws"] * 100).round(1)
    stats["Avg Points"] = stats["Avg_Points"].round(2)
    stats["Avg Error (mm)"] = stats["Avg_Error_mm"].round(1)
    stats["Error SD (mm)"] = stats["Std_Error_mm"].round(1)
    stats["Points per Hit"] = (stats["Total_Points"] / stats["Hits"].replace(0, np.nan)).round(2)
    stats["Efficiency Rank"] = stats["Avg_Points"].rank(ascending=False, method="min").astype(int)
    return stats.sort_values(["Avg_Points", "Accuracy %"], ascending=[False, False])


def tab_points(df):
    st.subheader("Points Report — Segment Efficiency")
    include_all_modes = st.toggle("Include all modes in this report", value=False, key="points_include_all_modes", help="Off = Points only. On = use all currently filtered data.")
    points_df, scope_label = get_mode_scoped_df(df, "Points", include_all_modes)
    if points_df.empty:
        st.info("No data found for this Points report with the current filters.")
        return
    st.caption(format_mode_scope_caption(points_df, scope_label))
    stats = build_points_segment_stats(points_df)
    if stats.empty:
        st.info("Not enough data to build the Points report.")
        return
    best_avg = stats.iloc[0]
    most_accurate = stats.sort_values(["Accuracy %", "Throws"], ascending=[False, False]).iloc[0]
    best_double = stats.sort_values(["Double %", "Throws"], ascending=[False, False]).iloc[0]
    best_triple = stats.sort_values(["Triple %", "Throws"], ascending=[False, False]).iloc[0]
    safest = stats.sort_values(["Miss %", "Throws"], ascending=[True, False]).iloc[0]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Best Avg Points", f"{best_avg['Target Segment']}", f"{best_avg['Avg Points']:.2f} pts/throw")
    c2.metric("Best Accuracy", f"{most_accurate['Target Segment']}", f"{most_accurate['Accuracy %']:.1f}%")
    c3.metric("Best Double Rate", f"{best_double['Target Segment']}", f"{best_double['Double %']:.1f}%")
    c4.metric("Best Triple Rate", f"{best_triple['Target Segment']}", f"{best_triple['Triple %']:.1f}%")
    c5.metric("Lowest Miss Rate", f"{safest['Target Segment']}", f"{safest['Miss %']:.1f}%")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Average Points per Throw")
        top_avg = stats.sort_values(["Avg_Points", "Throws"], ascending=[False, False]).head(12)
        fig = px.bar(top_avg.sort_values("Avg_Points"), x="Avg_Points", y="Target Segment", orientation="h", text="Avg Points", color="Accuracy %", color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], labels={"Avg_Points": "Avg points per throw", "Target Segment": "Target segment"})
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(coloraxis_colorbar_title="Accuracy %", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=420, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True, key="points_average_per_throw")
    with col2:
        st.subheader("Accuracy vs Scoring Value")
        bubble = stats.copy()
        fig2 = px.scatter(bubble, x="Accuracy %", y="Avg_Points", size="Throws", color="Adjacent Miss %", text="Target Segment", color_continuous_scale="RdYlGn_r", hover_data={"Throws": True, "Double %": ":.1f", "Triple %": ":.1f", "Avg Error (mm)": ":.1f", "Miss %": ":.1f", "Adjacent Miss %": ":.1f"}, labels={"Avg_Points": "Avg points per throw", "Accuracy %": "Accuracy %"})
        fig2.update_traces(textposition="top center")
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="rgba(255,255,255,0.05)"), yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=420, margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True, key="points_accuracy_vs_scoring")
    st.subheader("Segment Detail")
    st.dataframe(stats[["Efficiency Rank", "Target Segment", "Throws", "Total_Points", "Avg Points", "Accuracy %", "Double %", "Triple %", "Miss %", "Adjacent Miss %", "Points per Hit", "Avg Error (mm)", "Error SD (mm)", "Unique_Sessions"]], use_container_width=True, hide_index=True)
    st.subheader("Outcome Mix by Target Segment")
    outcome = stats[["Target Segment", "Double %", "Triple %", "Miss %", "Adjacent Miss %"]].copy()
    outcome = outcome.sort_values("Target Segment", key=lambda s: s.map(segment_sort_key))
    melted = outcome.melt(id_vars="Target Segment", var_name="Outcome", value_name="Rate")
    fig3 = px.bar(melted, x="Target Segment", y="Rate", color="Outcome", barmode="group", color_discrete_map={"Double %": "#3498db", "Triple %": "#9b59b6", "Miss %": COLORS["miss"], "Adjacent Miss %": COLORS["adjacent"]}, labels={"Rate": "Rate %", "Target Segment": "Target segment"})
    fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=380, margin=dict(t=10))
    st.plotly_chart(fig3, use_container_width=True, key="points_outcome_mix")
    st.subheader("Sessions Trend")
    sess = points_df.dropna(subset=["Session"]).groupby("Session").agg(Throws=("Score", "count"), Total_Points=("Score", "sum"), Avg_Points=("Score", "mean")).reset_index().sort_values("Session")
    if sess.empty:
        st.info("No session-level data available for this report.")
        return
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=sess["Session"], y=sess["Avg_Points"], mode="lines+markers", name="Avg points/throw", line=dict(color=COLORS["primary"], width=3)))
    fig4.add_trace(go.Bar(x=sess["Session"], y=sess["Total_Points"], name="Total points", marker_color="rgba(79,152,163,0.45)", yaxis="y2"))
    fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(title="Session", gridcolor="rgba(255,255,255,0.05)"), yaxis=dict(title="Avg points/throw", gridcolor="rgba(255,255,255,0.05)"), yaxis2=dict(title="Total points", overlaying="y", side="right", showgrid=False), barmode="overlay", height=380, margin=dict(t=10))
    st.plotly_chart(fig4, use_container_width=True, key="points_session_trend")


def add_board_traces(fig):
    theta = np.linspace(0, 2 * np.pi, 721)
    ring_styles = [
        (RING_RADII_PCT["bull_inner"], COLORS["board_bold"], 2), (RING_RADII_PCT["bull_outer"], COLORS["board"], 1.5),
        (RING_RADII_PCT["triple_inner"], COLORS["board"], 1), (RING_RADII_PCT["triple_outer"], COLORS["board_bold"], 2),
        (RING_RADII_PCT["double_inner"], COLORS["board"], 1), (RING_RADII_PCT["double_outer"], COLORS["board_bold"], 2),
    ]
    for radius, color, width in ring_styles:
        fig.add_trace(go.Scatter(x=radius * np.sin(theta), y=radius * np.cos(theta), mode="lines", line=dict(color=color, width=width), showlegend=False, hoverinfo="skip"))
    for angle_deg in np.arange(9, 360, 18):
        angle = np.deg2rad(angle_deg)
        fig.add_trace(go.Scatter(x=[0, np.sin(angle)], y=[0, np.cos(angle)], mode="lines", line=dict(color="rgba(255,255,255,0.10)", width=1), showlegend=False, hoverinfo="skip"))
    number_x, number_y, number_text = [], [], []
    for i, seg in enumerate(DARTBOARD_ORDER):
        angle = np.deg2rad(i * 18)
        number_x.append(1.08 * np.sin(angle))
        number_y.append(1.08 * np.cos(angle))
        number_text.append(str(seg))
    fig.add_trace(go.Scatter(x=number_x, y=number_y, mode="text", text=number_text, textfont=dict(color="rgba(255,255,255,0.70)", size=12), showlegend=False, hoverinfo="skip"))


def board_layout(fig, title=None):
    fig.update_layout(title=title, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=700, margin=dict(t=40 if title else 10, b=10), xaxis=dict(title="Horizontal position (board radii)", range=[-1.15, 1.15], gridcolor="rgba(255,255,255,0.04)", zeroline=False), yaxis=dict(title="Vertical position (board radii)", range=[-1.15, 1.15], gridcolor="rgba(255,255,255,0.04)", zeroline=False, scaleanchor="x", scaleratio=1), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0))


def add_target_arrows(fig, arrow_df):
    for _, row in arrow_df.iterrows():
        fig.add_annotation(x=row["Result X Pct"], y=row["Result Y Pct"], ax=row["Target X Pct"], ay=row["Target Y Pct"], xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.2, arrowcolor=COLORS["target_line"], opacity=0.65)


def make_transparent_heatmap(plot_df, bins=48):
    x = plot_df["Result X Pct"].to_numpy(dtype=float)
    y = plot_df["Result Y Pct"].to_numpy(dtype=float)
    x_edges = np.linspace(-1.15, 1.15, bins + 1)
    y_edges = np.linspace(-1.15, 1.15, bins + 1)
    hist, x_edges, y_edges = np.histogram2d(x, y, bins=[x_edges, y_edges])
    z = hist.T
    z[z == 0] = np.nan
    x_centres = (x_edges[:-1] + x_edges[1:]) / 2
    y_centres = (y_edges[:-1] + y_edges[1:]) / 2
    return go.Heatmap(x=x_centres, y=y_centres, z=z, colorscale="YlOrRd", colorbar=dict(title="Throws"), hoverongaps=False, hovertemplate="X %{x:.2f}<br>Y %{y:.2f}<br>Count %{z:.0f}<extra></extra>")


def tab_positions(df):
    st.subheader("Throw Positions")
    st.caption("This view uses the radius/angle fields. 0° is straight up, 90° is right, and 1.0 is the outer board edge. Values above 1.0 are outside the board.")
    target_options = sorted(df["Target Segment"].dropna().unique().tolist(), key=segment_sort_key)
    controls = st.columns([1.1, 1.1, 1.1, 1.2])
    with controls[0]:
        selected_seg = st.selectbox("Filter by Target Segment", ["All"] + [str(s) for s in target_options], key="positions_target_segment")
    with controls[1]:
        view_mode = st.radio("View", ["Individual throws", "Heatmap"], horizontal=True, key="positions_view_mode")
    with controls[2]:
        show_targets = st.checkbox("Show target markers + arrows", value=False, key="positions_show_targets")
    with controls[3]:
        max_arrows = st.slider("Max arrows", min_value=25, max_value=500, value=150, step=25, key="positions_max_arrows")
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
            targets_df = plot_df.dropna(subset=["Target X Pct", "Target Y Pct"]).copy()
            if not targets_df.empty:
                if len(targets_df) > max_arrows:
                    targets_df = targets_df.sort_values("Timestamp", na_position="last").tail(max_arrows)
                add_target_arrows(fig, targets_df)
                fig.add_trace(go.Scattergl(x=targets_df["Target X Pct"], y=targets_df["Target Y Pct"], mode="markers", name="Targets", marker=dict(symbol="x", size=9, color=COLORS["target"], line=dict(width=1)), customdata=np.stack([targets_df["Target Segment"].astype(str), targets_df["Target Modifier"].astype(str), targets_df["Target Radius Pct"].round(3), targets_df["Target Angle"].round(1)], axis=-1), hovertemplate=("Target %{customdata[0]} (%{customdata[1]})<br>Radius %{customdata[2]}<br>Angle %{customdata[3]}°<extra></extra>")))
        for label, subset, color in [("Hit", plot_df[plot_df["Hit"]], COLORS["hit"]), ("Miss", plot_df[~plot_df["Hit"]], COLORS["miss"] )]:
            if subset.empty:
                continue
            fig.add_trace(go.Scattergl(x=subset["Result X Pct"], y=subset["Result Y Pct"], mode="markers", name=label, marker=dict(size=9, color=color, opacity=0.72, line=dict(width=0)), customdata=np.stack([subset["Name"].astype(str), subset["Target Segment"].astype(str), subset["Result Segment"].astype(str), subset["Result Modifier"].astype(str), subset["Adjacent Miss Type"].astype(str), subset["Result Radius Pct"].round(3), subset["Result Angle"].round(1), subset["Score"], subset["Session"].astype(str)], axis=-1), hovertemplate=("%{customdata[0]}<br>Target: %{customdata[1]}<br>Result: %{customdata[2]} (%{customdata[3]})<br>Miss class: %{customdata[4]}<br>Radius: %{customdata[5]}<br>Angle: %{customdata[6]}°<br>Score: %{customdata[7]}<br>Session: %{customdata[8]}<extra></extra>")))
        board_layout(fig)
        st.plotly_chart(fig, use_container_width=True, key="positions_individual_throws")
        if show_targets and len(plot_df) > max_arrows:
            st.caption(f"Showing arrows for the most recent {max_arrows} throws to keep the chart responsive.")
    else:
        fig = go.Figure()
        fig.add_trace(make_transparent_heatmap(plot_df))
        add_board_traces(fig)
        board_layout(fig)
        st.plotly_chart(fig, use_container_width=True, key="positions_heatmap")
        st.caption("Zero-count bins are transparent so only areas with actual throws are coloured.")
    st.subheader("Distance from Target Centre (mm)")
    dist_df = plot_df.dropna(subset=["Distance from Target mm"])
    avg_dist = dist_df["Distance from Target mm"].mean() if not dist_df.empty else np.nan
    if dist_df.empty:
        st.info("No distance data available.")
    else:
        fig2 = px.histogram(dist_df, x="Distance from Target mm", nbins=30, color_discrete_sequence=[COLORS["secondary"]], labels={"Distance from Target mm": "Distance from target (mm)"})
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=300, margin=dict(t=10), bargap=0.1)
        st.plotly_chart(fig2, use_container_width=True, key="positions_distance_hist")
    st.caption(f"Average distance from target centre: **{avg_dist:.1f} mm**" if pd.notna(avg_dist) else "Average distance from target centre: —")


def build_consecutive_hit_streaks(source_df):
    if source_df.empty:
        return pd.DataFrame(columns=["Streak Length", "Count", "Label"]), pd.DataFrame()
    working = source_df.reset_index().rename(columns={"index": "Row Order Tmp"}).copy()
    working["Hit"] = working["Hit"].fillna(False).astype(bool)
    group_cols = [col for col in ["Name", "Session"] if col in working.columns]
    sort_cols = group_cols.copy()
    if "Timestamp" in working.columns:
        sort_cols.append("Timestamp")
    sort_cols.append("Row Order Tmp")
    working = working.sort_values(sort_cols, na_position="last").copy()
    streak_rows = []
    grouped = working.groupby(group_cols, dropna=False, sort=False) if group_cols else [("All", working)]
    for group_key, group in grouped:
        run = 0
        for hit in group["Hit"].tolist():
            if hit:
                run += 1
            else:
                if run >= 2:
                    streak_rows.append({"Group": group_key, "Streak Length": run})
                run = 0
        if run >= 2:
            streak_rows.append({"Group": group_key, "Streak Length": run})
    detail = pd.DataFrame(streak_rows)
    if detail.empty:
        return pd.DataFrame(columns=["Streak Length", "Count", "Label"]), detail
    summary = detail["Streak Length"].value_counts().sort_index().reset_index()
    summary.columns = ["Streak Length", "Count"]
    summary["Label"] = summary["Streak Length"].astype(int).astype(str) + "x"
    return summary, detail


def tab_rtw(df):
    st.subheader("Round the World — Performance")
    include_all_modes = st.toggle("Include all modes in this report", value=False, key="rtw_include_all_modes", help="Off = RTW only. On = use all currently filtered data.")
    rtw_df, scope_label = get_mode_scoped_df(df, "RTW", include_all_modes)
    if rtw_df.empty:
        st.info("No data found for this RTW report with current filters.")
        return
    st.caption(format_mode_scope_caption(rtw_df, scope_label))
    total_throws = len(rtw_df)
    hit_rate = rtw_df["Hit"].mean() * 100 if total_throws else 0
    miss_rate = (rtw_df["Result Modifier"] == "M").mean() * 100 if total_throws else 0
    avg_score = rtw_df["Score"].mean() if total_throws else 0
    avg_dist = rtw_df["Distance from Target mm"].dropna().mean() if total_throws else np.nan
    adj_rate = rtw_df["Is Adjacent Miss"].mean() * 100 if total_throws else 0
    streak_summary, streak_detail = build_consecutive_hit_streaks(rtw_df)
    longest_streak = int(streak_detail["Streak Length"].max()) if not streak_detail.empty else 0
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Accuracy", f"{hit_rate:.1f}%")
    col2.metric("Total Throws", f"{total_throws:,}")
    col3.metric("Avg Score", f"{avg_score:.2f}")
    col4.metric("Miss Rate", f"{miss_rate:.1f}%")
    col5.metric("Adjacent Miss Rate", f"{adj_rate:.1f}%")
    col6.metric("Longest Hit Streak", f"{longest_streak}x" if longest_streak else "—")
    st.caption(f"Average distance from target centre: **{avg_dist:.1f} mm**" if pd.notna(avg_dist) else "Average distance from target centre: —")
    st.subheader("Accuracy by Number (1-20)")
    rtw_num = rtw_df[rtw_df["Target Segment"].apply(lambda x: str(x).strip().isdigit())].copy()
    if rtw_num.empty:
        st.info("No numeric target segments are available for the current RTW report scope.")
    else:
        rtw_num["Target Segment"] = rtw_num["Target Segment"].astype(int)
        rtw_seg = rtw_num.groupby("Target Segment").agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index().sort_values("Target Segment")
        rtw_seg["Accuracy"] = (rtw_seg["Hits"] / rtw_seg["Throws"] * 100).round(1)
        fig = px.bar(rtw_seg, x="Target Segment", y="Accuracy", color="Accuracy", color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"], range_color=[0, 100], text="Accuracy", labels={"Target Segment": "Number", "Accuracy": "Hit Rate (%)"})
        fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
        fig.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"), xaxis=dict(tickmode="linear", tick0=1, dtick=1), height=400, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True, key="rtw_accuracy_by_number")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Accuracy Trend per Session")
        sess_rtw = rtw_df.dropna(subset=["Session"]).groupby("Session").agg(Throws=("Hit", "count"), Hits=("Hit", "sum")).reset_index().sort_values("Session")
        if sess_rtw.empty:
            st.info("No session data available for the trend view.")
        else:
            sess_rtw["Accuracy"] = (sess_rtw["Hits"] / sess_rtw["Throws"] * 100).round(1)
            fig2 = px.line(sess_rtw, x="Session", y="Accuracy", markers=True, color_discrete_sequence=[COLORS["primary"]])
            if len(sess_rtw) >= 3:
                sess_rtw["Rolling"] = sess_rtw["Accuracy"].rolling(3, min_periods=1).mean().round(1)
                fig2.add_scatter(x=sess_rtw["Session"], y=sess_rtw["Rolling"], mode="lines", name="3-session avg", line=dict(dash="dash", color=COLORS["secondary"], width=2))
            fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"), height=320, margin=dict(t=10))
            st.plotly_chart(fig2, use_container_width=True, key="rtw_accuracy_trend")
    with col2:
        st.subheader("Miss Breakdown by Number")
        misses_df = rtw_df[rtw_df["Result Modifier"] == "M"]
        if misses_df.empty:
            st.success("No misses recorded in the current report scope! 🎯")
        else:
            miss_counts = misses_df["Target Segment"].value_counts().reset_index()
            miss_counts.columns = ["Segment", "Misses"]
            fig3 = px.bar(miss_counts.head(10), x="Segment", y="Misses", color_discrete_sequence=[COLORS["miss"]], labels={"Segment": "Target Segment", "Misses": "Total Misses"})
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(type="category"), yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=320, margin=dict(t=10))
            st.plotly_chart(fig3, use_container_width=True, key="rtw_miss_breakdown")
    st.subheader("Consecutive Hit Streaks")
    if streak_summary.empty:
        st.info("No streaks of 2 or more consecutive hits were found.")
    else:
        s1, s2 = st.columns(2)
        s1.metric("2+ Hit Streaks", f"{int(streak_summary['Count'].sum()):,}")
        s2.metric("Unique Streak Lengths", f"{len(streak_summary):,}")
        fig4 = px.bar(streak_summary.sort_values("Streak Length"), x="Count", y="Label", orientation="h", text="Count", color="Streak Length", color_continuous_scale=["#4f98a3", "#01696f"], labels={"Count": "Number of streaks", "Label": "Consecutive hits"})
        fig4.update_traces(texttemplate="%{text}", textposition="outside")
        fig4.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="rgba(255,255,255,0.05)"), yaxis=dict(type="category"), height=max(300, 70 * len(streak_summary)), margin=dict(t=10))
        st.plotly_chart(fig4, use_container_width=True, key="rtw_hit_streaks")
    render_adjacent_section(rtw_df, "RTW Adjacent Miss Analysis", section_key="rtw")


def build_competition_match_summary(comp_df):
    if comp_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    comp_df = comp_df.copy().sort_values(["Session", "Timestamp", "Row Order"], na_position="last")
    match_cols = ["Session"]
    if "Date" in comp_df.columns:
        match_cols.append("Date")
    player_match = comp_df.groupby(match_cols + ["Name"]).agg(
        Throws=("Score", "count"), Total_Scored=("Score", "sum"), Avg_Points_Throw=("Score", "mean"),
        Checkout_Attempts=("Checkout Attempt", "sum"), Checkout_Successes=("Checkout Success", "sum"), Busts=("Competition Bust", "sum"),
        Avg_Remaining=("Points Remaining", "mean"), Start_Target=("Points Target", "max")
    ).reset_index()
    if player_match.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    visit_df = comp_df.groupby(["Session", "Name", "Visit Number"]).agg(Visit_Points=("Score", "sum")).reset_index()
    visit_summary = visit_df.groupby(["Session", "Name"]).agg(Visits=("Visit_Points", "count"), Avg_Points_Visit=("Visit_Points", "mean"), Best_Visit=("Visit_Points", "max")).reset_index()
    player_match = player_match.merge(visit_summary, on=["Session", "Name"], how="left")
    player_match["Checkout %"] = (player_match["Checkout_Successes"] / player_match["Checkout_Attempts"].replace(0, np.nan) * 100).round(1)
    player_match["Avg_Points_Throw"] = player_match["Avg_Points_Throw"].round(2)
    player_match["Avg_Points_Visit"] = player_match["Avg_Points_Visit"].round(2)
    player_match["Best_Visit"] = player_match["Best_Visit"].fillna(0).astype(float).round(0)
    winners = player_match.sort_values(["Session", "Checkout_Successes", "Total_Scored", "Avg_Points_Throw"], ascending=[True, False, False, False]).groupby("Session").head(1)[["Session", "Name"]].rename(columns={"Name": "Winner"})
    session_summary = comp_df.groupby(["Session"]).agg(Date=("Date", "max"), Players=("Name", lambda x: ", ".join(sorted(pd.Series(x).dropna().astype(str).unique()))), Total_Throws=("Score", "count"), Total_Points=("Score", "sum"), Checkout_Attempts=("Checkout Attempt", "sum"), Checkout_Successes=("Checkout Success", "sum"), Busts=("Competition Bust", "sum")).reset_index().merge(winners, on="Session", how="left").sort_values("Session", ascending=False)
    session_summary["Checkout %"] = (session_summary["Checkout_Successes"] / session_summary["Checkout_Attempts"].replace(0, np.nan) * 100).round(1)
    throw_split = comp_df.groupby(["Name", "Throw In Visit"]).agg(Throws=("Score", "count"), Avg_Points=("Score", "mean"), Total_Points=("Score", "sum"), Checkout_Attempts=("Checkout Attempt", "sum"), Checkout_Successes=("Checkout Success", "sum")).reset_index()
    throw_split["Checkout %"] = (throw_split["Checkout_Successes"] / throw_split["Checkout_Attempts"].replace(0, np.nan) * 100).round(1)
    throw_split["Avg_Points"] = throw_split["Avg_Points"].round(2)
    return player_match, session_summary, throw_split


def tab_competition(df):
    st.subheader("Competition Report — 501 Match Analysis")
    include_all_modes = st.toggle("Include all modes in this report", value=False, key="competition_include_all_modes", help="Off = Competition only. On = use all currently filtered data.")
    comp_df, scope_label = get_mode_scoped_df(df, "Competition", include_all_modes)
    if comp_df.empty:
        st.info("No data found for this Competition report with the current filters.")
        return
    st.caption(format_mode_scope_caption(comp_df, scope_label))
    player_match, session_summary, throw_split = build_competition_match_summary(comp_df)
    if player_match.empty:
        st.info("Not enough Competition data to build the report.")
        return
    overall_checkout_attempts = int(comp_df["Checkout Attempt"].sum())
    overall_checkout_successes = int(comp_df["Checkout Success"].sum())
    overall_checkout_pct = (overall_checkout_successes / overall_checkout_attempts * 100) if overall_checkout_attempts else 0
    overall_avg_throw = comp_df["Score"].mean() if len(comp_df) else 0
    visit_points = comp_df.groupby(["Session", "Name", "Visit Number"]).agg(Visit_Points=("Score", "sum")).reset_index()
    overall_avg_visit = visit_points["Visit_Points"].mean() if not visit_points.empty else 0
    bust_rate = comp_df["Competition Bust"].mean() * 100 if len(comp_df) else 0
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Matches", f"{session_summary['Session'].nunique():,}")
    c2.metric("Avg Points / Throw", f"{overall_avg_throw:.2f}")
    c3.metric("Avg Points / Visit", f"{overall_avg_visit:.2f}")
    c4.metric("Checkout %", f"{overall_checkout_pct:.1f}%")
    c5.metric("Checkout Successes", f"{overall_checkout_successes:,}")
    c6.metric("Bust Rate", f"{bust_rate:.1f}%")
    st.subheader("Match Winners")
    st.dataframe(session_summary[["Session", "Date", "Players", "Winner", "Total_Throws", "Total_Points", "Checkout_Attempts", "Checkout_Successes", "Checkout %", "Busts"]], use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Player Match Summary")
        display_df = player_match.copy().sort_values(["Session", "Avg_Points_Throw"], ascending=[False, False])
        st.dataframe(display_df[["Session", "Name", "Throws", "Total_Scored", "Avg_Points_Throw", "Avg_Points_Visit", "Best_Visit", "Checkout_Attempts", "Checkout_Successes", "Checkout %", "Busts"]], use_container_width=True, hide_index=True)
    with col2:
        st.subheader("Average Scoring by Match")
        fig = px.bar(player_match.sort_values(["Session", "Name"]), x="Session", y="Avg_Points_Throw", color="Name", barmode="group", text="Avg_Points_Throw", labels={"Avg_Points_Throw": "Avg points / throw"})
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=420, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True, key="competition_scoring_by_match")
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Average Points per Visit")
        fig2 = px.bar(player_match.sort_values("Avg_Points_Visit", ascending=False), x="Name", y="Avg_Points_Visit", color="Name", text="Avg_Points_Visit", labels={"Avg_Points_Visit": "Avg points / visit of 3"})
        fig2.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=360, margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True, key="competition_avg_per_visit")
    with col4:
        st.subheader("Checkout and Bust Profile")
        profile = player_match.groupby("Name").agg(Checkout_Attempts=("Checkout_Attempts", "sum"), Checkout_Successes=("Checkout_Successes", "sum"), Busts=("Busts", "sum"), Throws=("Throws", "sum")).reset_index()
        profile["Checkout %"] = (profile["Checkout_Successes"] / profile["Checkout_Attempts"].replace(0, np.nan) * 100).round(1)
        profile["Bust %"] = (profile["Busts"] / profile["Throws"].replace(0, np.nan) * 100).round(1)
        melted = profile.melt(id_vars="Name", value_vars=["Checkout %", "Bust %"], var_name="Metric", value_name="Rate")
        fig3 = px.bar(melted, x="Name", y="Rate", color="Metric", barmode="group", text="Rate", color_discrete_map={"Checkout %": COLORS["hit"], "Bust %": COLORS["miss"]})
        fig3.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=360, margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True, key="competition_checkout_bust_profile")
    st.subheader("First, Second, Third Dart Breakdown")
    if throw_split.empty:
        st.info("No throw-order data available.")
    else:
        throw_labels = {1: "1st dart", 2: "2nd dart", 3: "3rd dart"}
        throw_split["Throw Label"] = throw_split["Throw In Visit"].map(throw_labels).fillna(throw_split["Throw In Visit"].astype(str))
        fig4 = px.bar(throw_split, x="Throw Label", y="Avg_Points", color="Name", barmode="group", text="Avg_Points", labels={"Avg_Points": "Avg points"})
        fig4.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig4.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=360, margin=dict(t=10))
        st.plotly_chart(fig4, use_container_width=True, key="competition_throw_order_breakdown")
        st.dataframe(throw_split[["Name", "Throw Label", "Throws", "Avg_Points", "Total_Points", "Checkout_Attempts", "Checkout_Successes", "Checkout %"]], use_container_width=True, hide_index=True)
    st.subheader("Scoring Bands")
    scoring = comp_df.copy()
    scoring["Scoring Band"] = pd.cut(scoring["Score"], bins=[-1, 0, 20, 40, 60, 100, 180], labels=["0", "1-20", "21-40", "41-60", "61-100", "101-180"])
    bands = scoring.groupby(["Name", "Scoring Band"], observed=False).size().reset_index(name="Count")
    if not bands.empty:
        fig5 = px.bar(bands, x="Scoring Band", y="Count", color="Name", barmode="group")
        fig5.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(gridcolor="rgba(255,255,255,0.05)"), height=340, margin=dict(t=10))
        st.plotly_chart(fig5, use_container_width=True, key="competition_scoring_bands")
    render_adjacent_section(comp_df, "Competition Adjacent Miss Analysis", section_key="competition")


def tab_players(df):
    st.subheader("Player Comparison")
    player_stats = df.groupby("Name").agg(Throws=("Hit", "count"), Hits=("Hit", "sum"), Misses=("Result Modifier", lambda x: (x == "M").sum()), Avg_Score=("Score", "mean"), Avg_Error_mm=("Distance from Target mm", "mean"), Doubles=("Result Modifier", lambda x: (x == "D").sum()), Triples=("Result Modifier", lambda x: (x == "T").sum()), Adjacent_Misses=("Is Adjacent Miss", "sum"), Sessions=("Session", "nunique")).reset_index()
    if player_stats.empty:
        st.info("No player data available.")
        return
    player_stats["Accuracy (%)"] = (player_stats["Hits"] / player_stats["Throws"] * 100).round(1)
    player_stats["Avg Score"] = player_stats["Avg_Score"].round(2)
    player_stats["Avg Error (mm)"] = player_stats["Avg_Error_mm"].round(1)
    player_stats["Adjacent Miss %"] = (player_stats["Adjacent_Misses"] / player_stats["Throws"] * 100).round(1)
    st.dataframe(player_stats[["Name", "Throws", "Hits", "Misses", "Accuracy (%)", "Avg Score", "Avg Error (mm)", "Adjacent Miss %", "Doubles", "Triples", "Sessions"]], use_container_width=True, hide_index=True)
    if len(df["Name"].dropna().unique()) >= 2:
        fig = px.bar(player_stats, x="Name", y="Accuracy (%)", color="Name", color_discrete_sequence=px.colors.qualitative.Set2, text="Accuracy (%)")
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False, yaxis=dict(range=[0, 110], gridcolor="rgba(255,255,255,0.05)"), height=350, margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True, key="players_comparison_accuracy")
    else:
        st.info("Add more players to see a comparison chart.")


def tab_sessions(df):
    st.subheader("Session Summary")
    sess_stats = df.groupby(["Session", "Name", "Date"]).agg(Throws=("Hit", "count"), Hits=("Hit", "sum"), Misses=("Result Modifier", lambda x: (x == "M").sum()), Avg_Score=("Score", "mean"), Avg_Error_mm=("Distance from Target mm", "mean"), Adjacent_Misses=("Is Adjacent Miss", "sum"), Modes=("Mode", lambda x: ", ".join(sorted(pd.Series(x).dropna().astype(str).unique())))).reset_index()
    if sess_stats.empty:
        st.info("No session data available.")
        return
    sess_stats["Accuracy (%)"] = (sess_stats["Hits"] / sess_stats["Throws"] * 100).round(1)
    sess_stats["Avg Score"] = sess_stats["Avg_Score"].round(2)
    sess_stats["Avg Error (mm)"] = sess_stats["Avg_Error_mm"].round(1)
    sess_stats["Adjacent Miss %"] = (sess_stats["Adjacent_Misses"] / sess_stats["Throws"] * 100).round(1)
    sess_stats = sess_stats.sort_values("Session", ascending=False)
    st.dataframe(sess_stats[["Session", "Name", "Date", "Modes", "Throws", "Hits", "Misses", "Accuracy (%)", "Avg Score", "Avg Error (mm)", "Adjacent Miss %"]], use_container_width=True, hide_index=True)
    trend = df.dropna(subset=["Session"]).groupby("Session").agg(Throws=("Hit", "count"), Hits=("Hit", "sum"), Avg_Score=("Score", "mean")).reset_index().sort_values("Session")
    if trend.empty:
        return
    trend["Accuracy (%)"] = (trend["Hits"] / trend["Throws"] * 100).round(1)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=trend["Session"], y=trend["Throws"], name="Throws", marker_color="rgba(79,152,163,0.45)", yaxis="y2"))
    fig.add_trace(go.Scatter(x=trend["Session"], y=trend["Accuracy (%)"], mode="lines+markers", name="Accuracy (%)", line=dict(color=COLORS["primary"], width=3)))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(title="Session", gridcolor="rgba(255,255,255,0.05)"), yaxis=dict(title="Accuracy (%)", gridcolor="rgba(255,255,255,0.05)"), yaxis2=dict(title="Throws", overlaying="y", side="right", showgrid=False), height=360, margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True, key="sessions_summary_trend")


def tab_raw(df):
    st.subheader("Raw Data")
    col1, col2 = st.columns([1, 1])
    with col1:
        max_rows = st.slider("Rows to show", min_value=25, max_value=1000, value=250, step=25, key="raw_rows")
    with col2:
        sort_desc = st.checkbox("Newest first", value=True, key="raw_sort_desc")
    raw_df = df.copy()
    if "Timestamp" in raw_df.columns:
        raw_df = raw_df.sort_values("Timestamp", ascending=not sort_desc, na_position="last")
    st.dataframe(raw_df.head(max_rows), use_container_width=True, hide_index=True)
    csv = raw_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered data as CSV", data=csv, file_name="dart_tracker_filtered_data.csv", mime="text/csv")


def show_troubleshooting():
    st.markdown("""
- Confirm the Google Sheet ID is correct.
- Confirm the worksheet name is `data`.
- Share the Google Sheet with the service account email as Viewer.
- Add a valid `[gcp_service_account]` section to Streamlit secrets.
- Make sure `private_key` contains real newlines, not escaped `\\n`.
- Check that all expected columns exist in the sheet.
    """)


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
    tabs = st.tabs(["📊 Overview", "🎯 Accuracy", "💯 Points", "🏆 Competition", "📍 Positions", "🔄 RTW", "👥 Players", "📅 Sessions", "🗃️ Raw Data"])
    with tabs[0]:
        tab_overview(filtered)
    with tabs[1]:
        tab_accuracy(filtered)
    with tabs[2]:
        tab_points(filtered)
    with tabs[3]:
        tab_competition(filtered)
    with tabs[4]:
        tab_positions(filtered)
    with tabs[5]:
        tab_rtw(filtered)
    with tabs[6]:
        tab_players(filtered)
    with tabs[7]:
        tab_sessions(filtered)
    with tabs[8]:
        tab_raw(filtered)


if __name__ == "__main__":
    main()
