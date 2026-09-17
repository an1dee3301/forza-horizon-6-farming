# Phase 2 — credit exhaustion run

Phase 2 completed on **2026-09-17 at 20:39 JST** after the last affordable Mazda was purchased, its mastery reward was verified, SP was restored to **999**, and the filtered garage was verified at **zero Mad Mikes**. A fresh full-header account read then confirmed **11,170 CR**, below the 95,000 CR purchase price.

## Result

| Measurement | Phase 2 result |
|---|---:|
| Verified new Super Wheelspins | **1,281** |
| Cars bought and processed | **1,281** |
| Final saved inventory | **2,482 SW · 221 WS** |
| Final Skill Points | **999 / 999** |
| Farm runs | **104** |
| Gross Mazda spend | **121,695,000 CR** |
| Opening / final credits | **120,157,670 → 11,170 CR** |
| Other reconciled in-game credit inflow | **+1,548,500 CR** |
| Mad Mikes remaining | **0 verified** |
| Level / prestige | **278 · prestige 6** |

The final 2,482 SW figure uses the program's hybrid inventory rule: **2,481** was read directly from My Horizon and the last verified mastery node was added afterward. Wheelspins remain the direct My Horizon value of **221**.

## Speed and throughput

| Metric | Result |
|---|---:|
| Cycle P50 / P90 / P99 | **45.44s / 54.33s / 58.96s** |
| Latest-20 P50 / P90 | **46.55s / 56.05s** |
| First-pass yield | **97.11%** |
| Conversion capacity | **63.3 cars/h** |
| Farm capacity | **49.8 cars/h** |
| Retained SP / farm hour | **1045 SP/h** |
| Verified SW / active hour | **27.65** |
| Verified SW / wall hour | **22.16** |
| Goal active / wall time | **46.33h / 57.81h** |

![Phase comparison](charts/01_phase_comparison.png)

![Cycle timeline](charts/02_cycle_timeline.png)

![Stage percentiles](charts/03_stage_percentiles.png)

## Farming

The 104 recorded runs retained **27,524 SP** in **26.34 active hours**. The phase-wide rate was **1045 SP/h** or **49.8 Mazda-equivalents/h**. This remained the production bottleneck. The requested 15% target was **1,405 SP/h** from the 1,221.6 SP/h baseline; it was not sustained phase-wide.

| Run type | Runs | Retained SP | SP/h | Drive P50 | Drive P90 |
|---|---:|---:|---:|---:|---:|
| natural_completion | 68 | 19,675 | 1035 | 917.2s | 917.4s |
| intentional_top_up | 29 | 6,167 | 1147 | 700.3s | 839.5s |
| interrupted | 7 | 1,682 | 861 | 917.2s | 917.3s |


Estimated cap loss in rows where the estimator was available was **34.7 SP**. This estimate is not a complete raw-yield ledger.

![Farm throughput](charts/04_farm_throughput.png)

## Reliability

The broad mission counters recorded **297 retries** and **7 crashes**. Cause-level recovery has **42 completed rows** totaling **15.8 minutes**; broad and classified counts have different instrumentation scope.

| Cause | Events | Recovery minutes | Mean cost |
|---|---:|---:|---:|
| choose_timeout | 1 | 0.5 | 28.3s |
| mastery_detection | 13 | 3.2 | 14.8s |
| other | 27 | 11.9 | 26.5s |
| return_timeout | 1 | 0.2 | 12.0s |


![Reliability](charts/06_reliability.png)

## Phase 1 comparison

The published Phase 1 production cohort is used for conversion percentiles; full-operation totals are used for overall rates and reliability.

| Metric | Phase 1 | Phase 2 | Change |
|---|---:|---:|---:|
| Rewards | 1915 | 1281 | — |
| Cycle P50 (s) | 47.37 | 45.44 | -4.1% |
| Cycle P90 (s) | 58.69 | 54.33 | -7.4% |
| Cycle P99 (s) | 83.46 | 58.96 | -29.4% |
| SW / active hour | 25.89 | 27.65 | +6.8% |
| SW / wall hour | 22.00 | 22.16 | +0.7% |
| Crashes / 1,000 cars | 11.49 | 5.46 | -52.4% |
| Retries / 1,000 cars | 950.39 | 231.85 | -75.6% |


Phase 2 improved conversion P50 by **4.1%**, P90 by **7.4%**, and P99 by **29.4%**. Crash incidence per 1,000 cars fell **52.4%** and retry incidence fell **75.6%**. Farm throughput did not improve phase-wide and remains the clearest next target.

## Finance and cleanup

![Credit timeline](charts/05_credit_timeline.png)

The credit bridge reconciles as **120,157,670 opening + 1,548,500 other in-game inflow − 121,695,000 purchases = 11,170 final**. The cleanup log contains **1,277 Phase 2 removal events**; four purchases fall outside that row-level removal coverage, while the final two-state filter/manufacturer check proves no Mad Mike remained.

## Material changes since Phase 1

- Credit decisions now require matching full-header readings and a completed mission reopens if a post-farm credit reward funds another exact Mazda.
- Terminal shutdown restores SP to 999 before cleanup and resumes from crash-safe checkpoints.
- Cleanup runs every 500 cars, switches to the single-copy filter after duplicates are exhausted, and verifies the manufacturer index at zero.
- Empty filtered garages are recognized explicitly and recovered through Filter Selection instead of looping on pause-menu recovery.
- Farm motion monitoring detects a stationary car and performs a bounded five-second reverse recovery.
- Account reads, Discord rendering, screenshots, analytics aggregation, and report work run off the input-critical path where safe.
- OpenCV templates handle calibrated visual states; OCR remains for variable text and numeric account fields, with multi-read confirmation for spending decisions.
- Game capture freshness is restricted and stale screenshots are excluded from Discord delivery.

## Evidence and limitations

Exact: purchases, verified mastery rewards, cycle rows, farm pre/post SP, final credit proof, terminal SP proof, and zero-car cleanup. Derived: percentiles, throughput, purchase spend, and reconciled non-purchase credit inflow. The 2,482 SW total is a hybrid estimate based on a direct 2,481 My Horizon read plus one subsequent verified reward. Recorded farm SP does not fully reconcile the opening balance, 26,901 SP consumed, and terminal 999 SP; the report therefore labels it recorded retained SP rather than an exact full SP ledger.

## Inspectable exports

- [Reviewed snapshot](reviewed_snapshot.json)
- [Stage percentiles](data/stage_percentiles.csv)
- [Farm profiles](data/farm_profiles.csv)
- [Classified failures](data/classified_failures.csv)
- [Phase 1 comparison](data/phase_1_comparison.csv)

Raw logs, screenshots, purchase ledgers, LocalState, and Discord credentials are excluded.
