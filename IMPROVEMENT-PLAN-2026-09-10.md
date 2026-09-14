FH6 Wheelspin Workshop — improvement plan for later

Research date: 10 September 2026. Planning only; this document does not authorize execution or change the app, game, checkpoints, or scheduled monitor. This is a broad review of relevant public sources, not an exhaustive search of the internet. Community claims are leads for testing, not verified performance on this PC.

The intended route remains: Steam → complete cloud sync → My Cars → Favorites → prepared 1998 Subaru 22B → Mega V6 until actual SP reaches 999 → home → Collection Journal → buy one Mad Mike → My Cars → Recently Added → enter and verify a fresh mastery tree → claim six nodes → return to collection. Repeat the car cycle up to 47 times, then refill SP. Stop at the existing 500-claim target and leave the Super Wheelspins unopened.

The local checkpoint read during planning records 120/500 claims, with 382 SP last observed and a later farm interrupted. These are saved observations, not a new live verification. Preserve the 120; do not infer additional earnings from elapsed farm time.

**What the research changes**

| Finding | Consequence for this program |
|---|---|
| Forza specifically advises waiting for cloud synchronization, avoiding force quits during saves, and allowing uploads after exiting. [Forza save notice](https://support.forza.net/hc/en-us/articles/52517543779859-Notice-Regarding-Lost-Save-Issues-in-Forza-Horizon-6) | Sync must cover startup, gameplay interruptions, shutdown, and relaunch. A restart delay alone is insufficient. |
| Microsoft's Game Saves documentation says cancelling sync can allow offline gameplay. Local saving and cloud upload are distinct operations. [Microsoft sync flow](https://learn.microsoft.com/en-us/gaming/gdk/docs/features/common/game-save/game-saves-syncing?view=gdk-2604) | A home screen, disappearance of a dialog, or a local file timestamp cannot independently certify cloud completion. |
| The Mega V6 creator supplies code 155439962, requires the maxed 22B, automatic steering/braking off, Skills HUD off, and periodic movement. Earlier versions failed with a season change. [Creator's V6 post](https://www.reddit.com/r/ForzaHorizon6/comments/1w6xpvf/new_400sp15min_mega_farm_v6/) | Keep settings specific to this challenge. Revalidate after updates/seasons and measure actual retained SP. |
| The upstream winter issue reports two added filter rows above Duplicate; another issue reports failure to select the 22B. [Issue 33](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/issues/33), [issue 31](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/issues/31) | Find filter labels and selected checkboxes dynamically. Do not depend on row counts. The winter report concerns added rows, not evidence of a color-recognition defect. |
| The creator's earlier comparison measured Mini v2 at about 132 SP/5 min versus Mega v5 at 358 SP/15 min, excluding load times; subsequent comments say v4/v5 broke. [Creator's comparison](https://www.reddit.com/r/ForzaHorizon6/comments/1w343yi/new_400sp15min_mega_farm_v5_some_simple_math/) | Short farms are a later benchmark candidate, not an automatic replacement for V6. Those measurements are not current V6 results. |
| Official Data Out provides driving telemetry including timestamps, throttle and car-model identity. [Forza Data Out](https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation) | Add optional local telemetry to diagnose driving. It provides no SP, saved-spin count, cloud status, or unique garage-copy identity. |
| FHC11 is associated with unsupported drivers or hardware, with GTX 10xx given as an example. [Official crash codes](https://support.forza.net/hc/en-us/articles/51642089902739-Forza-Horizon-6-PC-Crash-Error-Codes) | Track graphics failures separately from navigation mistakes; software retries cannot guarantee this PC will never crash. |

**1. Finish the mandatory sync gate first**

The current guard blocks visible Gaming UI/cloud dialogs and persists pending state. Its release rule accepts stable game screens. This is a useful input block, but does not yet meet a strict claim of independently verified full cloud synchronization.

Plan explicit states: Unknown, Downloading, Uploading, Failed, Conflict, Verified. Unknown/failed/conflict never authorize mission input. Record which observable evidence produced Verified and when. Investigate the actual game/client sync indicators described by Forza; confirm which belongs to FH6's Xbox save rather than unrelated Steam data. If no trustworthy completion signal is exposed on this installation, keep the status unknown and request user verification instead of inventing a guarantee. Microsoft GDK interfaces are title-development APIs; do not assume the macro can query another game's authenticated save provider.

All input entry points must share this mandatory gate. Local inspection found that the standalone live-check helper constructs a navigator without installing the guard; audit this and legacy launch paths before further live tests. Separate account login from cloud errors. A future Try again action may target only the verified retry control, once per observed failure; never press generic Enter on Gaming UI. Stop syncing, Play offline, save deletion and automatic conflict selection remain excluded.

At a normal session end, finish the current verified transaction, wait for the save indicator to clear, exit normally, and observe upload completion before relaunch. On a crash, retain a pending-sync state even if the game process disappears. A fixed 30-second or five-minute wait is never proof of success. These are proposed behaviors to validate, not completed capabilities.

Acceptance: sync at 0%, 100% but still active, behind the game, failed, cancelled, conflicted, and interrupted by worker restart all prevent mission inputs. F7 releases held keys and stops immediately. Offline gameplay must not satisfy the gate.

**2. Implement one shared garage-filter module**

Farm selection: My Cars → filter Favorites → verify the selected card is the 1998 Subaru 22B → Get In Car → verify current-car header and its prepared mastery. Confirm the Favorites list contains the expected sole car; zero/multiple/unreadable results require correction rather than arbitrary selection.

Conversion selection: My Cars → explicitly clear the Favorites filter → Recently Added → newest Mad Mike → verify model/year and fresh mastery. Clearing Favorites is essential because filter state may carry across visits. Keep the normal pipeline free of Designs & Paints.

Navigation should be resumable from the garage, filter dialog, sort dialog, car-action dialog and showroom. Resolve labels, not a predetermined number of Down presses. Test focus-only first clicks and the row changes reported in winter.

**3. Complete the 999-SP / 47-car batch checkpoints**

Batch policy already exists locally, but the complete Favorites/refill/conversion route still needs live validation. Fill to an observed 999; do not equate three challenge completions with a full bank. At 21 SP each, 47 cars consume 987 SP and leave 12. At the currently recorded 95,000 CR price, a full batch costs 4,465,000 CR; verify price and funds in-game before spending.

Process each car immediately after its purchase; repeat that cycle 47 times. Bulk-buying all 47 first makes duplicate identity harder and offers no established benefit here. Cap the last batch to the remaining mission target. From 120/500, this is eight batches of 47 and a final four cars, requiring 7,980 SP spent and 36,100,000 CR at the recorded price. The requested refill-to-999 policy also applies before the final four unless the user later changes it.

Make batch reservation and car-session creation recoverable if the worker stops between those writes. Persist batch goal ID, intended count, completed index, current transaction, and observed SP separately from estimates. Reconcile partial mastery by node ownership; never count a reward twice or repeat a pending purchase. Check actual SP on the already-open mastery screen and check again after a crash or manual interruption. Preserve the accepted owned-node reward test; opening spins remains disabled.

**4. Replace repeated failures with recovery specific to each stage**

Each navigation step needs a starting screen, one allowed action, an expected resulting screen, and a recovery path. On a missed click, first observe: if the destination is already present, advance the checkpoint; if the original screen is unchanged, repeat only the reversible navigation; if another known screen appears, route from that screen.

Purchases require receipt reconciliation, not blind retry. Sync requires waiting. A verified crash requires process recovery followed by sync and state reconciliation. A user stop must remain stopped. Retain the mission indefinitely while recovery is possible, but show when a repeated condition needs new evidence instead of looping the same ineffective action forever.

Store a compact before/after screenshot pair, expected/observed screen, selected label, retry reason, and elapsed time. Deduplicate identical errors while counting repetitions.

**5. Improve speed by removing work, then tune waits**

Measure complete saved claims per hour, including farming, loading, sync and recovery. Record normal and slow transition times separately. First remove manufacturer scanning for the Subaru, repeated whole-menu journeys to inspect SP after every car, and avoidable Collection Journal visits between refill runs. Cache verified farm settings within an uninterrupted refill session; invalidate that cache after restart, profile changes or manual control.

Read small, stable regions for SP, focused cards, mastery interiors, and the challenge timer. Keep multiple agreeing observations and focus-border exclusion for ownership. Use full-screen OCR when the screen is unknown. Timing can adapt per transition once measured; slower loads must lengthen waits rather than cause extra Enter presses. Benchmark with and without changes using the same route and car.

A proposed first acceptance target is at least a 20% reduction in median car-cycle time with no increase in navigation failures and no transaction mistakes. This is a benchmark target, not a promised improvement. Leave the 15-minute challenge duration unchanged unless a separately tested farm is demonstrably faster end to end.

**6. Trial optional Data Out and compare farms later**

Use the official localhost UDP output to verify throttle arrives, identify the model being driven, and distinguish a live driving simulation from an OCR failure. Combine packet freshness with timer/UI evidence. Packets normally stop in menus, so silence alone must never trigger a crash restart. Model identity cannot justify deleting a particular duplicate.

For possible shorter farms, preserve V6 as the configured default. First verify availability and instructions on the current season; compare at least five runs using retained SP divided by total elapsed time, including loading and navigation. Only investigate direct result-screen retries if the actual SP balance can still be established. Do not buy from estimated challenge yields.

**7. Keep the program modular and the interface simple**

The main page should show the requested Super Wheelspins, F6 Start/Resume, F7 Stop, observed SP, saved claims, current batch, current activity and sync status/evidence. Show last observation times; separate estimates from measurements. Detailed recovery controls and diagnostics belong in an Advanced view.

Keep separate modules for sync, launcher, recognition, input, garage filters, farm profiles, funding, purchasing, mastery, durable mission state, recovery and diagnostics. Use a feature checklist for upstream parity. The upstream release adds OCR checks, modular full-loop work and notifications; reuse relevant ideas after tests. [Upstream releases](https://github.com/M-Haziq-Iqbal/Forza-Horizon-6-Wheelspin-Macro/releases)

Other car profiles, optional spin opening, duplicate selling/gifting, overlays and notifications can follow the reliable earn-and-save route. They must remain independently selectable and must not activate in the 500-spin mission. Exact-copy removal remains unresolved. Another public macro uses randomized waits and prescribed starting screens; it offers little evidence of improved recovery for this project. [Alternative implementation](https://github.com/Tunaaaaqqq/ForzaHorizon6-Macros)

**Validation and release order**

1. Replay recorded sync, seasonal filter, focus, purchase, and mastery failures without inputs. Audit every entry point for the sync gate.
2. Later, with live testing resumed: Favorites Subaru selection, clearing the filter, and newest-Mazda selection independently.
3. One purchase and mastery, then five consecutive conversions with checked receipts and returns to collection.
4. One verified refill to 999 and one 47-car batch; compare real before/after SP and goal totals.
5. Exercise worker stops at batch reservation, purchase confirmation, node claim, return navigation and final completion using simulated faults. Never deliberately crash the live game during save/sync.
6. Complete two refill/conversion rounds without manual navigation before calling the route unattended-ready. Preserve the old working release and its state format for rollback.

Game-version checks belong in preparation: the official Series 5 announcement dates the update to September 7 and playlist change to September 10. Revalidate relevant screens and challenge behavior after these changes; this does not establish that V6 is broken. The detailed patch-note redirect could not be retrieved during research. [Official Series 5 announcement](https://forza.net/news/forza-horizon-6-series-5)

Research also reviewed first-hand Steam/Reddit sync complaints. They corroborate that sync failures occur, but suggested save deletion, offline bypasses and service resets are not part of the automatic recovery plan. [Steam sync discussion](https://steamcommunity.com/app/2483190/discussions/0/653730014598204894/), [Reddit sync reports](https://www.reddit.com/r/ForzaHorizon/comments/1thldv3/forza_horizon_6_cant_sync_with_cloud_various/)
