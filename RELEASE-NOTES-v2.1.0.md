# FH6 Auto v2.1.0

This release packages the current public source at an immutable commit and provides a deterministic Windows archive with a SHA-256 manifest.

## Safety and reliability

- Adds the user's Subaru Impreza 22B to the protected keep policy, including full-name and native duplicate-dialog aliases. Both owned copies are retained; unrelated Subaru models are not added to the keep list.
- Adds regression coverage at the keep-policy and durable destructive-action interlock.
- Setup now targets the tested CPython 3.12 runtime, installs an exact Windows dependency lock, checks dependency consistency and runs a no-input import/file smoke check before launching.
- Uses one OpenCV distribution consistently with the window-capture package to avoid overlapping `cv2` files.
- Start refuses to run before setup or when AutoHotkey v2 is missing.
- Adds deterministic archive construction, source-commit manifest, ZIP CRC validation and SHA-256 sidecar generation.

## Known limits

- No software can be guaranteed never to fail. This release has automated tests and setup/package checks, not proof of failure-free operation on every PC.
- Automatic Wheelspin Lab actions remain disabled pending fresh live safety validation. Do not enable them based on this package alone.
- The operational target of 33 saved Super Wheelspins per hour is not established. Historical farm throughput is not a substitute for the required adjacent native-inventory windows.
- Windows 10/11, AutoHotkey v2, Steam FH6, English menus and 1920×1080 remain required. Run the dashboard in a dedicated game session and use F7 to stop.
