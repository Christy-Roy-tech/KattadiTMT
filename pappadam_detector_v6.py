import cv2
import numpy as np
import time

# ==========================================================
# PAPPADAM PLUCKER - CAMERA DETECTION SYSTEM (v6)
#
# New vs v5 (based on your debug log):
#   - Circularity now passes correctly (hull-based fix worked). The remaining
#     failures were workbench clutter (tools/wires) getting merged into the
#     same connected blob as the pappadam, inflating area/aspect/solidity.
#   - Added a one-time "drag a box around your plate" step at startup
#     (cv2.selectROI). Everything outside that box is now completely ignored
#     for both calibration and detection - clutter elsewhere in the shot can
#     no longer be mistaken for the pappadam.
# ==========================================================
PHONE_URL = "http://192.168.132.198:8080/video"
WINDOW_NAME = "Pappadam Plucker - Live Camera"

# ---------- DETECTION SETTINGS ----------
MIN_AREA = 4000
MIN_CIRCULARITY = 0.55
MIN_ASPECT_RATIO = 0.50
MAX_ASPECT_RATIO = 1.80
MIN_SOLIDITY = 0.65             # was 0.75 - your real pappadam measured 0.67 even before ROI cropping

DIFF_THRESHOLD = 30
BG_BLUR = (7, 7)
AUTO_CALIBRATION_SECONDS = 2.5

# Widened: was S>=20 which cuts out pale, flour-dusted pappadams (low saturation).
LOWER_PAPPADAM = np.array([0, 0, 90])
UPPER_PAPPADAM = np.array([45, 200, 255])

LOCK_STABLE_FRAMES = 12
LOCK_MOVE_TOLERANCE = 20

ZOOM_STEPS = 12          # frames to animate the zoom-in over
ZOOM_HOLD_SECONDS = 2.0  # how long to hold "TARGET ACQUIRED" before resetting
# ---------------------------------------


