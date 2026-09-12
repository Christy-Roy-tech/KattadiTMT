import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk
import serial
import serial.tools.list_ports
import threading
import time
import cv2
import numpy as np
from PIL import Image, ImageTk, ImageEnhance

# --- Initialize Modern Monochrome Glass Theme ---
ctk.set_appearance_mode("dark")

# ==========================================================
# ASSET / CAMERA CONFIG  -  fill these in
# ==========================================================
PHONE_URL = "http://10.10.182.191:8080/video"     # IP Webcam /video URL
BG_IMAGE_PATH = "assets/panel_background.png"     # smoked-glass UI background (was undefined before)
INTRO_IMAGE_PATH = "assets/intro.png"             # splash image shown before the CRT transition
CRUSH_SOUND_PATH = "assets/crush.wav"             # sound played the instant the gripper crushes

VIDEO_DISPLAY_SIZE = (440, 330)   # embedded video panel size, in pixels

# ---------- DETECTION SETTINGS (same tuning as detector v3) ----------
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

LOCK_STABLE_FRAMES = 15      # consecutive frames the target must stay put before the arm fires
LOCK_MOVE_TOLERANCE = 18     # px of drift still counted as "steady"

# --- optional sound backend ---
try:
    import pygame
    pygame.mixer.init()
    _SOUND_BACKEND = "pygame"
except Exception:
    _SOUND_BACKEND = None


def play_sound(path):
    if _SOUND_BACKEND != "pygame":
        print(f"[sound] pygame not available - would play {path}")
        return
    try:
        pygame.mixer.Sound(path).play()
    except Exception as e:
        print(f"[sound] failed to play {path}: {e}")


# ==========================================================
# DETECTION HELPERS (module-level, same approach as detector v3)
# ==========================================================
def get_gray(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, BG_BLUR, 0)


def draw_crosshair(image, cx, cy, radius):
    cv2.circle(image, (cx, cy), radius, (0, 255, 0), 2)
    cv2.circle(image, (cx, cy), 5, (0, 0, 255), -1)
    size = 20
    cv2.line(image, (cx - size, cy), (cx + size, cy), (0, 0, 255), 1)
    cv2.line(image, (cx, cy - size), (cx, cy + size), (0, 0, 255), 1)


