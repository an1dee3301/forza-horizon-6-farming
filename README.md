# FH6 Auto

Windows automation for the Forza Horizon 6 Super Wheelspin loop: farm Skill Points, buy the 95,000-CR Mad Mike Mazda, select the newest copy, claim and verify its 21-SP mastery path, bank the reward, and repeat. **F6 starts. F7 stops.**

## 1. Install and run

### Requirements

- Windows 10 or 11
- Python 3.10 or newer
- Forza Horizon 6 through Steam
- English game menus at 1920×1080
- The maxed 1998 Subaru Impreza 22B set as the only Favorite
- Mega Farm V6 share code `155 439 962`

### Install

1. Download and extract the latest release.
2. Run `Setup FH6 Auto.cmd` once. It creates a private Python environment, installs the required packages, and opens the dashboard.
3. For later runs, use `Start FH6 Auto.cmd`.

For development installs, clone the repository and run the same setup file. Tests require `requirements-dev.txt` and run with `python -m pytest`.

### Run

1. Open Steam and sign in.
2. Start FH6 Auto.
3. Choose a mode and target in Mission Control.
4. Put Forza in a supported home or festival state.
5. Press **F6**.
6. Press **F7** whenever you want the worker to stop safely.

The program can launch FH6 through Steam and resume after a crash. A visible cloud-sync gate always takes priority; it waits for synchronization and never chooses offline play.

### Production loop

1. Read the current SP balance.
2. Run Mega Farm V6 in full-run or headroom-aware top-up mode.
3. Buy exactly one Mad Mike Mazda through Car Collection.
4. Open My Cars → Recently Added and select the newest untouched copy.
5. Claim and visually verify all six required mastery nodes.
6. Record the Super Wheelspin reward and return to the next purchase.
7. At the configured cleanup interval, remove processed Mad Mikes and verify the filtered inventory.
8. In credit-limited mode, stop buying below 95,000 CR, finish any paid copy, top SP up to 999, remove the remaining Mad Mikes, verify zero, and stop.

Rewards stay saved; the program does not open the wheelspins.

### Safety and recovery

- Checks window identity, foreground focus, resolution, language, and expected screen before critical input.
- Uses OpenCV for calibrated visual states and OCR for variable numbers and text.
- Compares mastery-node interiors, excluding the changing focus border.
- Verifies each node changed from locked to owned before advancing.
- Checks the exact car, 95,000-CR offer, selected Buy action, and purchase confirmation.
- Never repeats an uncertain purchase.
- Requires two matching credit reads before a credit-limited purchase decision.
- Uses hybrid inventory tracking: verified rewards update immediately, then a fresh My Horizon read corrects the total.
- Saves checkpoints, error screenshots, failure causes, and recovery timing.
- Detects a stationary farm car and performs bounded reverse recovery.
- Keeps Discord rendering, analytics, screenshots, and account reads off the input-critical path where safe.

### Optional Discord reporting

Add a webhook in the dashboard to receive the live mission board and current game capture. The webhook is encrypted with Windows DPAPI for the current Windows user and is excluded from Git and release archives.

### Project map

| Path | Purpose |
|---|---|
| `FH6 Auto.pyw` | Mission Control desktop app |
| `fh6/` | Navigation, recognition, farming, recovery, analytics, and reporting |
| `forza_cycle.py` | Shared configuration and mission state |
| `recognition/`, `templates/`, `calibration/` | Screen and mastery references |
| `profiles/` | Farm profiles |
| `tests/` | Public regression suite |
| [`MODULES.md`](MODULES.md) | Module-level map |
| [`RECOGNITION.md`](RECOGNITION.md) | Recognition and calibration notes |
| [`CHART-METHODS.md`](CHART-METHODS.md) | Chart and metric conventions |
| [`SECURITY.md`](SECURITY.md) | Private-state and credential handling |

Private gameplay captures, `runs/`, `failures/`, `purchases/`, `LocalState/`, virtual environments, process identifiers, and Discord credentials stay outside Git.

## 2. Data analysis

The complete operation is split into three measured cohorts. **Pre-Phase 1** is the original 0→517 run, **Phase 1** is the 1,398-car restart, and **Phase 2** is the final credit-exhaustion run. Missing historical values stay **N/A**.

### Final Phase 2 result

**1,337 new SW · 1,337 cars · 112 farms · 2,506 saved SW · 230 WS · 999 SP · 42,170 CR · 0 Mad Mikes**

| Cohort | Cars | Farms | Active | Wall | P50 | P90 | P99 | SW/active h | Farm SP/h | Retries | Crashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre-Phase 1 · 0→517 | 517 | 35 | 19.26h | N/A | 56.09s | 63.63s | 72.35s | 26.85 | 1116 | 76 | 2 |
| Phase 1 · restart from 333 | 1,398 | 116 | 54.72h | N/A | 47.37s | 58.69s | 83.46s | 25.55 | 1117 | 1,744 | 20 |
| Phase 2 · credit exhaustion | 1,337 | 112 | 46.65h | 61.34h | 45.62s | 54.64s | 59.01s | 28.66 | 1036 | 306 | 7 |

