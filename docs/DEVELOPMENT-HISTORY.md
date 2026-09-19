# Development history

Times are **Japan Standard Time (UTC+09:00)**. Git tracking begins on **September 14, 2026**. The preceding section reconstructs earlier local work from dated recording notes, file creation times, mission notes, and run logs. Those dates identify evidence of work, **not individual commits or exact deployment times**. The upstream macro's older changelog describes upstream development and is not presented as this project's own history.

## Current performance aims

| Aim | Measurement | Status |
|---|---|---|
| **40 seconds per car** | Rolling median of complete buy → mastery → return cycles; keep slow cycles and recovery in the recorded distribution. | Target, not yet established as sustained performance. |
| **1,400 retained SP/hour** | Actual SP kept, divided by complete farm time including challenge setup, loading, top-ups, and farm recovery; cap loss does not count as retained SP. | Target, not yet established as sustained performance. |

The [three-phase comparison](../README.md#2-three-phase-highlights) reports measured historical results; those values must not be relabeled as either target being met.

**Colors:** 🟩 farm and speed · 🟥 safety and recovery · 🟪 Wheelspin Lab · 🟦 measurements and reports · 🟨 release and documentation. A change can have more than one color.

## Before Git tracking · reconstructed local work

| When (JST) | Type | Evidence-backed development | Local evidence |
|---|---|---|---|
| Sep 7 | 🟦🟥 | Reviewed the 98-second, 1920×1080 English-UI manual cycle. Identified the 95,000-CR purchase, newest-car route, six-node 21-SP mastery path, and duplicate-removal ambiguity. | `video_review/observations.md`; recording named `Recording 2026-09-07 231512.mp4` |
| Sep 8 | 🟨🟥 | Created the first local Python package with separate purchase, mastery, session, pipeline, controller, and GUI modules. Began logged live attempts that afternoon. | Local file creation dates; earliest retained run log `20260908_152247_524917.log` |
| Sep 9 | 🟩🟥 | Added production/goal planning, farm profiles, single-worker ownership, game lifecycle, supervision and cloud-sync gating. Integrated the local Python worker with the imported AHK panel, keeping the upstream project distinct. | Local module creation dates; `Forza-Horizon-6-Wheelspin-Macro-main/LOCAL-EDITION.md` |
| Sep 10 | 🟥🟩🟦 | Added durable mission reset/checkpoint work. Started a fresh 500-reward mission; measured one complete car cycle at 54.683s after a prior 20-cycle mean of about 85.7s. One cycle was not a sustained median. | `runs/FRESH-500-STATUS.md`; `runs/SPEED-REPORT.md`; [research plan](../IMPROVEMENT-PLAN-2026-09-10.md) |
| Sep 11 | 🟦🟥 | Started a fresh 1,000-reward mission with in-app analytics and user-triggered exports. Tested Steam crash restart, saved-goal resume, Subaru selection and share-code entry. | `runs/FRESH-1000-STATUS.md`; mission ID `20260911_014620_313216` |
| Sep 12 | 🟩🟦🟥 | Instrumented cycle stages, transition latency, farm economics and Discord boards. Tested early-exit Mega top-ups and a Mini V2 trial; the 200-reward Mini trial was reverted after lower retained SP/hour. Applied a conversion pipeline optimizer at a clean checkpoint and measured its later results rather than assuming a speed gain. | `docs/OPERATIONS_METRICS.md`; `docs/SUB30_SPEED_PLAN.md`; `docs/UI_RECOGNITION_RESEARCH.md` |
| Sep 13 | 🟩🟥🟦 | Continued local farm, home-route, OCR and recovery candidates, including SP read/recovery and return navigation. These candidate files establish experimentation; they do not prove every candidate was deployed. | Dated `runs/optimizer_candidates/` directories and `tests/` files |

The local `runs/`, video-review captures and private checkpoints are excluded from Git. Their evidence names are given for provenance; only the linked public docs and later commits are available from GitHub.

## Committed history

| When (JST) | Type | What changed | Commit |
|---|---|---|---|
| Sep 14, 18:33 | 🟨🟩🟥🟦 | First tracked release: modular farm, purchase, mastery, cleanup, recognition, crash recovery, desktop panel, and reports. Earlier development is bundled in this initial snapshot. | [`9cb2d00`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/9cb2d00) |
| Sep 14, 18:41 | 🟦 | Added the complete operation data and charts to the README and corrected exported percentile calculations. | [`e98b847`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/e98b847) |
| Sep 17, 20:55 | 🟩🟥🟦 | Recorded the Phase 2 credit-exhaustion operation and updated farm motion, setup, credit, analytics, and reporting code. | [`97141c6`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/97141c6) |
| Sep 17, 21:20 | 🟦🟨 | Split the install guide from the detailed Phase 2 comparison, with added timing and capacity analysis. | [`4532a4d`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/4532a4d) |
| Sep 18, 00:26 | 🟦 | Finalized the Phase 2 extension data and three-cohort comparison. | [`e486a00`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/e486a00) |
| Sep 18, 01:27 | 🟦🟨 | Consolidated the three-phase results into one full report and shortened the README. | [`a909593`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/a909593) |
| Sep 18, 01:50 | 🟦 | Expanded the all-phase tables and stage percentile data. | [`cc0d98d`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/cc0d98d) |
| Sep 18, 01:54 | 🟦 | Added four richer three-phase comparison charts to the README and full report. | [`4fff29a`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/4fff29a) |
| Sep 19, 05:21 | 🟪🟥🟦 | Added Wheelspin Lab, guarded reward handling, a 500-spin operation report, and reward-level data exports. | [`18209d3`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/18209d3) |
| Sep 19, 12:24 | 🟥🟪 | Added another block on selling protected cars and corrected the incident report. | [`6485d5c`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/6485d5c) |
| Sep 19, 12:45 | 🟥🟪 | Separated the informational Wheelspin-exclusive catalog from the actual keep/sell policy; expanded policy regression tests. | [`4d48a71`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/4d48a71) |
| Sep 19, 16:35 | 🟦🟨 | Restored the chart-heavy phase comparison in the README and placed Wheelspin results below farming results. | [`1cb54f5`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/1cb54f5) |
| Sep 19, 16:54 | 🟩🟥 | Made the farm's stuck-car check use the actual speed display ahead of scenery movement; low-yield runs now force a full setup recheck. | [`970400b`](https://github.com/an1dee3301/forza-horizon-6-farming/commit/970400b) |

The [full commit history](https://github.com/an1dee3301/forza-horizon-6-farming/commits/main/) remains the source of truth for exact files and diffs. The [all-phase operation report](full-operation-report/REPORT.md) records gameplay results and methods; it is separate from this code-change timeline.
