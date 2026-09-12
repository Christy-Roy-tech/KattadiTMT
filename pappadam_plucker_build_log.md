# Autonomous Pappadam Plucker — Build Log
**Team:** KattadiTMT — TinkerHub Useless Projects 3.0

Keep this updated as you complete each step of the build guide. Copy the finished
sections straight into your submission README when you're done.

---

## Problem / Solution (from your template)
> While eating rice, we often have to crush pappadam first before mixing it with
> rice and curry. This robotic arm helps us crush pappadam before eating.

**Solution:** A 6-axis robotic arm watches a plate through a phone camera. When it
spots a pappadam, it locks a targeting crosshair on it, moves to a pre-taught
"pluck" position, crushes it, plays a crunch sound effect, and returns home —
fully hands-free.

---

## Technologies / Components Used

**Software**
- Python 3 — main application language
- `customtkinter` — dark-glass control panel UI
- `OpenCV` (`opencv-python`) — camera capture + pappadam detection
- `NumPy` — image math for the background-subtraction detector
- `Pillow` (PIL) — image handling for the intro image, CRT transition, and embedding video frames in the Tkinter UI
- `pygame` — plays the crushing sound effect
- `pyserial` — USB serial link from the control panel to the ESP32
- IP Webcam (Android app) — turns a phone into a Wi-Fi camera source

**Hardware**
- 6-axis robotic arm (reused from an earlier project)
- ESP32 microcontroller running the arm firmware
- Adafruit PCA9685 PWM servo driver (16-channel)
- Servos: MG995 (base rotation, shoulder, wrist pitch), SG90 (elbow, wrist roll, gripper)
- ESP8266-based glove controller (optional manual override input, via ESP-NOW)
- Phone (any Android device with IP Webcam installed), mounted to view the plate

---

## How Detection Works
Instead of matching pappadam by color alone (too easy to confuse with skin, wood,
walls, etc.), the detector:
1. Captures ~2.5 seconds of the **empty plate** as a reference "background" (median of many frames, so one bad frame doesn't wreck it).
2. Compares each new frame against that background — anything that changed is a candidate object.
3. Filters candidates by circularity, aspect ratio, and convex-hull solidity (rejects hands, shadows, non-round objects).
4. Requires the detected center to stay within a small pixel radius for ~15 consecutive frames before it's considered "locked" — this debounce stops a single noisy frame from firing the arm.

## How the Pluck Sequence Works
1. Operator manually jogs the arm to a pluck position (over the plate, gripper closed enough to crush) and clicks **Save Pluck**.
2. Operator jogs to a safe home/away position and clicks **Save Unpluck**.
3. Clicking **Start Hunting** runs: intro image → CRT power-off transition → auto-calibration → live scanning.
4. On a stable lock, the arm animates to the saved pluck pose; the crush sound fires the instant the gripper starts closing.
5. After a short pause, the arm animates back to the saved unpluck pose, and scanning resumes automatically.

---

## Build Log

### Session 1 — [fill in date]
- [ ] Camera-only detector tested standalone — works? Y/N, notes:
- [ ] Arm-only control panel tested standalone — works? Y/N, notes:
- [ ] Assets ready (intro image, crush sound)?

### Session 2 — [fill in date]
- [ ] Merged app runs, intro + transition display correctly
- [ ] Calibration completes without errors
- [ ] First successful auto-lock
- [ ] Detection tuning notes (what you changed, why):

### Session 3 — [fill in date]
- [ ] Full pluck → crush sound → return cycle confirmed
- [ ] Repeatability tested (how many runs, success rate)
- [ ] Final tuning values used:

---

## Screenshots (add at least 3)
![Camera detection working](add-screenshot-here.png)
*Caption: crosshair locked onto a pappadam during standalone detector testing*

![Arm control panel](add-screenshot-here.png)
*Caption: the dark-glass control UI with pluck/unpluck presets saved*

![Full system running](add-screenshot-here.png)
*Caption: the integrated app mid-hunt, showing the military-HUD scanning view*

## Workflow Diagram
*(Use the state-machine diagram from earlier in the build conversation: Intro → CRT transition → Scanning → Target locked → Pluck triggered → Return to home → back to Scanning)*
