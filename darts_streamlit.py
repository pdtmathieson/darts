import streamlit as st
import streamlit.components.v1 as components
import math
import csv
import datetime
import base64
import io
import json
import requests
import pandas as pd

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dartboard Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── GitHub config ────────────────────────────────────────────────────────────
GITHUB_TOKEN  = st.secrets["github"]["token"]
GITHUB_USER   = st.secrets["github"]["username"]
GITHUB_REPO   = st.secrets["github"]["repo"]
CSV_PATH      = "dart_data.csv"
RAW_CSV_URL   = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/{CSV_PATH}"
API_FILE_URL  = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{CSV_PATH}"
GH_HEADERS    = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
CSV_COLUMNS = [
    "Timestamp", "Target Segment", "Target Modifier",
    "Target X Offset", "Target Y Offset",
    "Result Segment", "Result Modifier",
    "Result X Offset", "Result Y Offset",
    "Name", "Mode", "Session"
]

# ─── GitHub CSV helpers ───────────────────────────────────────────────────────
def load_csv_from_github() -> pd.DataFrame:
    try:
        resp = requests.get(RAW_CSV_URL, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            return pd.read_csv(io.StringIO(resp.text))
    except Exception:
        pass
    return pd.DataFrame(columns=CSV_COLUMNS)


def append_row_to_github(row: list):
    r = requests.get(API_FILE_URL, headers=GH_HEADERS, timeout=10)
    if r.status_code == 200:
        file_info = r.json()
        sha       = file_info["sha"]
        old_text  = base64.b64decode(
            file_info["content"].replace("\n", "")
        ).decode("utf-8")
    else:
        sha      = None
        old_text = ""

    buf = io.StringIO()
    if old_text.strip():
        buf.write(old_text)
        if not old_text.endswith("\n"):
            buf.write("\n")
    else:
        writer = csv.writer(buf)
        writer.writerow(CSV_COLUMNS)

    writer = csv.writer(buf)
    writer.writerow(row)
    new_content = buf.getvalue()

    encoded = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
    payload = {"message": f"dart throw - {row[0]}", "content": encoded}
    if sha:
        payload["sha"] = sha
    requests.put(API_FILE_URL, headers=GH_HEADERS, json=payload, timeout=15)


# ─── Dart logic ───────────────────────────────────────────────────────────────
def determine_segment(angle_deg: float) -> int:
    angle = (angle_deg - 90) % 360
    segment_order = [20,5,12,9,14,11,8,16,7,19,3,17,2,15,10,6,13,4,18,1,20]
    idx = int((angle + 9) // 18)
    idx = min(max(idx, 0), len(segment_order) - 1)
    return segment_order[idx]


def determine_modifier(dist, dbl_in, dbl_out, tri_in, tri_out, ibull, obull) -> str:
    if dist <= ibull:
        return "+"
    elif dist <= obull:
        return "*"
    elif dbl_in <= dist <= dbl_out:
        return "D"
    elif tri_in <= dist <= tri_out:
        return "T"
    elif dist > dbl_out:
        return "M"
    else:
        return "S"


# ─── Session state init ───────────────────────────────────────────────────────
def init_state():
    defaults = {
        "recording_target": True,
        "current_target_data": None,
        "hit_cnt": 0.0,
        "shot_cnt": 0.0,
        "x_miss_list": [],
        "y_miss_list": [],
        "display_text": "",
        "display_perc": "",
        "click_positions": [],
        "session_num": None,
        "last_click": None,
        "df_loaded": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

if not st.session_state["df_loaded"]:
    df_existing = load_csv_from_github()
    if not df_existing.empty and "Session" in df_existing.columns:
        try:
            st.session_state["session_num"] = int(df_existing["Session"].max()) + 1
        except Exception:
            st.session_state["session_num"] = 1
    else:
        st.session_state["session_num"] = 1
    st.session_state["df_loaded"] = True

session_num = st.session_state["session_num"]

# ─── Read click from query params (set by JS) ─────────────────────────────────
# JS writes ?click=xOff,yOff to the URL; Python reads it here before rendering UI
qp = st.query_params
if "click" in qp:
    try:
        raw = qp["click"]
        parts = raw.split(",")
        xd = float(parts[0])
        yd = float(parts[1])
        ck = (round(xd, 1), round(yd, 1))

        if st.session_state["last_click"] != ck:
            st.session_state["last_click"] = ck

            dist = math.sqrt(xd**2 + yd**2)
            # yd from canvas is Y-down; flip for angle calculation (up = positive)
            pygame_y = -yd
            angle = math.degrees(math.atan2(pygame_y, xd))
            if angle < 0:
                angle += 360

            seg = determine_segment(angle)
            OUTER_R = 300
            mod = determine_modifier(dist,
                OUTER_R*(162/170), float(OUTER_R),
                OUTER_R*(99/170),  OUTER_R*(107/170),
                OUTER_R*(6.35/170), OUTER_R*(16/170))
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if st.session_state["recording_target"]:
                st.session_state["current_target_data"] = [
                    now, seg, mod, xd, pygame_y,
                    None, None, None, None,
                    qp.get("name", "Patrick3"),
                    qp.get("mode", "RTW"),
                    0
                ]
                st.session_state["click_positions"].append(
                    {"type": "Target", "xOff": xd, "yOff": yd}
                )
                st.session_state["display_text"] = f"Target set: **{seg}{mod}**"
                st.session_state["recording_target"] = False

            else:
                td = st.session_state["current_target_data"]
                td[5]  = seg
                td[6]  = mod
                td[7]  = xd
                td[8]  = pygame_y
                td[9]  = qp.get("name", "Patrick3")
                td[10] = qp.get("mode", "RTW")
                td[11] = session_num

                x_miss = (td[3] - xd) * -1
                y_miss = (td[4] - pygame_y) * -1
                st.session_state["x_miss_list"].append(x_miss)
                st.session_state["y_miss_list"].append(y_miss)
                total_miss = round(math.sqrt(x_miss**2 + y_miss**2), 0)

                hit = (td[1] == seg and mod != "M")
                if hit:
                    st.session_state["hit_cnt"] += 1.0
                st.session_state["shot_cnt"] += 1.0

                hit_perc   = round(st.session_state["hit_cnt"] / st.session_state["shot_cnt"] * 100)
                miss_label = "HIT ✅" if hit else "MISS ❌"
                st.session_state["display_text"] = (
                    f"Result: **{seg}{mod}** — {miss_label} — Miss distance: {total_miss}px"
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

        # Clear param so it doesn't re-fire on next natural rerun
        st.query_params.clear()
    except Exception:
        st.query_params.clear()

# ─── Top controls ─────────────────────────────────────────────────────────────
col_name, col_mode, col_prompt = st.columns([2, 2, 5])
with col_name:
    inputuser = st.text_input("Name", value="Patrick3", key="inputuser")
with col_mode:
    inputmode = st.selectbox("Mode", ["RTW", "Points"], key="inputmode")
with col_prompt:
    st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
    if st.session_state["recording_target"]:
        st.info("🎯 Click the board to set **TARGET**")
    else:
        st.warning("🎯 Click the board to set **RESULT**")
    st.markdown("</div>", unsafe_allow_html=True)

# ─── Board geometry ───────────────────────────────────────────────────────────
OUTER_RADIUS = 300
CANVAS_W     = 720
CANVAS_H     = 720

inner_bull_r = OUTER_RADIUS * (6.35  / 170)
outer_bull_r = OUTER_RADIUS * (16    / 170)
triple_inner = OUTER_RADIUS * (99    / 170)
triple_outer = OUTER_RADIUS * (107   / 170)
double_inner = OUTER_RADIUS * (162   / 170)
double_outer = float(OUTER_RADIUS)

click_json    = json.dumps(st.session_state["click_positions"])
inputuser_js  = json.dumps(st.session_state.get("inputuser", "Patrick3"))
inputmode_js  = json.dumps(st.session_state.get("inputmode", "RTW"))

# ─── Dartboard HTML ───────────────────────────────────────────────────────────
# Orientation: 20 at top, 3 at bottom, 6 on RIGHT, 11 on LEFT
# Standard dartboard goes clockwise: 20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5
# In canvas (Y-down), clockwise = positive angle direction
# ANG_OFF = -PI/2 - PI/20  puts the LEFT edge of segment 20 at top,
# so the CENTRE of segment 20 is at -PI/2 (straight up). Clockwise from there:
# 1,18,4,13,6(right),10,15,2,17,3(bottom),19,7,16,8,11(left),14,9,12,5 — correct!
dartboard_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0e0e0e; display:flex; justify-content:center;
          align-items:center; height:{CANVAS_H+10}px; }}
  canvas {{ cursor:crosshair; }}
</style>
</head>
<body>
<canvas id="c" width="{CANVAS_W}" height="{CANVAS_H}"></canvas>
<script>
  const cv  = document.getElementById("c");
  const ctx = cv.getContext("2d");
  const CX  = {CANVAS_W}/2, CY = {CANVAS_H}/2;
  const R   = {OUTER_RADIUS};

  const IB = R*(6.35/170), OB = R*(16/170);
  const TI = R*(99/170),   TO = R*(107/170);
  const DI = R*(162/170),  DO = R;

  // Standard dartboard clockwise order starting from segment at top
  const SEGS    = [20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5];
  // -PI/2 aligns 12 o'clock; -PI/20 shifts so 20 is centred at top
  const ANG_OFF  = -Math.PI/2 - Math.PI/20;
  const ANG_INC  = 2*Math.PI/20;
  const LABEL_R  = DO + 26;

  function arc(r0, r1, a0, a1, fill) {{
    ctx.beginPath();
    if (r0 > 0) {{
      ctx.arc(CX, CY, r0, a0, a1);
      ctx.arc(CX, CY, r1, a1, a0, true);
    }} else {{
      ctx.moveTo(CX, CY);
      ctx.arc(CX, CY, r1, a0, a1);
    }}
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();
  }}

  function draw() {{
    ctx.clearRect(0, 0, {CANVAS_W}, {CANVAS_H});
    ctx.fillStyle = "#0e0e0e";
    ctx.fillRect(0, 0, {CANVAS_W}, {CANVAS_H});

    ctx.beginPath(); ctx.arc(CX, CY, DO+22, 0, 2*Math.PI);
    ctx.fillStyle="#1a1a1a"; ctx.fill();

    for (let i=0; i<20; i++) {{
      const a0   = i*ANG_INC + ANG_OFF;
      const a1   = (i+1)*ANG_INC + ANG_OFF;
      const even = (i%2===0);
      const bw   = even ? "#2a2a2a" : "#e8e0cc";
      const col  = even ? "#1e7a36" : "#c0182a";
      arc(OB, TI, a0, a1, bw);
      arc(TO, DI, a0, a1, bw);
      arc(TI, TO, a0, a1, col);
      arc(DI, DO, a0, a1, col);
    }}

    ctx.strokeStyle="rgba(0,0,0,0.7)"; ctx.lineWidth=1.5;
    for (let i=0; i<20; i++) {{
      const a = i*ANG_INC + ANG_OFF;
      ctx.beginPath();
      ctx.moveTo(CX, CY);
      ctx.lineTo(CX + DO*Math.cos(a), CY + DO*Math.sin(a));
      ctx.stroke();
    }}

    [OB, TI, TO, DI, DO].forEach(r => {{
      ctx.beginPath(); ctx.arc(CX, CY, r, 0, 2*Math.PI);
      ctx.strokeStyle="rgba(0,0,0,0.55)"; ctx.lineWidth=2; ctx.stroke();
    }});

    ctx.beginPath(); ctx.arc(CX, CY, OB, 0, 2*Math.PI);
    ctx.fillStyle="#1e7a36"; ctx.fill();
    ctx.strokeStyle="rgba(0,0,0,0.5)"; ctx.lineWidth=1.5; ctx.stroke();

    ctx.beginPath(); ctx.arc(CX, CY, IB, 0, 2*Math.PI);
    ctx.fillStyle="#c0182a"; ctx.fill();

    ctx.font="bold 17px Arial, sans-serif";
    ctx.textAlign="center"; ctx.textBaseline="middle";
    for (let i=0; i<20; i++) {{
      const a = (i + 0.5)*ANG_INC + ANG_OFF;
      ctx.fillStyle="white";
      ctx.fillText(SEGS[i], CX + LABEL_R*Math.cos(a), CY + LABEL_R*Math.sin(a));
    }}

    // Click markers
    const clicks = {click_json};
    clicks.forEach(c => {{
      const px = CX + c.xOff;
      const py = CY + c.yOff;
      const col = c.type === "Target" ? "#ffe033" : "#ff8c00";
      const s = 11;
      ctx.lineWidth=3; ctx.strokeStyle=col;
      ctx.beginPath(); ctx.moveTo(px-s,py-s); ctx.lineTo(px+s,py+s); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px+s,py-s); ctx.lineTo(px-s,py+s); ctx.stroke();
      ctx.beginPath(); ctx.arc(px, py, 4, 0, 2*Math.PI);
      ctx.fillStyle=col; ctx.fill();
    }});
  }}

  draw();

  cv.addEventListener("click", function(e) {{
    const rect = cv.getBoundingClientRect();
    const sx = cv.width  / rect.width;
    const sy = cv.height / rect.height;
    const xOff = Math.round(((e.clientX - rect.left) * sx - CX) * 100) / 100;
    const yOff = Math.round(((e.clientY - rect.top)  * sy - CY) * 100) / 100;
    // Use fetch to set query param and trigger Streamlit rerun
    const name = {inputuser_js};
    const mode = {inputmode_js};
    const url  = window.location.pathname +
                 "?click=" + xOff + "%2C" + yOff +
                 "&name="  + encodeURIComponent(name) +
                 "&mode="  + encodeURIComponent(mode);
    window.parent.location.href = url;
  }});
</script>
</body>
</html>"""

# ─── Render board ─────────────────────────────────────────────────────────────
components.html(dartboard_html, height=CANVAS_H + 20, scrolling=False)

# ─── Stats bar ────────────────────────────────────────────────────────────────
st.divider()
c1, c2, c3 = st.columns([4, 3, 2])

with c1:
    if st.session_state["display_text"]:
        st.markdown(st.session_state["display_text"])
    if st.session_state["display_perc"]:
        st.markdown(st.session_state["display_perc"])

with c2:
    if st.session_state["x_miss_list"]:
        xl = st.session_state["x_miss_list"]
        yl = st.session_state["y_miss_list"]
        st.markdown(f"X Miss Avg: **{round(sum(xl)/len(xl), 2)}px**")
        st.markdown(f"Y Miss Avg: **{round(sum(yl)/len(yl), 2)}px**")
    st.caption(f"Session #{session_num}")

with c3:
    if st.button("🔄 Reset Markers", use_container_width=True):
        st.session_state["click_positions"] = []
        st.session_state["recording_target"] = True
        st.session_state["display_text"] = ""
        st.session_state["display_perc"] = ""
        st.session_state["last_click"] = None
        st.rerun()
    if st.button("🆕 New Session", use_container_width=True):
        for k in ["recording_target","current_target_data","hit_cnt","shot_cnt",
                  "x_miss_list","y_miss_list","display_text","display_perc",
                  "click_positions","last_click","df_loaded","session_num"]:
            st.session_state.pop(k, None)
        st.rerun()
