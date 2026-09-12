import cv2
import numpy as np
import time

# ==========================================================
# PAPPADAM PLUCKER - CAMERA DETECTION SYSTEM (v3)
#
# Fixes vs v2:
#   - Background is auto-calibrated at startup (median of ~2.5s of frames),
#     so you don't need to click the video window and press 'b' before it
#     starts working. 'b' still works any time to force a re-calibration.
#   - Using median-of-many-frames instead of a single frame makes the
#     background far less sensitive to a stray reflection/glare pixel.
# ========================================================
# Your IP Webcam video URL
PHONE_URL = "http://192.168.132.198:8080/video"


WINDOW_NAME = "Pappadam Plucker - Live Camera"

# ---------- DETECTION SETTINGS ----------
MIN_AREA = 5000
MIN_CIRCULARITY = 0.55
MIN_ASPECT_RATIO = 0.75
MAX_ASPECT_RATIO = 1.30
MIN_SOLIDITY = 0.85

DIFF_THRESHOLD = 30
BG_BLUR = (7, 7)
AUTO_CALIBRATION_SECONDS = 2.5

LOWER_PAPPADAM = np.array([10, 20, 100])
UPPER_PAPPADAM = np.array([40, 160, 255])
# ---------------------------------------


def draw_crosshair(image, cx, cy, radius):
    cv2.circle(image, (cx, cy), radius, (0, 255, 0), 3)
    cv2.circle(image, (cx, cy), 7, (0, 0, 255), -1)
    size = 32
    cv2.line(image, (cx - size, cy), (cx + size, cy), (0, 0, 255), 2)
    cv2.line(image, (cx, cy - size), (cx, cy + size), (0, 0, 255), 2)
    bracket = 15
    cv2.line(image, (cx - radius, cy - bracket), (cx - radius, cy + bracket), (0, 255, 0), 3)
    cv2.line(image, (cx + radius, cy - bracket), (cx + radius, cy + bracket), (0, 255, 0), 3)


def get_gray(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, BG_BLUR, 0)


def auto_calibrate(cap, window_name, seconds):
    """Collect frames for `seconds` and return their per-pixel median as the background.
    Median is far more robust to a single glare frame or MJPEG glitch than one snapshot."""
    print(f"\nAuto-calibrating background for {seconds:.1f}s - KEEP THE PLATE EMPTY now...")
    calib_frames = []
    start_time = time.time()

    while time.time() - start_time < seconds:
        ok, frame = cap.read()
        if not ok:
            continue
        frame = cv2.resize(frame, (900, 650))
        calib_frames.append(get_gray(frame))

        preview = frame.copy()
        remaining = seconds - (time.time() - start_time)
        cv2.putText(preview, f"CALIBRATING... KEEP PLATE EMPTY ({remaining:.1f}s)",
                    (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.imshow(window_name, preview)
        cv2.waitKey(1)

    if not calib_frames:
        print("WARNING: could not read any frames during calibration - staying uncalibrated.")
        return None

    background = np.median(np.stack(calib_frames, axis=0), axis=0).astype(np.uint8)
    print("Background calibrated.\n")
    return background


cap = cv2.VideoCapture(PHONE_URL)
if not cap.isOpened():
    print("\nERROR: Phone camera feed cannot be opened.")
    print("1. Start IP Webcam server on the phone.")
    print("2. Make sure laptop and phone use the same Wi-Fi/hotspot.")
    print("3. Check that the URL ends with /video.\n")
    raise SystemExit

cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)

print("PAPPADAM TACTICAL TARGETING SYSTEM v3 STARTED")
print("Press 'b' any time to force a re-calibration (keep plate empty when you do).")
print("Press 'q' to quit. Press 's' to save a screenshot.")

background_gray = auto_calibrate(cap, WINDOW_NAME, AUTO_CALIBRATION_SECONDS)

while True:
    ok, frame = cap.read()
    if not ok:
        print("ERROR: No frame received from phone camera.")
        break

    frame = cv2.resize(frame, (900, 650))
    display = frame.copy()
    gray = get_gray(frame)

    detected = False
    best_contour = None
    best_area = 0
    best_circularity = 0

    if background_gray is None:
        cv2.putText(display, "PRESS 'b' TO CALIBRATE BACKGROUND (empty plate)",
                    (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
    else:
        diff = cv2.absdiff(background_gray, gray)
        _, change_mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

        kernel = np.ones((5, 5), np.uint8)
        change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_OPEN, kernel)
        change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, LOWER_PAPPADAM, UPPER_PAPPADAM)
        combined_mask = cv2.bitwise_and(change_mask, color_mask)

        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < MIN_AREA:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue

            circularity = (4 * np.pi * area) / (perimeter * perimeter)
            if circularity < MIN_CIRCULARITY:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            aspect_ratio = w / float(h)
            if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
                continue

            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            solidity = area / hull_area if hull_area > 0 else 0
            if solidity < MIN_SOLIDITY:
                continue

            if area > best_area:
                best_area = area
                best_contour = contour
                best_circularity = circularity

        cv2.imshow("Change Mask", change_mask)
        cv2.imshow("Combined Mask (final)", combined_mask)

    if best_contour is not None:
        detected = True
        (center_x, center_y), radius = cv2.minEnclosingCircle(best_contour)
        center_x, center_y, radius = int(center_x), int(center_y), int(radius)
        draw_crosshair(display, center_x, center_y, radius)

        cv2.putText(display, "PAPPADAM DETECTED - TARGET LOCKED", (20, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
        cv2.putText(display, f"TARGET PIXEL: X={center_x}, Y={center_y}", (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(display, f"ROUND SCORE: {best_circularity:.2f} | AREA: {int(best_area)}",
                    (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    elif background_gray is not None:
        cv2.putText(display, "SCANNING FOR PAPPADAM...", (20, 85),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)

    cv2.putText(display, "PAPPADAM TACTICAL TARGETING SYSTEM", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    status = "STATUS: TARGET LOCKED" if detected else "STATUS: SEARCHING"
    status_colour = (0, 255, 0) if detected else (0, 200, 255)
    cv2.putText(display, status, (20, 620), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_colour, 2)

    cv2.imshow(WINDOW_NAME, display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    elif key == ord("b"):
        background_gray = auto_calibrate(cap, WINDOW_NAME, AUTO_CALIBRATION_SECONDS)
    elif key == ord("s"):
        filename = f"pappadam_detection_{int(time.time())}.jpg"
        cv2.imwrite(filename, display)
        print(f"Screenshot saved: {filename}")

cap.release()
cv2.destroyAllWindows()