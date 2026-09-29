# Tokyo City Food Delivery

Tokyo Delivery is a mode of the FH6 Auto dashboard. It runs through the same
`LocalPanel → bridge.py → Controller` worker as the farming modes, with one input
owner, F7 stop handling, process and foreground checks, display checks, and the
cloud-sync gate. The mode uses a virtual Xbox controller for job menus and
driving. It does not buy cars or spend Skill Points.

## Set up

1. Install AutoHotkey v2 and 64-bit Python 3.12, then run **Setup FH6 Auto.cmd**.
   Setup installs the pinned `vgamepad==0.1.0` package.
2. Ensure the ViGEmBus virtual-controller driver is installed and healthy on
   Windows. A `vgamepad` source install may launch a driver installer, but the
   package smoke check does not independently verify the driver. See the
   [vgamepad Windows setup](https://github.com/yannbouteiller/vgamepad#installation)
   and [ViGEmBus releases](https://github.com/nefarius/ViGEmBus/releases).
3. Use the English game interface at 1920 × 1080 and keep the game in the
   foreground. Finish an unfinished farming goal or purchased-car checkpoint
   before changing modes.
4. Select **Tokyo Delivery**, enter 1–10,000 shifts, and press **F6**. **F7**
   releases the controller and requests a stop. From the repository root you
   may also launch the panel with
   `Forza-Horizon-6-Wheelspin-Macro-main/Main.ahk --tokyo-delivery 1`.

The panel displays verified completed shifts, remaining shifts, stage, and
active run time. The requested count is retained when an unfinished delivery
checkpoint is resumed.

## What the worker verifies

The worker observes home, free roam, map, job intro, Solo, active shift, and
summary screens. It identifies the Tokyo job on the map before requesting fast
travel. An input intent is saved before Solo, Continue, fast travel, or the next
shift is submitted. If a slow transition leaves acceptance uncertain, the
worker keeps that intent and does not submit the button again.

During a shift, the worker uses the virtual controller to open ANNA and enable
Auto Drive only when that exact option is visible. The enable intent is saved
before input and is never repeated if acceptance is uncertain. The worker then
checks the native Auto Drive status, timer and route distance. During a timed
destination leg where ANNA does not offer Auto Drive, it can follow the visible
road chevrons with short controller pulses. This requires a clear, continuous
route cue and stops on lost visibility, excess speed, or lack of route progress.
On the verified local game setup, Auto-Steering and Assisted Braking can be
enabled in the game's Difficulty settings. A separate local session record
allows the worker to use bounded throttle pulses on a timed delivery when those
settings have been visibly verified. This setting is specific to that game
session; the release does not enable it by default.
If the game asks for a route or distance stops improving, it releases input and
retains the checkpoint. Near the parking trigger, braking and small approach inputs have
checkpointed limits. An unexpected screen or unverified result also stops
driving input.

Each shift has three drop-offs. ANNA may change the route after a delivery;
the worker accepts a new waypoint when ANNA confirms it or when two fresh
distance readings confirm a route recalculation.

A delivery is recorded only when the native summary shows positive Shift Stars,
an advancing Shift Progress fraction, and no failed result. The worker continues
at 1/3 and 2/3; it counts a shift only at a verified 3/3 summary. Credit or
job-progress text alone is not a completed shift.

## Saved state and recovery

Delivery state is stored in `runs/tokyo_delivery.json`; its recovery copy is
`runs/tokyo_delivery.json.bak`. Both are local runtime files and are excluded
from Git and release archives. Keep them intact when stopping or restarting.
The farming goal and car checkpoints remain separate.

If a saved menu input is uncertain, inspect the current game screen before
resuming. A later verified destination screen can reconcile the saved intent;
repeated starts do not replay the uncertain button. If the game is still at the
original menu, resolve the game state manually and then resume the saved target.
Do not clear the checkpoint to force another submission.

The standalone `fh6.tokyo_delivery_control` module is a developer diagnostic
and also owns controller input. Run it only after the dashboard worker is
stopped.

## Validation status

The route and checkpoint logic has portable synthetic tests. Local saved-frame
checks exercise screen and route recognition. One live shift reached a native
3/3 summary with 4 Shift Stars on September 29, 2026; other route, parking,
and seasonal variants remain unverified. ANNA Auto
Drive can stop short or become obstructed, and the guided route follower remains
experimental. The worker requires fresh progress instead of assuming it reached
the waypoint. Use the Activity and Recovery views to inspect what the current
game actually proved.
