# Historical farming and Wheelspin results

The operation contains three measured cohorts. The README keeps only the comparison; the [complete all-phase report](full-operation-report/REPORT.md) contains the full timing, farming, finance, reliability, inventory, cleanup, methods, and evidence detail.

| Metric | Pre-Phase 1 · 0→517 | Phase 1 · restart from 333 | Phase 2 · credit exhaustion |
|---|---:|---:|---:|
| Cars / new Super Wheelspins | 517 | 1,398 | 1,337 |
| Farm runs | 35 | 116 | 112 |
| Recorded active time | 19.26h | 54.72h | 46.65h |
| Recorded farm time | 10.39h | 25.55h | 27.70h |
| Retained farm SP | 11,600 | 28,534 | 28,700 |
| Cycle P50 | 56.09s | 47.37s | **45.62s** |
| Cycle P90 | 63.63s | 58.69s | **54.64s** |
| Cycle P99 | 72.35s | 83.46s | **59.01s** |
| SW / active hour | 26.85 | 25.55 | **28.66** |
| Retained SP / farm hour | 1,116 | **1,117** | 1,036 |
| Farm-supported cars / hour | 53.15 | **53.19** | 49.34 |
| Conversion capacity | 61.92 cars/h | **64.48 cars/h** | 63.19 cars/h |
| First-pass yield | 96.71% | 95.92% | **97.23%** |
| Broad retries | **76** | 1,744 | 306 |
| Retries / 1,000 cars | **147.0** | 1,247.5 | 228.9 |
| Crashes | **2** | 20 | 7 |
| Crashes / 1,000 cars | **3.87** | 14.31 | 5.24 |
| Gross Mazda spend | 49.12M CR | 132.81M CR | 127.02M CR |

Phase 2 was the strongest conversion and recovery cohort: versus Phase 1, P50 improved **3.68%**, P90 **6.91%**, P99 **29.30%**, and active reward throughput **12.19%**. SP farming fell **7.22%**, leaving farm output as the main remaining bottleneck.

### Speed

![Cycle percentiles across all phases](full-operation-report/charts/18_three_phase_cycle_percentiles.png)

![Cycle-duration distributions](full-operation-report/charts/14_three_phase_cycle_ecdf.png)

![Stage P50 across all cohorts](full-operation-report/charts/16_three_phase_stage_p50.png)

### Throughput

![Active reward and SP farm throughput](full-operation-report/charts/19_three_phase_throughput.png)

### Reliability and workload

![Normalized reliability and first-pass yield](full-operation-report/charts/20_three_phase_reliability.png)

![Cars, farm runs, and recorded hours](full-operation-report/charts/21_three_phase_workload.png)

Across all three phases: **3,252 cars**, **3,252 verified rewards**, **263 farm runs**, and **308.94M CR** spent on Mazdas. The final verified Phase 2 state was **2,506 saved SW**, **230 WS**, **999 SP**, **42,170 CR**, and **zero Mad Mikes**.

## Wheelspin results

The [500-Super-Wheelspin operation report](WHEELSPIN-OPERATION-2026-09-19.md) records the first completed Wheelspin Lab run. These are opened spins and their rewards; they are **separate from** the three farming cohorts above.

| Result | 500-spin run |
|---|---:|
| Spins completed / reward slots recorded | **500 / 1,500** |
| Credit / car / other rewards | 1,126 / 349 / 25 |
| Direct credit rewards | **85.14M CR** |
| Verified duplicate-sale credits | **48.78M CR** |
| Total credits logged | **133.92M CR** |
| Duplicate cars sold / kept | 346 / 3 |
| Protected car pulls / kept / sold in error | **8 / 3 / 5** |
| Wall time / throughput | 2.63h / 189.91 spins/h |
| Spin duration P50 / P90 | 7.02s / 8.71s |

Five protected cars were sold in error during this run, including four Lamborghinis. The kept-car count must not be read as successful enforcement of the retention policy. The corrected policy keeps **CLK GTR, One:1, Venom GT, Nevera, Apollo IE, 599XX Evolution, both Subaru Impreza 22B-STi copies, and every Lamborghini**; the 45-car Wheelspin-exclusive catalog is for statistics only. Automatic Wheelspin Lab actions are disabled locally pending fresh live safety validation. The [full report](WHEELSPIN-OPERATION-2026-09-19.md) includes the audited incidents, car pulls, recovery data, and [machine-readable results](data/wheelspin-operation-20260919/summary.json).
