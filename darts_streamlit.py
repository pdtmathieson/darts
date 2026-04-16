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

OUTER_R      = 300
inner_bull_r = OUTER_R * (6.35  / 170)
outer_bull_r = OUTER_R * (16    / 170)
triple_inner = OUTER_R * (99    / 170)
triple_outer = OUTER_R * (107   / 170)
double_inner = OUTER_R * (162   / 170)
double_outer = float(OUTER_R)

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


def determine_modifier(dist) -> str:
    if dist <= inner_bull_r:
        return "+"
    elif dist <= outer_bull_r:
        return "*"
    elif double_inner <= dist <= double_outer:
        return "D"
    elif triple_inner <= dist <= triple_outer:
        return "T"
    elif dist > double_outer:
        return "M"
    else:
        return "S"


# ─── Session state init ───────────────────────────────────────────────────────
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
    "pending_xoff": None,
    "pending_yoff": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

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

# ─── Top controls ─────────────────────────────────────────────────────────────
col_name, col_mode, col_prompt = st.columns([2, 2, 5])
with col_name:
    inputuser = st.text_input("Name", value="Patrick", key="inputuser")
with col_mode:
    inputmode = st.selectbox("Mode", ["RTW", "Points"], key="inputmode")
with col_prompt:
    st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
    if st.session_state["recording_target"]:
        st.info("🎯 Click the board to set **TARGET**")
    else:
        st.warning("🎯 Click the board to set **RESULT**")
    st.markdown("</div>", unsafe_allow_html=True)

# ─── Hidden number inputs — JS writes here, Streamlit reads on rerun ─────────
# We use st.number_input with a unique key that JS targets via the DOM label.
# A cleaner approach: use a plain st.text_input hidden behind CSS, updated by JS.

click_xoff = st.session_state.get("pending_xoff")
click_yoff = st.session_state.get("pending_yoff")

# Render two hidden text inputs that JS will populate and trigger change on
xoff_val = st.text_input("_xoff", value="", key="xoff_input",
                          label_visibility="collapsed")
yoff_val = st.text_input("_yoff", value="", key="yoff_input",
                          label_visibility="collapsed")

# ─── Process a pending click ─────────────────────────────────────────────────
if xoff_val and yoff_val:
    try:
        xd = float(xoff_val)
        yd = float(yoff_val)
        ck = (round(xd, 1), round(yd, 1))

        if st.session_state["last_click"] != ck:
            st.session_state["last_click"] = ck

            dist     = math.sqrt(xd**2 + yd**2)
            pygame_y = -yd  # flip Y: canvas Y-down → up-positive for angle calc
            angle    = math.degrees(math.atan2(pygame_y, xd))
            if angle < 0:
                angle += 360

            seg = determine_segment(angle)
            mod = determine_modifier(dist)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if st.session_state["recording_target"]:
                st.session_state["current_target_data"] = [
                    now, seg, mod, xd, pygame_y,
                    None, None, None, None,
                    st.session_state["inputuser"],
                    st.session_state["inputmode"],
                    0
                ]
                st.session_state["click_positions"].append(
                    {"type": "Target", "xOff": xd, "yOff": yd}
                )
                st.session_state["display_text"] = f"Target set: **{seg}{mod}**"
                st.session_state["recording_target"] = False

            else:
                td     = st.session_state["current_target_data"]
                td[5]  = seg
                td[6]  = mod
                td[7]  = xd
                td[8]  = pygame_y
                td[9]  = st.session_state["inputuser"]
                td[10] = st.session_state["inputmode"]
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

            # Clear the inputs for next click
            st.session_state["xoff_input"] = ""
            st.session_state["yoff_input"] = ""
            st.rerun()
    except (ValueError, TypeError):
        pass

# ─── Board geometry & canvas ──────────────────────────────────────────────────
CANVAS_W  = 720
CANVAS_H  = 720
click_json = json.dumps(st.session_state["click_positions"])

dartboard_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0e0e0e; display:flex; flex-direction:column;
          justify-content:center; align-items:center; height:{CANVAS_H+10}px; }}
  canvas {{ cursor:crosshair; }}