![Three-cohort speed and throughput](docs/phase-2-report/charts/01_phase_comparison.png)

![Cycle-duration distributions](docs/phase-2-report/charts/07_cycle_ecdf.png)

### Phase 2 line data

| Metric | Value |
|---|---:|
| Cycle P50 / P90 / P99 | **45.62s / 54.64s / 59.01s** |
| Latest-20 P50 / P90 | **47.29s / 56.41s** |
| First-pass yield | **97.23%** |
| Farm capacity | **49.34 cars/h** |
| Conversion capacity | **63.19 cars/h** |
| Retained farm output | **1036 SP/h** |
| Phase 2 SW / active hour | **28.66** |
| Phase 2 SW / wall hour | **21.80** |
| Broad retries / crashes | **306 / 7** |

![Phase 2 cycle timeline](docs/phase-2-report/charts/02_cycle_timeline.png)

![Stage P50 across all cohorts](docs/phase-2-report/charts/09_stage_p50_comparison.png)

![Farm throughput](docs/phase-2-report/charts/04_farm_throughput.png)

![Farm and conversion capacity](docs/phase-2-report/charts/10_capacity_comparison.png)

#### Detailed phase data

Cycle P50/P90/P99: **45.62s / 54.64s / 59.01s**. Latest-20 P50/P90: **47.29s / 56.41s**. First-pass yield: **97.23%**. Conversion capacity: **63.19 cars/h**.

![Phase 2 timeline](docs/phase-2-report/charts/02_cycle_timeline.png)

| Stage | Pre-P1 P50 | P1 P50 | P2 P50 | P2 P90 | P2 P99 |
|---|---:|---:|---:|---:|---:|
| collection | 0.469s | 0.063s | 0.062s | 0.125s | 0.766s |
| buy | 6.907s | 4.031s | 3.828s | 4.437s | 13.304s |
| bought | 1.266s | 0.985s | 0.875s | 1.047s | 1.151s |
| choose | 24.031s | 21.157s | 20.906s | 26.012s | 32.469s |
| open_mastery | 3.313s | 3.438s | 3.187s | 3.563s | 14.515s |
| mastery | 8.375s | 7.312s | 6.860s | 7.125s | 7.281s |
| return | 11.468s | 9.719s | 9.328s | 9.891s | 10.368s |

![Stage latency](docs/phase-2-report/charts/03_stage_percentiles.png)

![Stage comparison](docs/phase-2-report/charts/09_stage_p50_comparison.png)

#### SP farming

The **112** Phase 2 farm runs retained **28,700 SP** in **27.70 active hours**: **1036 SP/h**, supporting **49.34 cars/h**. The 15% target from the 1,221.6 SP/h baseline was 1,404.8 SP/h and was not sustained phase-wide.

| Run type | Runs | Retained SP | Active | SP/h | Cars/h | Drive P50 | Drive P90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| natural_completion | 71 | 20,565 | 19.96h | 1030 | 49.07 | 917.2s | 917.4s |
| intentional_top_up | 34 | 6,453 | 5.79h | 1115 | 53.11 | 639.2s | 836.4s |
| interrupted | 7 | 1,682 | 1.95h | 861 | 41.00 | 917.2s | 917.3s |

Estimated cap loss where instrumented: **70.9 SP**.

![Farm throughput](docs/phase-2-report/charts/04_farm_throughput.png)

![Capacity](docs/phase-2-report/charts/10_capacity_comparison.png)

#### Reliability

Broad counters: **306 retries**, **7 crashes**, **97.23% first-pass yield**.

| Cause | Events | Recovery | Mean cost |
|---|---:|---:|---:|
| choose_timeout | 1 | 0.5 min | 28.3s |
| mastery_detection | 13 | 3.2 min | 14.8s |
| other | 27 | 11.9 min | 26.5s |
| return_timeout | 1 | 0.2 min | 12.0s |

![Reliability](docs/phase-2-report/charts/06_reliability.png)

### Finance and terminal proof

| Item | Value |
|---|---:|
| Opening credits | **120,157,670 CR** |
| Other reconciled in-game inflow | **+6,899,500 CR** |
| Mazda spend | **−127,015,000 CR** |
| Latest observed credits | **42,170 CR** |
| Terminal purchase gate | **41,170 CR · 3 matching reads** |
| Terminal SP | **999 / 999** |
| Mad Mikes remaining | **0 verified** |

![Credit observations](docs/phase-2-report/charts/05_credit_timeline.png)

### Files

- [Full Phase 2 report](docs/phase-2-report/REPORT.md)
- [Reviewed snapshot](docs/phase-2-report/reviewed_snapshot.json)
- [Three-cohort CSV](docs/phase-2-report/data/cohort_comparison.csv)
- [Stage percentiles](docs/phase-2-report/data/stage_percentiles.csv)
- [Farm profiles](docs/phase-2-report/data/farm_profiles.csv)
- [Classified failures](docs/phase-2-report/data/classified_failures.csv)

Raw logs, screenshots, purchase ledgers, local state, and Discord credentials are excluded from Git. Pre-Phase 1 fields without preserved cohort-level proof are reported as N/A rather than inferred.
