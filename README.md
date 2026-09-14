# FH6 Auto

Windows automation for a complete Forza Horizon 6 Super Wheelspin production loop.

1. Farm Skill Points with Mega Farm V6 (`155 439 962`) and the favorite 1998 Subaru 22B.
2. Read the actual SP balance and choose a full run or a headroom-aware top-up.
3. Buy the 95,000-CR Mad Mike Mazda from Car Collection.
4. Select the newest untouched copy through My Cars → Recently Added.
5. Claim and verify the six-node mastery path, costing 21 SP and banking one Super Wheelspin.
6. Return to Car Collection and repeat.
7. In credit-limited mode, stop buying below 95,000 CR, finish any paid copy, remove all Mad Mikes, verify none remain, and stop.

Rewards remain saved. **F6 starts and F7 stops.**

## Start

Use English menus at 1920×1080. Make the maxed 1998 Subaru Impreza 22B your only Favorite.

1. Run `Setup FH6 Auto.cmd` once.
2. Open Steam and sign in.
3. Run `Start FH6 Auto.cmd`.
4. Choose the mission mode and target.
5. Press F6.

The program can open FH6 through Steam and resume after crashes. A visible cloud synchronization gate always takes priority; the automation does not select offline play or bypass unresolved synchronization.

## Main safeguards

- Window identity, foreground focus, resolution, language, and expected-screen checks
- Interior-only mastery recognition that excludes the focus border
- Locked/unlocked verification before advancing to the next node
- Exact Mazda, 95,000-CR offer, selected Buy action, and single-attempt purchase ledger
- No repeated purchase after uncertain confirmation
- Recently Added + NEW/fresh-mastery checks for the newest Mad Mike
- Two matching credit reads before a credit-limited purchase decision
- Hybrid saved-inventory tracking corrected by direct My Horizon reads
- Error screenshots, bounded retries, crash recovery, and F7 cancellation throughout

## Speed and farm policy

Analytics, report rendering, account OCR, and diagnostics run in background workers where possible. Navigation uses screen-specific polling and stable-target checks instead of long fixed sleeps.

Mega Farm V6 is the production profile. Full runs handle bulk refill; shortened top-ups stop near the SP needed for the next car batch. Mini Farm V2 (`169 055 890`) remains available for measurement but was slower in the completed trial on retained SP per active farm hour.

The completed operation measured a final 20-car conversion P50 of 46.7 seconds and P90 of 57.5 seconds. The 30-second target was not reached.

## Analytics and Discord

The Analytics page records cycle and stage P50/P90/P99, transition and recovery timing, first-pass yield, retries by cause, recovery cost, active and wall-clock SW/hour, retained SP/hour, farm and conversion capacity, cap flags, crashes, credits, SP, level, prestige, purchases, processing, and removals.

Discord reporting is optional. The webhook is encrypted with Windows DPAPI under the current user profile and is never stored in the repository.

## Complete recorded-operation report

The retrospective covers the entire **0 → 517 → 333 reset → 1,680 saved Super Wheelspins** operation:

- [Full detailed report](docs/full-operation-report/REPORT.md)
- [Reviewed aggregate snapshot](docs/full-operation-report/reviewed_snapshot.json)
- [Inspectible CSV tables](docs/full-operation-report/data/)

It includes 1,915 verified mastery rewards, 151 farm runs, 40,215 SP consumed, 181.925M CR in gross Mazda purchases, timing distributions, farm-profile comparisons, failure costs, account progression, and final cleanup.

## Project layout

- `fh6/` — production modules, navigation, recognition, farming, recovery, analytics, and reporting
- `forza_cycle.py` — shared configuration and mission state
- `FH6 Auto.pyw` — Mission Control panel
- `recognition/`, `templates/`, `calibration/` — screen and mastery references
- `profiles/` — farm profiles
- `tests/` — automated regression suite
- `MODULES.md` — detailed module map
- `RECOGNITION.md` — recognition and calibration notes
- `CHART-METHODS.md` — chart definitions and statistical conventions

## Tests

Install `requirements-dev.txt`, then run `python -m pytest`. The public suite covers mission state, refill policy, telemetry, background work, synchronization gates, retry accounting, and pipeline control. Image-based tests that require private gameplay captures remain local.

## Private local state

The following stay outside Git: `runs/`, `failures/`, `purchases/`, `LocalState/`, virtual environments, screenshots, recordings, and encrypted Discord credentials. See [SECURITY.md](SECURITY.md).
