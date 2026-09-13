<img width="1280" height="640" alt="git (1)" src="https://github.com/user-attachments/assets/8920b256-2ba8-4988-b824-5351134eb4bd" />


# Pappadam Plucker

![Pappadam Plucker Front Page](./assets/front%20page%20(1).png)

> An unnecessarily advanced robotic system that detects a pappadam, locks onto it, and crushes it before it can peacefully join your rice and curry.

## Basic Details

### Team Name: KattadiTMT: Ith Kaatath Adilla

### Team Members
- Team Lead: Mekha Rachel — Saintgits College of Engineering
- Member 2: Christy Roy — Saintgits College of Engineering

### Project Description

We are KattadiTMT, presenting the **Autonomous Pappadam Plucker**: a 6-axis robotic arm that automates the deeply exhausting task of crushing pappadam before eating.

The system uses an Android phone as an overhead camera, OpenCV-based pappadam detection, a tactical crosshair interface, and a robotic arm with saved coordinates. Once the pappadam is locked onto, the arm moves to a pre-taught crushing position, plays a dramatic crunch sound, and returns safely home.

### The Problem (that doesn't exist)

While eating rice, we often have to crush pappadam before mixing it with rice and curry. This robotic arm helps crush pappadam before eating.

More importantly, it protects humanity from the unbearable inconvenience of using its own fingers.

### The Solution (that nobody asked for)

A 6-axis robot arm watches a plate through a phone camera like a highly overqualified surveillance system.

1. The phone streams a live view of the plate to Python through IP Webcam.
2. The software learns what the empty plate looks like during calibration.
3. When a pappadam appears, the system checks whether the new object is sufficiently round and pappadam-like.
4. A military-style interface announces `PAPPADAM DETECTED - TARGET LOCKED` and draws a crosshair at the pappadam’s centre.
5. The robotic arm moves smoothly to a pre-saved pluck position.
6. The gripper/crusher closes, a crunch sound plays, and the pappadam is eliminated.
7. The arm returns to its safe home position, ready for its next extremely important mission.

## Technical Details

### Technologies/Components Used

#### For Software
- Python 3 — main application language
- CustomTkinter — dark-glass robot control interface
- OpenCV (`opencv-python`) — phone-camera capture, calibration, background subtraction, object detection, and tactical crosshair rendering
- NumPy — image-processing calculations
- Pillow (`PIL`) — splash-image handling, CRT-style transition, and Tkinter image rendering
- Pygame — pappadam-crushing sound effect playback
- PySerial — USB serial communication from laptop to ESP32
- IP Webcam (Android app) — turns the phone into a Wi-Fi camera source
- VS Code — development environment
- GitHub — code, documentation, build log, and project story

#### For Hardware
- 6-axis robotic arm, reused and upgraded from an earlier project
- ESP32 microcontroller running the arm firmware
- Adafruit PCA9685 16-channel PWM servo driver
- MG995 servo motors for base rotation, shoulder, and wrist pitch
- SG90 servo motors for elbow, wrist roll, and gripper
- Robotic gripper/crusher mechanism
- ESP8266-based glove controller for optional ESP-NOW manual override
- Android phone running IP Webcam, mounted above the plate
- Custom power module using battery packs, BMS boards, buck converters, rocker switch, and DC barrel connector
- A plate and one unfortunate pappadam

## Implementation

### Installation

```powershell
# Create and activate a project environment
uv venv .venv --python 3.14
.\.venv\Scripts\Activate.ps1

# Install Python requirements
uv pip install opencv-python numpy customtkinter pyserial pillow pygame
```

### Run

1. Power the robot arm using its external servo power system.
2. Connect the ESP32 to the laptop using USB.
3. Connect the Android phone and laptop to the same Wi-Fi network or hotspot.
4. Open IP Webcam on the phone and start the video server.
5. Copy the phone camera URL ending in `/video`.
6. Update the camera URL in the Python file:

```python
PHONE_URL = "http://192.168.132.198:808//video"
```

7. Run the full cinematic application:

```powershell
python kattadi_app.py
```

8. Keep the plate empty during the 2.5-second background calibration.
9. In the control panel, select the correct COM port, click **Connect**, then **Enable System**.
10. Manually position the arm over the plate and click **Save Pluck**.
11. Move the arm to a safe return position and click **Save Unpluck**.
12. Start hunting and place a pappadam in the tray.

## How Detection Works

Colour-only detection was rejected because skin, wood, walls, and random objects can also look pappadam-coloured. Instead, the detector follows these steps:

1. It captures about 2.5 seconds of the empty plate and calculates a median background image.
2. Each new phone-camera frame is compared against that background.
3. Only newly introduced objects become possible targets.
4. A cream/yellow colour filter removes clearly unrelated objects.
5. Contour filters check minimum area, circularity, aspect ratio, and convex-hull solidity.
6. The pappadam centre must remain stable for several frames before the system declares a target lock.

This reduces false targets caused by hands, plate reflections, shadows, rectangular objects, and random background clutter.

## How the Full Sequence Works

1. The operator manually controls and calibrates each robot joint from the dark-glass control panel, and saves **Pluck** (over the crushing area) and **Unpluck** (safe home position) presets.
2. Both presets are written to disk immediately (`coordinates.txt` / `saved_coordinates.json`), so they survive an app restart — the operator only has to calibrate once.
3. Launching the app shows a full-screen splash image with a slowly blinking **"PRESS ANY KEY TO CONTINUE"** prompt.
4. A key press or click plays a short VHS/static transition effect, like an old CRT monitor powering on.
5. The live phone-camera feed appears inside a detective/tactical-style HUD (scanline sweep, corner brackets, a blinking REC indicator, live clock) — deliberately with no drawn crosshair or green markers.
6. A background theme plays on loop while the system silently scans for a pappadam.
7. Once a target holds steady for enough consecutive frames, the view smoothly zooms in on it and overlays a custom aim graphic, with a "TARGET ACQUIRED" banner.
8. A short celebration video plays.
9. In the background, the saved Pluck coordinates are sent to the arm; the crunch happens as the gripper closes.
10. After a short pause, the saved Unpluck coordinates return the arm to home.
11. After 5 seconds showing "MISSION ACCOMPLISHED", the whole app resets to the splash screen and loops, ready for the next pappadam.