def draw_crosshair(image, cx, cy, radius):
    cv2.circle(image, (cx, cy), radius, (0, 255, 0), 2)
    cv2.circle(image, (cx, cy), 5, (0, 0, 255), -1)
    size = max(15, radius // 3)
    cv2.line(image, (cx - size, cy), (cx + size, cy), (0, 0, 255), 2)
    cv2.line(image, (cx, cy - size), (cx, cy + size), (0, 0, 255), 2)


def get_gray(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, BG_BLUR, 0)


def hull_circularity(contour, area, hull, hull_area):
    """Circularity measured against the convex hull's smooth perimeter instead of the
    raw (possibly jagged/textured) contour perimeter. hull_area is passed in as it's
    already computed by the caller for the solidity check - no need to redo it."""
    hull_perimeter = cv2.arcLength(hull, True)
    if hull_perimeter == 0:
        return 0
    return (4 * np.pi * hull_area) / (hull_perimeter * hull_perimeter)


def analyze_contours(combined_mask):
    """Returns (best_accepted_or_None, debug_info_for_largest_raw_contour_or_None)."""
    contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_contour = None
    best_area = 0
    best_circularity = 0

    largest_raw = None
    largest_raw_area = 0
    debug_info = None

    for c in contours:
        area = cv2.contourArea(c)
        if area < 200:  # ignore pure noise specks for debug purposes too
            continue

        if area > largest_raw_area:
            largest_raw_area = area
            largest_raw = c

        if area < MIN_AREA:
            continue

        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0

        circularity = hull_circularity(c, area, hull, hull_area)
        if circularity < MIN_CIRCULARITY:
            continue

        x, y, w, h = cv2.boundingRect(c)
        aspect_ratio = w / float(h)
        if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
            continue

        if solidity < MIN_SOLIDITY:
            continue

        if area > best_area:
            best_area = area
            best_contour = c
            best_circularity = circularity

    if best_contour is None and largest_raw is not None:
        hull = cv2.convexHull(largest_raw)
        hull_area = cv2.contourArea(hull)
        circularity = hull_circularity(largest_raw, largest_raw_area, hull, hull_area)
        x, y, w, h = cv2.boundingRect(largest_raw)
        aspect_ratio = w / float(h) if h > 0 else 0
        solidity = largest_raw_area / hull_area if hull_area > 0 else 0
        debug_info = {
            "area": largest_raw_area, "circularity": circularity,
            "aspect_ratio": aspect_ratio, "solidity": solidity
        }

    if best_contour is None:
        return None, debug_info

    (cx, cy), radius = cv2.minEnclosingCircle(best_contour)
    return (int(cx), int(cy), int(radius), best_circularity), None


cap = cv2.VideoCapture(PHONE_URL)
if not cap.isOpened():
    print("\nERROR: Phone camera feed cannot be opened.")
    print("1. Start IP Webcam server on the phone.")
    print("2. Make sure laptop and phone use the same Wi-Fi/hotspot.")
    print("3. Check that the URL ends with /video.\n")
    raise SystemExit

cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

print("PAPPADAM TACTICAL TARGETING SYSTEM v6 STARTED")
print("IMPORTANT: keep the pappadam OUT of frame during calibration below.")
print("Press 'b' any time to force a re-calibration. Press 'q' to quit.\n")

# --- ONE-TIME: drag a box tightly around the plate, press ENTER/SPACE to confirm ---
ok, first_frame = cap.read()
if not ok:
    print("ERROR: could not read a frame to set up the plate region.")
    raise SystemExit

first_frame = cv2.resize(first_frame, (900, 650))
print("A window will appear - drag a rectangle around JUST your plate, then press ENTER or SPACE.")
print("(Press 'c' first if you want to cancel and use the whole frame instead.)")
roi_x, roi_y, roi_w, roi_h = cv2.selectROI(WINDOW_NAME, first_frame, showCrosshair=True, fromCenter=False)

if roi_w == 0 or roi_h == 0:
    print("No region selected - falling back to the full frame.")
    roi_x, roi_y, roi_w, roi_h = 0, 0, 900, 650
else:
    print(f"Plate region set to x={roi_x}, y={roi_y}, w={roi_w}, h={roi_h}\n")


def auto_calibrate(cap, window_name, seconds):
    print(f"Calibrating for {seconds:.1f}s - KEEP THE PLATE EMPTY now...")
    calib_frames = []
    start_time = time.time()

    while time.time() - start_time < seconds:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.resize(frame, (900, 650))
        frame = frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
        calib_frames.append(get_gray(frame))

        preview = frame.copy()
        remaining = seconds - (time.time() - start_time)
        cv2.putText(preview, f"CALIBRATING... KEEP PLATE EMPTY ({remaining:.1f}s)",
                    (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow(window_name, preview)
        cv2.waitKey(1)

    if not calib_frames:
        print("WARNING: could not read any frames during calibration.")
        return None

    background = np.median(np.stack(calib_frames, axis=0), axis=0).astype(np.uint8)
    print("Background calibrated.\n")
    return background


background_gray = auto_calibrate(cap, WINDOW_NAME, AUTO_CALIBRATION_SECONDS)

state = "SCANNING"          # SCANNING -> FOCUSING -> HOLD -> back to SCANNING
lock_history = []
focus_step = 0
lock_target = None          # (cx, cy, radius) captured at the moment lock begins
hold_start_time = None
last_debug_print = 0

while True:
    ok, frame = cap.read()
    if not ok:
        print("ERROR: No frame received from phone camera.")
        break

    frame = cv2.resize(frame, (900, 650))
    frame = frame[roi_y:roi_y + roi_h, roi_x:roi_x + roi_w]
    frame_h, frame_w = frame.shape[:2]
    display = frame.copy()

    if background_gray is None:
        cv2.putText(display, "PRESS 'b' TO CALIBRATE BACKGROUND (empty plate)",
                    (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)

    elif state == "SCANNING":
        gray = get_gray(frame)
        diff = cv2.absdiff(background_gray, gray)
        _, change_mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        open_kernel = np.ones((5, 5), np.uint8)
        close_kernel = np.ones((15, 15), np.uint8)
        # Open first to remove small noise specks, then a much bigger close to smooth
        # over the pappadam's own dimpled texture (that's what was wrecking circularity).
        change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_OPEN, open_kernel)
        change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_CLOSE, close_kernel, iterations=3)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, LOWER_PAPPADAM, UPPER_PAPPADAM)
        combined_mask = cv2.bitwise_and(change_mask, color_mask)

        result, debug_info = analyze_contours(combined_mask)

        cv2.imshow("Change Mask", change_mask)
        cv2.imshow("Combined Mask (final)", combined_mask)

        if result is not None:
            cx, cy, radius, circularity = result
            draw_crosshair(display, cx, cy, radius)
            cv2.putText(display, "PAPPADAM DETECTED", (20, 85),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
            cv2.putText(display, f"ROUND SCORE: {circularity:.2f}", (20, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            lock_history.append((cx, cy, radius))
            if len(lock_history) > LOCK_STABLE_FRAMES:
                lock_history.pop(0)

            if len(lock_history) == LOCK_STABLE_FRAMES:
                xs = [p[0] for p in lock_history]
                ys = [p[1] for p in lock_history]
                if (max(xs) - min(xs) <= LOCK_MOVE_TOLERANCE) and (max(ys) - min(ys) <= LOCK_MOVE_TOLERANCE):
                    state = "FOCUSING"
                    focus_step = 0
                    lock_target = (cx, cy, radius)
        else:
            lock_history = []
            cv2.putText(display, "SCANNING FOR PAPPADAM...", (20, 85),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)

            if debug_info is not None and time.time() - last_debug_print > 1.0:
                print(f"[debug] largest candidate rejected — "
                      f"area={debug_info['area']:.0f} (need >={MIN_AREA}), "
                      f"circularity={debug_info['circularity']:.2f} (need >={MIN_CIRCULARITY}), "
                      f"aspect_ratio={debug_info['aspect_ratio']:.2f} (need {MIN_ASPECT_RATIO}-{MAX_ASPECT_RATIO}), "
                      f"solidity={debug_info['solidity']:.2f} (need >={MIN_SOLIDITY})")
                last_debug_print = time.time()

    elif state == "FOCUSING":
        cx, cy, radius = lock_target
        progress = min(1.0, focus_step / ZOOM_STEPS)

        start_half = max(frame_w, frame_h) / 2
        target_half = max(radius * 2.5, 80)
        half = start_half + (target_half - start_half) * progress

        x1 = int(max(0, cx - half)); x2 = int(min(frame_w, cx + half))
        y1 = int(max(0, cy - half)); y2 = int(min(frame_h, cy + half))
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            display = frame.copy()
        else:
            sx = frame_w / crop.shape[1]
            sy = frame_h / crop.shape[0]
            display = cv2.resize(crop, (frame_w, frame_h))
            zcx = int((cx - x1) * sx)
            zcy = int((cy - y1) * sy)
            zradius = int(radius * sx)
            draw_crosshair(display, zcx, zcy, zradius)

        cv2.putText(display, "TARGET ACQUIRED", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3)

        focus_step += 1
        if focus_step > ZOOM_STEPS:
            state = "HOLD"
            hold_start_time = time.time()

    elif state == "HOLD":
        cx, cy, radius = lock_target
        target_half = max(radius * 2.5, 80)
        x1 = int(max(0, cx - target_half)); x2 = int(min(frame_w, cx + target_half))
        y1 = int(max(0, cy - target_half)); y2 = int(min(frame_h, cy + target_half))
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            display = frame.copy()
        else:
            sx = frame_w / crop.shape[1]
            display = cv2.resize(crop, (frame_w, frame_h))
            zcx = int((cx - x1) * sx)
            zcy = int((cy - y1) * sx)
            zradius = int(radius * sx)
            draw_crosshair(display, zcx, zcy, zradius)

        cv2.putText(display, "TARGET ACQUIRED - (would fire arm here)", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        if time.time() - hold_start_time > ZOOM_HOLD_SECONDS:
            state = "SCANNING"
            lock_history = []

    cv2.putText(display, "PAPPADAM TACTICAL TARGETING SYSTEM", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    status_text = {"SCANNING": "STATUS: SEARCHING", "FOCUSING": "STATUS: LOCKING",
                   "HOLD": "STATUS: TARGET LOCKED"}.get(state, "STATUS: SEARCHING")
    status_colour = (0, 255, 0) if state != "SCANNING" else (0, 200, 255)
    cv2.putText(display, status_text, (20, 620), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_colour, 2)

    cv2.imshow(WINDOW_NAME, display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("b"):
        background_gray = auto_calibrate(cap, WINDOW_NAME, AUTO_CALIBRATION_SECONDS)
        state = "SCANNING"
        lock_history = []
    elif key == ord("s"):
        filename = f"pappadam_detection_{int(time.time())}.jpg"
        cv2.imwrite(filename, display)
        print(f"Screenshot saved: {filename}")

cap.release()
cv2.destroyAllWindows()
