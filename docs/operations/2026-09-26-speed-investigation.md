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

The observed route difference alone is too small to prove the target. At roughly 63–65 seconds per conversion plus about 61 seconds of farming per 21 SP, the full operation needs a larger measured improvement, including cleanup time. Continue measuring complete wall-clock windows with fresh native saved-spin evidence. Claim the 33/hour target only after two adjacent windows each add at least 100 saved Super Wheelspins.

## Tool research

The local [Good AI List](https://goodailist.com/) curation identifies [RapidOCR](https://github.com/RapidAI/RapidOCR), [ONNX Runtime](https://github.com/microsoft/onnxruntime), [Optuna](https://github.com/optuna/optuna), and [Supervision](https://github.com/roboflow/supervision) as possible development tools. Their installed smoke checks confirm availability, not a production speedup. The catalog is a large dynamic directory, so this is a relevant-tool review rather than an exhaustive inventory. Any OCR or inference replacement needs a labeled, offline comparison of latency and false positives before use in the game worker.
