#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║   PAPPADAM PLUCKER — CINEMATIC AUTONOMOUS TARGETING SYSTEM      ║
║   Team KattadiTMT                                               ║
║                                                                  ║
║   Full cinematic loop:                                           ║
║   Splash → VHS → Camera HUD → Detect → Celebrate → Pluck/Reset ║
╚══════════════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import cv2
import numpy as np
import threading
import time
import json
import os
import ast
import math

# ─── Optional dependencies ───────────────────────────────────────
try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("[WARN] pyserial not installed — serial commands disabled")

try:
    import pygame
    pygame.mixer.init()
    HAS_AUDIO = True
except Exception:
    HAS_AUDIO = False
    print("[WARN] pygame not available — audio disabled")

# ═════════════════════════════════════════════════════════════════
# FILE PATHS
# ═════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR  = os.path.join(BASE_DIR, "reference")

FRONT_PAGE_PATH      = os.path.join(REF_DIR, "front page.png")
VHS_VIDEO_PATH       = os.path.join(REF_DIR,
    "Old VHS Effect TV Turn off Vintage static _4K_ Snowman Digital_2160p.mp4")
VHS_OPTIMIZED_PATH   = os.path.join(REF_DIR, "vhs_optimized.mp4")
DETECTION_IMG_PATH   = os.path.join(REF_DIR, "detection.png")
CELEBRATION_VID_PATH = os.path.join(REF_DIR, "papadam detected.mp4")
COWBOY_THEME_PATH    = os.path.join(REF_DIR, "cowboy_theme.mp3")
COORDINATES_PATH     = os.path.join(BASE_DIR, "coordinates.txt")
SAVED_CONFIG_PATH    = os.path.join(BASE_DIR, "saved_coordinates.json")
ROI_CONFIG_PATH      = os.path.join(BASE_DIR, "saved_roi.json")

# ═════════════════════════════════════════════════════════════════
# CAMERA CONFIG
# ═════════════════════════════════════════════════════════════════
PHONE_URL  = "http://192.168.132.198:8080/video"
FRAME_SIZE = (900, 650)          # resize every raw frame to this

# ═════════════════════════════════════════════════════════════════
# DETECTION SETTINGS (from pappadam_detector_v6.py)
# ═════════════════════════════════════════════════════════════════
MIN_AREA            = 4000
MIN_CIRCULARITY     = 0.55
MIN_ASPECT_RATIO    = 0.50
MAX_ASPECT_RATIO    = 1.80
MIN_SOLIDITY        = 0.65
DIFF_THRESHOLD      = 30
BG_BLUR             = (7, 7)
AUTO_CALIB_SECONDS  = 2.5
LOWER_PAPPADAM      = np.array([0, 0, 90])
UPPER_PAPPADAM      = np.array([45, 200, 255])
LOCK_STABLE_FRAMES  = 12
LOCK_MOVE_TOLERANCE = 20
ZOOM_STEPS          = 15
ZOOM_HOLD_SECONDS   = 2.0

# ═════════════════════════════════════════════════════════════════
# JOINT CONFIGURATION  (mirrors Python GUI.py slider setup)
# Slider values are stored in coordinates.txt; inversion is
# applied before sending over serial — exactly as the GUI does.
# ═════════════════════════════════════════════════════════════════
JOINTS_CFG = {
    'A1': {'lo': 0,  'hi': 180, 'invert': True},    # Shoulder MG995
    'A2': {'lo': 9,  'hi': 64,  'invert': False},   # Elbow    SG90
    'A3': {'lo': 0,  'hi': 180, 'invert': False},   # Wrist P  MG995
    'A4': {'lo': 0,  'hi': 180, 'invert': True},    # Wrist R  SG90
    'G':  {'lo': 0,  'hi': 90,  'invert': False},   # Gripper
}


# ═════════════════════════════════════════════════════════════════
# DETECTION UTILITIES  (ported from pappadam_detector_v6.py)
# ═════════════════════════════════════════════════════════════════
def get_gray(frame):
    return cv2.GaussianBlur(
        cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), BG_BLUR, 0)


def hull_circularity(hull, hull_area):
    p = cv2.arcLength(hull, True)
    return (4 * np.pi * hull_area) / (p * p) if p else 0


