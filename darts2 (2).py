import pygame
import math
import csv
import datetime
import os
import pandas as pd

#folder_path=r"C:\\Darts\\Darts2"
folder_path=r"/storage/emulated/0/pythonfiles/"

def determine_segment(angle):
    angle = (angle - 90) % 360
    segment_order = [20, 5, 12, 9, 14, 11, 8, 16, 7, 19, 3, 17, 2, 15, 10, 6, 13, 4, 18, 1, 20]
    angle_increment = 18
    segment_index = int((angle + 9) // angle_increment)
    segment_index = min(max(segment_index, 0), len(segment_order) - 1)
    return segment_order[segment_index]

def determine_modifier(distance, double_inner, double_outer, triple_inner, triple_outer, inner_bull_radius, outer_bull_radius):
    if distance <= inner_bull_radius:
        return "+"
    elif inner_bull_radius < distance <= outer_bull_radius:
        return "*"
    elif double_inner <= distance <= double_outer:
        return "D"
    elif triple_inner <= distance <= triple_outer:
        return "T"
    elif distance > double_outer:
        return "M"
    else:
        return "S"

def record_to_csv(data, filename):
    write_header = not os.path.isfile(filename) or os.stat(filename).st_size == 0
    with open(filename, 'a', newline='') as file:
        writer = csv.writer(file)
        if write_header:
            headers = ["Timestamp", "Target Segment", "Target Modifier", "Target X Offset", "Target Y Offset",
                       "Result Segment", "Result Modifier", "Result X Offset", "Result Y Offset", "Name", "Mode", "Session"]
            writer.writerow(headers)
        writer.writerow(data)

def create_dartboard(screen, center, outer_radius, ui_scale):
    inner_bull_radius = outer_radius * (6.35 / 170)
    outer_bull_radius = outer_radius * (16 / 170)
    triple_inner      = outer_radius * (99 / 170)
    triple_outer      = outer_radius * (107 / 170)
    double_inner      = outer_radius * (162 / 170)
    double_outer      = outer_radius

    angle_offset    = math.radians(-9 + 90)
    angle_increment = 360 / 20
    colors = ["black", "white"]

    for i in range(20):
        start_angle = math.radians(i * angle_increment) + angle_offset
        end_angle   = math.radians((i + 1) * angle_increment) + angle_offset
        pygame.draw.polygon(
            screen, colors[i % 2],
            [
                center,
                (center[0] + double_outer * math.cos(start_angle), center[1] - double_outer * math.sin(start_angle)),
                (center[0] + double_outer * math.cos(end_angle),   center[1] - double_outer * math.sin(end_angle)),
            ],
        )

    pygame.draw.circle(screen, "red",   center, int(inner_bull_radius))
    pygame.draw.circle(screen, "green", center, int(outer_bull_radius), max(1, int(5 * ui_scale)))
    pygame.draw.circle(screen, "red",   center, int(triple_inner), max(1, int(5 * ui_scale)))
    pygame.draw.circle(screen, "red",   center, int(triple_outer), max(1, int(5 * ui_scale)))
    pygame.draw.circle(screen, "green", center, int(double_inner), max(1, int(5 * ui_scale)))
    pygame.draw.circle(screen, "green", center, int(double_outer), max(1, int(5 * ui_scale)))

    segment_order = [20, 5, 12, 9, 14, 11, 8, 16, 7, 19, 3, 17, 2, 15, 10, 6, 13, 4, 18, 1]
    font_size = max(12, int(24 * ui_scale))
    font = pygame.font.Font(None, font_size)

    for i in range(20):
        angle = math.radians(i * angle_increment) + angle_offset
        pygame.draw.line(
            screen, "black", center,
            (center[0] + double_outer * math.cos(angle), center[1] - double_outer * math.sin(angle)), 2,
        )

    # Number label offset — keep labels well inside the horizontal edges
    label_offset = double_outer + max(10, int(16 * ui_scale))
    for i in range(20):
        angle_mid = math.radians(i * angle_increment + angle_increment / 2) + angle_offset
        text_x = center[0] + label_offset * math.cos(angle_mid)
        text_y = center[1] - label_offset * math.sin(angle_mid)
        text      = font.render(str(segment_order[i]), True, "white")
        text_rect = text.get_rect(center=(text_x, text_y))
        screen.blit(text, text_rect)

def main():
    pygame.init()

    # --- Aspect ratio 11.5 wide x 19 high, scaled to 90% of available space ---
    ASPECT_W = 15
    ASPECT_H = 17

    display_info = pygame.display.Info()
    avail_w = display_info.current_w
    avail_h = display_info.current_h

    scale_factor  = min(avail_w / ASPECT_W, avail_h / ASPECT_H) * 0.99  # 90% cap

    screen_width  = int(ASPECT_W * scale_factor)
    screen_height = int(ASPECT_H * scale_factor)

    screen = pygame.display.set_mode((screen_width, screen_height))
    pygame.display.set_caption("Dartboard")

    ui_scale = screen_height / 900  # relative to original 900 px design

    # --- Layout zones ---
    TOP_BAR_H    = int(90 * ui_scale)
    BOTTOM_BAR_H = int(110 * ui_scale)
    board_area_h = screen_height - TOP_BAR_H - BOTTOM_BAR_H

    # Horizontal padding so numbers never clip the edges
    H_PAD = int(36 * ui_scale)

    # Board radius: largest circle that fits board area AND horizontal space
    max_r_h = board_area_h // 2 - int(8 * ui_scale)
    max_r_w = (screen_width - H_PAD * 2) // 2 - int(8 * ui_scale)
    # Subtract label clearance (~18 px at ui_scale=1) from radius so numbers fit
    label_clearance = int(20 * ui_scale)
    outer_radius = min(max_r_h, max_r_w) - label_clearance

    center = (screen_width // 2, TOP_BAR_H + board_area_h // 2)

    # Ring distances
    inner_bull_radius = outer_radius * (6.35 / 170)
    outer_bull_radius = outer_radius * (16 / 170)
    triple_inner      = outer_radius * (99 / 170)
    triple_outer      = outer_radius * (107 / 170)
    double_inner      = outer_radius * (162 / 170)
    double_outer      = outer_radius

    # --- CSV / session ---
    csv_file_path = folder_path + r"dart_data.csv"
    if os.path.exists(csv_file_path):
        data = pd.read_csv(csv_file_path)
        if "Session" in data.columns and not data["Session"].empty:
            session_num = int(data["Session"].max()) + 1
        else:
            session_num = 1
    else:
        session_num = 1

    # --- Fonts ---
    font_small  = pygame.font.Font(None, max(16, int(26 * ui_scale)))
    font_medium = pygame.font.Font(None, max(18, int(32 * ui_scale)))
    font_btn    = pygame.font.Font(None, max(16, int(24 * ui_scale)))

    # --- Name text box ---
    inputuser     = "Patrick"
    name_active   = False
    ctrl_h        = int(34 * ui_scale)
    ctrl_y        = int(8 * ui_scale)
    name_box_w    = int(180 * ui_scale)
    name_box_rect = pygame.Rect(int(10 * ui_scale), ctrl_y + int(18 * ui_scale), name_box_w, ctrl_h)

    # --- Mode dropdown ---
    MODE_OPTIONS  = ["RTW", "Points"]
    inputmode     = MODE_OPTIONS[0]
    mode_open     = False
    mode_box_w    = int(130 * ui_scale)
    mode_box_rect = pygame.Rect(name_box_rect.right + int(60 * ui_scale),
                                ctrl_y + int(18 * ui_scale), mode_box_w, ctrl_h)
    mode_item_rects = []

    # --- CLOSE button (top right) ---
    close_btn_w   = int(80 * ui_scale)
    close_btn_h   = int(34 * ui_scale)
    close_btn_rect = pygame.Rect(screen_width - close_btn_w - int(8 * ui_scale),
                                  ctrl_y + int(18 * ui_scale), close_btn_w, close_btn_h)

    # --- Stats ---
    hit_cnt     = 0.0
    shot_cnt    = 0.0
    x_miss_list = []
    y_miss_list = []

    target_prompt    = "Click board: set Target"
    result_prompt    = "Click board: set Result"
    recording_target = True
    running          = True
    current_target_data = None
    display_text     = ""
    display_perc     = ""
    click_positions  = []

    pygame.key.set_repeat(400, 50)
    clock = pygame.time.Clock()

    while running:
        screen.fill("black")

        # ── Top bar background ──
        pygame.draw.rect(screen, (30, 30, 30), (0, 0, screen_width, TOP_BAR_H))

        # ── Name label + box ──
        lbl_name = font_small.render("Name:", True, "white")
        screen.blit(lbl_name, (name_box_rect.x, ctrl_y))
        pygame.draw.rect(screen, (50, 50, 50), name_box_rect)
        pygame.draw.rect(screen, (255, 255, 100) if name_active else (180, 180, 180), name_box_rect, 2)
        clip_r = name_box_rect.inflate(-6, -4)
        screen.set_clip(clip_r)
        ns = font_small.render(inputuser, True, "white")
        screen.blit(ns, (name_box_rect.x + 4,
                         name_box_rect.y + (ctrl_h - ns.get_height()) // 2))
        screen.set_clip(None)
        if name_active and (pygame.time.get_ticks() // 500) % 2 == 0:
            cx = name_box_rect.x + 4 + min(ns.get_width(), clip_r.width - 4)
            pygame.draw.line(screen, "white",
                             (cx, name_box_rect.y + 4),
                             (cx, name_box_rect.bottom - 4), 2)

        # ── Mode label + dropdown box ──
        lbl_mode = font_small.render("Mode:", True, "white")
        screen.blit(lbl_mode, (mode_box_rect.x, ctrl_y))
        pygame.draw.rect(screen, (50, 50, 50), mode_box_rect)
        pygame.draw.rect(screen, (180, 180, 180), mode_box_rect, 2)
        ms = font_small.render(inputmode + "  ▼", True, "white")
        screen.blit(ms, (mode_box_rect.x + 6,
                         mode_box_rect.y + (ctrl_h - ms.get_height()) // 2))

        # ── CLOSE button ──
        pygame.draw.rect(screen, (180, 40, 40), close_btn_rect, border_radius=4)
        cs = font_btn.render("CLOSE", True, "white")
        screen.blit(cs, (close_btn_rect.x + (close_btn_rect.width  - cs.get_width())  // 2,
                         close_btn_rect.y + (close_btn_rect.height - cs.get_height()) // 2))

        # ── Prompt ──
        prompt_surf = font_small.render(result_prompt if not recording_target else target_prompt, True, "white")
        screen.blit(prompt_surf, (int(10 * ui_scale),
                                  TOP_BAR_H - prompt_surf.get_height() - int(4 * ui_scale)))

        # ── Dartboard ──
        create_dartboard(screen, center, outer_radius, ui_scale)

        # ── Click markers ──
        for click in click_positions:
            xo, yo = click["position"]
            color  = "yellow" if click["type"] == "Target" else "orange"
            cx, cy = center[0] + xo, center[1] - yo
            s = max(6, int(10 * ui_scale))
            pygame.draw.line(screen, color, (cx - s, cy - s), (cx + s, cy + s), 3)
            pygame.draw.line(screen, color, (cx + s, cy - s), (cx - s, cy + s), 3)

        # ── Bottom-right summary panel ──
        line_h    = font_small.get_height() + int(4 * ui_scale)
        panel_w   = int(290 * ui_scale)
        summary_x = screen_width  - panel_w
        summary_y = screen_height - BOTTOM_BAR_H + int(8 * ui_scale)

        if display_text:
            screen.blit(font_small.render(display_text, True, "yellow"), (summary_x, summary_y))
        if display_perc:
            screen.blit(font_small.render(display_perc, True, "yellow"), (summary_x, summary_y + line_h))
        if x_miss_list:
            x_avg = round(sum(x_miss_list) / len(x_miss_list), 2)
            y_avg = round(sum(y_miss_list) / len(y_miss_list), 2)
            screen.blit(font_small.render(f"X Miss Avg: {x_avg}", True, "yellow"),
                        (summary_x, summary_y + line_h * 2))
            screen.blit(font_small.render(f"Y Miss Avg: {y_avg}", True, "yellow"),
                        (summary_x, summary_y + line_h * 3))

        # ── Mode dropdown overlay ──
        if mode_open:
            mode_item_rects.clear()
            for idx, opt in enumerate(MODE_OPTIONS):
                ir = pygame.Rect(mode_box_rect.x,
                                 mode_box_rect.bottom + idx * ctrl_h,
                                 mode_box_w, ctrl_h)
                mode_item_rects.append(ir)
                pygame.draw.rect(screen, (60, 60, 60), ir)
                pygame.draw.rect(screen, (200, 200, 200), ir, 1)
                os_ = font_small.render(opt, True, "white")
                screen.blit(os_, (ir.x + 6, ir.y + (ctrl_h - os_.get_height()) // 2))

        # ── Events ──
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN and name_active:
                if event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    name_active = False
                elif event.key == pygame.K_BACKSPACE:
                    inputuser = inputuser[:-1]
                elif event.unicode and event.unicode.isprintable():
                    inputuser += event.unicode

            elif event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos

                # Close button
                if close_btn_rect.collidepoint(mx, my):
                    running = False
                    continue

                # Dropdown item selection
                if mode_open:
                    clicked_item = False
                    for idx, ir in enumerate(mode_item_rects):
                        if ir.collidepoint(mx, my):
                            inputmode    = MODE_OPTIONS[idx]
                            mode_open    = False
                            clicked_item = True
                            break
                    if not clicked_item:
                        mode_open = False
                    continue

                if name_box_rect.collidepoint(mx, my):
                    name_active = True
                    continue

                if mode_box_rect.collidepoint(mx, my):
                    name_active = False
                    mode_open   = True
                    continue

                name_active = False

                # Board clicks only below top bar
                if my < TOP_BAR_H:
                    continue

                x_diff = mx - center[0]
                y_diff = center[1] - my
                distance_to_center = math.sqrt(x_diff ** 2 + y_diff ** 2)
                angle = math.degrees(math.atan2(y_diff, x_diff))
                if angle < 0:
                    angle += 360

                segment_number = determine_segment(angle)
                modifier       = determine_modifier(distance_to_center, double_inner, double_outer,
                                                    triple_inner, triple_outer,
                                                    inner_bull_radius, outer_bull_radius)
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if recording_target:
                    current_target_data = [now, segment_number, modifier, x_diff, y_diff,
                                           None, None, None, None, inputuser, inputmode, 0]
                    recording_target = False
                    display_text     = f"Target: {segment_number}{modifier}"
                    click_positions.append({"type": "Target", "position": (x_diff, y_diff)})
                else:
                    current_target_data[5]  = segment_number
                    current_target_data[6]  = modifier
                    current_target_data[7]  = x_diff
                    current_target_data[8]  = y_diff
                    current_target_data[9]  = inputuser
                    current_target_data[10] = inputmode
                    current_target_data[11] = session_num

                    x_miss = (current_target_data[3] - x_diff) * -1
                    y_miss = (current_target_data[4] - y_diff) * -1
                    x_miss_list.append(x_miss)
                    y_miss_list.append(y_miss)
                    total_miss = round(math.sqrt(x_miss ** 2 + y_miss ** 2), 0)

                    if current_target_data[1] == current_target_data[5] and modifier != "M":
                        miss_text = "HIT"
                        hit_cnt  += 1.0
                    else:
                        miss_text = "MISS"
                    shot_cnt += 1.0

                    hit_perc     = round(hit_cnt / shot_cnt * 100)
                    display_text = f"Result: {segment_number}{modifier} - {miss_text} - Miss {total_miss}"
                    display_perc = f"Hit %: {hit_perc}%"
                    click_positions.append({"type": "Result", "position": (x_diff, y_diff)})
                    record_to_csv(current_target_data, csv_file_path)
                    recording_target = True

        pygame.display.update()
        clock.tick(60)

    # Save screenshot
    filename        = f"Board Image - Session {session_num}.png"
    screenshot_path = os.path.join(folder_path, filename)
    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
    pygame.image.save(screen, screenshot_path)
    pygame.quit()

if __name__ == "__main__":
    main()