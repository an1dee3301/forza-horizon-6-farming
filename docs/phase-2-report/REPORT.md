# Phase 2 — credit exhaustion run

Phase 2 completed on **2026-09-18 at 00:11 JST**. The worker processed **1,337** Mazdas, restored SP to **999**, removed the last Mad Mike, and verified the filtered garage empty. The purchase gate used three matching reads at **41,170 CR**; the latest later account observation was **42,170 CR**, still below the 95,000 CR purchase price.

## Result

| Measurement | Result |
|---|---:|
| New Super Wheelspins | **1,337** |
| Cars bought / processed | **1,337 / 1,337** |
| Final saved inventory | **2,506 SW · 230 WS** |
| Final SP | **999 / 999** |
| Farm runs | **112** |
| Gross Mazda spend | **127,015,000 CR** |
| Opening / latest credits | **120,157,670 → 42,170 CR** |
| Reconciled other credit inflow | **+6,899,500 CR** |
| Mad Mikes remaining | **0 verified** |
| Level / prestige | **302 · prestige 6** |

## Three-cohort comparison

| Cohort | Cars | Farms | Active | Wall | P50 | P90 | P99 | SW/active h | Farm SP/h | Retries | Crashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre-Phase 1 · 0→517 | 517 | 35 | 19.26h | N/A | 56.09s | 63.63s | 72.35s | 26.85 | 1116 | 76 | 2 |
| Phase 1 · restart from 333 | 1,398 | 116 | 54.72h | N/A | 47.37s | 58.69s | 83.46s | 25.55 | 1117 | 1,744 | 20 |
| Phase 2 · credit exhaustion | 1,337 | 112 | 46.65h | 61.34h | 45.62s | 54.64s | 59.01s | 28.66 | 1036 | 306 | 7 |

Historical wall time is **N/A** where the cohort-specific boundary was not preserved.

![Cohort comparison](charts/01_phase_comparison.png)

![Cycle distributions](charts/07_cycle_ecdf.png)

## Phase 2 speed

Cycle P50/P90/P99: **45.62s / 54.64s / 59.01s**. Latest-20 P50/P90: **47.29s / 56.41s**. First-pass yield: **97.23%**. Conversion capacity: **63.19 cars/h**.

![Phase 2 timeline](charts/02_cycle_timeline.png)

| Stage | Pre-P1 P50 | P1 P50 | P2 P50 | P2 P90 | P2 P99 |
|---|---:|---:|---:|---:|---:|
| collection | 0.469s | 0.063s | 0.062s | 0.125s | 0.766s |
| buy | 6.907s | 4.031s | 3.828s | 4.437s | 13.304s |
| bought | 1.266s | 0.985s | 0.875s | 1.047s | 1.151s |
| choose | 24.031s | 21.157s | 20.906s | 26.012s | 32.469s |
| open_mastery | 3.313s | 3.438s | 3.187s | 3.563s | 14.515s |
| mastery | 8.375s | 7.312s | 6.860s | 7.125s | 7.281s |
| return | 11.468s | 9.719s | 9.328s | 9.891s | 10.368s |

![Stage latency](charts/03_stage_percentiles.png)

![Stage comparison](charts/09_stage_p50_comparison.png)

## SP farming

The **112** Phase 2 farm runs retained **28,700 SP** in **27.70 active hours**: **1036 SP/h**, supporting **49.34 cars/h**. The 15% target from the 1,221.6 SP/h baseline was 1,404.8 SP/h and was not sustained phase-wide.

| Run type | Runs | Retained SP | Active | SP/h | Cars/h | Drive P50 | Drive P90 |
|---|---:|---:|---:|---:|---:|---:|---:|
| natural_completion | 71 | 20,565 | 19.96h | 1030 | 49.07 | 917.2s | 917.4s |
| intentional_top_up | 34 | 6,453 | 5.79h | 1115 | 53.11 | 639.2s | 836.4s |
| interrupted | 7 | 1,682 | 1.95h | 861 | 41.00 | 917.2s | 917.3s |

Estimated cap loss where instrumented: **70.9 SP**.

![Farm throughput](charts/04_farm_throughput.png)

![Capacity](charts/10_capacity_comparison.png)

## Reliability

Broad counters: **306 retries**, **7 crashes**, **97.23% first-pass yield**.

| Cause | Events | Recovery | Mean cost |
|---|---:|---:|---:|
| choose_timeout | 1 | 0.5 min | 28.3s |
| mastery_detection | 13 | 3.2 min | 14.8s |
| other | 27 | 11.9 min | 26.5s |
| return_timeout | 1 | 0.2 min | 12.0s |

![Reliability](charts/06_reliability.png)

## Finance and cleanup

**120,157,670 opening + 6,899,500 other inflow − 127,015,000 purchases = 42,170 latest observed CR.** Cleanup telemetry recorded **1,330 removals**; terminal duplicate-off and manufacturer-index checks verified zero remaining.

![Credits](charts/05_credit_timeline.png)

## Evidence limits

Raw purchases, mastery rewards, cycle rows, farm pre/post SP, terminal SP, credit reads, and zero-car cleanup are directly recorded. Rates and percentiles are derived. Historical wall time, final credits, final SP, and final garage state are **N/A** for Pre-Phase 1 because cohort-specific terminal proof was not preserved. Phase 2 goal-active time is the persisted mission counter; asynchronous category timers have different scopes and are not summed into it.
