import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
from datetime import datetime

st.set_page_config(
    page_title="Dart Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODIFIER_SCORES = {"S": 1, "D": 2, "T": 3, "M": 0}
MODIFIER_LABELS = {
    "S": "Single", "D": "Double", "T": "Triple",
    "M": "Miss", "+": "Bullseye", "*": "Bull Socket"
}
COLORS = {
    "hit": "#2ecc71", "miss": "#e74c3c",
    "primary": "#01696f", "secondary": "#4f98a3",
}


def score_throw(result_segment, result_modifier):
    seg = str(result_segment)
    mod = str(result_modifier)
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
    if str(result_mod) == "M":
        return False
    return str(target_seg) == str(result_seg)


@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_drive():
    errors = []

    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        file_id = st.secrets["drive"]["file_id"]
    except KeyError as e:
        return None, [f"❌ Missing secret key: {e}. Check your secrets config has [gcp_service_account] and [drive] sections."]

    try:
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
    except Exception as e:
        return None, [f"❌ Failed to build credentials: {e}\n\nCheck your private_key formatting — it needs real newlines, not \\\\n."]

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        return None, [f"❌ Failed to connect to Google Drive API: {e}"]

    try:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buffer.seek(0)
    except Exception as e:
        err_str = str(e)
        if "404" in err_str:
            return None, ["❌ File not found (404). Check the file_id in your secrets and that the file is shared with the service account email."]
        elif "403" in err_str:
            return None, ["❌ Permission denied (403). Make sure you shared the CSV with the service account email as Viewer."]
        else:
            return None, [f"❌ Failed to download file: {e}"]

    try:
        df = pd.read_csv(buffer)
    except Exception as e:
        return None, [f"❌ Failed to parse CSV: {e}\n\nMake sure the file on Drive is a valid CSV."]

    expected = [
        "Timestamp", "Target Segment", "Target Modifier",
        "Target X Offset", "Target Y Offset",
        "Result Segment", "Result Modifier",
        "Result X Offset", "Result Y Offset",
        "Name", "Mode", "Session"
    ]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        return None, [f"❌ CSV is missing columns: {missing}. Found: {list(df.columns)}"]

    try:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"])
        df["Session"] = df["Session"].astype(int)
        for col in ["Target X Offset", "Target Y Offset", "Result X Offset", "Result Y Offset"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    except Exception as e:
        return None, [f"❌ Type conversion error: {e}"]

    df["Score"] = df.apply(lambda r: score_throw(r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Hit"] = df.apply(lambda r: is_hit(r["Target Segment"], r["Result Segment"], r["Result Modifier"]), axis=1)
    df["Date"] = df["Timestamp"].dt.date
    df["Result Modifier Label"] = df["Result Modifier"].map(MODIFIER_LABELS).fillna(df["Result Modifier"])

    return df, []


def render_sidebar(df):
    st.sidebar.markdown("## 🎯 Dart Tracker")
    st.sidebar.markdown("---")

    if st.sidebar.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Filters")

    players = sorted(df["Name"].dropna().unique().tolist())
    selected_player = st.sidebar.selectbox("Player", ["All"] + players)

    modes = sorted(df["Mode"].dropna().unique().tolist())
    selected_mode = st.sidebar.selectbox("Mode", ["All"] + modes)

    sessions = sorted(df["Session"].unique().tolist())
    session_options = ["All"] + [f"Session {s}" for s in sessions]
    selected_session_label = st.sidebar.selectbox("Session", session_options)
    selected_session = None if selected_session_label == "All" else int(selected_session_label.split(" ")[1])

    dates = sorted(df["Date"].unique())
    if len(dates) > 1:
        date_range = st.sidebar.date_input(
            "Date range", value=(dates[0], dates[-1]),
            min_value=dates[0], max_value=dates[-1],
        )
    else:
        date_range = (dates[0], dates[0])

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Data last fetched: {datetime.now().strftime('%H:%M:%S')}")

    return selected_player, selected_mode, selected_session, date_range


def apply_filters(df, player, mode, session, date_range):
    f = df.copy()
    if player != "All":
        f = f[f["Name"] == player]
    if mode != "All":
        f = f[f["Mode"] == mode]
    if session is not None:
        f = f[f["Session"] == session]
    try:
        start, end = date_range[0], date_range[-1]
        f = f[(f["Date"] >= start) & (f["Date"] <= end)]
    except Exception:
        pass
    return f


def render_kpis(df):
    total = len(df)
    hits = df["Hit"].sum()
    misses = (df["Result Modifier"] == "M").sum()
    acc = (hits / total * 100) if total > 0 else 0
    avg_sc = df["Score"].mean() if total > 0 else 0
    doubles = (df["Result Modifier"] == "D").sum()
    triples = (df["Result Modifier"] == "T").sum()

    cols = st.columns(7)
    for col, (label, value) in zip(cols, [
        ("🎯 Throws", f"{total:,}"),
        ("✅ Hits", f"{hits:,}"),
        ("💥 Misses", f"{misses:,}"),
        ("📊 Accuracy", f"{acc:.1f}%"),
        ("⚡ Avg Score", f"{avg_sc:.2f}"),
        ("✌️ Doubles", f"{doubles:,}"),
        ("🔱 Triples", f"{triples:,}"),
    ]):
        col.metric(label, value)


def tab_overview(df):
    st.subheader("Accuracy by Segment")

    seg_stats = (
        df.groupby("Target Segment")
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
    )
    seg_stats["Accuracy"] = (seg_stats["Hits"] / seg_stats["Throws"] * 100).round(1)
    seg_stats = seg_stats.sort_values(
        "Target Segment",
        key=lambda s: s.apply(lambda v: (0, int(v)) if str(v).lstrip("-").isdigit() else (1, str(v)))
    )

    fig = px.bar(
        seg_stats, x="Target Segment", y="Accuracy",
        color="Accuracy",
        color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
        range_color=[0, 100], text="Accuracy",
    )
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(
        coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
        xaxis=dict(type="category"), height=400, margin=dict(t=20, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Result Breakdown")
        mod_counts = df["Result Modifier Label"].value_counts().reset_index()
        mod_counts.columns = ["Modifier", "Count"]
        fig2 = px.pie(mod_counts, names="Modifier", values="Count",
                      color_discrete_sequence=px.colors.qualitative.Set2, hole=0.4)
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=320, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        st.subheader("Score Distribution")
        fig3 = px.histogram(df[df["Score"] > 0], x="Score", nbins=20,
                            color_discrete_sequence=[COLORS["primary"]])
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                           height=320, margin=dict(t=10, b=10), bargap=0.1)
        st.plotly_chart(fig3, use_container_width=True)


def tab_accuracy(df):
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Accuracy Over Time (by Session)")
        sess_acc = (
            df.groupby("Session")
            .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
            .reset_index()
        )
        sess_acc["Accuracy"] = (sess_acc["Hits"] / sess_acc["Throws"] * 100).round(1)
        if len(sess_acc) >= 3:
            sess_acc["Rolling Avg (3)"] = sess_acc["Accuracy"].rolling(3, min_periods=1).mean().round(1)

        fig = px.line(sess_acc, x="Session", y="Accuracy", markers=True,
                      color_discrete_sequence=[COLORS["primary"]])
        if "Rolling Avg (3)" in sess_acc.columns:
            fig.add_scatter(x=sess_acc["Session"], y=sess_acc["Rolling Avg (3)"],
                            mode="lines", name="3-session avg",
                            line=dict(dash="dash", color=COLORS["secondary"], width=2))
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"),
                          height=350, margin=dict(t=10))
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
        fig2 = px.bar(worst, x="Accuracy", y="Target Segment", orientation="h",
                      color="Accuracy",
                      color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
                      range_color=[0, 100], text="Accuracy",
                      labels={"Target Segment": "Segment", "Accuracy": "Hit Rate (%)"})
        fig2.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
        fig2.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)",
                           plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(type="category"),
                           xaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
                           height=350, margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Accuracy Heatmap — Segment × Session")
    pivot = (
        df.groupby(["Session", "Target Segment"])
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
    )
    pivot["Accuracy"] = (pivot["Hits"] / pivot["Throws"] * 100).round(1)
    try:
        heat = pivot.pivot(index="Target Segment", columns="Session", values="Accuracy")
        fig3 = px.imshow(heat, color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
                         range_color=[0, 100], aspect="auto", labels=dict(color="Accuracy %"))
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           height=500, margin=dict(t=10))
        st.plotly_chart(fig3, use_container_width=True)
    except Exception as e:
        st.info(f"Heatmap requires data across multiple sessions. ({e})")


def tab_scatter(df):
    st.subheader("Throw Positions — Where Darts Actually Land")
    st.caption("X/Y = mm from board centre. Green = hit, Red = miss.")

    target_options = sorted(
        df["Target Segment"].unique().tolist(),
        key=lambda v: (0, int(v)) if str(v).lstrip("-").isdigit() else (1, str(v))
    )
    selected_seg = st.selectbox("Filter by Target Segment", ["All"] + [str(s) for s in target_options])

    plot_df = df.copy()
    if selected_seg != "All":
        plot_df = plot_df[plot_df["Target Segment"].astype(str) == selected_seg]

    plot_df["hit_label"] = plot_df["Hit"].map({True: "Hit", False: "Miss"})

    fig = px.scatter(
        plot_df, x="Result X Offset", y="Result Y Offset",
        color="hit_label",
        color_discrete_map={"Hit": COLORS["hit"], "Miss": COLORS["miss"]},
        hover_data=["Name", "Target Segment", "Target Modifier",
                    "Result Segment", "Result Modifier", "Score", "Session"],
        opacity=0.65,
        labels={"Result X Offset": "X (mm)", "Result Y Offset": "Y (mm)", "hit_label": "Result"},
    )

    theta = np.linspace(0, 2 * np.pi, 200)
    for r in [6.35, 15.9, 99, 107, 162, 170]:
        fig.add_trace(go.Scatter(
            x=r * np.cos(theta), y=r * np.sin(theta),
            mode="lines",
            line=dict(color="rgba(255,255,255,0.15)", width=1, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", zeroline=False, scaleanchor="x"),
        height=560, margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Distance from Target Centre (mm)")
    df2 = df.copy()
    df2["Distance"] = np.sqrt(
        (df2["Result X Offset"] - df2["Target X Offset"])**2 +
        (df2["Result Y Offset"] - df2["Target Y Offset"])**2
    )
    avg_dist = df2["Distance"].mean()
    fig2 = px.histogram(df2, x="Distance", nbins=30,
                        color_discrete_sequence=[COLORS["secondary"]],
                        labels={"Distance": "Distance from target (mm)"})
    fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                       yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                       height=300, margin=dict(t=10), bargap=0.1)
    st.plotly_chart(fig2, use_container_width=True)
    st.caption(f"Average distance from target centre: **{avg_dist:.1f} mm**")


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

    st.subheader("Accuracy by Number (1–20)")
    rtw_num = rtw_df[rtw_df["Target Segment"].apply(lambda x: str(x).isdigit())].copy()
    rtw_num["Target Segment"] = rtw_num["Target Segment"].astype(int)
    rtw_seg = (
        rtw_num.groupby("Target Segment")
        .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
        .reset_index()
        .sort_values("Target Segment")
    )
    rtw_seg["Accuracy"] = (rtw_seg["Hits"] / rtw_seg["Throws"] * 100).round(1)

    fig = px.bar(rtw_seg, x="Target Segment", y="Accuracy",
                 color="Accuracy",
                 color_continuous_scale=["#e74c3c", "#f39c12", "#2ecc71"],
                 range_color=[0, 100], text="Accuracy",
                 labels={"Target Segment": "Number", "Accuracy": "Hit Rate (%)"})
    fig.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
    fig.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",
                      yaxis=dict(range=[0, 115], gridcolor="rgba(255,255,255,0.05)"),
                      xaxis=dict(tickmode="linear", tick0=1, dtick=1),
                      height=400, margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Accuracy Trend per Session")
        sess_rtw = (
            rtw_df.groupby("Session")
            .agg(Throws=("Hit", "count"), Hits=("Hit", "sum"))
            .reset_index()
        )
        sess_rtw["Accuracy"] = (sess_rtw["Hits"] / sess_rtw["Throws"] * 100).round(1)
        fig2 = px.line(sess_rtw, x="Session", y="Accuracy", markers=True,
                       color_discrete_sequence=[COLORS["primary"]])
        if len(sess_rtw) >= 3:
            sess_rtw["Rolling"] = sess_rtw["Accuracy"].rolling(3, min_periods=1).mean().round(1)
            fig2.add_scatter(x=sess_rtw["Session"], y=sess_rtw["Rolling"],
                             mode="lines", name="3-session avg",
                             line=dict(dash="dash", color=COLORS["secondary"], width=2))
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis=dict(range=[0, 105], gridcolor="rgba(255,255,255,0.05)"),
                           height=320, margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        st.subheader("Miss Breakdown by Number")
        misses_df = rtw_df[rtw_df["Result Modifier"] == "M"]
        if not misses_df.empty:
            miss_counts = misses_df["Target Segment"].value_counts().reset_index()
            miss_counts.columns = ["Segment", "Misses"]
            fig3 = px.bar(miss_counts.head(10), x="Segment", y="Misses",
                          color_discrete_sequence=[COLORS["miss"]],
                          labels={"Segment": "Target Segment", "Misses": "Total Misses"})
            fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               xaxis=dict(type="category"),
                               yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                               height=320, margin=dict(t=10))
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
            Doubles=("Result Modifier", lambda x: (x == "D").sum()),
            Triples=("Result Modifier", lambda x: (x == "T").sum()),
            Sessions=("Session", "nunique"),
        )
        .reset_index()
    )
    player_stats["Accuracy (%)"] = (player_stats["Hits"] / player_stats["Throws"] * 100).round(1)
    player_stats["Avg Score"] = player_stats["Avg_Score"].round(2)

    st.dataframe(
        player_stats[["Name", "Throws", "Hits", "Misses", "Accuracy (%)", "Avg Score", "Doubles", "Triples", "Sessions"]],
        use_container_width=True, hide_index=True,
    )

    players = df["Name"].dropna().unique()
    if len(players) >= 2:
        fig = px.bar(player_stats, x="Name", y="Accuracy (%)", color="Name",
                     color_discrete_sequence=px.colors.qualitative.Set2,
                     text="Accuracy (%)")
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          showlegend=False,
                          yaxis=dict(range=[0, 110], gridcolor="rgba(255,255,255,0.05)"),
                          height=350, margin=dict(t=10))
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
            Modes=("Mode", lambda x: ", ".join(sorted(x.unique()))),
        )
        .reset_index()
    )
    sess_stats["Accuracy (%)"] = (sess_stats["Hits"] / sess_stats["Throws"] * 100).round(1)
    sess_stats["Avg Score"] = sess_stats["Avg_Score"].round(2)
    sess_stats = sess_stats.sort_values("Session", ascending=False)

    st.dataframe(
        sess_stats[["Session", "Name", "Date", "Throws", "Hits", "Misses", "Accuracy (%)", "Avg Score", "Modes"]],
        use_container_width=True, hide_index=True,
    )

    st.subheader("Throws per Session")
    fig = px.bar(sess_stats.sort_values("Session"), x="Session", y="Throws", color="Name",
                 color_discrete_sequence=px.colors.qualitative.Set2,
                 labels={"Session": "Session #", "Throws": "Total Throws"})
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      yaxis=dict(gridcolor="rgba(255,255,255,0.05)"),
                      xaxis=dict(tickmode="linear"), height=350, margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True)


