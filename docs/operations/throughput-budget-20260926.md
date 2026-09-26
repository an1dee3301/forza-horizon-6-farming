# Measured throughput budget

This is a diagnostic budget, **not a verified saved Super Wheelspin rate**. The accompanying JSON contains sanitized measurements with no account or receipt identifiers.

- Two complete farm observations produced 721 SP in 2,028 seconds: approximately 1,280 SP/hour **during farming**, including the recorded farm boundaries.
- The next 22 conversion observations had a median of 53.797 seconds per car. Restart downtime is excluded from this median.
- A prior verified cleanup removed 33 cars in 194.197 seconds, or 5.885 seconds per car. Final-only cleanup defers this cost; it does not make the cost disappear.
- At the measured farming yield, 21 SP costs about 59.068 seconds. A 33/hour target allows 109.091 seconds total per saved reward. After farming and the cleanup reference, conversion needs to average at most **44.138 seconds**, before allowing extra recovery or other overhead.

The stage arithmetic gives approximately 30.316 rewards/hour. The actual 34-reward batch from the first farm start through final conversion took 4,831 seconds, including interruptions: **25.336 mission rewards/hour before final cleanup**. Neither number establishes native saved inventory growth.

The remaining conversion gap is about 9.66 seconds per car, plus recovery overhead. Replacing subsecond menu pauses alone cannot establish the target. A healthy observed selection route included about ten seconds between Get In Car and the next usable screen; this is an observed transition, not proof that all of its duration is unavoidable engine work.

Final-only cleanup is now supported. Sustained-rate qualification still requires adjacent native inventory windows, correct purchase/reward accounting, and all farming, conversion, cleanup, and recovery wall time. These measurements do not pass that qualification.
