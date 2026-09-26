# September 26 speed investigation

This note contains de-identified aggregate measurements from the local production run. Raw game captures, account observations, receipts, and logs remain local.

## Baseline

The table uses completed conversion cycles from `analytics_cycles.jsonl`. Cycle time includes buying, selecting the newly purchased car, claiming mastery, and returning. It excludes SP farming and garage cleanup.

| Batch | Cycles | Median cycle | Mean cycle | Median car selection |
| --- | ---: | ---: | ---: | ---: |
| A | 35 | 60.56 s | 63.97 s | 28.98 s |
| B | 33 | 61.39 s | 62.75 s | 29.05 s |
| C | 33 | 62.22 s | 65.05 s | 29.34 s |

Two adjacent, naturally completed farm runs produced 355 and 347 SP in 1,041 and 1,011 seconds respectively. Each Mad Mike conversion costs 21 SP. Those farm runs therefore fund about 33.4 conversions over 34.2 minutes, before buying, mastery, and cleanup. A representative 33-car conversion batch takes about 35 minutes at the observed mean. The observed 32-car cleanup took about 335 seconds. Combined, the recent operation is approximately 135 seconds per reward, or 26–27 rewards/hour before fresh native saved-spin qualification. Reaching 33/hour requires at most 109.1 seconds per reward, a roughly 26-second reduction. This baseline does not establish 33 saved Super Wheelspins/hour.

## Bottleneck and candidate

Recent production traces show a repeated six-key traversal in the garage sort dialog before selecting `Recently Added`. That traversal consumes about 4–5 seconds per car. A pointer selection path initially looked faster, but a prior production trace shows a click that failed to change screens and consumed a 30-second timeout before recovery. The shortcut was rejected; the current worker remains on the keyboard route. A faster selection method needs reliable transition evidence across repeated live trials before deployment.

An earlier three-car prebuy pilot preserved distinct receipts and proved three saved rewards. Its comparable core route saved only 11.3 seconds per triplet; including native proof and return it was slower than ordinary conversion. Larger prebuy batches lack verified card selection across scrolling and resumable partial-cohort recovery, so they are research candidates rather than production changes.

A one-car seven-Down cleanup pilot is prepared locally and passes 17 offline tests. The latest 32-car cleanup took about 335 seconds from start through final verification; its median interval between removals was 7 seconds. The proposed input burst might save about 1.8–2 seconds per removal, but this is a projection. It remains isolated until a single removal proves the exact filtered Mad Mike, fresh menu focus, Yes confirmation, journal entry, and returned grid. The prior world Pause conversion pilot could not buy from that screen and had no measured speed gain.

The observed route difference alone is too small to prove the target. At roughly 63–65 seconds per conversion plus about 61 seconds of farming per 21 SP, the full operation needs a larger measured improvement, including cleanup time. Continue measuring complete wall-clock windows with fresh native saved-spin evidence. Claim the 33/hour target only after two adjacent windows each add at least 100 saved Super Wheelspins.

The next completed 33-reward batch took about 4,570 seconds from the previous verified cleanup finish through its own verified cleanup finish, an observed **26.0 rewards/hour**. Its conversion cycles totaled 2,133 seconds, of which car selection consumed 1,005 seconds. This complete batch needs about 29 seconds less per reward to reach 33/hour. Full-menu OCR took roughly 70 ms per read in the performance counters, so OCR substitutions cannot close that gap. These are reward and wall-clock measurements, not a native saved-spin rate claim. A local opt-in native inventory cadence now records a fresh two-frame baseline at a completed batch boundary and will sample after each subsequent 100 new rewards; it is not yet part of the older public runtime.

## Adaptive focus experiment

A single local conversion used two distinct fresh focus observations to advance eligible menu selections instead of fixed settling delays. It completed in **61.359 seconds**, compared with a ten-cycle baseline mean of **64.042 seconds** and median of **62.117 seconds**. Six checks proved focus; two fell back to normal navigation. The 2.683-second difference from the baseline mean is not a causal speed estimate: one trial is insufficient and normal cycle variance is substantial. The experiment consumed its one-cycle marker and subsequent cycles use normal pacing. Machine-readable, de-identified measurements are in [adaptive-focus-trial.json](adaptive-focus-trial.json).

A reversible direct-Autoshow inspection reached the exact Mad Mike's 95,000-CR offer through manufacturer selection, recommended designs and manufacturer colors, then canceled without purchasing. Delivery and automatic equip remain unverified. A receipt-aware adapter is required before a paid trial can establish whether this route removes the roughly 30-second garage-selection stage. No full-rate qualification follows from either experiment.

## Tool research sources

The local [Good AI List](https://goodailist.com/) curation identifies [RapidOCR](https://github.com/RapidAI/RapidOCR), [ONNX Runtime](https://github.com/microsoft/onnxruntime), [Optuna](https://github.com/optuna/optuna), and [Supervision](https://github.com/roboflow/supervision) as possible development tools. Their installed smoke checks confirm availability, not a production speedup. The catalog is a large dynamic directory, so this is a relevant-tool review rather than an exhaustive inventory. Any OCR or inference replacement needs a labeled, offline comparison of latency and false positives before use in the game worker.