def tab_raw(df):
    st.subheader(f"Raw Data — {len(df):,} rows")
    st.dataframe(df.drop(columns=["Date"], errors="ignore"),
                 use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download filtered CSV", csv,
                       "dart_throws_filtered.csv", "text/csv")


def main():
    with st.spinner("Fetching data from Google Drive..."):
        df, errors = load_data_from_drive()

    if errors:
        st.error("### ⚠️ Could not load data")
        for err in errors:
            st.error(err)
        with st.expander("🔧 Troubleshooting checklist"):
            st.markdown("""
**Most common issues:**

1. **Private key formatting** — In Streamlit secrets, the key must use triple quotes with real newlines:
```
private_key = """-----BEGIN RSA PRIVATE KEY-----
MIIEo...
-----END RSA PRIVATE KEY-----
"""
```
Do NOT use `\\n` escape sequences.

2. **File not shared** — Right-click the CSV in Drive → Share → add the service account email as Viewer.

3. **Wrong file_id** — Copy just the ID from the Drive URL:
`drive.google.com/file/d/`**`THIS_PART`**`/view`

4. **Drive API not enabled** — Google Cloud Console → APIs & Services → Enable "Google Drive API".

5. **Wrong project_id** — Must match the project where the service account lives.
            """)
        st.stop()

    if df is None or df.empty:
        st.warning("The CSV loaded but contains no data.")
        st.stop()

    player, mode, session, date_range = render_sidebar(df)
    filtered = apply_filters(df, player, mode, session, date_range)

    st.title("🎯 Dart Tracker")

    if filtered.empty:
        st.warning("No data matches the current filters. Try adjusting the sidebar.")
        st.stop()

    render_kpis(filtered)
    st.markdown("---")

    tabs = st.tabs([
        "📊 Overview", "🎯 Accuracy", "📍 Positions",
        "🔄 RTW", "👥 Players", "📅 Sessions", "🗃️ Raw Data"
    ])
    with tabs[0]: tab_overview(filtered)
    with tabs[1]: tab_accuracy(filtered)
    with tabs[2]: tab_scatter(filtered)
    with tabs[3]: tab_rtw(filtered)
    with tabs[4]: tab_players(filtered)
    with tabs[5]: tab_sessions(filtered)
    with tabs[6]: tab_raw(filtered)


if __name__ == "__main__":
    main()
