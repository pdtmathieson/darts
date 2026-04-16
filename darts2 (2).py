import streamlit as st
import math
import csv
import datetime
import os
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(SCRIPT_DIR, "dart_data.csv")

st.set_page_config(page_title="Dartboard", layout="centered")

# ── Dart logic ───────────────────────────────────────────────────────────────
def determine_segment(angle):
    angle = (angle - 90) % 360
    segment_order = [20, 5, 12, 9, 14, 11, 8, 16, 7, 19, 3, 17, 2, 15, 10, 6, 13, 4, 18, 1, 20]
    segment_index = int((angle + 9) // 18)
    segment_index = min(max(segment_index, 0), len(segment_order) - 1)
    return segment_order[segment_index]

def determine_modifier(distance, double_inner, double_outer, triple_inner, triple_outer,
                       inner_bull_radius, outer_bull_radius):
    if distance <= inner_bull_radius:
        return "+"
    elif distance <= outer_bull_radius:
        return "*"
    elif double_inner <= distance <= double_outer:
        return "D"
    elif triple_inner <= distance <= triple_outer:
        return "T"
    elif distance > double_outer:
        return "M"
    else:
        return "S"

def record_to_csv(data):
    write_header = not os.path.isfile(CSV_FILE_PATH) or os.stat(CSV_FILE_PATH).st_size == 0
    with open(CSV_FILE_PATH, 'a', newline='') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["Timestamp", "Target Segment", "Target Modifier",
                             "Target X Offset", "Target Y Offset",
                             "Result Segment", "Result Modifier",
                             "Result X Offset", "Result Y Offset",
                             "Name", "Mode", "Session"])
        writer.writerow(data)

def get_session_num():
    if os.path.exists(CSV_FILE_PATH):
        try:
            df = pd.read_csv(CSV_FILE_PATH)
            if "Session" in df.columns and len(df) > 0:
                return int(df["Session"].max()) + 1
        except Exception:
            pass
    return 1

# ── Board renderer ───────────────────────────────────────────────────────────
BOARD_PX = 560  # canvas pixel size

