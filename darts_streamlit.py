import streamlit as st
import math
import csv
import datetime
import base64
import io
import json
import requests
import pandas as pd
import streamlit.components.v1 as components

APP_VERSION = "v0.7"

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

OUTER_R      = 280
inner_bull_r = OUTER_R * (6.35 / 170)
outer_bull_r = OUTER_R * (16   / 170)
triple_inner = OUTER_R * (99   / 170)
triple_outer = OUTER_R * (107  / 170)
double_inner = OUTER_R * (162  / 170)
double_outer = float(OUTER_R)
CANVAS_W     = 680
CANVAS_H     = 680

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
        sha      = None
        old_text = ""
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

# ─── Process click from query params (set by JS form submit) ─────────────────
qp = st.query_params
if "xOff" in qp and "yOff" in qp:
    try:
        xd = float(qp["xOff"])
        yd = float(qp["yOff"])
        ck = (round(xd, 1), round(yd, 1))

        if st.session_state["last_click"] != ck:
            st.session_state["last_click"] = ck
            st.session_state["last_raw_x"] = str(round(xd, 1))
            st.session_state["last_raw_y"] = str(round(yd, 1))

            dist     = math.sqrt(xd**2 + yd**2)
            pygame_y = -yd
            angle    = math.degrees(math.atan2(pygame_y, xd))
            if angle < 0:
                angle += 360

            seg = determine_segment(angle)
            mod = determine_modifier(dist)
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            name = qp.get("name", "Patrick")
            mode = qp.get("mode", "RTW")

            if st.session_state["recording_target"]:
                st.session_state["current_target_data"] = [
                    now, seg, mod, xd, pygame_y,
                    None, None, None, None, name, mode, 0
                ]
                st.session_state["click_positions"].append(
                    {"type": "Target", "xOff": xd, "yOff": yd}
                )
                st.session_state["display_text"]     = f"Target: **{seg}{mod}**"
                st.session_state["recording_target"] = False

            else:
                td = st.session_state["current_target_data"]
                td[5:12] = [seg, mod, xd, pygame_y, name, mode, session_num]

                x_miss = (td[3] - xd) * -1
                y_miss = (td[4] - pygame_y) * -1
                st.session_state["x_miss_list"].append(x_miss)
                st.session_state["y_miss_list"].append(y_miss)
                total_miss = round(math.sqrt(x_miss**2 + y_miss**2), 0)

                hit = (td[1] == seg and mod != "M")
                if hit:
                    st.session_state["hit_cnt"] += 1.0
                st.session_state["shot_cnt"] += 1.0
                hit_perc = round(st.session_state["hit_cnt"] / st.session_state["shot_cnt"] * 100)

                st.session_state["display_text"] = (
                    f"Result: **{seg}{mod}** — {'HIT ✅' if hit else 'MISS ❌'} — {total_miss}px"
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

        st.query_params.clear()
    except Exception:
        st.query_params.clear()

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

# ─── Build board HTML ─────────────────────────────────────────────────────────
click_json    = json.dumps(st.session_state["click_positions"])
inputuser_esc = json.dumps(st.session_state.get("inputuser","Patrick"))
inputmode_esc = json.dumps(st.session_state.get("inputmode","RTW"))

board_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
  width:{CANVAS_W}px; height:{CANVAS_H}px;
  background:#0e0e0e; overflow:hidden;
  display:flex; justify-content:center; align-items:center;
}}
canvas {{ cursor:crosshair; display:block; }}
</style>
</head>
<body>
<canvas id="c" width="{CANVAS_W}" height="{CANVAS_H}"></canvas>
<script>
const cv=document.getElementById("c"),ctx=cv.getContext("2d");
const CX={CANVAS_W}/2, CY={CANVAS_H}/2, R={OUTER_R};
const IB=R*(6.35/170),OB=R*(16/170),TI=R*(99/170),TO=R*(107/170),DI=R*(162/170),DO=R;
const SEGS=[20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5];
const AO=-Math.PI/2-Math.PI/20, AI=2*Math.PI/20, LR=DO+26;

function arc(r0,r1,a0,a1,f){{
  ctx.beginPath();
  if(r0>0){{ctx.arc(CX,CY,r0,a0,a1);ctx.arc(CX,CY,r1,a1,a0,true);}}
  else{{ctx.moveTo(CX,CY);ctx.arc(CX,CY,r1,a0,a1);}}
  ctx.closePath();ctx.fillStyle=f;ctx.fill();
}}

