import streamlit as st
import math
import csv
import datetime
import base64
import io
import json
import requests
import pandas as pd
import plotly.graph_objects as go

APP_VERSION = "v0.8"

st.set_page_config(
    page_title="Dartboard Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── GitHub config ────────────────────────────────────────────────────────────
GITHUB_TOKEN = st.secrets["github"]["token"]
GITHUB_USER  = st.secrets["github"]["username"]
GITHUB_REPO  = st.secrets["github"]["repo"]
CSV_PATH     = "dart_data.csv"
RAW_CSV_URL  = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/{CSV_PATH}"
API_FILE_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{CSV_PATH}"
GH_HEADERS   = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
CSV_COLUMNS = [
    "Timestamp","Target Segment","Target Modifier",
    "Target X Offset","Target Y Offset",
    "Result Segment","Result Modifier",
    "Result X Offset","Result Y Offset",
    "Name","Mode","Session"
]

# Board geometry (in data coordinates — board radius = 170 units, matching real dartboard mm)
R            = 170.0
inner_bull_r = 6.35
outer_bull_r = 16.0
triple_inner = 99.0
triple_outer = 107.0
double_inner = 162.0
double_outer = 170.0

# ─── GitHub helpers ───────────────────────────────────────────────────────────
def load_csv_from_github():
    try:
        resp = requests.get(RAW_CSV_URL, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            return pd.read_csv(io.StringIO(resp.text))
    except Exception:
        pass
    return pd.DataFrame(columns=CSV_COLUMNS)

def append_row_to_github(row):
    r = requests.get(API_FILE_URL, headers=GH_HEADERS, timeout=10)
    if r.status_code == 200:
        info     = r.json()
        sha      = info["sha"]
        old_text = base64.b64decode(info["content"].replace("\n","")).decode("utf-8")
    else:
        sha = None; old_text = ""
    buf = io.StringIO()
    if old_text.strip():
        buf.write(old_text)
        if not old_text.endswith("\n"):
            buf.write("\n")
    else:
        csv.writer(buf).writerow(CSV_COLUMNS)
    csv.writer(buf).writerow(row)
    encoded = base64.b64encode(buf.getvalue().encode()).decode()
    payload = {"message": f"dart throw - {row[0]}", "content": encoded}
    if sha:
        payload["sha"] = sha
    requests.put(API_FILE_URL, headers=GH_HEADERS, json=payload, timeout=15)

# ─── Dart logic ───────────────────────────────────────────────────────────────
def determine_segment(angle_deg):
    angle = (angle_deg - 90) % 360
    order = [20,5,12,9,14,11,8,16,7,19,3,17,2,15,10,6,13,4,18,1,20]
    idx   = int((angle + 9) // 18)
    return order[min(max(idx, 0), len(order)-1)]

def determine_modifier(dist):
    if   dist <= inner_bull_r:                 return "+"
    elif dist <= outer_bull_r:                 return "*"
    elif double_inner <= dist <= double_outer: return "D"
    elif triple_inner <= dist <= triple_outer: return "T"
    elif dist > double_outer:                  return "M"
    else:                                      return "S"

# ─── Build Plotly dartboard figure ───────────────────────────────────────────
def build_dartboard(click_positions):
    fig = go.Figure()

    segment_order = [20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5]
    n_segs        = 20
    angle_inc     = 360 / n_segs
    # offset so segment 20 straddles the top (90 degrees in standard math coords)
    offset        = 90 + angle_inc / 2

    def seg_color(i, ring):
        # ring: "single","double","triple"
        even = (i % 2 == 0)
        if ring == "single":
            return "#2a2a2a" if even else "#e8e0cc"
        elif ring == "double":
            return "#1e7a36" if even else "#c0182a"
        elif ring == "triple":
            return "#1e7a36" if even else "#c0182a"
        return "#888"

    def make_sector_path(r_inner, r_outer, a_start_deg, a_end_deg):
        """Return SVG-style path for an annular sector."""
        steps = 12
        angles = [a_start_deg + (a_end_deg - a_start_deg) * t / steps for t in range(steps+1)]
        # outer arc forward
        ox = [r_outer * math.cos(math.radians(a)) for a in angles]
        oy = [r_outer * math.sin(math.radians(a)) for a in angles]
        # inner arc backward
        ix = [r_inner * math.cos(math.radians(a)) for a in reversed(angles)]
        iy = [r_inner * math.sin(math.radians(a)) for a in reversed(angles)]
        xs = ox + ix + [ox[0]]
        ys = oy + iy + [oy[0]]
        return xs, ys

    # ── Draw outer miss ring ──
    theta = list(range(361))
    fig.add_trace(go.Scatterpolar(
        r=[double_outer + 18] * 361, theta=theta,
        fill="toself", fillcolor="#1a1a1a",
        line=dict(color="#1a1a1a", width=0),
        hoverinfo="skip", showlegend=False,
        mode="lines"
    ))

    # Use cartesian coordinates for sectors (easier geometry)
    fig.update_layout(
        xaxis=dict(visible=False, range=[-210, 210], scaleanchor="y"),
        yaxis=dict(visible=False, range=[-210, 210]),
        plot_bgcolor="#0e0e0e",
        paper_bgcolor="#0e0e0e",
        margin=dict(l=10, r=10, t=10, b=10),
        width=640, height=640,
        showlegend=False,
        dragmode=False,
    )

    # Draw outer dark background circle
    circle_t = [i * 2 * math.pi / 360 for i in range(361)]
    fig.add_trace(go.Scatter(
        x=[(double_outer+20)*math.cos(t) for t in circle_t],
        y=[(double_outer+20)*math.sin(t) for t in circle_t],
        fill="toself", fillcolor="#1a1a1a",
        line=dict(color="#111", width=1),
        hoverinfo="skip", showlegend=False, mode="lines"
    ))

    rings = [
        ("single_outer", double_inner, double_outer, "double"),
        ("single_bed",   triple_outer, double_inner, "single"),
        ("triple",       triple_inner, triple_outer, "triple"),
        ("single_inner", outer_bull_r, triple_inner, "single"),
    ]

    for ring_name, r_in, r_out, ring_type in rings:
        for i in range(n_segs):
            a_start = offset - (i+1) * angle_inc
            a_end   = offset - i     * angle_inc
            xs, ys  = make_sector_path(r_in, r_out, a_start, a_end)
            seg_num = segment_order[i]
            color   = seg_color(i, ring_type)
            fig.add_trace(go.Scatter(
                x=xs, y=ys,
                fill="toself", fillcolor=color,
                line=dict(color="#000", width=0.8),
                mode="lines",
                hoverinfo="text",
                hovertext=f"{ring_type[0].upper()}{seg_num}",
                showlegend=False,
                customdata=[[seg_num, ring_type]],
            ))

    # Outer bull (green)
    t = [i * 2 * math.pi / 60 for i in range(61)]
    fig.add_trace(go.Scatter(
        x=[outer_bull_r*math.cos(a) for a in t],
        y=[outer_bull_r*math.sin(a) for a in t],
        fill="toself", fillcolor="#1e7a36",
        line=dict(color="#000", width=1),
        hoverinfo="text", hovertext="*25",
        showlegend=False, mode="lines"
    ))

    # Inner bull (red)
    fig.add_trace(go.Scatter(
        x=[inner_bull_r*math.cos(a) for a in t],
        y=[inner_bull_r*math.sin(a) for a in t],
        fill="toself", fillcolor="#c0182a",
        line=dict(color="#000", width=1),
        hoverinfo="text", hovertext="*50",
        showlegend=False, mode="lines"
    ))

    # Segment number labels
    label_r = double_outer + 14
    for i, seg in enumerate(segment_order):
        a_mid = math.radians(offset - (i + 0.5) * angle_inc)
        fig.add_annotation(
            x=label_r * math.cos(a_mid),
            y=label_r * math.sin(a_mid),
            text=str(seg),
            showarrow=False,
            font=dict(size=13, color="white", family="Arial Black"),
            xanchor="center", yanchor="middle"
        )

    # ── Click marker traces ──
    for cp in click_positions:
        xd   = cp["xOff"]
        yd   = cp["yOff"]
        col  = "#ffe033" if cp["type"] == "Target" else "#ff8c00"
        s    = 8
        # Draw X as two line segments
        fig.add_trace(go.Scatter(
            x=[xd-s, xd+s, None, xd+s, xd-s],
            y=[yd-s, yd+s, None, yd-s, yd+s],
            mode="lines",
            line=dict(color=col, width=3),
            hoverinfo="skip", showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=[xd], y=[yd], mode="markers",
            marker=dict(color=col, size=6),
            hoverinfo="skip", showlegend=False
        ))

    # Invisible scatter over the full board to capture clicks anywhere
    # Dense grid of points covering the board
    click_xs, click_ys, hover_texts = [], [], []
    step = 5
    for xi in range(-int(double_outer+18), int(double_outer+18)+1, step):
        for yi in range(-int(double_outer+18), int(double_outer+18)+1, step):
            dist = math.sqrt(xi**2 + yi**2)
            if dist <= double_outer + 18:
                click_xs.append(xi)
                click_ys.append(yi)
                seg = determine_segment(math.degrees(math.atan2(yi, xi)) if dist > outer_bull_r else 0)
                mod = determine_modifier(dist)
                hover_texts.append(f"{mod}{seg}" if dist > inner_bull_r else "Bull")

    fig.add_trace(go.Scatter(
        x=click_xs, y=click_ys,
        mode="markers",
        marker=dict(size=step*1.5, color="rgba(0,0,0,0)", opacity=0),
        hoverinfo="text",
        hovertext=hover_texts,
        showlegend=False,
        name="clickzone"
    ))

    fig.update_layout(
        xaxis=dict(visible=False, range=[-210, 210], scaleanchor="y", fixedrange=True),
        yaxis=dict(visible=False, range=[-210, 210], fixedrange=True),
        plot_bgcolor="#0e0e0e",
        paper_bgcolor="#0e0e0e",
        margin=dict(l=5, r=5, t=5, b=5),
        width=640, height=640,
        showlegend=False,
        dragmode="select",
        clickmode="event",
    )

    return fig

# ─── Session state ────────────────────────────────────────────────────────────
for k, v in {
    "recording_target": True,
    "current_target_data": None,
    "hit_cnt": 0.0, "shot_cnt": 0.0,
    "x_miss_list": [], "y_miss_list": [],
    "display_text": "", "display_perc": "",
    "click_positions": [],
    "session_num": None, "last_click": None,
    "df_loaded": False,
    "last_raw_x": "", "last_raw_y": "",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state["df_loaded"]:
    df0 = load_csv_from_github()
    st.session_state["session_num"] = (
        int(df0["Session"].max()) + 1
        if not df0.empty and "Session" in df0.columns else 1
    )
    st.session_state["df_loaded"] = True

session_num = st.session_state["session_num"]

# ─── Header ───────────────────────────────────────────────────────────────────
hc1, hc2, hc3, hc4 = st.columns([2, 2, 5, 1])
with hc1:
    inputuser = st.text_input("Name", value="Patrick", key="inputuser")
with hc2:
    inputmode = st.selectbox("Mode", ["RTW","Points"], key="inputmode")
with hc3:
    st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
    if st.session_state["recording_target"]:
        st.info("🎯 Click the board to set **TARGET**")
    else:
        st.warning("🎯 Click the board to set **RESULT**")
    st.markdown("</div>", unsafe_allow_html=True)
with hc4:
    st.markdown(
        f"<div style='padding-top:32px;text-align:right;color:#888;font-size:12px'>{APP_VERSION}</div>",
        unsafe_allow_html=True)

# ─── Layout: board + panel ────────────────────────────────────────────────────
board_col, panel_col = st.columns([3, 1])

with board_col:
    fig = build_dartboard(st.session_state["click_positions"])
    click_event = st.plotly_chart(
        fig,
        use_container_width=False,
        key="dartboard",
        on_select="rerun",
        selection_mode="points",
    )

    raw_x = st.session_state.get("last_raw_x", "")
    raw_y = st.session_state.get("last_raw_y", "")
    if raw_x and raw_y:
        st.caption(f"Last click — X: {raw_x}  Y: {raw_y}")

with panel_col:
    st.markdown("### 📊 Session Stats")
    st.markdown(f"**Session:** #{session_num}")
    st.divider()
    if st.session_state["display_text"]:
        st.markdown(st.session_state["display_text"])
    if st.session_state["display_perc"]:
        st.markdown(st.session_state["display_perc"])
    st.divider()
    if st.session_state["x_miss_list"]:
        xl = st.session_state["x_miss_list"]
        yl = st.session_state["y_miss_list"]
        st.markdown(f"**X Miss Avg:** {round(sum(xl)/len(xl),2)}")
        st.markdown(f"**Y Miss Avg:** {round(sum(yl)/len(yl),2)}")
        st.markdown(f"**Throws:** {int(st.session_state['shot_cnt'])}")
    else:
        st.caption("No throws yet")
    st.divider()
    st.markdown("🟡 Yellow X = Target")
    st.markdown("🟠 Orange X = Result")
    st.divider()
    if st.button("🔄 Reset Markers", use_container_width=True):
        st.session_state["click_positions"] = []
        st.session_state["recording_target"] = True
        st.session_state["display_text"]     = ""
        st.session_state["display_perc"]     = ""
        st.session_state["last_click"]       = None
        st.session_state["last_raw_x"]       = ""
        st.session_state["last_raw_y"]       = ""
        st.rerun()
    if st.button("🆕 New Session", use_container_width=True):
        for k in ["recording_target","current_target_data","hit_cnt","shot_cnt",
                  "x_miss_list","y_miss_list","display_text","display_perc",
                  "click_positions","last_click","df_loaded","session_num",
                  "last_raw_x","last_raw_y"]:
            st.session_state.pop(k, None)
        st.rerun()

# ─── Process Plotly click event ───────────────────────────────────────────────
if (click_event and
        hasattr(click_event, "selection") and
        click_event.selection and
        click_event.selection.get("points")):

    pts = click_event.selection["points"]
    if pts:
        pt   = pts[0]
        xd   = float(pt["x"])
        yd   = float(pt["y"])
        ck   = (round(xd, 1), round(yd, 1))

        if st.session_state["last_click"] != ck:
            st.session_state["last_click"] = ck
            st.session_state["last_raw_x"] = str(round(xd, 1))
            st.session_state["last_raw_y"] = str(round(yd, 1))

            dist  = math.sqrt(xd**2 + yd**2)
            angle = math.degrees(math.atan2(yd, xd))
            if angle < 0:
                angle += 360

            seg = determine_segment(angle)
            mod = determine_modifier(dist)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if st.session_state["recording_target"]:
                st.session_state["current_target_data"] = [
                    now, seg, mod, xd, yd,
                    None, None, None, None,
                    st.session_state["inputuser"],
                    st.session_state["inputmode"], 0
                ]
                st.session_state["click_positions"].append(
                    {"type": "Target", "xOff": xd, "yOff": yd}
                )
                st.session_state["display_text"]     = f"Target: **{seg}{mod}**"
                st.session_state["recording_target"] = False

            else:
                td = st.session_state["current_target_data"]
                td[5:12] = [seg, mod, xd, yd,
                            st.session_state["inputuser"],
                            st.session_state["inputmode"], session_num]

                x_miss = (td[3] - xd) * -1
                y_miss = (td[4] - yd) * -1
                st.session_state["x_miss_list"].append(x_miss)
                st.session_state["y_miss_list"].append(y_miss)
                total_miss = round(math.sqrt(x_miss**2 + y_miss**2), 0)

                hit = (td[1] == seg and mod != "M")
                if hit:
                    st.session_state["hit_cnt"] += 1.0
                st.session_state["shot_cnt"] += 1.0
                hit_perc = round(st.session_state["hit_cnt"] / st.session_state["shot_cnt"] * 100)

                st.session_state["display_text"] = (
                    f"Result: **{seg}{mod}** — {'HIT ✅' if hit else 'MISS ❌'} — {total_miss}mm"
                )
                st.session_state["display_perc"] = (
                    f"Hit rate: **{hit_perc}%** "
                    f"({int(st.session_state['hit_cnt'])}/{int(st.session_state['shot_cnt'])})"
                )
                st.session_state["click_positions"].append(
                    {"type": "Result", "xOff": xd, "yOff": yd}
                )
                append_row_to_github(td)
                st.session_state["recording_target"] = True

            st.rerun()