def detect_pappadam(frame, bg_gray):
    """Full v6 pipeline.  Returns (cx, cy, radius, circularity) or None."""
    if bg_gray is None:
        return None

    gray = get_gray(frame)
    diff = cv2.absdiff(bg_gray, gray)
    _, mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

    ok5  = np.ones((5, 5), np.uint8)
    ok15 = np.ones((15, 15), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  ok5)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ok15, iterations=3)

    hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    cmask = cv2.inRange(hsv, LOWER_PAPPADAM, UPPER_PAPPADAM)
    combined = cv2.bitwise_and(mask, cmask)

    cnts, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)

    best, best_area = None, 0
    for c in cnts:
        a = cv2.contourArea(c)
        if a < MIN_AREA:
            continue
        hull  = cv2.convexHull(c)
        ha    = cv2.contourArea(hull)
        sol   = a / ha if ha else 0
        circ  = hull_circularity(hull, ha)
        if circ < MIN_CIRCULARITY:
            continue
        x, y, w, h = cv2.boundingRect(c)
        ar = w / float(h)
        if ar < MIN_ASPECT_RATIO or ar > MAX_ASPECT_RATIO:
            continue
        if sol < MIN_SOLIDITY:
            continue
        if a > best_area:
            best_area = a
            best = c

    if best is None:
        return None
    (cx, cy), r = cv2.minEnclosingCircle(best)
    hull  = cv2.convexHull(best)
    ha    = cv2.contourArea(hull)
    circ  = hull_circularity(hull, ha)
    return (int(cx), int(cy), int(r), circ)