def draw_board(click_positions):
    """
    Renders the full dartboard with all persistent click markers.
    click_positions: list of {"type": "Target"|"Result", "position": (x_diff, y_diff)}
    """
    size = BOARD_PX
    img  = Image.new("RGB", (size, size), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    cx   = cy = size // 2
    R    = size // 2 - 32  # outer_radius

    # Ring radii
    inner_bull = R * (6.35 / 170)
    outer_bull = R * (16   / 170)
    t_inner    = R * (99   / 170)
    t_outer    = R * (107  / 170)
    d_inner    = R * (162  / 170)
    d_outer    = float(R)

    segment_order   = [20, 5, 12, 9, 14, 11, 8, 16, 7, 19, 3, 17, 2, 15, 10, 6, 13, 4, 18, 1]
    angle_offset    = math.radians(-9 + 90)
    angle_increment = math.radians(18)

    # ── Step 1: black/white wedge fills out to double ring ──────────────────
    for i in range(20):
        a0    = i * angle_increment + angle_offset
        a1    = a0 + angle_increment
        steps = 40
        pts   = [(cx, cy)]
        for s in range(steps + 1):
            a = a0 + (a1 - a0) * s / steps
            pts.append((cx + d_outer * math.cos(a),
                         cy - d_outer * math.sin(a)))
        fill = (0, 0, 0) if i % 2 == 0 else (220, 220, 220)
        draw.polygon(pts, fill=fill)

    # ── Step 2: triple ring (red/green alternating) ──────────────────────────
    # Draw the full triple-outer disc, then punch out triple-inner with wedge base colours
    for i in range(20):
        a0    = i * angle_increment + angle_offset
        a1    = a0 + angle_increment
        steps = 40

        # Outer arc slice (t_inner → t_outer)
        pts_outer = []
        for s in range(steps + 1):
            a = a0 + (a1 - a0) * s / steps
            pts_outer.append((cx + t_outer * math.cos(a),
                               cy - t_outer * math.sin(a)))
        pts_inner = []
        for s in range(steps, -1, -1):
            a = a0 + (a1 - a0) * s / steps
            pts_inner.append((cx + t_inner * math.cos(a),
                               cy - t_inner * math.sin(a)))
        pts = pts_outer + pts_inner
        # Alternate red/green for triple ring
        fill = (200, 30, 30) if i % 2 == 0 else (30, 160, 30)
        draw.polygon(pts, fill=fill)

    # ── Step 3: double ring (green/red alternating) ──────────────────────────
    for i in range(20):
        a0    = i * angle_increment + angle_offset
        a1    = a0 + angle_increment
        steps = 40

        pts_outer = []
        for s in range(steps + 1):
            a = a0 + (a1 - a0) * s / steps
            pts_outer.append((cx + d_outer * math.cos(a),
                               cy - d_outer * math.sin(a)))
        pts_inner = []
        for s in range(steps, -1, -1):
            a = a0 + (a1 - a0) * s / steps
            pts_inner.append((cx + d_inner * math.cos(a),
                               cy - d_inner * math.sin(a)))
        pts  = pts_outer + pts_inner
        fill = (30, 160, 30) if i % 2 == 0 else (200, 30, 30)
        draw.polygon(pts, fill=fill)

    # ── Step 4: segment divider lines ────────────────────────────────────────
    for i in range(20):
        a = i * angle_increment + angle_offset
        draw.line([(cx, cy),
                   (cx + d_outer * math.cos(a),
                    cy - d_outer * math.sin(a))],
                  fill=(0, 0, 0), width=2)

    # ── Step 5: bullseye ─────────────────────────────────────────────────────
    draw.ellipse([cx - outer_bull, cy - outer_bull,
                  cx + outer_bull, cy + outer_bull], fill=(30, 160, 30))
    draw.ellipse([cx - inner_bull, cy - inner_bull,
                  cx + inner_bull, cy + inner_bull], fill=(200, 30, 30))

    # ── Step 6: outer border ──────────────────────────────────────────────────
    draw.ellipse([cx - d_outer, cy - d_outer,
                  cx + d_outer, cy + d_outer],
                 outline=(255, 255, 255), width=2)

    # ── Step 7: segment numbers ───────────────────────────────────────────────
    label_r = d_outer + 17
    try:
        fnt = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except Exception:
        fnt = ImageFont.load_default()

    for i in range(20):
        a_mid = (i + 0.5) * angle_increment + angle_offset
        tx    = cx + label_r * math.cos(a_mid)
        ty    = cy - label_r * math.sin(a_mid)
        draw.text((tx, ty), str(segment_order[i]),
                  fill=(255, 255, 255), font=fnt, anchor="mm")

    # ── Step 8: ALL persistent click markers ─────────────────────────────────
    for click in click_positions:
        xo, yo   = click["position"]
        px, py   = cx + xo, cy - yo
        s        = 9
        color    = (255, 220, 0) if click["type"] == "Target" else (255, 140, 0)
        draw.line([(px - s, py - s), (px + s, py + s)], fill=color, width=3)
        draw.line([(px + s, py - s), (px - s, py + s)], fill=color, width=3)

    return img


# ── Session state init ────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "session_num":         None,   # resolved below
        "recording_target":    True,
        "current_target_data": None,
        "hit_cnt":             0.0,
        "shot_cnt":            0.0,
        "x_miss_list":         [],
        "y_miss_list":         [],
        "display_text":        "",
        "display_perc":        "",
        "click_positions":     [],     # ALL clicks this session
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # session_num is fetched once on first run
    if st.session_state["session_num"] is None:
        st.session_state["session_num"] = get_session_num()

init_state()
s = st.session_state

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    from streamlit_image_coordinates import streamlit_image_coordinates
except ImportError:
    st.error("Add `streamlit-image-coordinates` to requirements.txt and redeploy.")
    st.stop()

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("🎯 Dartboard Recorder")

col_name, col_mode = st.columns([2, 1])
with col_name:
    inputuser = st.text_input("Name", value="Patrick", key="name_input")
with col_mode:
    inputmode = st.selectbox("Mode", ["RTW", "Points"], key="mode_input")

if s.recording_target:
    st.info("🟡 **Click the board to set the TARGET**")
else:
    st.warning("🟠 **Click the board to set the RESULT**")

# Render board with all marks so far
board_img = draw_board(s.click_positions)
click     = streamlit_image_coordinates(board_img, key="board_click")

# ── Process click ─────────────────────────────────────────────────────────────
if click is not None:
    raw_x  = click["x"]
    raw_y  = click["y"]
    cx_px  = cy_px = BOARD_PX // 2
    x_diff = raw_x - cx_px
    y_diff = cy_px - raw_y

    R      = BOARD_PX // 2 - 32
    ib     = R * (6.35 / 170)
    ob     = R * (16   / 170)
    ti     = R * (99   / 170)
    to_    = R * (107  / 170)
    di     = R * (162  / 170)
    do_    = float(R)

    distance = math.sqrt(x_diff ** 2 + y_diff ** 2)
    angle    = math.degrees(math.atan2(y_diff, x_diff))
    if angle < 0:
        angle += 360

    segment  = determine_segment(angle)
    modifier = determine_modifier(distance, di, do_, ti, to_, ib, ob)
    now      = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if s.recording_target:
        s.current_target_data = [now, segment, modifier, x_diff, y_diff,
                                  None, None, None, None,
                                  inputuser, inputmode, 0]
        s.click_positions.append({"type": "Target", "position": (x_diff, y_diff)})
        s.recording_target = False
        s.display_text     = f"Target set: {segment}{modifier}"
        st.rerun()
    else:
        td = s.current_target_data
        td[5], td[6], td[7], td[8] = segment, modifier, x_diff, y_diff
        td[9], td[10], td[11]      = inputuser, inputmode, s.session_num

        x_miss     = (td[3] - x_diff) * -1
        y_miss     = (td[4] - y_diff) * -1
        total_miss = round(math.sqrt(x_miss ** 2 + y_miss ** 2), 0)
        s.x_miss_list.append(x_miss)
        s.y_miss_list.append(y_miss)

        if td[1] == td[5] and modifier != "M":
            miss_text = "HIT"
            s.hit_cnt += 1.0
        else:
            miss_text = "MISS"
        s.shot_cnt += 1.0

        hit_perc       = round(s.hit_cnt / s.shot_cnt * 100)
        s.display_text = f"Result: {segment}{modifier} — {miss_text} — Miss dist: {total_miss}"
        s.display_perc = f"Hit %: {hit_perc}%"
        s.click_positions.append({"type": "Result", "position": (x_diff, y_diff)})
        record_to_csv(td)
        s.recording_target = True
        st.rerun()

# ── Summary ───────────────────────────────────────────────────────────────────
if s.display_text or s.display_perc or s.x_miss_list:
    st.divider()
    _, col_right = st.columns([1, 1])
    with col_right:
        if s.display_text:
            st.markdown(f"**{s.display_text}**")
        if s.display_perc:
            st.markdown(f"**{s.display_perc}**")
        if s.x_miss_list:
            x_avg = round(sum(s.x_miss_list) / len(s.x_miss_list), 2)
            y_avg = round(sum(s.y_miss_list) / len(s.y_miss_list), 2)
            st.markdown(f"X Miss Avg: **{x_avg}**")
            st.markdown(f"Y Miss Avg: **{y_avg}**")

# ── CSV download ──────────────────────────────────────────────────────────────
if os.path.exists(CSV_FILE_PATH):
    st.divider()
    with open(CSV_FILE_PATH, "rb") as f:
        st.download_button("⬇️ Download dart_data.csv", f,
                           file_name="dart_data.csv", mime="text/csv")
