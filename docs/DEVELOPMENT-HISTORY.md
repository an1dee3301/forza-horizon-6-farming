# Development history

This timeline follows the repository's committed code history. Times are **Japan Standard Time (UTC+09:00)**. Git tracking begins on **September 14, 2026**; earlier local prototypes and gameplay experiments are not dated here because their individual changes cannot be reconstructed from this repository.

**Colors:** 🟩 farm and speed · 🟥 safety and recovery · 🟪 Wheelspin Lab · 🟦 measurements and reports · 🟨 release and documentation. A change can have more than one color.

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
