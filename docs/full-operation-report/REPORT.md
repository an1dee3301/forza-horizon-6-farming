# FH6 farming operation: complete retrospective

**Period:** 2026-09-11 01:46 to 2026-09-14 16:48 JST
**Account:** aichan3301
**End state:** credit limit reached, final paid car completed, garage cleanup verified

## Final result

The operation produced **1,915 verified Super Wheelspin mastery rewards** from **1,915 purchased Mad Mike Mazdas**.

The first mission moved saved inventory from **0 to 517**. The inventory was then reduced to **333** after **184 spins were used**. The second mission verified **1,398** more mastery rewards. The last direct My Horizon read was **1,678 SW and 219 WS** at reward 1,396; two later verified mastery claims give a final hybrid inventory of **1,680 SW and 219 WS**.

The second mission's reward ledger would have reached 1,731 SW from the 333 opening balance. Actual inventory finished at 1,680, so **51 additional SW were used or otherwise reduced during that mission**. The known inventory reduction across both usage periods is **235 SW**.

| Final state | Value |
|---|---:|
| Saved Super Wheelspins | **1,680** |
| Wheelspins | **219** |
| Verified mastery rewards | **1,915** |
| Mad Mike Mazdas bought and processed | **1,915** |
| Credits | **87,720 CR** |
| Skill Points | **39 SP** |
| Level / prestige | **387 / 5** |
| Mad Mike cars remaining | **0, verified** |
| Recorded removal events | **1,288** |
| Removed in final automated pass | **78** |

![Saved inventory timeline](charts/01_inventory_timeline.png)

## Production timeline

| Phase | Result | Farm runs | Cycle P50 | Cycle P90 | Cycle P99 | Active time | Recovery | Crashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Initial 0→517 | 517 SW | 35 | 56.1s | 63.6s | 72.4s | 19.26h | 0.23h | 2 |
| Restart from 333 | 1,398 rewards | 116 | 47.4s | 58.7s | 83.5s | 54.72h | 7.33h | 20 |
| **Total** | **1,915 rewards** | **151** | — | — | — | **73.97h** | **7.56h** | **22** |

The end-to-end wall window was **87.04 hours**. Output averaged **25.89 verified rewards per recorded active hour** and **22.00 per wall hour**. The latest 20-car window finished at **P50 46.73s, P90 57.52s, P99 57.73s**, with **100% first-pass yield**.

The second phase cut the whole-cycle P50 by **15.6%** and P90 by **7.8%** versus the first phase. The stable final median was about 46.7 seconds; the 30-second target was not reached.

![Cycle percentiles](charts/03_cycle_percentiles.png)

### Per-stage distributions

| Phase | Stage | n | P50 | P90 | P99 | Mean |
|---|---|---:|---:|---:|---:|---:|
| 0→517 | Collection | 517 | 0.47s | 0.52s | 0.59s | 0.48s |
| 0→517 | Buy | 517 | 6.91s | 7.36s | 17.02s | 6.96s |
| 0→517 | Bought transition | 517 | 1.27s | 1.31s | 1.34s | 1.21s |
| 0→517 | Choose newest car | 517 | 24.03s | 29.98s | 35.84s | 25.33s |
| 0→517 | Open mastery | 512 | 3.31s | 3.62s | 13.44s | 3.48s |
| 0→517 | Mastery path | 517 | 8.38s | 8.58s | 9.00s | 8.40s |
| 0→517 | Return | 517 | 11.47s | 12.44s | 16.57s | 11.77s |
| Restart from 333 | Collection | 1,398 | 0.06s | 0.13s | 0.69s | 0.15s |
| Restart from 333 | Buy | 1,398 | 4.03s | 5.59s | 14.56s | 5.23s |
| Restart from 333 | Bought transition | 1,398 | 0.98s | 1.13s | 1.22s | 0.96s |
| Restart from 333 | Choose newest car | 1,398 | 21.16s | 29.04s | 34.25s | 23.45s |
| Restart from 333 | Open mastery | 1,394 | 3.44s | 3.81s | 14.94s | 4.02s |
| Restart from 333 | Mastery path | 1,398 | 7.31s | 11.46s | 11.67s | 8.35s |
| Restart from 333 | Return | 1,398 | 9.72s | 12.88s | 23.34s | 10.47s |