</style>
</head>
<body>
<canvas id="c" width="{CANVAS_W}" height="{CANVAS_H}"></canvas>
<script>
  const cv  = document.getElementById("c");
  const ctx = cv.getContext("2d");
  const CX  = {CANVAS_W}/2, CY = {CANVAS_H}/2;
  const R   = {OUTER_R};

  const IB = R*(6.35/170), OB = R*(16/170);
  const TI = R*(99/170),   TO = R*(107/170);
  const DI = R*(162/170),  DO = R;

  const SEGS    = [20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5];
  const ANG_OFF = -Math.PI/2 - Math.PI/20;
  const ANG_INC = 2*Math.PI/20;
  const LABEL_R = DO + 26;

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
    ctx.fillStyle = "#1a1a1a"; ctx.fill();

    for (let i = 0; i < 20; i++) {{
      const a0   = i*ANG_INC + ANG_OFF;
      const a1   = (i+1)*ANG_INC + ANG_OFF;
      const even = (i%2 === 0);
      const bw   = even ? "#2a2a2a" : "#e8e0cc";
      const col  = even ? "#1e7a36" : "#c0182a";
      arc(OB, TI, a0, a1, bw);
      arc(TO, DI, a0, a1, bw);
      arc(TI, TO, a0, a1, col);
      arc(DI, DO, a0, a1, col);
    }}

    ctx.strokeStyle = "rgba(0,0,0,0.7)"; ctx.lineWidth = 1.5;
    for (let i = 0; i < 20; i++) {{
      const a = i*ANG_INC + ANG_OFF;
      ctx.beginPath();
      ctx.moveTo(CX, CY);
      ctx.lineTo(CX + DO*Math.cos(a), CY + DO*Math.sin(a));
      ctx.stroke();
    }}

    [OB, TI, TO, DI, DO].forEach(r => {{
      ctx.beginPath(); ctx.arc(CX, CY, r, 0, 2*Math.PI);
      ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 2; ctx.stroke();
    }});

    ctx.beginPath(); ctx.arc(CX, CY, OB, 0, 2*Math.PI);
    ctx.fillStyle = "#1e7a36"; ctx.fill();
    ctx.strokeStyle = "rgba(0,0,0,0.5)"; ctx.lineWidth = 1.5; ctx.stroke();

    ctx.beginPath(); ctx.arc(CX, CY, IB, 0, 2*Math.PI);
    ctx.fillStyle = "#c0182a"; ctx.fill();

    ctx.font = "bold 17px Arial, sans-serif";
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    for (let i = 0; i < 20; i++) {{
      const a = (i + 0.5)*ANG_INC + ANG_OFF;
      ctx.fillStyle = "white";
      ctx.fillText(SEGS[i], CX + LABEL_R*Math.cos(a), CY + LABEL_R*Math.sin(a));
    }}

    const clicks = {click_json};
    clicks.forEach(c => {{
      const px  = CX + c.xOff;
      const py  = CY + c.yOff;
      const col = c.type === "Target" ? "#ffe033" : "#ff8c00";
      const s   = 11;
      ctx.lineWidth = 3; ctx.strokeStyle = col;
      ctx.beginPath(); ctx.moveTo(px-s,py-s); ctx.lineTo(px+s,py+s); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(px+s,py-s); ctx.lineTo(px-s,py+s); ctx.stroke();
      ctx.beginPath(); ctx.arc(px, py, 4, 0, 2*Math.PI);
      ctx.fillStyle = col; ctx.fill();
    }});
  }}

  draw();

  // ── Click handler: find Streamlit text inputs in parent and set values ──
  cv.addEventListener("click", function(e) {{
    const rect = cv.getBoundingClientRect();
    const sx   = cv.width  / rect.width;
    const sy   = cv.height / rect.height;
    const xOff = Math.round(((e.clientX - rect.left) * sx - CX) * 100) / 100;
    const yOff = Math.round(((e.clientY - rect.top)  * sy - CY) * 100) / 100;

    // Walk up to the parent Streamlit document and find the hidden inputs
    try {{
      const doc    = window.parent.document;
      const inputs = doc.querySelectorAll('input[type="text"]');
      let xInput   = null;
      let yInput   = null;

      // The inputs have aria-labels matching our label text
      inputs.forEach(inp => {{
        const label = inp.getAttribute('aria-label') || '';
        if (label === '_xoff') xInput = inp;
        if (label === '_yoff') yInput = inp;
      }});

      if (xInput && yInput) {{
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.parent.HTMLInputElement.prototype, 'value'
        ).set;
        nativeInputValueSetter.call(xInput, String(xOff));
        nativeInputValueSetter.call(yInput, String(yOff));
        xInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        yInput.dispatchEvent(new Event('input', {{ bubbles: true }}));

        // Submit the form by pressing Enter on the last input
        yInput.dispatchEvent(new KeyboardEvent('keydown', {{
          key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
        }}));
      }}
    }} catch(err) {{
      console.warn("Could not reach parent inputs:", err);
    }}
  }});
</script>
</body>
</html>"""

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
        st.session_state["display_text"]     = ""
        st.session_state["display_perc"]     = ""
        st.session_state["last_click"]       = None
        st.rerun()
    if st.button("🆕 New Session", use_container_width=True):
        for k in ["recording_target","current_target_data","hit_cnt","shot_cnt",
                  "x_miss_list","y_miss_list","display_text","display_perc",
                  "click_positions","last_click","df_loaded","session_num",
                  "xoff_input","yoff_input"]:
            st.session_state.pop(k, None)
        st.rerun()