function draw(){{
  ctx.fillStyle="#0e0e0e";ctx.fillRect(0,0,{CANVAS_W},{CANVAS_H});
  ctx.beginPath();ctx.arc(CX,CY,DO+22,0,2*Math.PI);ctx.fillStyle="#1a1a1a";ctx.fill();
  for(let i=0;i<20;i++){{
    const a0=i*AI+AO,a1=(i+1)*AI+AO,ev=i%2===0;
    const bw=ev?"#2a2a2a":"#e8e0cc",cl=ev?"#1e7a36":"#c0182a";
    arc(OB,TI,a0,a1,bw);arc(TO,DI,a0,a1,bw);
    arc(TI,TO,a0,a1,cl);arc(DI,DO,a0,a1,cl);
  }}
  ctx.strokeStyle="rgba(0,0,0,0.7)";ctx.lineWidth=1.5;
  for(let i=0;i<20;i++){{
    const a=i*AI+AO;
    ctx.beginPath();ctx.moveTo(CX,CY);ctx.lineTo(CX+DO*Math.cos(a),CY+DO*Math.sin(a));ctx.stroke();
  }}
  [OB,TI,TO,DI,DO].forEach(r=>{{
    ctx.beginPath();ctx.arc(CX,CY,r,0,2*Math.PI);
    ctx.strokeStyle="rgba(0,0,0,0.55)";ctx.lineWidth=2;ctx.stroke();
  }});
  ctx.beginPath();ctx.arc(CX,CY,OB,0,2*Math.PI);ctx.fillStyle="#1e7a36";ctx.fill();
  ctx.strokeStyle="rgba(0,0,0,0.5)";ctx.lineWidth=1.5;ctx.stroke();
  ctx.beginPath();ctx.arc(CX,CY,IB,0,2*Math.PI);ctx.fillStyle="#c0182a";ctx.fill();
  ctx.font="bold 17px Arial";ctx.textAlign="center";ctx.textBaseline="middle";
  for(let i=0;i<20;i++){{
    const a=(i+0.5)*AI+AO;
    ctx.fillStyle="white";ctx.fillText(SEGS[i],CX+LR*Math.cos(a),CY+LR*Math.sin(a));
  }}
  const clicks={click_json};
  clicks.forEach(c=>{{
    const px=CX+c.xOff,py=CY+c.yOff;
    const col=c.type==="Target"?"#ffe033":"#ff8c00",s=12;
    ctx.save();ctx.lineWidth=3;ctx.strokeStyle=col;ctx.shadowColor=col;ctx.shadowBlur=8;
    ctx.beginPath();ctx.moveTo(px-s,py-s);ctx.lineTo(px+s,py+s);ctx.stroke();
    ctx.beginPath();ctx.moveTo(px+s,py-s);ctx.lineTo(px-s,py+s);ctx.stroke();
    ctx.restore();
    ctx.beginPath();ctx.arc(px,py,5,0,2*Math.PI);ctx.fillStyle=col;ctx.fill();
  }});
}}
draw();

cv.addEventListener("click",function(e){{
  const rect=cv.getBoundingClientRect();
  const sx=cv.width/rect.width,sy=cv.height/rect.height;
  const xOff=Math.round(((e.clientX-rect.left)*sx-CX)*100)/100;
  const yOff=Math.round(((e.clientY-rect.top)*sy-CY)*100)/100;
  const name={inputuser_esc};
  const mode={inputmode_esc};
  const base=window.parent.location.href.split("?")[0];
  const url=base+"?xOff="+xOff+"&yOff="+yOff
            +"&name="+encodeURIComponent(name)
            +"&mode="+encodeURIComponent(mode);
  window.parent.location.href=url;
}});
</script>
</body>
</html>"""

# ─── Layout ───────────────────────────────────────────────────────────────────
board_col, panel_col = st.columns([3, 1])

with board_col:
    components.html(board_html, height=CANVAS_H + 10, scrolling=False)
    raw_x = st.session_state.get("last_raw_x","")
    raw_y = st.session_state.get("last_raw_y","")
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
        st.markdown(f"**X Miss Avg:** {round(sum(xl)/len(xl),2)}px")
        st.markdown(f"**Y Miss Avg:** {round(sum(yl)/len(yl),2)}px")
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