![Stage percentiles](charts/04_stage_percentiles.png)

### Recorded time allocation

| Phase | Farming | Conversion | Recovery | Sync | Total |
|---|---:|---:|---:|---:|---:|
| Initial 0→517 | 10.67h | 8.35h | 0.23h | unavailable | 19.26h |
| Restart from 333 | 25.69h | 21.68h | 7.33h | 0.01h | 54.72h |
| **Total** | **36.36h** | **30.03h** | **7.56h** | **0.01h recorded** | **73.97h** |

![Time allocation](charts/07_time_allocation.png)

## Skill Point farming

Every Mazda consumed 21 SP. Both phases therefore consumed exactly **40,215 SP**. Farming retained **40,134 SP** over **35.94 farm-run hours**. The SP ledger reconciles exactly:

| Phase | Opening SP | Retained farm SP | SP consumed | Ending SP |
|---|---:|---:|---:|---:|
| Initial 0→517 | 12 inferred | 11,600 | 10,857 | 755 |
| Restart from 333 | 863 verified | 28,534 | 29,358 | 39 |
| **Total** | — | **40,134** | **40,215** | — |

The first opening balance is inferred from the exact identity `opening + farmed − consumed = ending`; it is not a direct OCR read.

### Farm profile comparison

| Farm group | Runs | Retained SP | Active hours | Retained SP/h | Cars supported/h | Drive P50 |
|---|---:|---:|---:|---:|---:|---:|
| Mega V6 — natural completion | 31 | 10,936 | 8.84 | **1,237** | **58.9** | 917.2s |
| Mega V6 — intentional top-up | 25 | 4,876 | 4.01 | **1,216** | **57.9** | 600.2s |
| Untagged — natural completion | 1 | 373 | 0.31 | 1,200 | 57.1 | 915.8s |
| Untagged — intentional top-up | 1 | 242 | 0.21 | 1,133 | 54.0 | 600.6s |
| Untagged legacy | 11 | 3,718 | 3.29 | 1,131 | 53.8 | unavailable |
| Initial farm telemetry | 35 | 11,600 | 10.39 | 1,116 | 53.2 | unavailable |
| Mini V2 — natural completion | 29 | 3,712 | 3.46 | **1,072** | **51.0** | 298.6s |
| Mega V6 — interrupted | 8 | 2,893 | 2.78 | 1,039 | 49.5 | 917.3s |
| Untagged capped | 5 | 1,110 | 1.50 | 742 | 35.3 | unavailable |
| Mini V2 — interrupted | 5 | 674 | 1.14 | 591 | 28.1 | 298.7s |

Natural Mega V6 beat natural Mini V2 by **15.4%** on retained SP per active farm hour. Intentional Mega top-ups preserved almost the same throughput while avoiding oversized final runs. This is why the controller reverted from Mini V2 and kept Mega for both bulk and top-up work.

Telemetry flagged **18 capped runs** across both phases. Historic cap-loss magnitude was not measured consistently, so no exact SP-waste total is claimed.

![Farm throughput](charts/05_farm_throughput.png)

## In-game finances

Each Mad Mike cost 95,000 CR. Exact gross purchase spend was:

| Phase | Cars | Gross Mazda spend |
|---|---:|---:|
| Initial 0→517 | 517 | 49,115,000 CR |
| Restart from 333 | 1,398 | 132,810,000 CR |
| **Total** | **1,915** | **181,925,000 CR** |

The first phase opening balance and detailed credit inflows were not recorded, so an all-period net credit bridge would be false precision. The first reliable phase-end balance was **92,352,392 CR**.

| Second-phase credit bridge | Amount |
|---|---:|
| Start after spins were used | 122,277,466 CR |
| Other in-game inflow required to reconcile | **+10,620,254 CR** |
| Mazda purchases | **−132,810,000 CR** |
| Final verified balance | **87,720 CR** |

The balance rose by **29,925,074 CR** between the first phase-end read and the second mission baseline, consistent with the user's wheelspin-opening period and any other intervening game income. During the second mission, the net balance decline was **122,189,746 CR**, equal to **87,403 CR per verified reward** after other in-game inflows. The final account was **7,280 CR short** of another Mazda.

