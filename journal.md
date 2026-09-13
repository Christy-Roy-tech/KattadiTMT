---
title: "The Pappadam Plucker Journal"
layout: default
---

# We Built a Robot to Crush Pappadam. It Fought Us the Whole Way.

*A KattadiTMT build story — TinkerHub Useless Projects 3.0*

![Pappadam Plucker Front Page](./assets/front_page.png)

There is no shortage of real problems in the world. We picked none of them. Instead, we
decided that the two extra seconds it takes to crush a pappadam by hand before mixing it
into rice and curry was an injustice worth solving with a 6-axis robotic arm, a phone
camera, computer vision, and — eventually — a cowboy-themed soundtrack.

This is the story of how that went.

---

## Day 1 — "It Detects Everything As Pappadam"

We already had a 6-axis arm sitting around from an earlier project, so the hardware side
felt like a head start. The plan was simple: point a phone camera at a plate, use OpenCV
to spot a pappadam, and have the arm crush it.

The first version of the detector used plain color filtering — "if it's cream-and-yellow,
it's probably a pappadam." It was not probably a pappadam. It was hands, wood, walls, and
at one point what we're fairly sure was a wall socket. The HSV range we'd picked accepted
almost anything under normal lighting.

**Learning #1:** color alone is never enough for real-world object detection. You need
something that captures *what changed*, not just *what color it is*.

**The fix:** background subtraction. Capture the empty plate first, then only look at
pixels that changed from that reference. Suddenly the detector stopped hallucinating
pappadams out of furniture.

> 🖼️ *Insert: screenshot of the "detects everything" mask next to the fixed version*

## Day 2 — The Case of the Missing Keypress

Once background subtraction was in, we needed to calibrate it — press a key with the
plate empty, then place the pappadam. Except... it never seemed to calibrate. Turns out
`cv2.waitKey()` only listens when its own window has focus, and we kept typing into the
terminal instead of clicking the video window first.

The fix that actually mattered here wasn't clever, it was just removing the human step
entirely: the app now auto-calibrates for 2.5 seconds the moment it starts, using the
*median* of many frames instead of one single (possibly glare-ruined) snapshot. No more
clicking the right window at the right time.

## Day 3 — The Circularity Crisis

This was the one that nearly broke us.

The detector was finding *something* the right size and roughly the right shape, but
kept rejecting it — circularity scores like `0.05`, `0.06`, `0.14`, when we needed at
least `0.4`. A pappadam is basically a circle. Why did the math think it was a straight
line?

We added debug logging that printed out exactly why the best candidate got rejected
every second, and stared at the numbers until it clicked: **a pappadam is not smooth.**
All those little dimples, bubbles, and bumps on its surface show up as gaps and notches
in the detection mask, turning a clean circular outline into something jagged. Circularity
is calculated from perimeter — and a jagged perimeter is a *much* longer perimeter for
the same area, which tanks the score even for an object that's obviously round to a
human eye.

**The fix:** measure circularity against the *convex hull* of the shape instead of its
raw, texture-noisy outline. The hull smooths right over the dimples. Circularity scores
jumped from `0.05` to `0.6–0.8` on the very next test — same pappadam, same lighting,
completely different number, just because we were measuring it correctly.

> 🎬 *Insert: the failed_attempt_demo.mp4 clip here — this is the debugging phase it
> came from.*

## Day 4 — "Other Parts" Kept Getting Detected

With circularity fixed, a new problem showed up: sometimes a tool on the workbench, or a
reflection off the plate's plastic lid, would get merged into the same blob as the
pappadam, throwing off the shape checks in the other direction.

**The fix:** at startup, drag a box around just the plate. Everything outside it stops
existing as far as the detector is concerned. Simple, a little inelegant, extremely
effective — sometimes the right fix isn't a smarter algorithm, it's just not looking at
the parts of the picture you don't care about.

## Day 5 — Building the Body

While the vision side was being debugged, the hardware side was evolving in parallel.
The first power module revision ran off a 2S battery pack through a small buck converter:

![Power module v1](./assets/power_module_wiring_1.png)

It worked, but the wiring was tight and the power margin was thinner than we wanted. The
second revision moved to a 3S pack, a proper 3A buck converter, and a real DC barrel
connector instead of loose leads:

![Power module v2](./assets/power_module_wiring_2.png)

**Learning:** the first working version of anything is rarely the version you keep. Both
the detector and the power module went through a "make it work" pass and then a
"make it work *properly*" pass.

## Day 6 — Making It Permanent

Small but important fix: the arm's saved Pluck and Unpluck coordinates were living only
in memory. Close the app, lose the calibration. We added persistence to
`coordinates.txt` / `saved_coordinates.json` so calibration only has to happen once, ever
— confirmed working:

```
✅ Pluck Saved: {'A1': 172, 'A2': 52, 'A3': 0, 'A4': 0, 'G': 0}
✅ Unpluck Saved: {'A1': 0, 'A2': 9, 'A3': 0, 'A4': 0, 'G': 0}
```

## Day 7 — Going Full Cinematic

At this point detection was solid and the arm was reliable, so naturally we decided the
project needed a splash screen, a VHS-static transition, a detective-noir HUD with a
scanline sweep and a blinking REC light, a cowboy-themed soundtrack, a custom
target-lock graphic, and a celebration video — because if you're going to build an
unnecessary robot, you should not stop at "functional."

The final sequence: splash → press any key → VHS transition → live tactical camera feed
→ silent scanning (cowboy theme looping) → zoom-in lock with aim overlay → celebration
clip → pluck → crunch → return home → 5-second countdown → loop forever.

> 🎬 *Insert: full end-to-end run once recorded*
> 🖼️ *Insert: GIF of the zoom-to-lock moment — this is the most visually striking part,
> worth its own GIF*

![Live build session at the venue](./assets/build_venue_photo.jpg)

*Debugging the detector live at the venue — the laptop screen shows the actual camera
feed and code side by side, arm and bowl sitting right there on the desk.*

## Day 8 — It Actually Works

[Final demo](./assets/final_demo.mp4) — the full cycle, recorded.

*(fill in — what it felt like watching it complete a full cycle for the first time)*

---

## Team Contributions

- **Mekha Rachel** — Python development, OpenCV detection pipeline (and all of its
  debugging), CustomTkinter control interface, serial communication, cinematic app
  integration, documentation.
- **Christy Roy** — Robot arm construction, mechanical setup, servo wiring, power module
  design and revisions, ESP32/PCA9685 firmware, arm calibration, physical testing.

## What We'd Do Differently

*(fill in — what surprised you, what you'd tell a team starting this from scratch)*

---

Made with ❤️, background subtraction, and an unreasonable amount of confidence at
TinkerHub Useless Projects 3.0.