### Detection Region (ROI)
On first launch, the app asks you to drag a rectangle tightly around the plate. Everything outside that box is ignored for both calibration and detection — this was added specifically to stop workbench clutter (tools, wires, reflections) from ever being mistaken for a pappadam. The selection is saved (`saved_roi.json`) so you only do it once per camera position.

## Project Documentation

### Screenshots

![Pappadam target](./assets/pappadam_labeled.png)

*The pappadam target placed inside the detection tray before the crushing mission begins.*


*The OpenCV detector locks onto the pappadam and draws a crosshair at its calculated centre.*

*The dark-glass control interface is implemented in the integrated Python application.*

### Workflow Diagram

![Workflow Diagram](./assets/workflow_diagram.svg)

*Splash screen → VHS transition → empty-plate calibration → silent scanning (cowboy theme) → target lock with zoom + aim overlay → celebration video → pluck + crush → return home → 5-second reset → loop forever.*

## Hardware Documentation

### Circuit & Power Module

![Power module version 1](./assets/power_module_wiring_1.png)

*First power-module build using a DC-DC buck converter, rocker switch, 2S BMS, and motor-output wiring in a repurposed plastic container.*

![Power module version 2](./assets/power_module_wiring_2.png)

*Second power-module revision with a 3S BMS, 3A buck converter, DC barrel connector, and cleaner cable routing.*

### Build Photos

![Final build model](./assets/build_image.jpeg)

*The completed Autonomous Pappadam Plucker ready for testing.*

![Live build session](./assets/build_venue_photo.jpg)

*Debugging the detector live at the venue — the laptop screen shows the actual camera feed and code side by side.*


## Build Log

### Session 1 — September 12, 2026
- Camera-only detector tested standalone: IP Webcam feed and background-calibration workflow tested.
- Arm-only control panel tested standalone: manual axes, COM-port scanning, saved pluck pose, and saved return pose implemented.
- Assets prepared: Intro splash screen ready; crush sound and final demo video pending.
- Main challenge: naive colour-only detection matched almost anything cream-coloured (skin, wood, walls) — switched to background subtraction instead.

### Session 2 — September 13, 2026
- Phone camera stream configured using IP Webcam; detector compares each live frame against a calibrated empty-plate background.
- Contour filters added for object area, circularity, aspect ratio, and solidity.
- Main challenge: raw contour circularity was unreliable — a pappadam's own dimpled texture makes its outline jagged, tanking the circularity score even on a correctly-detected blob.
- Fix: circularity is now measured against the convex hull's perimeter instead of the raw contour, which ignores that texture noise.
- Main challenge #2: workbench clutter (tools, wires, a curved plastic-lid reflection) occasionally got merged into the same blob as the pappadam.
- Fix: added a one-time "drag a box around the plate" region-of-interest step at startup — everything outside it is now ignored entirely.
- Result: detection locks reliably and repeatably on the actual pappadam.

### Session 3 — Integration
- Robot-arm control panel and vision system merged into a single application.
- Pluck/Unpluck coordinates are now saved to disk (`coordinates.txt` / `saved_coordinates.json`) instead of only living in memory, so calibration work survives an app restart.
- Confirmed working: saving a Pluck pose (`{'A1': 172, 'A2': 52, 'A3': 0, 'A4': 0, 'G': 0}`) and Unpluck pose (`{'A1': 0, 'A2': 9, 'A3': 0, 'A4': 0, 'G': 0}`) both persist correctly.
- Full cinematic experience built: splash screen → VHS transition → detective-style HUD scanning → zoom-and-lock with aim overlay → celebration video → pluck/crush/unpluck → 5-second reset loop.

### Session 4 — Final testing
- Full detection → target lock → pluck → crunch sound → return cycle: `[update after test]`
- Repeatability test: `[update number of runs and successful runs]`
- Final detection tuning values: `[update after final test]`
- Final improvements: `[update with final changes]`

## Project Demo

### Video

[Final demo video](./assets/final_demo.mp4)

*Shows empty-plate calibration, pappadam detection, crosshair target lock, robotic movement to the saved pluck position, crunch sound playback, and safe return to the home position.*

### Additional Demo

[Early Attempt Demo](https://github.com/Christy-Roy-tech/KattadiTMT/blob/main/assets/failed_attempt_demo.mp4)

*An early test of the full sequence. It is kept as evidence of the debugging process and will be followed by the final working demo.*

## Team Contributions

- **Mekha Rachel:** Python development, OpenCV pappadam detection, phone-camera integration, CustomTkinter control interface, robot serial communication, UI design, visual targeting system, and documentation.
- **Christy Roy:** Robot-arm construction, mechanical setup, servo wiring, power-module development, ESP32/PCA9685 setup, arm calibration, physical testing, and demo support.

---

Made with ❤️ at TinkerHub Useless Projects

![Static Badge](https://img.shields.io/badge/TinkerHub-24?color=%23000000&link=https%3A%2F%2Fwww.tinkerhub.org%2F)
![Static Badge](https://img.shields.io/badge/UselessProjects--26-26?link=https%3A%2F%2Ftinkerhub.org%2Fevents%2F1M8ORET9A1%2Fuseless-projects-3.0)