![Credit timeline](charts/02_credit_timeline.png)

## Reliability and recovery

The broad telemetry recorded **1,820 retry/recovery events**, **22 crashes**, and **7.56 hours** in recovery. Failure taxonomy was introduced during the second mission; **501 rows** are fully classified and account for **2.73 hours**. Remaining recovery time is legacy or unclassified and is not assigned to a cause.

| Classified cause | Events | Recovery time | Mean cost |
|---|---:|---:|---:|
| OCR fail | 341 | 97.2 min | 17.1s |
| Mastery detection | 71 | 21.3 min | 18.0s |
| Purchase fail | 27 | 20.4 min | 45.3s |
| Game crash | 2 | 6.8 min | 203.8s |
| Choose timeout | 7 | 5.2 min | 44.8s |
| Focus lost | 30 | 5.1 min | 10.3s |
| Unexpected screen | 9 | 3.8 min | 25.1s |
| Other | 5 | 2.3 min | 27.5s |
| Return timeout | 9 | 1.9 min | 12.5s |

OCR failures were the largest classified time sink in aggregate. Crashes were far less frequent but much more expensive per event. Only two crashes occurred after cause-level timing was added; the broad counter recorded 22 across both phases.

![Failure cost](charts/06_failure_cost.png)

## Account progression and cleanup

The second mission began at **level 320, prestige 4** and ended at **level 387, prestige 5**: a displayed level change of **320 → 387 with prestige 4 → 5** (the total number of levels earned across the prestige rollover is not established here). The first phase ended at level 299, prestige 4.

Cleanup telemetry contains **1,288 recorded removal events**, including **78 in the final automated pass**. The final manufacturer-index check verified no Mad Mike Mazda remained. The difference between 1,915 purchases and recorded automated removals represents manual/early cleanup and periods before removal telemetry existed; it does not represent cars still present.

## Improvements that produced measurable gains

- Cycle P50 fell from **56.1s to 47.4s**; the last-20 P50 reached **46.7s**.
- Recently Added + newest-car selection kept duplicate selection constant-time.
- Direct house entry removed unnecessary return-home travel.
- Settings, Skill HUD, and assistance checks were cached per mission/process instead of repeated per car.
- Analytics, account reads, screenshots, Discord rendering, and diagnostics moved to background workers where safe.
- Purchase polling and screen recognition replaced many fixed waits while retaining stable-screen checks.
- Mastery navigation used direct pointer targets plus interior-only owned/unowned checks.
- Mega V6 bulk and shortened top-up modes reduced refill restarts and cap exposure.
- Mini V2 was tested for 34 recorded runs and rejected based on retained SP/hour.
- Credit checks required two matching reads and stopped at 87,720 CR.
- Crash recovery, Steam relaunch, focus recovery, and synchronized mission checkpoints prevented lost progress.
- Final cleanup removed every remaining filtered Mad Mike and verified zero inventory.

## Evidence quality

**Exact or directly verified:** purchase and mastery counts, fixed purchase price, cycle timestamps, farm pre/post SP, My Horizon inventory reads, second-phase credit baseline and final balance, final zero-car cleanup, level and prestige reads.

**Derived from exact records:** SP consumption, phase throughput, percentiles, gross Mazda spend, second-phase non-purchase inflow, and the final 1,680 SW hybrid value from a direct 1,678 read plus two later verified nodes.

**Incomplete:** first-phase opening credits, first-phase detailed credit inflows, cause-level failure telemetry before classification existed, exact historic cap loss, and removals before cleanup telemetry was introduced. Missing values remain unknown rather than zero.

## Inspectable data

- [`reviewed_snapshot.json`](reviewed_snapshot.json)
- [`phase_summary.csv`](data/phase_summary.csv)
- [`stage_percentiles.csv`](data/stage_percentiles.csv)
- [`farm_profiles.csv`](data/farm_profiles.csv)
- [`classified_failures.csv`](data/classified_failures.csv)

Raw logs, screenshots, process identifiers, purchase ledgers, and Discord credentials are intentionally excluded from Git.