def detect_pappadam(frame, background_gray):
    """Returns ((cx, cy), radius, circularity) for the best candidate, or None."""
    if background_gray is None:
        return None

    gray = get_gray(frame)
    diff = cv2.absdiff(background_gray, gray)
    _, change_mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

    kernel = np.ones((5, 5), np.uint8)
    change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_OPEN, kernel)
    change_mask = cv2.morphologyEx(change_mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    color_mask = cv2.inRange(hsv, LOWER_PAPPADAM, UPPER_PAPPADAM)
    combined = cv2.bitwise_and(change_mask, color_mask)

    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_contour = None
    best_area = 0
    best_circularity = 0

    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_AREA:
            continue

        perimeter = cv2.arcLength(c, True)
        if perimeter == 0:
            continue

        circularity = (4 * np.pi * area) / (perimeter * perimeter)
        if circularity < MIN_CIRCULARITY:
            continue

        x, y, w, h = cv2.boundingRect(c)
        aspect_ratio = w / float(h)
        if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
            continue

        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        if solidity < MIN_SOLIDITY:
            continue

        if area > best_area:
            best_area = area
            best_contour = c
            best_circularity = circularity

    if best_contour is None:
        return None

    (cx, cy), radius = cv2.minEnclosingCircle(best_contour)
    return (int(cx), int(cy)), int(radius), best_circularity


class RobotArmPro:
    def __init__(self, root):
        self.root = root
        self.root.title("6-Axis Robot Control (Monochrome UI)")
        self.root.geometry("560x1350")

        # Absolute pitch black background for maximum contrast depth
        self.root.configure(fg_color="#000000")

        # --- CUSTOM BACKGROUND IMAGE PROCESSING ---
        try:
            bg_image = Image.open(BG_IMAGE_PATH)
            enhancer = ImageEnhance.Brightness(bg_image)
            dark_bg = enhancer.enhance(0.3)

            self.bg_img = ctk.CTkImage(light_image=dark_bg, dark_image=dark_bg, size=(560, 1350))
            self.bg_label = ctk.CTkLabel(self.root, image=self.bg_img, text="")
            self.bg_label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception as e:
            print(f"Background image not found or error: {e}")

        self.ser = None
        self.is_powered = False
        self.last_val = {}

        # --- DYNAMIC PRESET STORAGE ---
        self.pluck_coords = None
        self.unpluck_coords = None

        # --- COM PORT DETECTION STORAGE ---
        self.port_lookup = {}

        # ===================== NEW: AUTO-DETECT STATE =====================
        self.cap = None
        self.video_thread = None
        self.video_thread_stop = threading.Event()
        self.latest_frame_lock = threading.Lock()
        self.latest_display_frame = None
        self.hunting_active = False
        self.hunt_state = "IDLE"     # IDLE, INTRO, TRANSITION, CALIBRATING, SCANNING, LOCKED, PLUCKING, RETURNING
        self.background_gray = None
        self.lock_center_history = []
        self.calib_frames_buffer = []
        self.calib_start_time = None
        self.gui_update_job = None
        # ====================================================================

        self.main_container = ctk.CTkScrollableFrame(self.root, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True)

        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def create_glass_frame(self, parent, title):
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", padx=15, pady=10)

        lbl = ctk.CTkLabel(container, text=title, font=("Segoe UI", 12, "bold"), text_color="#888888")
        lbl.pack(anchor="w", padx=15, pady=(0, 5))

        glass = ctk.CTkFrame(container, fg_color="#0A0A0A", corner_radius=16,
                             border_width=1, border_color="#222222")
        glass.pack(fill="x")
        return glass

    def setup_ui(self):
        # --- Connection Section ---
        c_frame = self.create_glass_frame(self.main_container, "USB CONNECTION")

        inner_c = ctk.CTkFrame(c_frame, fg_color="transparent")
        inner_c.pack(padx=15, pady=15, fill="x")

        self.port_var = ctk.StringVar(value="Scanning...")
        self.port_menu = ctk.CTkOptionMenu(inner_c, width=190, variable=self.port_var,
                                           values=["Scanning..."], corner_radius=8,
                                           fg_color="#000000", button_color="#1A1A1A",
                                           button_hover_color="#333333", text_color="#FFFFFF",
                                           dropdown_fg_color="#0A0A0A", dropdown_hover_color="#222222",
                                           font=("Segoe UI", 12))
        self.port_menu.pack(side="left", padx=(0, 8))

        ctk.CTkButton(inner_c, text="⟳", width=36, corner_radius=8,
                      fg_color="#1A1A1A", hover_color="#333333", text_color="#FFFFFF",
                      font=("Segoe UI", 14, "bold"), command=self.refresh_ports).pack(side="left", padx=(0, 8))

        ctk.CTkButton(inner_c, text="Connect", width=90, corner_radius=8,
                      fg_color="#FFFFFF", text_color="#000000", hover_color="#CCCCCC",
                      font=("Segoe UI", 13, "bold"), command=self.toggle_connection).pack(side="left")

        self.lbl_conn_status = ctk.CTkLabel(c_frame, text="", font=("Segoe UI", 11),
                                            text_color="#666666", anchor="w")
        self.lbl_conn_status.pack(fill="x", padx=15, pady=(0, 15))

        self.refresh_ports()

        # --- Power Button ---
        self.pwr_btn = ctk.CTkButton(self.main_container, text="ENABLE SYSTEM", fg_color="#111111", hover_color="#222222",
                                     height=55, font=("Segoe UI", 15, "bold"), corner_radius=12, text_color="#555555",
                                     command=self.toggle_power, state="disabled", border_width=1, border_color="#333333")
        self.pwr_btn.pack(fill="x", padx=20, pady=(5, 15))

        # --- Base 360 Control ---
        b_frame = self.create_glass_frame(self.main_container, "BASE ROTATION (360 MG995)")
        inner_b = ctk.CTkFrame(b_frame, fg_color="transparent")
        inner_b.pack(pady=15)

        self.bl = ctk.CTkButton(inner_b, text="ROTATE LEFT", width=140, height=40, corner_radius=8,
                                fg_color="#1A1A1A", hover_color="#333333", text_color="#FFFFFF", state="disabled")
        self.bl.grid(row=0, column=0, padx=10)
        self.bl.bind("<ButtonPress-1>", lambda e: self.send_cmd("B:L"))
        self.bl.bind("<ButtonRelease-1>", lambda e: self.send_cmd("B:S"))

        self.br = ctk.CTkButton(inner_b, text="ROTATE RIGHT", width=140, height=40, corner_radius=8,
                                fg_color="#1A1A1A", hover_color="#333333", text_color="#FFFFFF", state="disabled")
        self.br.grid(row=0, column=1, padx=10)
        self.br.bind("<ButtonPress-1>", lambda e: self.send_cmd("B:R"))
        self.br.bind("<ButtonRelease-1>", lambda e: self.send_cmd("B:S"))

        # --- Joint Sliders ---
        s_frame = self.create_glass_frame(self.main_container, "JOINT POSITIONS")
        self.create_slider(s_frame, "Shoulder (MG995)", 0, 180,  "A1", invert=True)
        self.create_slider(s_frame, "Elbow (SG90)", 9, 64, "A2")
        self.create_slider(s_frame, "Wrist Pitch (MG995)", 0, 180, "A3")
        self.create_slider(s_frame, "Wrist Roll (SG90)", 0, 180, "A4")

        # --- Gripper Section (Slider) ---
        g_frame = self.create_glass_frame(self.main_container, "GRIPPER CONTROL")
        self.create_slider(g_frame, "Gripper Claw", 0, 90, "G", smooth=False)

        # --- DYNAMIC PRESET SECTION ---
        p_frame = self.create_glass_frame(self.main_container, "DYNAMIC PRESETS (Transport -> Actuate)")

        pluck_row = ctk.CTkFrame(p_frame, fg_color="transparent")
        pluck_row.pack(fill="x", padx=15, pady=(15, 5))

        self.btn_save_pluck = ctk.CTkButton(pluck_row, text="💾 Save Pluck", width=120, height=35, corner_radius=8,
                                            fg_color="#0A0A0A", hover_color="#222222", border_width=1,
                                            border_color="#FFFFFF", text_color="#FFFFFF", font=("Segoe UI", 12, "bold"),
                                            state="disabled", command=self.save_pluck)
        self.btn_save_pluck.pack(side="left", padx=5)

        self.btn_run_pluck = ctk.CTkButton(pluck_row, text="▶ RUN PLUCK", width=120, height=35, corner_radius=8,
                                           fg_color="#FFFFFF", hover_color="#CCCCCC", text_color="#000000", font=("Segoe UI", 12, "bold"),
                                           state="disabled", command=self.run_pluck)
        self.btn_run_pluck.pack(side="left", padx=5)

        self.lbl_pluck = ctk.CTkLabel(pluck_row, text="[Unsaved]", font=("Segoe UI", 12), text_color="#555555")
        self.lbl_pluck.pack(side="left", padx=10)

        unpluck_row = ctk.CTkFrame(p_frame, fg_color="transparent")
        unpluck_row.pack(fill="x", padx=15, pady=(5, 15))

        self.btn_save_unpluck = ctk.CTkButton(unpluck_row, text="💾 Save Unpluck", width=120, height=35, corner_radius=8,
                                              fg_color="#0A0A0A", hover_color="#222222", border_width=1,
                                              border_color="#FFFFFF", text_color="#FFFFFF", font=("Segoe UI", 12, "bold"),
                                              state="disabled", command=self.save_unpluck)
        self.btn_save_unpluck.pack(side="left", padx=5)

        self.btn_run_unpluck = ctk.CTkButton(unpluck_row, text="▶ RUN UNPLUCK", width=120, height=35, corner_radius=8,
                                             fg_color="#FFFFFF", hover_color="#CCCCCC", text_color="#000000", font=("Segoe UI", 12, "bold"),
                                             state="disabled", command=self.run_unpluck)
        self.btn_run_unpluck.pack(side="left", padx=5)

        self.lbl_unpluck = ctk.CTkLabel(unpluck_row, text="[Unsaved]", font=("Segoe UI", 12), text_color="#555555")
        self.lbl_unpluck.pack(side="left", padx=10)

        # ===================== NEW: AUTO-DETECT PANEL =====================
        self.create_auto_detect_panel()
        # ====================================================================

    # ================================================================
    # NEW: AUTO-DETECT (CAMERA) PANEL
    # ================================================================
    def create_auto_detect_panel(self):
        d_frame = self.create_glass_frame(self.main_container, "AUTO-DETECT (CAMERA)")
        inner_d = ctk.CTkFrame(d_frame, fg_color="transparent")
        inner_d.pack(padx=15, pady=15, fill="x")

        self.video_label = tk.Label(inner_d, bg="black", fg="#555555",
                                     text="CAMERA OFFLINE", font=("Segoe UI", 12))
        self.video_label.pack(pady=(0, 10))

        self.lbl_hunt_status = ctk.CTkLabel(inner_d, text="IDLE", font=("Segoe UI", 12, "bold"),
                                            text_color="#666666")
        self.lbl_hunt_status.pack(pady=(0, 10))

        btn_row = ctk.CTkFrame(inner_d, fg_color="transparent")
        btn_row.pack()

        self.btn_start_hunt = ctk.CTkButton(btn_row, text="▶ Start Hunting", width=150, height=36, corner_radius=8,
                                            fg_color="#FFFFFF", text_color="#000000", hover_color="#CCCCCC",
                                            font=("Segoe UI", 12, "bold"), command=self.start_hunting)
        self.btn_start_hunt.pack(side="left", padx=5)

        self.btn_stop_hunt = ctk.CTkButton(btn_row, text="■ Stop Hunting", width=150, height=36, corner_radius=8,
                                           fg_color="#1A1A1A", hover_color="#333333", text_color="#FFFFFF",
                                           font=("Segoe UI", 12, "bold"), state="disabled", command=self.stop_hunting)
        self.btn_stop_hunt.pack(side="left", padx=5)

    def _lock_manual_controls(self, lock):
        state = "disabled" if lock else ("normal" if self.is_powered else "disabled")
        keys = ["bl", "br", "s_A1", "s_A2", "s_A3", "s_A4", "s_G",
                "btn_save_pluck", "btn_run_pluck", "btn_save_unpluck", "btn_run_unpluck"]
        for k in keys:
            if hasattr(self, k):
                getattr(self, k).configure(state=state)

    def start_hunting(self):
        if not self.is_powered:
            messagebox.showwarning("System Off", "Enable the system before starting the camera.")
            return
        if not self.pluck_coords or not self.unpluck_coords:
            messagebox.showwarning("Presets Missing", "Save both a Pluck and an Unpluck position first.")
            return
        if self.hunting_active:
            return

        self.hunting_active = True
        self.btn_start_hunt.configure(state="disabled")
        self.btn_stop_hunt.configure(state="normal")
        self._lock_manual_controls(True)

        self.lock_center_history = []
        self.background_gray = None
        self.video_thread_stop.clear()

        self.video_thread = threading.Thread(target=self._video_worker, daemon=True)
        self.video_thread.start()

        self._show_intro_sequence()

        self.gui_update_job = self.root.after(30, self.update_video_frame)

    def stop_hunting(self):
        self.hunting_active = False
        self.video_thread_stop.set()

        if self.gui_update_job:
            self.root.after_cancel(self.gui_update_job)
            self.gui_update_job = None

        self.hunt_state = "IDLE"
        self.lbl_hunt_status.configure(text="IDLE", text_color="#666666")
        self.video_label.configure(image="", text="CAMERA OFFLINE")
        self.video_label.image = None

        self.btn_start_hunt.configure(state="normal")
        self.btn_stop_hunt.configure(state="disabled")
        self._lock_manual_controls(False)

    # --- intro image -> CRT power-off transition -> calibration ---
    def _show_intro_sequence(self):
        self.hunt_state = "INTRO"
        self.lbl_hunt_status.configure(text="INITIALIZING...", text_color="#FFCC00")

        try:
            intro_img = Image.open(INTRO_IMAGE_PATH).resize(VIDEO_DISPLAY_SIZE)
            photo = ImageTk.PhotoImage(intro_img)
            self.video_label.configure(image=photo, text="")
            self.video_label.image = photo
        except Exception as e:
            print(f"Intro image not found/loaded: {e}")

        self.root.after(1800, lambda: self._crt_transition_step(0))

    def _crt_transition_step(self, step, total_steps=10):
        if not self.hunting_active:
            return
        if step > total_steps:
            self.hunt_state = "CALIBRATING"
            self.lbl_hunt_status.configure(text="CALIBRATING BACKGROUND - KEEP PLATE EMPTY", text_color="#FFCC00")
            self.calib_frames_buffer = []
            self.calib_start_time = time.time()
            return

        self.hunt_state = "TRANSITION"
        w, h = VIDEO_DISPLAY_SIZE
        collapsed_h = max(2, int(h * (1 - step / total_steps)))
        canvas = Image.new("RGB", (w, h), "black")
        band = Image.new("RGB", (w, collapsed_h), "black")
        canvas.paste(band, (0, (h - collapsed_h) // 2))
        photo = ImageTk.PhotoImage(canvas)
        self.video_label.configure(image=photo, text="")
        self.video_label.image = photo

        self.root.after(70, lambda: self._crt_transition_step(step + 1, total_steps))

    # --- background thread: reads camera + runs detection, never touches Tk widgets directly ---
    def _video_worker(self):
        self.cap = cv2.VideoCapture(PHONE_URL)
        if not self.cap.isOpened():
            print("ERROR: could not open phone camera feed.")
            self.root.after(0, lambda: self.lbl_hunt_status.configure(
                text="CAMERA ERROR - CHECK IP/WIFI", text_color="#FF5555"))
            return

        while not self.video_thread_stop.is_set():
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            frame = cv2.resize(frame, (900, 650))

            if self.hunt_state == "CALIBRATING":
                gray = get_gray(frame)
                self.calib_frames_buffer.append(gray)
                elapsed = time.time() - self.calib_start_time
                remaining = max(0.0, AUTO_CALIBRATION_SECONDS - elapsed)

                display = frame.copy()
                cv2.putText(display, f"CALIBRATING... KEEP PLATE EMPTY ({remaining:.1f}s)",
                            (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
                self._publish_frame(display)

                if elapsed >= AUTO_CALIBRATION_SECONDS:
                    if self.calib_frames_buffer:
                        self.background_gray = np.median(
                            np.stack(self.calib_frames_buffer, axis=0), axis=0).astype(np.uint8)
                    self.calib_frames_buffer = []
                    self.hunt_state = "SCANNING"

            elif self.hunt_state in ("SCANNING", "LOCKED"):
                display = frame.copy()
                result = detect_pappadam(frame, self.background_gray)

                if result is not None:
                    (cx, cy), radius, circularity = result
                    draw_crosshair(display, cx, cy, radius)
                    label = "TARGET LOCKED" if self.hunt_state == "LOCKED" else "PAPPADAM DETECTED"
                    cv2.putText(display, label, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    self.lock_center_history.append((cx, cy))
                    if len(self.lock_center_history) > LOCK_STABLE_FRAMES:
                        self.lock_center_history.pop(0)

                    if len(self.lock_center_history) == LOCK_STABLE_FRAMES and self.hunt_state != "LOCKED":
                        xs = [p[0] for p in self.lock_center_history]
                        ys = [p[1] for p in self.lock_center_history]
                        stable = (max(xs) - min(xs) <= LOCK_MOVE_TOLERANCE) and \
                                 (max(ys) - min(ys) <= LOCK_MOVE_TOLERANCE)
                        if stable:
                            self.hunt_state = "LOCKED"
                            self.root.after(0, self._fire_pluck_sequence)
                else:
                    self.lock_center_history = []
                    if self.hunt_state != "PLUCKING":
                        self.hunt_state = "SCANNING"
                    cv2.putText(display, "SCANNING FOR PAPPADAM...", (15, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2)

                self._publish_frame(display)

            else:
                # INTRO / TRANSITION / PLUCKING / RETURNING: video panel is being driven
                # by the GUI-thread animations above, just keep the capture buffer draining.
                pass

            time.sleep(0.01)

        if self.cap:
            self.cap.release()
            self.cap = None

    def _publish_frame(self, bgr_frame):
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        with self.latest_frame_lock:
            self.latest_display_frame = rgb

    def update_video_frame(self):
        if self.hunt_state in ("SCANNING", "LOCKED", "CALIBRATING"):
            with self.latest_frame_lock:
                frame = self.latest_display_frame
            if frame is not None:
                img = Image.fromarray(frame).resize(VIDEO_DISPLAY_SIZE)
                photo = ImageTk.PhotoImage(img)
                self.video_label.configure(image=photo, text="")
                self.video_label.image = photo

        if self.hunting_active:
            self.gui_update_job = self.root.after(30, self.update_video_frame)

    # --- called on the GUI thread once the target has held steady for LOCK_STABLE_FRAMES ---
    def _fire_pluck_sequence(self):
        if not self.hunting_active:
            return

        self.hunt_state = "PLUCKING"
        self.lbl_hunt_status.configure(text="TARGET LOCKED - PLUCKING...", text_color="#00FF88")

        def do_unpluck():
            self.hunt_state = "RETURNING"
            self.lbl_hunt_status.configure(text="RETURNING TO HOME...", text_color="#FFCC00")
            self.animate_pose(self.unpluck_coords, duration=2.0, on_complete=resume_scanning)

        def resume_scanning():
            self.lock_center_history = []
            if self.hunting_active:
                self.hunt_state = "SCANNING"
                self.lbl_hunt_status.configure(text="SCANNING...", text_color="#00CFFF")

        # crush sound plays the instant the gripper starts closing (see actuate_gripper)
        self.animate_pose(self.pluck_coords, duration=2.0,
                          on_complete=lambda: self.root.after(400, do_unpluck),
                          play_crush_sound=True)

    def on_close(self):
        self.stop_hunting()
        if self.ser and self.ser.is_open:
            try:
                self.send_cmd("P:OFF")
                self.ser.close()
            except Exception:
                pass
        self.root.destroy()

    # ================================================================
    # (unchanged) manual jog UI
    # ================================================================
    def create_slider(self, parent, label_text, f, t, prefix, invert=False, smooth=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=15, pady=12)

        lbl_frame = ctk.CTkFrame(row, fg_color="transparent")
        lbl_frame.pack(fill="x", pady=(0, 5))

        lbl = ctk.CTkLabel(lbl_frame, text=label_text, font=("Segoe UI", 13), text_color="#AAAAAA")
        lbl.pack(side="left")

        val_lbl = ctk.CTkLabel(lbl_frame, text=str(f), font=("Segoe UI", 14, "bold"), text_color="#FFFFFF")
        val_lbl.pack(side="right")

        initial_val = t if invert else f
        current_val = [initial_val]
        target_val = [initial_val]
        is_smoothing = [False]

        def smooth_loop():
            if current_val[0] == target_val[0]:
                is_smoothing[0] = False
                return

            step = 1 if target_val[0] > current_val[0] else -1
            if abs(target_val[0] - current_val[0]) <= 1:
                current_val[0] = target_val[0]
            else:
                current_val[0] += step

            self.send_cmd(f"{prefix}:{current_val[0]}")
            self.root.after(15, smooth_loop)

        def on_slide(v):
            val = int(v)
            val_lbl.configure(text=str(val))
            sent_val = t - (val - f) if invert else val

            if smooth:
                target_val[0] = sent_val
                if not is_smoothing[0]:
                    is_smoothing[0] = True
                    smooth_loop()
            else:
                self.send_cmd(f"{prefix}:{sent_val}")

        s = ctk.CTkSlider(row, from_=f, to=t, command=on_slide, state="disabled",
                          button_color="#FFFFFF", button_hover_color="#CCCCCC",
                          progress_color="#FFFFFF", fg_color="#000000", height=14)
        s.set(f)
        s.pack(fill="x", pady=(5, 0))

        def set_and_trigger(new_val):
            s.set(new_val)
            on_slide(new_val)

        setattr(self, f"set_{prefix}", set_and_trigger)
        setattr(self, f"s_{prefix}", s)

    # --- SAVE PRESET FUNCTIONS ---
    def save_pluck(self):
        self.pluck_coords = {
            'A1': int(self.s_A1.get()), 'A2': int(self.s_A2.get()),
            'A3': int(self.s_A3.get()), 'A4': int(self.s_A4.get()), 'G': int(self.s_G.get())
        }
        self.lbl_pluck.configure(text="[Saved!]", text_color="#FFFFFF")
        print(f"✅ Pluck Saved: {self.pluck_coords}")

    def save_unpluck(self):
        self.unpluck_coords = {
            'A1': int(self.s_A1.get()), 'A2': int(self.s_A2.get()),
            'A3': int(self.s_A3.get()), 'A4': int(self.s_A4.get()), 'G': int(self.s_G.get())
        }
        self.lbl_unpluck.configure(text="[Saved!]", text_color="#FFFFFF")
        print(f"✅ Unpluck Saved: {self.unpluck_coords}")

    # --- RUN PRESET FUNCTIONS (manual buttons - unchanged behavior, now crush sound on pluck) ---
    def run_pluck(self):
        if self.pluck_coords:
            self.animate_pose(self.pluck_coords, duration=2.0, play_crush_sound=True)
        else:
            messagebox.showwarning("Empty", "Please 'Save Pluck' position first!")

    def run_unpluck(self):
        if self.unpluck_coords:
            self.animate_pose(self.unpluck_coords, duration=2.0)
        else:
            messagebox.showwarning("Empty", "Please 'Save Unpluck' position first!")

    # --- SEQUENCED ANIMATOR (Arm first, then Gripper) ---
    def animate_pose(self, targets, duration, on_complete=None, play_crush_sound=False):
        arm_steps = 50
        arm_delay_ms = int((duration / arm_steps) * 1000)
        arm_keys = ['A1', 'A2', 'A3', 'A4']

        starts = {
            'A1': int(self.s_A1.get()), 'A2': int(self.s_A2.get()),
            'A3': int(self.s_A3.get()), 'A4': int(self.s_A4.get()), 'G': int(self.s_G.get())
        }

        arm_increments = {k: (targets[k] - starts[k]) / arm_steps for k in arm_keys if k in targets}

        controls_to_disable = ["s_A1", "s_A2", "s_A3", "s_A4", "s_G", "btn_save_pluck", "btn_run_pluck",
                                "btn_save_unpluck", "btn_run_unpluck"]
        for key in controls_to_disable:
            if hasattr(self, key):
                getattr(self, key).configure(state="disabled")

        def step_arm(current_step):
            if current_step <= arm_steps:
                for key in arm_keys:
                    if key in targets:
                        getattr(self, f"set_{key}")(int(starts[key] + arm_increments[key] * current_step))
                self.root.after(arm_delay_ms, step_arm, current_step + 1)
            else:
                if 'G' in targets:
                    actuate_gripper()
                else:
                    finish_animation()

        def actuate_gripper():
            target_g = targets['G']
            start_g = starts['G']

            if play_crush_sound:
                play_sound(CRUSH_SOUND_PATH)

            getattr(self, "set_G")(target_g)

            time_to_close_ms = abs(target_g - start_g) * 15
            self.root.after(time_to_close_ms + 100, finish_animation)

        def finish_animation():
            # while auto-hunting, keep controls locked - stop_hunting() re-enables them
            if not self.hunting_active:
                for key in controls_to_disable:
                    if hasattr(self, key):
                        getattr(self, key).configure(state="normal")
            print("✅ Sequenced Movement Complete!")
            if on_complete:
                on_complete()

        step_arm(1)

    # --- COM PORT DETECTION ---
    def get_available_ports(self):
        return list(serial.tools.list_ports.comports())

    def refresh_ports(self):
        ports = self.get_available_ports()

        if not ports:
            self.port_menu.configure(values=["No ports found"])
            self.port_var.set("No ports found")
            self.port_lookup = {}
            self.lbl_conn_status.configure(
                text="⚠ No devices detected — check the USB cable/drivers",
                text_color="#777777"
            )
            return

        self.port_lookup = {}
        display_values = []
        for p in ports:
            has_desc = p.description and p.description.lower() != "n/a"
            label = f"{p.device} - {p.description}" if has_desc else p.device
            self.port_lookup[label] = p.device
            display_values.append(label)

        self.port_menu.configure(values=display_values)

        if self.port_var.get() not in display_values:
            self.port_var.set(display_values[0])

        if not self.is_connected():
            self.lbl_conn_status.configure(
                text=f"✓ {len(ports)} port(s) detected",
                text_color="#4CD964"
            )

    def is_connected(self):
        return bool(self.ser and self.ser.is_open)

    def toggle_connection(self):
        selected = self.port_var.get()

        if selected in ("Scanning...", "No ports found"):
            messagebox.showwarning("No Port", "No COM port selected. Click ⟳ to scan again.")
            return

        device = self.port_lookup.get(selected, selected)

        try:
            self.ser = serial.Serial(device, 115200, timeout=0.05)
            self.pwr_btn.configure(state="normal")
            self.lbl_conn_status.configure(text=f"● Connected on {device}", text_color="#FFFFFF")
            messagebox.showinfo("USB", f"Connected to Robot on {device}!")
        except Exception as e:
            self.lbl_conn_status.configure(text=f"✗ Connection failed: {e}", text_color="#FF5555")
            messagebox.showerror("Error", str(e))

    def toggle_power(self):
        self.is_powered = not self.is_powered
        st = "normal" if self.is_powered else "disabled"

        self.pwr_btn.configure(
            text="SYSTEM ACTIVE" if self.is_powered else "ENABLE SYSTEM",
            fg_color="#FFFFFF" if self.is_powered else "#111111",
            text_color="#000000" if self.is_powered else "#555555",
            hover_color="#E5E5EA" if self.is_powered else "#222222"
        )
        self.send_cmd("P:ON" if self.is_powered else "P:OFF")

        for a in ["bl", "br", "s_A1", "s_A2", "s_A3", "s_A4", "s_G"]:
            if hasattr(self, a): getattr(self, a).configure(state=st)

        if self.is_powered:
            self.btn_save_pluck.configure(state="normal")
            self.btn_save_unpluck.configure(state="normal")
            if self.pluck_coords: self.btn_run_pluck.configure(state="normal")
            if self.unpluck_coords: self.btn_run_unpluck.configure(state="normal")
        else:
            self.btn_save_pluck.configure(state="disabled")
            self.btn_save_unpluck.configure(state="disabled")
            self.btn_run_pluck.configure(state="disabled")
            self.btn_run_unpluck.configure(state="disabled")
            if self.hunting_active:
                self.stop_hunting()

    def send_cmd(self, cmd):
        if ":" in cmd:
            pre, val = cmd.split(":")
            if self.last_val.get(pre) == val: return
            self.last_val[pre] = val
        if self.ser and self.ser.is_open:
            self.ser.write((cmd + '\n').encode())


if __name__ == "__main__":
    root = ctk.CTk()
    app = RobotArmPro(root)
    root.mainloop()
