# FH6 chart definitions

The report stays a wheelspin factory dashboard. Its values distinguish actual saved inventory, newly earned mission output, and estimates.

- **Saved SW / WS:** two fresh matching readings of the actual My Horizon Available counters. Show their read time. Both increases and decreases are valid. Starting inventory plus mission output is never a substitute for actual stock.
- **Mission output:** verified newly claimed Super Wheelspin nodes. Spending spins later does not change how many were earned.
- **SW/h:** newly earned mission output divided separately by recorded active hours and elapsed mission wall hours. Missing historical active intervals cannot be reconstructed.
- **Farm capacity:** retained SP per whole-farm active hour, divided by 21 SP/car. Select the current contiguous explicit farm profile before filtering timing. Mega and Mini are separate.
- **Conversion capacity:** completed cars divided by total recorded duration for the last 80 retained cars. Combined sequential capacity is `1 / (1 / farm_capacity + 1 / conversion_capacity)`.
- **Percentiles:** ordinary median for P50; nearest rank for P90 and P99. Always show sample counts. P99 with fewer than 100 samples is the observed maximum, not a stable tail estimate.
- **Comparisons:** last 20 cars versus the preceding 20. Only show percentage changes when both groups contain 20 recorded cars. A comparison does not prove which change caused the difference.
- **Cycle chart:** requested 25–60 second zoom, measured cars, rolling-20 median and 30-second target. Off-scale points are marked and remain in statistics. Bars start at zero. Missing values remain missing.
- **Challenge duration:** current farm only, minutes:seconds, with separate symbols/statistics for full runs, planned top-ups and partial/unknown timing. The current Mega chart never defaults to the retired Mini trial.
- **Retries / 100 cars and first-pass yield:** instrumented car cohort only; show coverage. Historical recovery totals remain separate from current failure behavior.
- **Forza tax:** duration-weighted unassigned residual within valid version-2 observed transitions, after measured polling and pacing. Show coverage. The causal game-only loading/animation share is unmeasured.
- **Cap waste:** an estimate with matched timing coverage. Unsupported capped runs suppress the headline waste rate; unavailable does not mean zero.
- **Forecast:** paired timing/yield from the latest 20 eligible complete uncapped full runs in the current farm regime. Planned top-ups conservatively use full-run time. Defaults or old profileless evidence are labeled. All finite positive cycle durations, including interruptions, remain eligible. The forecast range is not a confidence interval or a promised finish time.
- **Credits:** actual matching account readings with timestamps. Car cost is confirmed purchases × 95,000 CR. Affordable remaining output is an estimate, never proof of a purchase or reward.

Analytics stays in the app. Export occurs only when the user chooses it. Discord uses one container with three boards, the verified account crop, and the latest qualifying My Horizon / Return Home screenshot.

Trend axes run from 90% of the observed minimum to 110% of the observed maximum. Flat series retain a minimum visible span. SP targets remain visible. Absolute-magnitude bars remain zero-based. Current challenge duration uses the same 90%/110% rule across full runs and planned top-ups, placing both at their actual duration on one shared axis. Partial or unknown runs outside that production range retain edge markers and exact durations. The requested 25–60s car-cycle view remains fixed. These display changes never filter statistical samples.

Stage trends use the full observed minimum and maximum with the 90%/110% rule. No measured stage point is clipped. Smaller cohorts retain their full range.
