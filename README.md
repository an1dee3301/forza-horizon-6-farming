# FH6 Auto — Mission Control

## Wheelspin Lab

The current dashboard now includes **Wheelspin Lab**. Choose SUPER or REGULAR,
enter the quantity, and begin with **Dry Run** and **Stop on unknown** enabled.
Every resolved screen and slot crop is durably committed to
`runs/wheelspin_lab.sqlite` before Collect or duplicate processing. Exact
year/manufacturer/model matching protects the versioned 45-car catalog.
Automatic sell/keep confirmations stay activation-gated until live calibration.

The completed 500-spin validation, including the full reward ledger, exact
verified sale credits, kept-car list, timing percentiles, failures, recovery
events, and audited safety incidents, is published in
[the September 19 Wheelspin operation report](docs/WHEELSPIN-OPERATION-2026-09-19.md).

Double-click **Start FH6 Auto.cmd** or **FH6 Auto.pyw**. Both open the same dashboard.
The downloaded repository's **Start Local FH6.cmd** opens it too. Run **Setup FH6
Auto.cmd** if Python dependencies are missing. AutoHotkey v2 is required.

Choose **Earn saved Super Wheelspins**, enter the number to earn, and press **F6**.
**F7** stops. Before funding each new batch, the program runs **Mega Farm V6**
(155439962) until the actual balance reaches **999 SP**, then converts up to
**47 cars**, capped by the remaining target and your SP reserve.
One Mad Mike Mazda costs **95,000 CR + 21 SP** and earns
one Super Wheelspin. The target means additional spins earned during this run.
Spins stay saved and cars stay in the garage.

Assist/difficulty and Skills HUD checks are retained for the whole mission,
including automatic worker restarts. A new mission or changed challenge profile
requires a new full check. After a game process changes or farm yield is unusually
low, only the frame-rate cap is rechecked. When the verified maxed Subaru mastery
screen is already open, the next farm skips the repeated trip through My Cars.

The purchase route is **Home → Collection Journal → buy → My Cars → Recently
Added → newest untouched Mad Mike → mastery → Car Collection**. Designs & Paints
is no longer part of the route. The final car returns to Car Collection too.

An existing purchased car is finished before a new car is bought. A separate
wheelspin-target checkpoint records rewards across multiple SP balances. Neither
an uncertain purchase nor a completed reward is deliberately repeated after a restart.

## Steam launch and crash backup

**Recovery → Open through Steam and restart after crashes** is enabled by default.
F6 launches FH6 through Steam when it is closed, then recognizes Start Game and
the selected Continue button. Steam must already be installed and signed in.
Startup waits up to five minutes; sign-in, update and unexpected dialogs are never
clicked. **Modules → Open game through Steam** selects a launch-only mode; press
F6 to open the game without starting the saved wheelspin target.

The default is **unlimited crash restarts** (limit **0**). Set 1–10 for a finite cap.
Delays increase from 15 to 30, 60, then 120 seconds. F7 cancels startup and retries.
The backup only closes the verified FH6 executable after detecting its crash;
menu and resource errors retain the saved step and retry after a short delay.
Purchase verification still blocks uncertain transactions. **Prioritize game focus**
brings the game forward during the mission; turn it off to stop on focus loss.
It never kills Steam or starts a second copy of a running game.

After restarting, an interrupted farm reads the retained SP balance. Any verified
gain is used; otherwise preparation starts again. Completed car batches and the
return step after a recorded claim resume automatically without recounting rewards.
Interrupted purchases or partly claimed mastery wait for review after reopening,
because the exact car and game save may be uncertain.
The recovery marker survives closing the panel. No purchase ledger is cleared and
no wheelspin counter is increased by the restart module. Restarting does not fix
the underlying FHC11 hardware/driver crash. A challenge with no retained SP gain
returns through preparation and retries. F7 cancels these retries too.

The panel also watches the Python worker. An unexpected worker exit schedules a
restart after 15–120 seconds, with no attempt limit. Automatic restarts are locked
to the same saved mission ID; completing or changing that mission cancels them.
F7, closing the panel, and a stop request cancel the watchdog. Keep the panel open
for this backup. A challenge timer that remains frozen for 60 seconds triggers
game recovery; ordinary brief recognition gaps release driving inputs and wait.

## Current validation

September 11: a new mission starts at **0 of 1,000 additional saved spins**.
The previous 188 rewards are archived and excluded. The **Analytics** tab keeps
measurements inside the app: mission totals and active time, every completed car's
buy/choose/mastery/return timings, retries, challenge SP gains and durations,
and the number of launches and minutes needed for each 999-SP refill. Tables
remain empty until this mission produces measurements. Prior verified timings
provide clearly labeled initial estimates; they do not count as new progress.
**Export analytics CSV** is the only action that creates export files.
Internal measurements persist across restarts. Cars stay in the garage.
95 focused tests passed for analytics, reports, navigation, production and recovery;
the native panel's self-test passed. Seasonal update notifications now have
specific verified acknowledgement paths rather than waiting indefinitely for menus.

