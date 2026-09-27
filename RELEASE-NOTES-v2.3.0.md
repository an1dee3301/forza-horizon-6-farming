# FH6 Auto v2.3.0

## Desktop workspace

Redesigned the six-view desktop dashboard with a restrained dark palette, clearer spacing, persistent start/stop controls, readable status cards, and organized mission, activity, recovery, history, tools, and analytics views. Added a disconnected `--preview` mode for inspecting the interface without workers or game inputs.

## Reproducible operation analysis

Added anonymous, normalized CSV tables, a coverage and quality audit, a methods report, and three reproducible SVG charts. The main README now presents native outcome evidence, conversion stages, farm timing, and limitations alongside an actual dashboard screenshot. Original source records remain private and unchanged; missing timing and outliers are retained.

The completed operation stopped at 200,078,025 CR, verified zero Mad Mikes after final cleanup, and observed 2,197 Super Wheelspins and 402 regular Wheelspins. Final SP has no fresh native verification. The final +183 SW observation interval measured 28.105 SW/hour including final cleanup; this is not the entire-operation rate and does not prove 33/hour.

## Validation

Python regression suite, runtime smoke, dependency checks, and AutoHotkey self-test; visual inspection of Mission, Activity, and Analytics in disconnected preview. Packaging uses deterministic archives and SHA-256 verification. Existing reserve, receipt, keep-list and final-only cleanup behavior is preserved.
