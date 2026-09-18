# Wheelspin Workshop

## Wheelspin Lab

The new mode follows `LocalPanel → bridge.py → Controller → WheelspinLab` and
shares WorkerLease, F7, focus, display, sync and lifecycle guards. The legacy
`Mode_Spin.ahk` remains reference-only. SQLite enforces the record-first action
invariant; Dry Run is enabled until reviewed game captures pass calibration.

Open **Start FH6 Auto.cmd** or **FH6 Auto.pyw**. Both open the same dashboard.

Choose **Earn saved Super Wheelspins**, enter how many **additional** Super Wheelspins
you want, then press **F6**. **F7** stops. The program reads actual SP, finishes a
saved purchased car first, and runs Mega V6 when another 21-SP tree cannot be funded.
Each car ends back at Car Collection, including the last one. The earned spins stay saved.

Mega V6 has passed live refill and subsequent 47-car batch checks. The current
fresh target is 1,000 new saved spins, with earlier rewards excluded. Unexpected
screens preserve the checkpoint and retry; F7 cancels the mission.

## Mega V6 setup

- Challenge share code **155439962**, searched under **Challenges**, not race events.
- Start from a fully upgraded 1998 Subaru Impreza 22B with its mastery already completed.
- Automatic steering and braking off; HUD and Gameplay → Skills off.
- About 15 minutes per challenge. A short steering movement is sent every four minutes.
- The creator reports blank challenge names/descriptions. The module searches by share code.
- “400 SP” is the creator's advertised yield. Spending uses the measured SP balance only.

[Creator's Mega V6 instructions](https://www.reddit.com/r/ForzaHorizon6/comments/1w6xpvf/new_400sp15min_mega_farm_v6/)

English UI, 1920 × 1080, standard W/A/D driving controls, and game focus are required.
The Modules tab has a small challenge-settings dialog for the code and run duration.

## Modules

| Function | Entry point | Status |
|---|---|---|
| Wheelspin target planner | Main run mode | Offline accounting and restart tests pass; needs live full-route test |
| Mega V6 SP challenge | Farm SP only | Favorite Subaru, settings, timer, movement pulses, completion, exit and retained SP verified live (27 → 383 on the first fresh-mission run) |
| Farm setup check | Check farm setup | Checks visible assist and HUD rows; farming also verifies the Subaru's 14 owned nodes; no tune installation |
| Purchase + mastery loop | Full pipeline | Existing verified flow; now uses My Cars directly |
| Purchasing | Buy only | Finite SP-derived count; confirmed purchase ledger; no uncertain purchase retry |
| Mastery | Mastery only | Six-node Mad Mike path; verified arrow navigation, Enter claims and interior-only owned checks |
| Return navigation | Return to collection | Shared home / festival / collection navigation |
| Recognition | Recognition only | Reads screens without game inputs |
| Recovery and history | Recovery / History tabs | Shared original car checkpoint plus separate wheelspin-target checkpoint |
| Challenge profile | Modules → Challenge profile | Separate validated settings file; cannot change during an unfinished farm or target |
| Steam startup | Modules → Open game through Steam, or F6 when game is closed | Launches app 2483190 from the installed Steam library; recognizes Start Game and selected Continue |
| Crash backup | Recovery → Open through Steam and restart after crashes | Default unlimited restarts (limit 0), increasing delays, F7 cancellation; actual SP reconciliation; interrupted car cycles require review |
| Worker watchdog | Active wheelspin target | Panel retries an exited worker for the same unfinished mission only; F7 and panel close cancel; it never creates a replacement target |
| Discord reports | Modules → Discord reports | Independent process; new wheelspin updates with garage photos, verified farm-start notices, timestamped account data and credit budget; encrypted local webhook |

## Repository features still to migrate

The original repository's AHK modules remain in `Forza-Horizon-6-Wheelspin-Macro-main/Modules`;
its original entry point remains in `UpstreamMain.ahk.txt`. They are not silently used by
the new worker. Full feature parity is **not complete**: automatic spin opening with
keep/sell/gift choices, other car mastery profiles, duplicate removal, the floating
widget, and Special K/background operation are not connected to
the new dashboard. Purchased Mazdas currently remain in the garage.

Removal needs a reliable identity for the exact completed copy. NEW disappearing
does not prove which duplicate has completed mastery. No removal inputs are sent.

## Progressive checks

1. Recognition only at home, My Cars, and mastery.
2. Read actual SP and verify the current car before allowing inputs.
3. One new purchase and one mastery tree using the direct My Cars route.
4. Check farm setup, then Farm SP only: verify search code, timer, exit and actual SP gain.
5. One complete car cycle, then a small batch; verify the 47-car boundary returns
   to farming and that a final batch is capped by the remaining target.

Logs and errors are available from Recovery. Keep the current car unchanged after
a stop. Resuming preserves the target; ending a run requires checking its current car.

## Source layout

`fh6/analytics.py` records active timings, failed attempts, completed car cycles,
farm yields and 999-SP refill groups. The native Analytics page displays mission
totals, estimates and detailed tables. Export files are created only by the user's
Export action; internal records persist locally across worker restarts.

`fh6/production.py` coordinates the target; `fh6/farming.py` handles the challenge;
`fh6/farm_setup.py` retains assist/difficulty and Skills HUD verification per mission,
with a separate frame-rate check after a crash or low yield;
`fh6/profiles.py` validates challenge settings; `fh6/points.py` reads SP;
`fh6/video.py` verifies the farm frame-rate cap and saves verified increases
to at least 60 FPS without changing resolution or UI scale;
`fh6/game_lifecycle.py` owns Steam discovery, startup, crash detection and recovery;
`fh6/supervision.py` guards automatic worker resumes against completed or changed targets;
`fh6/pipeline.py` coordinates each purchase/mastery cycle; `fh6/navigation.py` handles
menus; `fh6/purchase.py` and `fh6/mastery.py` use the existing verified transaction engines.
`fh6/ownership.py` prevents simultaneous input workers. The dashboard is
`Forza-Horizon-6-Wheelspin-Macro-main/Modules/LocalPanel.ahk`, with `Runtime/bridge.py`
connecting it to the shared worker. No cloud services are used.
`Modules/MissionWatchdog.ahk` owns worker retry delays and cancellation separately
from game recovery and menu navigation.
`fh6/reporting.py` reads checkpoints, formats images and sends confirmed Discord
reports; `fh6/discord_reports.py` owns its independent watcher and settings window;
`fh6/farm_notices.py` verifies fresh farm starts and deduplicates their delivery separately from rewards;
`fh6/report_secrets.py` stores the webhook with Windows user encryption;
`fh6/report_images.py` caches only verified game evidence. Network retries and
image encoding do not run in the game input loop.
`fh6/cloud_sync.py` blocks inputs and crash recovery until synchronization is
verified for the current game process. `fh6/display.py` blocks calibrated inputs
if the selected Windows display changes from 1920 × 1080.

Steam backup settings are in `runs/launch_settings.json`. A pending
`runs/game_recovery.json` forces checkpoint review/reconciliation before inputs
resume. Crash screenshots and the numbered attempts appear in the existing logs.
Login or update prompts are left for the user; focus loss alone never restarts a game.
Game priority restores FH6 focus. F7 stops the mission, including infinite retries.
