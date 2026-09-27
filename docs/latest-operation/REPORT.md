# Latest operation: normalized evidence

The operation stopped purchasing at **200,078,025 CR**. Final native inventory: **2,197 Super Wheelspins** and **402 regular Wheelspins**. Final SP is **unavailable**: the last observation predates the final conversions. No estimated balance is presented as native evidence.

## Outcome and rate

The final two native observations added **183 SW** over **6.511 hours**, or **28.11 saved SW/hour**. The denominator includes all elapsed time and final cleanup. This is one interval, not two adjacent qualifying windows; **33 saved SW/hour remains unproved**. The endpoint is local native inventory, not proof of a cloud upload.

Final cleanup reached verified empty. The journal contains **317 removals after the stopping-floor check**, over **32.46 elapsed minutes**, including recovery. Journal records and lifetime running totals are different quantities; lifetime removal counters are deliberately not exported as this cleanup's count.

## Coverage and data quality

- 67 distinct farm records versus a goal counter of 68; this gap is retained, not filled with invented runs.
- 796 distinct cycle records versus 796 completed cars; 0 missing cycle records. Missing telemetry does not mean missing rewards.
- 12 farm records flag partial timing; 0 flag capped yield. These remain in the dataset with flags.
- 26 cycle observations exceed the upper Tukey fence (77.04 s); outliers are retained, not trimmed to improve speed.
- 561 failure records fall within operation time. They have no goal key, so they are time-scoped evidence, not a count of independent incidents. Their durations can overlap; do not add them to wall time.
- Stage sample counts vary; absent stage timings remain missing, not zero-filled. File input-quality counts cover each entire source file, while coverage and exported records are scoped to this operation.
- Exact duplicate JSON rows are removed before entity-key deduplication. First entity record wins; exclusions and malformed lines are counted in `audit.json`. Originals are untouched.

## Timing semantics

Farm wall time is `ended_at - started_at`; recorded active and drive durations are separate columns. Weighted farm throughput is **442.5 SP/hour**, excluding conversion/cleanup and subject to the timing flags. Median recorded conversion duration is **60.34 active seconds/car**. Stage medians do not sum to a median cycle and cannot isolate causal loading cost. These are observational diagnostics, not randomized experiment results or universal hardware benchmarks.

Naive source timestamps are interpreted in Japan time (UTC+09:00); offset-aware native timestamps preserve their offset. Public times are seconds since operation start. CSVs contain only explicit allowlisted measures, anonymous sequential row IDs and fixed stage labels; no account IDs, process IDs, paths, screenshots, purchase receipts or message text are copied.

## Reproduce

Run `python tools/analyze_operation.py --render-only` from the repository to reproduce SVG charts from the committed CSVs. To reproduce extraction, provide the private run directory with `--runs /path/to/runs`; the script only reads it. Python standard library only. The source captures are intentionally not distributed.

### Data dictionary

| File | Grain | Interpretation |
|---|---|---|
| farms.csv | One recorded farm | SP gain, wall/active/drive seconds, partial/cap flags |
| cycles.csv | One recorded paid-car cycle | Recorded active duration, end time, failed attempts |
| stages.csv | Stage aggregate | Sample count, median and sum of recorded seconds |
| cleanup.csv | One journal removal | Relative time and removal count, no vehicle/account IDs |
| recovery_records.csv | Time-scoped failure record | Recorded recovery wall time; may overlap |
| native_interval.csv | Final two verified observations | Local native SW/regular balances |
| summary.json | Operation outcome | Native balances, coverage-aware rates, cleanup result |
| audit.json | Input quality | Duplicates, malformed lines, missing coverage and outliers |

![Conversion stages](conversion-stages.svg)
![Saved SW rate](saved-wheelspin-rate.svg)
![Farm throughput](farm-throughput.svg)