# ═════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════
class KattadiApp:
    """Full-screen cinematic state machine."""

    def __init__(self, root):
        self.root = root
        self.root.title("PAPPADAM PLUCKER")
        self.root.configure(bg="black")
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda _: self.cleanup_and_exit())

        self.root.update_idletasks()
        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()

        self.canvas = tk.Canvas(root, width=self.sw, height=self.sh,
                                bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # ── state ────────────────────────────
        self.state        = "INIT"
        self.running      = True
        self.cam_opened   = False

        # ── camera ───────────────────────────
        self.cap          = None
        self.cam_thread   = None
        self.cam_stop     = threading.Event()
        self.frm_lock     = threading.Lock()
        self.latest_frame = None

        # ── detection ────────────────────────
        self.bg_gray      = None
        self.roi          = (0, 0, *FRAME_SIZE)
        self.lock_hist    = []
        self.lock_target  = None
        self.zoom_step    = 0

        # ── serial ───────────────────────────
        self.ser          = None
        self.last_sent    = {}

        # ── coordinates ──────────────────────
        self.pluck_coords   = None
        self.unpluck_coords = None
        self.cur_pos = {'A1': 0, 'A2': 9, 'A3': 0, 'A4': 0, 'G': 90}

        # ── HUD counters ─────────────────────
        self.scan_y   = 0
        self.hud_tick = 0

        # ── blink ────────────────────────────
        self.bv  = 40
        self.bd  = 1

        # ── photo refs (prevent GC) ─────────
        self._pr = None
        self._pr2 = None
        self._vhs_frames     = []
        self._vhs_photos     = []
        self._vhs_canvas_img = None
        self._celeb_canvas_img = None

        # ── boot ─────────────────────────────
        self._load_assets()
        self._load_coords()
        self._connect_serial()
        threading.Thread(target=self._preload_vhs, daemon=True).start()

        self.root.after(200, self.show_splash)
        self.root.protocol("WM_DELETE_WINDOW", self.cleanup_and_exit)

    # ─────────────────────────────────────────────────────────────
    # ASSETS
    # ─────────────────────────────────────────────────────────────
    def _load_assets(self):
        try:
            self.splash_pil = Image.open(FRONT_PAGE_PATH).resize(
                (self.sw, self.sh), Image.LANCZOS)
        except Exception as e:
            print(f"[WARN] front page: {e}")
            self.splash_pil = Image.new("RGB", (self.sw, self.sh), "black")

        try:
            self.det_overlay = Image.open(DETECTION_IMG_PATH).convert("RGBA")
        except Exception as e:
            print(f"[WARN] detection overlay: {e}")
            self.det_overlay = None

    def _preload_vhs(self):
        """Pre-decode and resize VHS frames in background during splash screen for smooth 30-45 FPS."""
        src = VHS_OPTIMIZED_PATH if os.path.exists(VHS_OPTIMIZED_PATH) else VHS_VIDEO_PATH
        if not os.path.exists(src):
            return
        try:
            cap = cv2.VideoCapture(src)
            frames = []
            while self.running:
                ret, f = cap.read()
                if not ret:
                    break
                f = cv2.resize(f, (self.sw, self.sh), interpolation=cv2.INTER_LINEAR)
                f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                frames.append(f)
            cap.release()
            self._vhs_frames = frames
            print(f"[OK] VHS video preloaded: {len(frames)} frames ready for instant 30-45 FPS playback")
        except Exception as e:
            print(f"[WARN] VHS preload: {e}")

    # ─────────────────────────────────────────────────────────────
    # COORDINATES
    # ─────────────────────────────────────────────────────────────
    def _load_coords(self):
        # 1) try permanent JSON
        if os.path.exists(SAVED_CONFIG_PATH):
            try:
                d = json.load(open(SAVED_CONFIG_PATH))
                self.pluck_coords   = d["pluck"]
                self.unpluck_coords = d["unpluck"]
                print(f"[OK] saved coords loaded  pluck={self.pluck_coords}  "
                      f"unpluck={self.unpluck_coords}")
                return
            except Exception:
                pass

        # 2) parse coordinates.txt
        try:
            for line in open(COORDINATES_PATH, encoding="utf-8"):
                line = line.strip()
                if "Pluck Saved:" in line and "Unpluck" not in line:
                    self.pluck_coords = ast.literal_eval(
                        line.split("Pluck Saved:")[1].strip())
                elif "Unpluck Saved:" in line:
                    self.unpluck_coords = ast.literal_eval(
                        line.split("Unpluck Saved:")[1].strip())

            if self.pluck_coords and self.unpluck_coords:
                json.dump({"pluck": self.pluck_coords,
                           "unpluck": self.unpluck_coords},
                          open(SAVED_CONFIG_PATH, "w"), indent=2)
                print(f"[OK] parsed & saved  pluck={self.pluck_coords}  "
                      f"unpluck={self.unpluck_coords}")
        except Exception as e:
            print(f"[ERR] coordinates: {e}")

    # ─────────────────────────────────────────────────────────────
    # SERIAL
    # ─────────────────────────────────────────────────────────────
    def _connect_serial(self):
        if not HAS_SERIAL:
            return
        for p in serial.tools.list_ports.comports():
            try:
                self.ser = serial.Serial(p.device, 115200, timeout=0.05)
                print(f"[OK] serial → {p.device}  ({p.description})")
                return
            except Exception:
                continue
        print("[WARN] no serial port found")

    def _tx(self, cmd):
        """Send a raw serial command with dedup."""
        if ":" in cmd:
            k, v = cmd.split(":", 1)
            if self.last_sent.get(k) == v:
                return
            self.last_sent[k] = v
        if self.ser and self.ser.is_open:
            try:
                self.ser.write((cmd + "\n").encode())
            except Exception:
                pass

    def _tx_joint(self, prefix, slider_val):
        """Apply inversion (same as Python GUI) then send."""
        c = JOINTS_CFG[prefix]
        sent = (c["hi"] - (slider_val - c["lo"])) if c["invert"] else slider_val
        self._tx(f"{prefix}:{sent}")

    # ═════════════════════════════════════════════════════════════
    # STATE 1 — SPLASH
    # ═════════════════════════════════════════════════════════════
    def show_splash(self):
        self.state = "SPLASH"
        self.canvas.delete("all")
        if HAS_AUDIO:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

        self._pr = ImageTk.PhotoImage(self.splash_pil)
        self.canvas.create_image(0, 0, anchor="nw", image=self._pr)

        # dark band for text readability
        bh = 70
        band = Image.new("RGBA", (self.sw, bh), (0, 0, 0, 190))
        self._pr2 = ImageTk.PhotoImage(band)
        self.canvas.create_image(0, self.sh - bh, anchor="nw", image=self._pr2)

        # shadow
        self.canvas.create_text(
            self.sw // 2 + 2, self.sh - bh // 2 + 2,
            text="P R E S S   A N Y   K E Y   T O   C O N T I N U E",
            font=("Consolas", 17, "bold"), fill="#111111")
        # main
        self._blink_id = self.canvas.create_text(
            self.sw // 2, self.sh - bh // 2,
            text="P R E S S   A N Y   K E Y   T O   C O N T I N U E",
            font=("Consolas", 17, "bold"), fill="#FFD700")

        self.bv, self.bd = 40, 1
        self._blink_loop()

        self.root.bind("<Key>",      self._key_splash)
        self.root.bind("<Button-1>", self._key_splash)

    def _blink_loop(self):
        if self.state != "SPLASH":
            return
        self.bv += self.bd * 5
        if self.bv >= 255:
            self.bv, self.bd = 255, -1
        elif self.bv <= 40:
            self.bv, self.bd = 40, 1
        v = self.bv
        r, g, b = int(v), int(v * 0.82), int(v * 0.05)
        self.canvas.itemconfig(self._blink_id, fill=f"#{r:02x}{g:02x}{b:02x}")
        self.root.after(35, self._blink_loop)

    def _key_splash(self, _):
        if self.state != "SPLASH":
            return
        self.root.unbind("<Key>")
        self.root.unbind("<Button-1>")
        self._play_vhs()

    # ═════════════════════════════════════════════════════════════
    # STATE 2 — VHS VIDEO (30-45 FPS, finishes strictly in <= 5.0 s)
    # ═════════════════════════════════════════════════════════════
    def _play_vhs(self):
        self.state = "VHS"
        self.canvas.delete("all")
        self._vhs_canvas_img = None

        # 1) If background thread already pre-cached frames in RAM
        if self._vhs_frames:
            self._vhs_photos = [
                ImageTk.PhotoImage(Image.fromarray(f)) for f in self._vhs_frames
            ]
        else:
            # 2) Fallback: read from optimized 720p file
            src = VHS_OPTIMIZED_PATH if os.path.exists(VHS_OPTIMIZED_PATH) else VHS_VIDEO_PATH
            if not os.path.exists(src):
                print("[WARN] VHS video not found — skipping")
                self._camera_phase()
                return
            cap = cv2.VideoCapture(src)
            self._vhs_photos = []
            while True:
                ret, f = cap.read()
                if not ret:
                    break
                f = cv2.resize(f, (self.sw, self.sh), interpolation=cv2.INTER_LINEAR)
                f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                self._vhs_photos.append(ImageTk.PhotoImage(Image.fromarray(f)))
            cap.release()

        if not self._vhs_photos:
            print("[WARN] No VHS frames available — skipping")
            self._camera_phase()
            return

        self._vhs_total = len(self._vhs_photos)
        # Target 30 FPS playback: 125 frames finish in ~4.16s (strictly <= 5.0 seconds)
        self._vhs_fps = 30.0
        self._vhs_start_time = time.time()
        self._vhs_canvas_img = self.canvas.create_image(
            0, 0, anchor="nw", image=self._vhs_photos[0]
        )
        self._vhs_step()

    def _vhs_step(self):
        if self.state != "VHS" or not self.running:
            return
        elapsed = time.time() - self._vhs_start_time
        idx = int(elapsed * self._vhs_fps)

        if idx >= self._vhs_total or elapsed >= 5.0:
            # VHS sequence completed! Free memory & transition to camera
            self._vhs_photos = []
            self._vhs_canvas_img = None
            self._camera_phase()
            return

        self.canvas.itemconfig(self._vhs_canvas_img, image=self._vhs_photos[idx])
        # Poll every 10ms for smooth 30-45+ FPS display
        self.root.after(10, self._vhs_step)

    # ═════════════════════════════════════════════════════════════
    # STATE 3 — CAMERA INIT  (ROI selection + thread start)
    # ═════════════════════════════════════════════════════════════
    def _camera_phase(self):
        if self.cam_opened:
            self._begin_calib()
            return

        self.state = "CAM_INIT"
        self.canvas.delete("all")
        self.canvas.create_text(
            self.sw // 2, self.sh // 2,
            text="INITIALIZING TACTICAL CAMERA...",
            font=("Consolas", 22, "bold"), fill="#00CCFF")
        self.root.update()

        # open IP Webcam feed
        self.cap = cv2.VideoCapture(PHONE_URL)
        if not self.cap.isOpened():
            self.canvas.delete("all")
            self.canvas.create_text(
                self.sw // 2, self.sh // 2,
                text="CAMERA OFFLINE\nVerify IP Webcam & WiFi",
                font=("Consolas", 20), fill="#FF4444", justify="center")
            return

        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        time.sleep(0.5)
        ok, first = self.cap.read()
        if not ok:
            return
        first = cv2.resize(first, FRAME_SIZE)

        # ── ROI ──────────────────────────────
        roi_ok = False
        if os.path.exists(ROI_CONFIG_PATH):
            try:
                self.roi = tuple(json.load(open(ROI_CONFIG_PATH))["roi"])
                roi_ok = True
                print(f"[OK] ROI loaded: {self.roi}")
            except Exception:
                pass

        if not roi_ok:
            self.root.attributes("-fullscreen", False)
            self.root.iconify()
            print("[INFO] Drag a rectangle around the plate → ENTER/SPACE")
            rx, ry, rw, rh = cv2.selectROI(
                "Select Plate Region", first,
                showCrosshair=True, fromCenter=False)
            cv2.destroyWindow("Select Plate Region")
            if rw > 0 and rh > 0:
                self.roi = (rx, ry, rw, rh)
            else:
                self.roi = (0, 0, *FRAME_SIZE)
            json.dump({"roi": list(self.roi)},
                      open(ROI_CONFIG_PATH, "w"))
            print(f"[OK] ROI saved: {self.roi}")
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.focus_force()

        # ── background reader thread ─────────
        self.cam_opened = True
        self.cam_stop.clear()
        self.cam_thread = threading.Thread(target=self._cam_loop, daemon=True)
        self.cam_thread.start()
        self._begin_calib()

    def _cam_loop(self):
        """Background: read frames, crop to ROI, publish."""
        while not self.cam_stop.is_set() and self.running:
            if self.cap and self.cap.isOpened():
                ok, f = self.cap.read()
                if ok:
                    f = cv2.resize(f, FRAME_SIZE)
                    rx, ry, rw, rh = self.roi
                    with self.frm_lock:
                        self.latest_frame = f[ry:ry+rh, rx:rx+rw]
                else:
                    time.sleep(0.03)
            else:
                time.sleep(0.1)
            time.sleep(0.008)

    # ═════════════════════════════════════════════════════════════
    # STATE 4 — CALIBRATION
    # ═════════════════════════════════════════════════════════════
    def _begin_calib(self):
        self.state = "CALIB"
        self._cbuf = []
        self._ct0  = time.time()
        self._calib_tick()

    def _calib_tick(self):
        if self.state != "CALIB" or not self.running:
            return
        with self.frm_lock:
            frm = self.latest_frame.copy() if self.latest_frame is not None else None
        if frm is None:
            self.root.after(30, self._calib_tick)
            return

        self._cbuf.append(get_gray(frm))
        elapsed = time.time() - self._ct0
        rem = max(0, AUTO_CALIB_SECONDS - elapsed)

        # draw progress overlay
        h, w = frm.shape[:2]
        disp = frm.copy()
        cv2.rectangle(disp, (0, 0), (w, 65), (0, 0, 0), -1)
        cv2.putText(disp,
                    f"CALIBRATING... KEEP PLATE EMPTY  ({rem:.1f}s)",
                    (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
        prog = min(1.0, elapsed / AUTO_CALIB_SECONDS)
        bw = w - 30
        cv2.rectangle(disp, (15, 42), (15 + bw, 55), (30, 30, 30), -1)
        cv2.rectangle(disp, (15, 42), (15 + int(bw * prog), 55), (0, 200, 255), -1)
        self._show_bgr(disp)

        if elapsed >= AUTO_CALIB_SECONDS and self._cbuf:
            self.bg_gray = np.median(
                np.stack(self._cbuf, axis=0), axis=0).astype(np.uint8)
            self._cbuf = []
            print("[OK] background calibrated")
            self._begin_scan()
            return
        self.root.after(30, self._calib_tick)

    # ═════════════════════════════════════════════════════════════
    # STATE 5 — SCANNING  (detective HUD, cowboy theme loops)
    # ═════════════════════════════════════════════════════════════
    def _begin_scan(self):
        self.state    = "SCAN"
        self.lock_hist = []
        self.scan_y    = 0
        self.hud_tick  = 0

        if HAS_AUDIO:
            try:
                pygame.mixer.music.load(COWBOY_THEME_PATH)
                pygame.mixer.music.play(-1)   # loop
            except Exception as e:
                print(f"[WARN] music: {e}")
        self._scan_tick()

    def _scan_tick(self):
        if self.state != "SCAN" or not self.running:
            return
        with self.frm_lock:
            frm = self.latest_frame.copy() if self.latest_frame is not None else None
        if frm is None:
            self.root.after(30, self._scan_tick)
            return

        # ── silent detection ─────────────────
        res = detect_pappadam(frm, self.bg_gray)
        if res:
            cx, cy, r, circ = res
            self.lock_hist.append((cx, cy, r))
            if len(self.lock_hist) > LOCK_STABLE_FRAMES:
                self.lock_hist.pop(0)
            if len(self.lock_hist) == LOCK_STABLE_FRAMES:
                xs = [p[0] for p in self.lock_hist]
                ys = [p[1] for p in self.lock_hist]
                if (max(xs)-min(xs) <= LOCK_MOVE_TOLERANCE and
                        max(ys)-min(ys) <= LOCK_MOVE_TOLERANCE):
                    self.lock_target = (cx, cy, r)
                    self._begin_target()
                    return
        else:
            self.lock_hist = []

        # ── detective HUD ────────────────────
        disp = self._draw_hud(frm)
        self._show_bgr(disp)
        self.hud_tick += 1
        self.root.after(30, self._scan_tick)

    # ─── HUD renderer ───────────────────────────────────────────
    def _draw_hud(self, frm):
        d = frm.copy()
        h, w = d.shape[:2]

        # colour palette (BGR) — NO GREEN
        CY  = (255, 200, 0)      # cyan
        AM  = (0, 165, 255)      # amber
        WH  = (220, 220, 220)    # white
        DM  = (100, 80, 0)      # dim cyan
        RD  = (0, 0, 255)        # red

        m  = 14   # margin
        bl = 38   # bracket length
        bt = 2    # bracket thickness

        # ── dark top / bottom bands for text readability ─────
        overlay_band = d.copy()
        cv2.rectangle(overlay_band, (0, 0), (w, 50), (0, 0, 0), -1)
        cv2.rectangle(overlay_band, (0, h - 55), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay_band, 0.5, d, 0.5, 0, d)

        # ── corner brackets ──────────────────
        for (bx, by, dx, dy) in [
            (m, m, 1, 1),   (w-m, m, -1, 1),
            (m, h-m, 1, -1), (w-m, h-m, -1, -1)]:
            cv2.line(d, (bx, by), (bx + dx*bl, by), CY, bt)
            cv2.line(d, (bx, by), (bx, by + dy*bl), CY, bt)

        # ── thin border + tick marks ─────────
        cv2.rectangle(d, (m, m), (w-m, h-m), DM, 1)
        for x in range(m+40, w-m, 40):
            th = 7 if (x-m) % 80 == 0 else 3
            cv2.line(d, (x, m), (x, m+th), DM, 1)
            cv2.line(d, (x, h-m), (x, h-m-th), DM, 1)
        for y in range(m+40, h-m, 40):
            tw = 7 if (y-m) % 80 == 0 else 3
            cv2.line(d, (m, y), (m+tw, y), DM, 1)
            cv2.line(d, (w-m, y), (w-m-tw, y), DM, 1)

        # ── scanline sweep ───────────────────
        self.scan_y = (self.scan_y + 2) % h
        ov = d.copy()
        cv2.line(ov, (m+3, self.scan_y), (w-m-3, self.scan_y), CY, 1)
        cv2.addWeighted(ov, 0.2, d, 0.8, 0, d)

        # ── REC indicator (blinks) ───────────
        if self.hud_tick % 30 < 22:
            cv2.circle(d, (m+16, m+22), 4, RD, -1)
            cv2.putText(d, "REC", (m+26, m+27),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, RD, 1)

        # ── LIVE FEED label ──────────────────
        cv2.putText(d, "LIVE FEED", (w-m-120, m+27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, CY, 1)

        # ── bottom-left: system name + status ─
        cv2.putText(d, "PAPPADAM TACTICAL TARGETING SYSTEM",
                    (m+8, h-m-28), cv2.FONT_HERSHEY_SIMPLEX, 0.4, CY, 1)
        cv2.putText(d, "STATUS: SCANNING",
                    (m+8, h-m-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, AM, 1)

        # ── bottom-right: time / date ────────
        cv2.putText(d, time.strftime("%H:%M:%S"),
                    (w-m-105, h-m-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WH, 1)
        cv2.putText(d, time.strftime("%Y-%m-%d"),
                    (w-m-120, h-m-28), cv2.FONT_HERSHEY_SIMPLEX, 0.35, DM, 1)

        # ── centre subtle crosshair ──────────
        cx, cy = w//2, h//2
        s = 14
        cv2.line(d, (cx-s, cy), (cx-4, cy), DM, 1)
        cv2.line(d, (cx+4, cy), (cx+s, cy), DM, 1)
        cv2.line(d, (cx, cy-s), (cx, cy-4), DM, 1)
        cv2.line(d, (cx, cy+4), (cx, cy+s), DM, 1)

        # ── diagonal corner accents ──────────
        a = 10
        for (ox, oy, dx, dy) in [
            (m, m, 1, 1), (w-m, m, -1, 1),
            (m, h-m, 1, -1), (w-m, h-m, -1, -1)]:
            cv2.line(d, (ox+dx*5, oy+dy*5), (ox+dx*(5+a), oy+dy*(5+a)), DM, 1)

        # ── signal bars (fake) ───────────────
        bx0, by0 = w - m - 50, m + 40
        for i in range(4):
            bh = 4 + i * 3
            clr = CY if i < 3 else DM
            cv2.rectangle(d, (bx0 + i*8, by0 + 16 - bh),
                          (bx0 + i*8 + 5, by0 + 16), clr, -1)

        return d

    # ═════════════════════════════════════════════════════════════
    # STATE 6 — TARGET ACQUIRED  (zoom + detection.png overlay)
    # ═════════════════════════════════════════════════════════════
    def _begin_target(self):
        self.state     = "TARGET"
        self.zoom_step = 0
        if HAS_AUDIO:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self._target_tick()

    def _target_tick(self):
        if self.state != "TARGET" or not self.running:
            return
        with self.frm_lock:
            frm = self.latest_frame.copy() if self.latest_frame is not None else None
        if frm is None:
            self.root.after(30, self._target_tick)
            return

        cx, cy, rad = self.lock_target
        fh, fw = frm.shape[:2]
        prog = min(1.0, self.zoom_step / ZOOM_STEPS)

        # ── zoom crop ────────────────────────
        half0 = max(fw, fh) / 2
        half1 = max(rad * 2.5, 80)
        half  = half0 + (half1 - half0) * prog

        x1 = int(max(0, cx - half));  x2 = int(min(fw, cx + half))
        y1 = int(max(0, cy - half));  y2 = int(min(fh, cy + half))
        crop = frm[y1:y2, x1:x2]

        if crop.size > 0:
            disp = cv2.resize(crop, (fw, fh))
        else:
            disp = frm.copy()

        # ── "TARGET ACQUIRED" banner ─────────
        cv2.rectangle(disp, (0, 0), (fw, 55), (0, 0, 0), -1)
        cv2.putText(disp, "TARGET ACQUIRED", (18, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

        # ── overlay detection.png when fully zoomed ──
        if prog >= 1.0 and self.det_overlay:
            sz = int(min(fw, fh) * 0.45)
            disp = self._composite_det(disp, fw//2, fh//2, sz)

        self._show_bgr(disp)
        self.zoom_step += 1

        total = ZOOM_STEPS + int(ZOOM_HOLD_SECONDS * 30)
        if self.zoom_step > total:
            self._play_celeb()
            return
        self.root.after(33, self._target_tick)

    def _composite_det(self, bgr, cx, cy, sz):
        """Alpha-composite detection.png onto frame."""
        rgb  = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        base = Image.fromarray(rgb).convert("RGBA")
        over = self.det_overlay.resize((sz*2, sz*2), Image.LANCZOS)
        base.paste(over, (cx-sz, cy-sz), over)
        return cv2.cvtColor(np.array(base.convert("RGB")), cv2.COLOR_RGB2BGR)

    # ═════════════════════════════════════════════════════════════
    # STATE 7 — CELEBRATION VIDEO
    # ═════════════════════════════════════════════════════════════
    def _play_celeb(self):
        self.state = "CELEB"
        self.canvas.delete("all")
        self._celeb_canvas_img = None
        self._cc = cv2.VideoCapture(CELEBRATION_VID_PATH)
        if not self._cc.isOpened():
            print("[WARN] celebration video not found — skipping")
            self._begin_pluck()
            return
        fps = self._cc.get(cv2.CAP_PROP_FPS) or 30
        self._cdel = max(1, int(1000 / fps))
        self._celeb_frame()

    def _celeb_frame(self):
        if self.state != "CELEB" or not self.running:
            return
        ok, f = self._cc.read()
        if not ok:
            self._cc.release()
            self._celeb_canvas_img = None
            self._begin_pluck()
            return
        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        f = cv2.resize(f, (self.sw, self.sh))
        self._pr = ImageTk.PhotoImage(Image.fromarray(f))
        if self._celeb_canvas_img is None:
            self.canvas.delete("all")
            self._celeb_canvas_img = self.canvas.create_image(
                0, 0, anchor="nw", image=self._pr
            )
        else:
            self.canvas.itemconfig(self._celeb_canvas_img, image=self._pr)
        self.root.after(self._cdel, self._celeb_frame)

    # ═════════════════════════════════════════════════════════════
    # STATE 8 — PLUCK  /  UNPLUCK  (serial, background)
    # ═════════════════════════════════════════════════════════════
    def _begin_pluck(self):
        self.state = "PLUCK"
        self.canvas.delete("all")

        self._sid = self.canvas.create_text(
            self.sw//2, self.sh//2 - 30,
            text=">>> EXECUTING PLUCK SEQUENCE",
            font=("Consolas", 26, "bold"), fill="#00FF88")
        self._ssid = self.canvas.create_text(
            self.sw//2, self.sh//2 + 25,
            text="Moving arm to pluck position...",
            font=("Consolas", 14), fill="#888888")

        if not self.pluck_coords or not self.unpluck_coords:
            self.canvas.itemconfig(self._sid,
                                   text="ERROR: NO COORDINATES", fill="#FF4444")
            self.root.after(3000, self._begin_reset)
            return

        self._tx("P:ON")
        self.last_sent.clear()
        self.root.after(350, lambda: self._anim_arm(
            self.pluck_coords, self._pluck_done))

    def _anim_arm(self, tgt, callback):
        """50-step smooth arm interpolation → gripper → callback."""
        keys  = ['A1', 'A2', 'A3', 'A4']
        steps = 50
        delay = 40    # ms per step  → ~2 s total
        st = dict(self.cur_pos)
        inc = {k: (tgt[k] - st[k]) / steps for k in keys}

        def step(i):
            if not self.running:
                return
            if i <= steps:
                for k in keys:
                    v = int(st[k] + inc[k] * i)
                    self._tx_joint(k, v)
                    self.cur_pos[k] = v
                self.root.after(delay, step, i + 1)
            else:
                # gripper phase
                if 'G' in tgt:
                    self._tx_joint('G', tgt['G'])
                    travel = abs(tgt['G'] - st.get('G', 0))
                    self.cur_pos['G'] = tgt['G']
                    self.root.after(travel * 15 + 250, callback)
                else:
                    callback()
        step(1)

    def _pluck_done(self):
        if not self.running:
            return
        print("[OK] pluck complete")
        self.canvas.itemconfig(self._ssid,
                               text="Pluck complete! Returning to home...")
        self.last_sent.clear()
        self.root.after(600, lambda: self._anim_arm(
            self.unpluck_coords, self._unpluck_done))

    def _unpluck_done(self):
        if not self.running:
            return
        print("[OK] unpluck complete")
        self.canvas.itemconfig(self._sid,
                               text="[ OK ] MISSION ACCOMPLISHED")
        self.canvas.itemconfig(self._ssid,
                               text="Resetting in 5 seconds...")
        self._tx("P:OFF")
        self.root.after(600, self._begin_reset)

    # ═════════════════════════════════════════════════════════════
    # STATE 9 — RESET  (5 s countdown → loop)
    # ═════════════════════════════════════════════════════════════
    def _begin_reset(self):
        self.state = "RESET"
        self.canvas.delete("all")

        self.canvas.create_text(
            self.sw//2, self.sh//2 - 25,
            text="[ OK ]  MISSION ACCOMPLISHED",
            font=("Consolas", 28, "bold"), fill="#00FF88")
        self._cdn = 5
        self._cdnid = self.canvas.create_text(
            self.sw//2, self.sh//2 + 30,
            text=f"Restarting in {self._cdn}...",
            font=("Consolas", 16), fill="#666666")
        self._reset_tick()

    def _reset_tick(self):
        if self.state != "RESET" or not self.running:
            return
        self._cdn -= 1
        if self._cdn <= 0:
            # wipe detection state, keep camera alive
            self.lock_hist   = []
            self.lock_target = None
            self.bg_gray     = None
            self.zoom_step   = 0
            self.last_sent.clear()
            self.show_splash()
            return
        self.canvas.itemconfig(self._cdnid,
                               text=f"Restarting in {self._cdn}...")
        self.root.after(1000, self._reset_tick)

    # ═════════════════════════════════════════════════════════════
    # DISPLAY HELPER
    # ═════════════════════════════════════════════════════════════
    def _show_bgr(self, bgr):
        """Render an OpenCV BGR frame to the canvas (scale to fill)."""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        fh, fw = rgb.shape[:2]
        sc = max(self.sw / fw, self.sh / fh)
        nw, nh = int(fw * sc), int(fh * sc)
        res = cv2.resize(rgb, (nw, nh))
        sx = (nw - self.sw) // 2
        sy = (nh - self.sh) // 2
        crop = res[sy:sy+self.sh, sx:sx+self.sw]
        self._pr = ImageTk.PhotoImage(Image.fromarray(crop))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._pr)

    # ═════════════════════════════════════════════════════════════
    # CLEANUP
    # ═════════════════════════════════════════════════════════════
    def cleanup_and_exit(self):
        self.running = False
        self.cam_stop.set()
        if HAS_AUDIO:
            try:
                pygame.mixer.music.stop()
                pygame.mixer.quit()
            except Exception:
                pass
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        if self.ser and self.ser.is_open:
            try:
                self._tx("P:OFF")
                self.ser.close()
            except Exception:
                pass
        self.root.destroy()


# ═════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    root = tk.Tk()
    app  = KattadiApp(root)
    root.mainloop()