September 10 speed update: one uninterrupted purchase → newest Mazda → six
verified claims → Car Collection cycle took **54.68 seconds**, versus **85.7
seconds** on average in the earlier run (about **36% faster**). The separate
navigation benchmark improved from **37.97 to 29.44 seconds**. Mastery took
**8.08 seconds** in the complete-cycle test, versus roughly 17 seconds earlier.
These are local measurements, not a guarantee for every cycle or machine.
The full suite passed **230 tests**. Fast navigation is the default; it retains
sync, focus, purchase, exact-caption and interior-ownership checks.

The original eight-hour cutoff incorrectly stopped the mission at 114 rewards.
On September 10 at 21:42 JST, the same mission resumed from **117/500**, with
**516 SP**. The cutoff has been removed from the runtime, including legacy
checkpoints: the mission runs until its target or an explicit stop such as F7.
Crash recovery and worker restarts remain unlimited. No counters were reset.
See `runs/SPEED-REPORT.md` for the measured speed improvements.

On September 10, the fresh mission verified three farm balances:
**27 → 383 → 692 → 999 SP**, then funded a 47-car batch. Repeated full cycles
have verified purchases, untouched Mad Mike selection, all six mastery nodes,
and the return to Car Collection. The sole Favorite Subaru, its 14 owned mastery
nodes, farm settings, challenge countdown and return-home route passed live checks.
A Windows resolution change interrupted the second farm; display protection was
added, and the run resumed after the verified 1920 × 1080 layout was restored.

Car Mastery, Recently Added and Mazda in the manufacturer list now use guarded
pointer selection. Bounded live checks measured 2.172, 2.954 and 2.969 seconds
respectively. All three routes also passed a complete normal car cycle;
Car Mastery has passed sustained repeated cycles.
The target must remain stable before clicking. Other menu navigation retains
its verified keyboard route; mastery claims still use Enter and interior-only
ownership checks. The full automated suite passed **186 tests** before this final
navigation changes; **37 navigation/sync tests** passed afterward, including
unstable-target blocking for all three fast entries.

A later 243-SP reading failure came from native-size OCR reading the tiny digits
as 713. Numeric crops and label contexts are now enlarged before recognition;
conflicting readings still block spending. **72 production/navigation/sync tests**
passed, including the real failure frame and earlier 51/91/143 cases. The fix
then read 243 correctly live and resumed the saved car's return without recounting
its already-verified reward.

The first 47-car batch completed with 12 SP and automatically entered farming
without buying a 48th car. A clipped scrolling Subaru name initially stopped
selection; the reader now waits for the same selected card's full identifying
text twice before entry. This fix passed live, followed by farm-setting checks
and a Mega V6 launch with an advancing countdown. **79 production/garage/navigation/sync
tests** passed. The three subsequent farms verified **12 → 370 → 737 → 999 SP**
without intervention. A second 47-car batch was funded automatically, and its
first completed car raised the fresh reward count to 48 with 978 SP remaining.
This validates the refill-to-next-batch loop; the full 500-reward target remains
in progress. Read the live checkpoint for the current count.
The process-bound startup gate recovered a real FHC11 crash on September 10:
Steam relaunched the game, the worker observed native Start/Continue through
stable home, and the retained 387 SP was verified without assistant input.
The separate visible cloud-dialog-to-100% branch still needs live validation.
Automated tests cover completion, reappearing dialogs, regressed progress,
process changes and no-bypass behavior.

That restart left the video cap at 20 FPS; the following farm earned only 2 SP.
Saving 60 FPS restored the visible frame rate to 57–60. Farm setup now checks
the cap and corrects a low value using verified setting changes. A small SP
gain also forces the next run to recheck its setup. The live 60 FPS setup check
and 83 focused tests passed. The next full live farm verified **389 → 757 SP
(+368)** after the correction, with no intervention during the run. Timer
progress alone is not proof of SP gain.

My Cars navigation also waits through the observed fading home-tab animation
before requiring two stable garage frames. The shared route is used for Mazda
selection and the Favorite Subaru. This removes a premature menu-mismatch retry;
unrelated dialogs still stop that transition. **91 focused tests** passed.

The previous mission and its 120 rewards are archived and excluded from the
fresh target. Do not reset an active mission to update the program. Opening the
dashboard does not start a run. Read the live panel and `runs/goal.json` for current
progress; `runs/FRESH-500-STATUS.md` records maintenance and live validation.

The hourly Codex check now follows the fresh 1,000-spin mission. Discord reporting
runs independently of the game worker; it does not start gameplay.

See **[MODULES.md](MODULES.md)** for setup, progressive tests, code modules,
recovery, and the repository features that still need migration. Full repository
feature parity is not yet complete.

