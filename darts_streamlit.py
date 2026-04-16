import streamlit as st
import math
import csv
import datetime
import base64
import io
import requests
import pandas as pd
import plotly.graph_objects as go

APP_VERSION = "v1.0"

st.set_page_config(
    page_title="Dartboard Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── GitHub config ─────────────────────────────────────────────────────────
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

# Board geometry in mm (real dartboard scale, radius=170)
inner_bull_r = 6.35
outer_bull_r = 16.0
triple_inner = 99.0
triple_outer = 107.0
double_inner = 162.0
double_outer = 170.0

# ─── GitHub helpers ─────────────────────────────────────────────────────────
def load_csv_from_github():
    try:
        resp = requests.get(RAW_CSV_URL, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            return pd.read_csv(io.StringIO(resp.text))
        elif resp.status_code != 200:
            st.warning(f"GitHub read: HTTP {resp.status_code}")
    except Exception as e:
        st.warning(f"GitHub read error: {e}")
    return pd.DataFrame(columns=CSV_COLUMNS)

def append_row_to_github(row):
    """Write a row to the CSV on GitHub. Returns (success, detail_message)."""
    try:
        r = requests.get(API_FILE_URL, headers=GH_HEADERS, timeout=10)
        if r.status_code == 200:
            info     = r.json()
            sha      = info["sha"]
            old_text = base64.b64decode(info["content"].replace("\n","")).decode("utf-8")
        elif r.status_code == 404:
            sha      = None
            old_text = ""
        else:
            return False, f"GET file failed: HTTP {r.status_code} — {r.text[:200]}"

        buf = io.StringIO()
        if old_text.strip():
            buf.write(old_text)
            if not old_text.endswith("\n"):
                buf.write("\n")
        else:
            csv.writer(buf).writerow(CSV_COLUMNS)
        csv.writer(buf).writerow(row)
        encoded = base64.b64encode(buf.getvalue().encode()).decode()

        payload = {
            "message": f"dart throw - {row[0]}",
            "content": encoded,
            "branch":  "main",
        }
        if sha:
            payload["sha"] = sha

        r2 = requests.put(API_FILE_URL, headers=GH_HEADERS, json=payload, timeout=15)
        if r2.status_code in (200, 201):
            return True, "Saved ✅"
        else:
            return False, f"PUT failed: HTTP {r2.status_code} — {r2.text[:300]}"

    except Exception as e:
        return False, f"Exception: {type(e).__name__}: {e}"

# ─── Dart logic ─────────────────────────────────────────────────────────────
def determine_segment(angle_deg):
    angle = (90 - angle_deg) % 360
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

# ─── Build Plotly dartboard ──────────────────────────────────────────────────
def make_arc(r, a_start, a_end, steps=30):
    angs = [math.radians(a_start + (a_end - a_start) * i / steps) for i in range(steps+1)]
    return [r*math.cos(a) for a in angs], [r*math.sin(a) for a in angs]

def make_sector(r_in, r_out, a_start, a_end, steps=30):
    ox, oy = make_arc(r_out, a_start, a_end, steps)
    ix, iy = make_arc(r_in,  a_end, a_start, steps)
    return ox + ix + [ox[0]], oy + iy + [oy[0]]

def build_dartboard(click_positions, board_active):
    fig  = go.Figure()
    segs = [20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5]
    n    = 20
    inc  = 360.0 / n
    off  = 90.0 + inc / 2.0

    surround_color = "#1e3a1e" if board_active else "#1a1a1a"
    sx, sy = make_arc(double_outer + 22, 0, 360, 90)
    fig.add_trace(go.Scatter(
        x=sx, y=sy, fill="toself", fillcolor=surround_color,
        line=dict(color=surround_color, width=0),
        mode="lines", hoverinfo="skip", showlegend=False
    ))

    if board_active:
        bx, by = make_arc(double_outer + 21, 0, 360, 90)
        fig.add_trace(go.Scatter(
            x=bx, y=by, fill="toself", fillcolor="rgba(0,0,0,0)",
            line=dict(color="#00cc44", width=3),
            mode="lines", hoverinfo="skip", showlegend=False
        ))

    rings = [
        (double_inner, double_outer, "#1e7a36", "#c0182a"),
        (triple_outer, double_inner, "#2a2a2a", "#e8e0cc"),
        (triple_inner, triple_outer, "#1e7a36", "#c0182a"),
        (outer_bull_r, triple_inner, "#2a2a2a", "#e8e0cc"),
    ]
    for r_in, r_out, c_even, c_odd in rings:
        for i in range(n):
            a_end   = off - i * inc
            a_start = off - (i+1) * inc
            xs, ys  = make_sector(r_in, r_out, a_start, a_end)
            color   = c_even if i % 2 == 0 else c_odd
            fig.add_trace(go.Scatter(
                x=xs, y=ys, fill="toself", fillcolor=color,
                line=dict(color="#000", width=0.5),
                mode="lines",
                hovertemplate=f"<b>{segs[i]}</b><extra></extra>",
                showlegend=False,
            ))

    bx2, by2 = make_arc(outer_bull_r, 0, 360, 60)
    fig.add_trace(go.Scatter(
        x=bx2, y=by2, fill="toself", fillcolor="#1e7a36",
        line=dict(color="#000", width=1), mode="lines",
        hovertemplate="<b>Bull 25</b><extra></extra>", showlegend=False
    ))
    ibx, iby = make_arc(inner_bull_r, 0, 360, 60)
    fig.add_trace(go.Scatter(
        x=ibx, y=iby, fill="toself", fillcolor="#c0182a",
        line=dict(color="#000", width=1), mode="lines",
        hovertemplate="<b>Bull 50</b><extra></extra>", showlegend=False
    ))

    lr = double_outer + 13
    for i, seg in enumerate(segs):
        a_mid = math.radians(off - (i + 0.5) * inc)
        fig.add_annotation(
            x=lr*math.cos(a_mid), y=lr*math.sin(a_mid),
            text=str(seg), showarrow=False,
            font=dict(size=13, color="white", family="Arial Black"),
            xanchor="center", yanchor="middle"
        )

    step    = 3
    board_r = double_outer + 18
    cxs, cys, ctexts = [], [], []
    for xi in range(-int(board_r), int(board_r)+1, step):
        for yi in range(-int(board_r), int(board_r)+1, step):
            if math.sqrt(xi*xi + yi*yi) <= board_r:
                cxs.append(xi)
                cys.append(yi)
                dist  = math.sqrt(xi*xi + yi*yi)
                angle = (math.degrees(math.atan2(yi, xi)) + 360) % 360
                seg   = determine_segment(angle)
                mod   = determine_modifier(dist)
                ctexts.append(f"{mod}{seg}")

    fig.add_trace(go.Scatter(
        x=cxs, y=cys, mode="markers",
        marker=dict(size=step*2, color="rgba(0,0,0,0)", opacity=0, line=dict(width=0)),
        text=ctexts,
        hovertemplate="%{text}<extra></extra>",
        showlegend=False, name="clickzone",
    ))

    for cp in click_positions:
        xd  = cp["xOff"]
        yd  = cp["yOff"]
        col = "#ffe033" if cp["type"] == "Target" else "#ff8c00"
        s   = 9
        fig.add_trace(go.Scatter(
            x=[xd-s, xd+s, None, xd+s, xd-s],
            y=[yd-s, yd+s, None, yd-s, yd+s],
            mode="lines", line=dict(color=col, width=3),
            hoverinfo="skip", showlegend=False
        ))
        fig.add_trace(go.Scatter(
            x=[xd], y=[yd], mode="markers",
            marker=dict(color=col, size=8, line=dict(color="#000", width=1)),
            hoverinfo="skip", showlegend=False
        ))

    fig.update_layout(
        xaxis=dict(visible=False, range=[-205, 205],
                   scaleanchor="y", scaleratio=1, fixedrange=True),
        yaxis=dict(visible=False, range=[-205, 205], fixedrange=True),
        plot_bgcolor="#0e0e0e",
        paper_bgcolor="#0e0e0e",
        margin=dict(l=5, r=5, t=5, b=5),
        width=620, height=620,
        showlegend=False,
        dragmode=False,
        clickmode="event",
    )
    return fig

# ─── Session state ────────────────────────────────────────────────────────────
defaults = {
    "recording_target": True,
    "current_target_data": None,
    "hit_cnt": 0.0, "shot_cnt": 0.0,
    "x_miss_list": [], "y_miss_list": [],
    "display_text": "", "display_perc": "",
    "click_positions": [],
    "session_num": None, "last_click": None,
    "df_loaded": False,
    "last_raw_x": "", "last_raw_y": "",
    "github_status": "",
    "board_active": False,
    "prev_selection": None,
}
for k, v in defaults.items():
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

# ─── Layout ───────────────────────────────────────────────────────────────────
board_col, panel_col = st.columns([3, 1])

with board_col:
    board_active = st.session_state["board_active"]

    if not board_active:
        st.markdown(
            "<div style='margin-bottom:6px;padding:8px 12px;background:#222;"
            "border:2px dashed #555;border-radius:8px;color:#aaa;font-size:14px;'>"
            "⚠️ <b>Board inactive</b> — click the button below, then click the board</div>",
            unsafe_allow_html=True
        )
        if st.button("🎯 Activate Board", type="primary", use_container_width=True):
            st.session_state["board_active"] = True
            st.rerun()
    else:
        st.markdown(
            "<div style='margin-bottom:6px;padding:6px 12px;background:#1a2e1a;"
            "border:2px solid #1e7a36;border-radius:8px;color:#4caf50;font-size:14px;'>"
            "✅ <b>Board active</b> — click anywhere on the board</div>",
            unsafe_allow_html=True
        )

    fig         = build_dartboard(st.session_state["click_positions"], board_active)
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
        st.caption(f"Last registered click — X: {raw_x}  Y: {raw_y}")

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
        st.markdown(f"**X Miss Avg:** {round(sum(xl)/len(xl),2)} mm")
        st.markdown(f"**Y Miss Avg:** {round(sum(yl)/len(yl),2)} mm")
        st.markdown(f"**Throws:** {int(st.session_state['shot_cnt'])}")
    else:
        st.caption("No throws yet")
    if st.session_state["github_status"]:
        st.caption(st.session_state["github_status"])
    st.divider()
    st.markdown("🟡 Yellow X = Target")
    st.markdown("🟠 Orange X = Result")
    st.divider()
    if st.button("🔄 Reset Markers", use_container_width=True):
        st.session_state["click_positions"]  = []
        st.session_state["recording_target"] = True
        st.session_state["display_text"]     = ""
        st.session_state["display_perc"]     = ""
        st.session_state["last_click"]       = None
        st.session_state["last_raw_x"]       = ""
        st.session_state["last_raw_y"]       = ""
        st.session_state["github_status"]    = ""
        st.session_state["prev_selection"]   = None
        st.rerun()
    if st.button("🆕 New Session", use_container_width=True):
        for k in list(defaults.keys()):
            st.session_state.pop(k, None)
        st.rerun()

    with st.expander("🔧 GitHub debug"):
        st.write(f"User: `{GITHUB_USER}`")
        st.write(f"Repo: `{GITHUB_REPO}`")
        st.write(f"File URL: `{API_FILE_URL}`")
        token_preview = GITHUB_TOKEN[:4] + "..." + GITHUB_TOKEN[-4:] if len(GITHUB_TOKEN) > 8 else "***"
        st.write(f"Token: `{token_preview}`")
        if st.button("Test GitHub connection"):
            r = requests.get(API_FILE_URL, headers=GH_HEADERS, timeout=10)
            st.write(f"GET status: {r.status_code}")
            if r.status_code == 200:
                st.success("File found on GitHub ✅")
            elif r.status_code == 404:
                st.warning("File not found (will be created on first save)")
            elif r.status_code == 401:
                st.error("401 Unauthorized — check your GitHub token")
            elif r.status_code == 403:
                st.error("403 Forbidden — token may lack repo write permissions")
            else:
                st.error(f"Unexpected: {r.text[:400]}")

# ─── Process click ─────────────────────────────────────────────────────────────
if (click_event
        and hasattr(click_event, "selection")
        and click_event.selection
        and click_event.selection.get("points")
        and st.session_state["board_active"]):

    pts = click_event.selection["points"]
    if pts:
        sel_key = str(pts[0])
        if st.session_state["prev_selection"] != sel_key:
            st.session_state["prev_selection"] = sel_key

            pt = pts[0]
            xd = float(pt["x"])
            yd = float(pt["y"])

            st.session_state["last_raw_x"] = str(round(xd, 1))
            st.session_state["last_raw_y"] = str(round(yd, 1))

            dist  = math.sqrt(xd**2 + yd**2)
            angle = (math.degrees(math.atan2(yd, xd)) + 360) % 360

            seg  = determine_segment(angle)
            mod  = determine_modifier(dist)
            now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            name = st.session_state["inputuser"]
            mode = st.session_state["inputmode"]

            if st.session_state["recording_target"]:
                st.session_state["current_target_data"] = [
                    now, seg, mod, xd, yd,
                    None, None, None, None, name, mode, 0
                ]
                st.session_state["click_positions"].append(
                    {"type": "Target", "xOff": xd, "yOff": yd}
                )
                st.session_state["display_text"]     = f"Target: **{seg}{mod}**"
                st.session_state["recording_target"] = False

            else:
                td = st.session_state["current_target_data"]
                td[5:12] = [seg, mod, xd, yd, name, mode, session_num]

                x_miss     = (td[3] - xd) * -1
                y_miss     = (td[4] - yd) * -1
                st.session_state["x_miss_list"].append(x_miss)
                st.session_state["y_miss_list"].append(y_miss)
                total_miss = round(math.sqrt(x_miss**2 + y_miss**2), 1)

                hit = (td[1] == seg and mod != "M")
                if hit:
                    st.session_state["hit_cnt"] += 1.0
                st.session_state["shot_cnt"] += 1.0
                hit_perc = round(
                    st.session_state["hit_cnt"] / st.session_state["shot_cnt"] * 100
                )

                st.session_state["display_text"] = (
                    f"Result: **{seg}{mod}** — "
                    f"{'HIT ✅' if hit else 'MISS ❌'} — {total_miss}mm off"
                )
                st.session_state["display_perc"] = (
                    f"Hit rate: **{hit_perc}%** "
                    f"({int(st.session_state['hit_cnt'])}"
                    f"/{int(st.session_state['shot_cnt'])})"
                )
                st.session_state["click_positions"].append(
                    {"type": "Result", "xOff": xd, "yOff": yd}
                )
                ok, detail = append_row_to_github(td)
                st.session_state["github_status"] = (
                    f"✅ {detail}" if ok else f"⚠️ {detail}"
                )
                st.session_state["recording_target"] = True

            st.rerun()
