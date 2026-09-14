# Local edition — FH6 Mission Control

Open **Start Local FH6.cmd**, **Main.ahk**, or the parent's **Start FH6 Auto.cmd**.
They open one AutoHotkey dashboard backed by the parent's Python modules.

The main input is now the desired number of **saved Super Wheelspins**. The target
planner refills actual SP to 999 with Mega V6 (155439962), then converts up to
47 cars, capped by the remaining target. It buys each Mad Mike once,
selects it through **My Cars → Recently Added**, verifies the six mastery claims,
and returns to Car Collection. There is no Designs & Paints detour.

The Modules tab exposes farm/setup, buying, mastery, return navigation and
recognition separately. It includes a challenge-settings dialog. F6 starts; F7
stops. One shared worker lock prevents modules from sending simultaneous inputs.

The existing car checkpoint, ledger, and history are retained. The target
planner has its own checkpoint and adopts a previously purchased car before
buying another. Reward accounting is idempotent after interruptions.

The Favorites checkbox is calibrated on/off with and without focus. Selecting the
sole Favorite Subaru passed a live test; buying resets all filters before selecting
the newest Mazda. Missing filter calibration blocks the mission before buying.
Cloud sync automatically watches completion and verifies stable game UI afterward.
An observed 100% is only a milestone: the dialog must close before release. A
normal worker-owned Start/Continue flow can establish startup readiness without
bypassing sync. Attaching to a visible menu or waiting alone is insufficient.
Conflicts remain held. F7 also stops sync waits. The panel uses square corners,
rectangular controls, monospaced text and a live mission time-window display.
Full parity with the original repository is also not complete. See the parent's
**[MODULES.md](../MODULES.md)** for the exact implemented and pending features.
The original repository modules, entry-point backup and MIT license are retained.