Use English menus, 1920 × 1080, and keep the game focused. Make the maxed 1998
Subaru 22B your **only Favorite**, with its mastery completed; turn automatic
steering/braking and Skills HUD off as specified
by the [Mega V6 creator](https://www.reddit.com/r/ForzaHorizon6/comments/1w6xpvf/new_400sp15min_mega_farm_v6/).

Cloud sync takes priority over the mission, focus priority, and crash recovery.
While Gaming UI or a cloud-sync/conflict dialog is visible, the app sends no
mission inputs and never chooses Play offline or Stop syncing. Waiting has no
timeout that permits a restart or bypass. F7 still stops immediately. The pending
sync gate is saved in `runs/cloud_sync.json`, so restarting the worker cannot
discard it. Observed 100% or an explicit completion message must be followed by
the dialog closing and three stable ready-screen observations. A worker-owned
native Start/Continue flow can also establish startup completion; attaching to
an already playable menu alone cannot. Completion proof belongs to the same
game process and creation time, so it cannot authorize a replacement process.
This checks visible completion; it does not read Microsoft's server-side sync
state. Unresolved sync errors or
account prompts need to be resolved in the game; the app does not dismiss them.

## Discord reports

**Modules → Discord reports** opens the rectangular settings panel. The saved
webhook is encrypted for this Windows user under `%LOCALAPPDATA%/FH6Auto`; it is
not stored in source, command-line settings, screenshots or ordinary logs.
The reporter starts with the dashboard and has its own single-instance process.

Reports include the fresh target, verified reward count, remaining spins,
observed SP and credits, purchased/pending cars, farm and batch progress, current
step, game/worker state, synchronization gate and run window. Account values have
observation times. The reward count represents verified owned Super Wheelspin
nodes, as accepted by the user; it is not a read of the saved-spin inventory.

Car batches reuse a verified clear garage-filter state until an interruption,
focus loss, filter action, farm-car selection or game restart. This avoids the
repeated filter reset. The client may still reset Recently Added sorting when
My Cars opens; that is checked and restored on screen. Current sorting,
the newest selected car, its NEW tag and fresh mastery remain screen-verified.

Fast navigation also polls purchase dialogs and acknowledgements every 50 ms
instead of 150 ms, with the same three consecutive recognition checks. It reuses
the collection check just completed by purchase recovery, then independently
verifies the exact Mazda and its focus before opening an offer. Price, selected
Buy button, single-attempt purchase ledger, success receipt and sync guards are
unchanged. Measured car times include purchase, mastery and return to collection.
Fast purchases select the verified Yes/Buy rows by keyboard, avoiding redundant
pointer hovering; the selected button and price still require three fresh checks
before purchase. If manufacturer scrolling leaves the visible list unchanged,
navigation switches to arrows and verifies Mazda's focus before selecting it.

Reports are sent every **60 seconds** by an independent background reporter.
One Discord container holds a current account strip, compact mission status,
and a carousel with three analytical boards plus one game image.
The full game image may show **only My Horizon / Return Home**.
The newest qualifying game-only capture is retained until a newer allowed menu
is captured; collection, mastery, driving, loading and other screens are excluded.
The account strip independently uses the latest verified compact or horizontal
layout. Both images retain their actual capture timestamps. Desktop pixels are
never a fallback. The combined car-cycle chart displays 25–60 seconds, with
outside-range samples marked and retained in statistics. The challenge active-time
panel shows only Mini V2 runs, including setup and exit time, in a 5:00–7:00 view.
It retains the 6:50 reference and labels the 7:33 reference above the view.
The boards contain 8, 4 and 5 charts: page 2 uses a 2×2 layout; page 3 gives
Input → usable screen the full bottom row. Panel numbers are sequential on each
page. Retained-SP-per-run, per-run SP/hour and the credits-versus-cost chart have
been removed from the boards; their underlying measurements remain available.
Account credits and level require two matching readings of the identified header.
If header OCR omits the colored level badge (observed at level 300), the reader
isolates and enlarges that badge for a second OCR pass. It still requires two
matching observations; prestige, nearby text and ambiguous badges are excluded.
Fresh readings are requested at worker resume, farm preparation/results, car
purchases and wheelspin claims, even when values are unchanged. Checks use the
existing garage route, with a bounded second observation for confirmation.
Missing or unreadable values retain their previous timestamp and are explicitly
marked as coming from the previous checkpoint in Discord; no account values are guessed.
Reports show observation times, mark prestige as last recorded, and estimate the
remaining credit budget after excluding cars already purchased but awaiting mastery.
Discord reporting has no game inputs and cannot bypass F7 or sync. The game
worker and panel watchdog perform retries; the reporter only sends updates.

Delivery is confirmed from the returned message and uploaded/resolved images.
Rate limits and network failures retry separately without slowing the input
worker. Deleted or unauthorized hooks wait for a configuration update. Settings
also provide **Send status now** (subject to the same new-spin check) and an enable/disable switch. Keep the local
reporter running to receive updates; it cannot report while this PC is off.
The implementation follows the official [Discord webhook API](https://docs.discord.com/developers/resources/webhook#execute-webhook)
and [rate-limit handling](https://docs.discord.com/developers/topics/rate-limits).
