# FH6 Auto v2.2.0

Final operational cleanup completed at the configured credit floor. See the sanitized [final run report](docs/operations/final-run-20260927.md).

## Controls and reporting

- Adds an optional credit reserve in the Mission tab and Runtime CLI. A paid car finishes before another purchase is considered; the worker verifies the remaining credits before completing the goal.
- Adds **Final cleanup only**, which defers Mad Mike removal until the credit reserve stops purchases. The saved policy survives worker resumes. Reserve-based completion skips the terminal SP top-up.
- Keeps the last verified inventory visible in the live panel and restores an enabled Discord reporter when farming starts through the CLI.
- Reports batch wall time and native inventory proof status separately from active-time and stage measurements.

## Navigation and recovery

- Recovers the verified Challenges empty-content notification without repeating acknowledgement inputs.
- Corrects refill planning when a small remaining target still needs SP and a full natural run fits available capacity.

- Uses fresh focus observations for fast mastery movement and selected return-menu confirmations, retaining ownership verification before advancing.
- Uses a verified one-Up garage shortcut where the current Recently Added grid supports it.
- Recovers the already-current farm car when its action menu has no Get In Car entry.
- Preserves removal receipts and cleanup counts through worker recovery, including fading confirmation dialogs. Protected-car rules remain in force.

## Performance evidence

The target of **33 saved Super Wheelspins per hour remains unproven**. It requires two adjacent native-inventory windows, each adding at least 100 saved spins, including all farming, conversion, recovery and cleanup wall time.

The [throughput budget](docs/operations/throughput-budget-20260926.md) documents the measured gap. Published Autoshow, Paints and other trial records include unsuccessful results; their presence in the repository does not mean those routes became the default or delivered a speed increase.

## Compatibility

Windows 10/11, the tested Python 3.12 environment, AutoHotkey v2, Steam FH6, English menus and 1920×1080 remain required. Use F7 to stop. Automatic Wheelspin Lab actions remain disabled pending fresh live validation.

Final packaging follows [the release checklist](RELEASE-CHECKLIST.md), including a deterministic archive, SHA-256 verification and a smoke check of the downloaded GitHub asset.
